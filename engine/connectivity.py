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

from PIL import Image, ImageDraw

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


def _wifi_off_icon(size: int, color: tuple[int, int, int]) -> Image.Image:
    """A wifi glyph with a diagonal slash, drawn with primitives (no SVG asset)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    stroke = max(1, round(size * 0.08))

    cx = size / 2
    cy = size * 0.84
    dot_r = max(1, round(size * 0.065))
    draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=color)

    for frac in (0.34, 0.62, 0.92):
        r = size * frac / 2
        bbox = [cx - r, cy - r, cx + r, cy + r]
        draw.arc(bbox, start=212, end=328, fill=color, width=stroke)

    draw.line([(size * 0.08, size * 0.08), (size * 0.92, size * 0.92)], fill=color, width=stroke + 1)
    return img


def draw_offline_message(canvas: Canvas) -> None:
    """Render a dim, centered "No wifi connection" message with a wifi-off icon to its left."""
    w, h = canvas.width, canvas.height
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
    icon = _wifi_off_icon(icon_size, _MESSAGE_COLOR)

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
    blit(canvas, img)
