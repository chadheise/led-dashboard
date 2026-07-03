"""Background internet-reachability check used to show a "No wifi connection"
overlay instead of rendering apps that need data none of them can fetch.

The check is a raw TCP connect to well-known IP literals (no DNS lookup, so a
broken resolver doesn't produce a false "online" or hang on lookup) run in a
thread executor so it never blocks the render loop.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from io import BytesIO

import cairosvg
from PIL import Image

from canvas.base import Canvas
from libraries.canvas_utils.library import blit
from libraries.text_renderer.library import can_fit_text, render_text

logger = logging.getLogger(__name__)

# Public resolvers used purely as TCP reachability probes (port 53), not for
# actual DNS lookups. Two independent operators so one outage doesn't read as
# "offline".
_PROBE_HOSTS: tuple[tuple[str, int], ...] = (
    ("1.1.1.1", 53),
    ("8.8.8.8", 53),
)
_DEFAULT_TIMEOUT = 3.0
_DEFAULT_CHECK_INTERVAL = 15.0


def check_internet(timeout: float = _DEFAULT_TIMEOUT) -> bool:
    """Best-effort synchronous internet reachability check. Blocking; run off-thread."""
    for host, port in _PROBE_HOSTS:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


class ConnectivityMonitor:
    """Polls `check_internet` in the background and exposes the latest result.

    Starts optimistic (`is_online=True`) so a normal boot never flashes the
    offline overlay before the first check completes.
    """

    def __init__(
        self,
        check_interval: float = _DEFAULT_CHECK_INTERVAL,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._check_interval = check_interval
        self._timeout = timeout
        self._is_online = True
        self._task: asyncio.Task[None] | None = None

    @property
    def is_online(self) -> bool:
        return self._is_online

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                self._is_online = await loop.run_in_executor(None, check_internet, self._timeout)
            except Exception as exc:
                logger.warning("Connectivity check error: %s", exc)
                self._is_online = False
            await asyncio.sleep(self._check_interval)


# ── "No wifi connection" overlay ────────────────────────────────────────────

_MESSAGE_COLOR: tuple[int, int, int] = (80, 80, 80)  # matches draw_status_message's dim gray
_MESSAGE_TEXT = "No wifi connection"
_MESSAGE_FONT_MAX = 14


# No-wifi badge icon (red circle, white slash, black wifi glyph), supplied by the user.
_WIFI_OFF_SVG = """\
<svg id="Layer_1" data-name="Layer 1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 122.88 122.88">\
<defs><style>.cls-1{fill:#fff;}.cls-2{fill:#d92d27;}</style></defs><title>no-wifi</title>\
<path class="cls-1" d="M101.68,32.93,32.92,101.68a49.29,49.29,0,0,0,77.83-40.24h0A49.34,49.34,0,0,0,108,45.15a48.85,\
48.85,0,0,0-6.32-12.22ZM24,93.5,93.49,24A49.31,49.31,0,0,0,24,93.5Z"/>\
<path d="M30.29,52A3,3,0,0,1,26,51.63v0a3,3,0,0,1,.34-4.24h0A59.27,59.27,0,0,1,43.27,37a48,48,0,0,1,36.4.31A61,61,0,\
0,1,96.46,47.9a1.29,1.29,0,0,1,.17.16,3,3,0,0,1,.27,4.07,1.54,1.54,0,0,1-.17.19,3,3,0,0,1-4.16.19A55.23,55.23,0,0,0,\
77.47,43a41.86,41.86,0,0,0-32.08-.27A53.38,53.38,0,0,0,30.29,52ZM61.44,76.09A6.59,6.59,0,1,1,56.77,78h0a6.62,6.62,0,\
0,1,4.67-1.93ZM50.05,72.5a3,3,0,0,1-4.16-.35,1.37,1.37,0,0,1-.16-.18,3,3,0,0,1,.43-4.07l.17-.14a27.64,27.64,0,0,1,\
7.33-4.33,21.68,21.68,0,0,1,7.84-1.52,21.35,21.35,0,0,1,7.8,1.47,27.12,27.12,0,0,1,7.34,4.36A3,3,0,0,1,77.08,72h0a3,\
3,0,0,1-2,1.1,3.06,3.06,0,0,1-2.21-.66h0a21.27,21.27,0,0,0-5.62-3.37,15.12,15.12,0,0,0-11.47,0,22,22,0,0,0-5.7,3.41Zm\
-9.56-9.71-.15.13a3.06,3.06,0,0,1-2.08.67,3,3,0,0,1-2-1,1,1,0,0,1-.14-.15,3,3,0,0,1,.34-4.16,45.78,45.78,0,0,1,\
12.36-8,30.76,30.76,0,0,1,25.6.42,45.74,45.74,0,0,1,12.11,8.41l.08.07a3.09,3.09,0,0,1,.87,2,3,3,0,0,1-.82,2.15l-.07,\
.08a3,3,0,0,1-2,.87,3,3,0,0,1-2.15-.81A40.13,40.13,0,0,0,72,56.28a24.75,24.75,0,0,0-21-.35,39.68,39.68,0,0,0-10.5,\
6.86Z"/>\
<path class="cls-2" d="M61.44,0A61.31,61.31,0,1,1,38,4.66,61.29,61.29,0,0,1,61.44,0Zm40.24,32.93L32.93,101.68A49.44,\
49.44,0,0,0,80.31,107,49.53,49.53,0,0,0,107,80.3a49,49,0,0,0,3.73-18.86h0a48.93,48.93,0,0,0-9.08-28.51ZM24,93.5,\
93.5,24A49.32,49.32,0,0,0,24,93.5Z"/></svg>
"""

_icon_cache: dict[int, Image.Image] = {}


def _wifi_off_icon(size: int) -> Image.Image:
    """Rasterize the no-wifi badge SVG at `size` px, cached (it never changes)."""
    cached = _icon_cache.get(size)
    if cached is not None:
        return cached
    png = cairosvg.svg2png(bytestring=_WIFI_OFF_SVG.encode(), output_width=size, output_height=size)
    img = Image.open(BytesIO(png)).convert("RGBA")
    _icon_cache[size] = img
    return img


# The composed message is static for a given canvas size, but render_frame()
# calls draw_offline_message() every rendered frame (up to config.yaml's fps)
# for as long as the connection is down. Rebuilding the icon + text + composite
# from scratch each call burned meaningful CPU on the Pi for no visual benefit,
# competing with the timing-sensitive rpi-rgb-led-matrix GPIO driver and (per a
# user report) destabilizing wifi/SSH — so the composed image is cached per
# (width, height) and only rebuilt when a new size is seen.
_message_cache: dict[tuple[int, int], Image.Image] = {}


def _build_offline_message_image(w: int, h: int) -> Image.Image:
    pad = 2
    icon_size = max(10, min(h - 2 * pad, 28))
    gap = 4

    max_text_w = max(6, w - 2 * pad - icon_size - gap)
    text = _MESSAGE_TEXT
    size = _MESSAGE_FONT_MAX
    while size > 6 and not can_fit_text(max_text_w, size, text):
        size -= 1
    while text and not can_fit_text(max_text_w, size, text):
        text = text[:-1]

    text_img = render_text(text, _MESSAGE_COLOR, size) if text else Image.new("RGB", (1, 1))
    icon = _wifi_off_icon(icon_size)

    text_w = text_img.width if text else 0
    group_gap = gap if text else 0
    group_w = icon_size + group_gap + text_w
    group_h = max(icon_size, text_img.height)

    img = Image.new("RGB", (w, h))
    x0 = max(0, (w - group_w) // 2)
    y0 = max(0, (h - group_h) // 2)
    img.paste(icon, (x0, y0 + (group_h - icon_size) // 2), icon.split()[3])
    if text:
        img.paste(text_img, (x0 + icon_size + group_gap, y0 + (group_h - text_img.height) // 2))
    return img


def draw_offline_message(canvas: Canvas) -> None:
    """Render a dim, centered "No wifi connection" message with a wifi-off icon to its left.

    The composited image is cached per canvas size (see `_message_cache`) since
    this is called every rendered frame while offline.
    """
    w, h = canvas.width, canvas.height
    key = (w, h)
    img = _message_cache.get(key)
    if img is None:
        img = _build_offline_message_image(w, h)
        _message_cache[key] = img
    blit(canvas, img)
