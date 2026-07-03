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
import time
from io import BytesIO
from pathlib import Path

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
# Consecutive failed checks required before we declare the link down and show
# the overlay. Hysteresis: a brief blip (one or two failed probes) no longer
# flashes the banner, so the display only switches on a sustained outage.
_DEFAULT_FAILURE_THRESHOLD = 3
# While offline, re-log the state at most this often (seconds) so a long outage
# stays visible on the journal timeline without spamming it every check.
_DEFAULT_OFFLINE_LOG_INTERVAL = 60.0


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

    Applies hysteresis: `is_online` only flips to False after
    `failure_threshold` *consecutive* failed probes, so a momentary blip
    doesn't flash the overlay; it flips back to True on the first success so
    apps return promptly. Every state transition is logged (and the offline
    state re-logged periodically) so the journal shows a wifi timeline
    alongside the vcgencmd temp/throttle health line from start.sh -- if the
    Pi is dropping the link, the two lines together tell you whether it
    coincides with undervoltage/thermal events.
    """

    def __init__(
        self,
        check_interval: float = _DEFAULT_CHECK_INTERVAL,
        timeout: float = _DEFAULT_TIMEOUT,
        failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
        offline_log_interval: float = _DEFAULT_OFFLINE_LOG_INTERVAL,
    ) -> None:
        self._check_interval = check_interval
        self._timeout = timeout
        self._failure_threshold = max(1, failure_threshold)
        self._offline_log_interval = offline_log_interval
        self._is_online = True
        self._consecutive_failures = 0
        self._offline_since: float | None = None
        self._last_offline_log = 0.0
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
                reachable = await loop.run_in_executor(None, check_internet, self._timeout)
            except Exception as exc:
                logger.warning("probe raised %s", exc)
                reachable = False
            self._record(reachable)
            await asyncio.sleep(self._check_interval)

    def _record(self, reachable: bool) -> None:
        """Fold one probe result into the online/offline state with hysteresis."""
        now = time.monotonic()

        if reachable:
            self._consecutive_failures = 0
            if not self._is_online:
                offline_for = now - self._offline_since if self._offline_since is not None else 0.0
                logger.info("internet reachable again after %.0fs offline", offline_for)
                self._is_online = True
                self._offline_since = None
            return

        self._consecutive_failures += 1
        if self._is_online:
            if self._consecutive_failures >= self._failure_threshold:
                self._is_online = False
                self._offline_since = now
                self._last_offline_log = now
                logger.warning(
                    "internet unreachable after %d consecutive failed checks; "
                    "showing offline overlay",
                    self._consecutive_failures,
                )
            else:
                # Below threshold: a transient blip. Don't flip; note at debug only.
                logger.debug(
                    "probe failed (%d/%d) - still treating link as up",
                    self._consecutive_failures,
                    self._failure_threshold,
                )
        elif now - self._last_offline_log >= self._offline_log_interval:
            # Already offline: heartbeat so a long outage stays on the timeline.
            self._last_offline_log = now
            offline_for = now - self._offline_since if self._offline_since is not None else 0.0
            logger.warning(
                "still offline after %.0fs (%d failed checks)",
                offline_for,
                self._consecutive_failures,
            )


# ── "No wifi connection" overlay ────────────────────────────────────────────

_MESSAGE_COLOR: tuple[int, int, int] = (255, 255, 255)  # white, matches the icon's wifi glyph
_MESSAGE_TEXT = "No wifi connection"
_MESSAGE_FONT_MAX = 14


# No-wifi badge icon (red circle, white wifi glyph, transparent background),
# supplied by the user.
_WIFI_OFF_SVG_PATH = Path(__file__).parent / "no_wifi.svg"

_icon_cache: dict[int, Image.Image] = {}


def _wifi_off_icon(size: int) -> Image.Image:
    """Rasterize the no-wifi badge SVG at `size` px, cached (it never changes)."""
    cached = _icon_cache.get(size)
    if cached is not None:
        return cached
    png = cairosvg.svg2png(url=str(_WIFI_OFF_SVG_PATH), output_width=size, output_height=size)
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
