from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image

from canvas.base import Canvas
from app_base import DisplayApp
from grid import SizeConstraints
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import render_text, can_fit_text, draw_status_message
from libraries.location.library import LocationLibrary
from libraries.timezones.library import (
    city_name,
    current_time,
    list_timezone_options,
    resolve_zone,
)

logger = logging.getLogger(__name__)

_TZ_OPTIONS: list[dict[str, str]] = list_timezone_options()
_TZ_ENUM: list[str] = [c["timezone"] for c in _TZ_OPTIONS]
_TZ_LABELS: dict[str, str] = {c["timezone"]: c["label"] for c in _TZ_OPTIONS}

_DEFAULT_COLOR: str = "#C8C8C8"

_MIN_CELL_W: int = 64
_MIN_CELL_H: int = 28


def _clip_text(text: str, size: int, max_w: int) -> str:
    while text:
        if render_text(text, (255, 255, 255), size).width <= max_w:
            return text
        text = text[:-1]
    return ""


def _fit_size(sample: str, max_size: int, max_width: int, min_size: int = 6) -> int:
    """Largest font size <= max_size at which `sample` fits within max_width."""
    size = max(min_size, max_size)
    while size > min_size and not can_fit_text(max_width, size, sample):
        size -= 1
    return size


def _dim(color: tuple[int, int, int], factor: float = 0.6) -> tuple[int, int, int]:
    return tuple(max(0, int(c * factor)) for c in color)  # type: ignore[return-value]


def _parse_city_item(item: Any) -> tuple[str | None, str | None]:
    """Normalize one configured city into (timezone, color hex or None).

    Accepts the current per-city object form ``{"timezone", "color"}`` as well
    as the legacy bare-timezone string, so instances saved before per-city
    colors keep working.
    """
    if isinstance(item, str):
        return (item or None), None
    if isinstance(item, dict):
        tz_name = item.get("timezone")
        if not isinstance(tz_name, str) or not tz_name:
            return None, None
        color = item.get("color")
        return tz_name, (color if isinstance(color, str) and color else None)
    return None, None


def _format_time(dt: datetime, time_fmt: str) -> tuple[str, str]:
    """Returns (display string, representative sample for sizing)."""
    if time_fmt == "24h":
        return f"{dt.hour}:{dt.minute:02d}", "00:00"
    h_val = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{h_val}:{dt.minute:02d} {ampm}", "12:00 PM"


# Each clock entry is (timezone, on-screen label, per-entry color hex or None).
# A None color falls back to the configured default/local text color.
ClockEntry = tuple[str, str, str | None]

_DEBUG_ENTRIES: list[ClockEntry] = [
    ("America/Chicago", "Chicago", None),
    ("Europe/London", "London", "#7FB2FF"),
    ("Asia/Tokyo", "Tokyo", "#FF8A8A"),
    ("Australia/Sydney", "Sydney", "#86E08C"),
    ("Pacific/Honolulu", "Honolulu", "#FFD27F"),
]


class WorldClockApp(DisplayApp):
    id: ClassVar[str] = "world_clock"
    name: ClassVar[str] = "World Clock"
    description: ClassVar[str] = (
        "Live local and world-city clocks — add any world city by typeahead "
        "search, give each its own text color, and see their current dates and "
        "times alongside your own"
    )
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    libraries: ClassVar[list[str]] = ["timezones", "location"]
    size_constraints: ClassVar[SizeConstraints] = SizeConstraints(min_width=64, min_height=32)
    global_config_schema: ClassVar[dict[str, Any]] = {}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "World Clock",
        "properties": {
            "show_local": {
                "type": "boolean",
                "title": "Show local time",
                "description": "Include your home location's current time, resolved via the Location library",
                "default": True,
            },
            "cities": {
                "type": "array",
                "title": "Clocks",
                "description": (
                    "Your local time plus any world city — search by typeahead "
                    "and give each clock its own text color."
                ),
                "x-input-type": "city-clock-list",
                "items": {
                    "type": "object",
                    "properties": {
                        "timezone": {"type": "string", "enum": _TZ_ENUM},
                        "color": {
                            "type": "string",
                            "x-input-type": "color",
                            "default": _DEFAULT_COLOR,
                        },
                    },
                },
                "x-enum-labels": _TZ_LABELS,
                "default": [],
            },
            "cycle_seconds": {
                "type": "number",
                "title": "Seconds per page",
                "default": 8,
                "minimum": 3,
            },
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 3600,
                "minimum": 60,
            },
            "debug": {
                "type": "boolean",
                "title": "Debug mode (static data)",
                "default": False,
            },
        },
    }

    def __init__(
        self,
        config: dict[str, Any],
        canvas: Canvas,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(config, canvas, global_config, library_configs)
        self._entries: list[ClockEntry] = []
        self._home_tz: str | None = None
        self._fetched_once: bool = False
        self._local_key: tuple[float, float] | None = None
        self._local_entry: tuple[str, str] | None = None
        self._page_idx: int = 0
        self._page_last_ts: float = time.monotonic()

    # ── Data fetching ──────────────────────────────────────────────────────────

    async def fetch_data(self) -> None:
        if self.config.get("debug", False):
            self._entries = list(_DEBUG_ENTRIES)
            self._home_tz = _DEBUG_ENTRIES[0][0]
            self._fetched_once = True
            return

        local = await self._resolve_local()
        self._home_tz = local[0] if local is not None else None

        entries: list[ClockEntry] = []
        if self.config.get("show_local", True) and local is not None:
            # Local time uses the default/local text color (None -> fallback).
            entries.append((local[0], local[1], None))

        for item in self.config.get("cities", []):
            tz_name, color = _parse_city_item(item)
            if tz_name:
                entries.append((tz_name, city_name(tz_name), color))

        self._entries = entries
        self._fetched_once = True

    async def _resolve_local(self) -> tuple[str, str] | None:
        """Resolve (timezone, label) for the user's home location.

        Cached by (lat, lon) so the network-bound reverse-geocode in
        `get_city_country` only runs when the location actually changes —
        mirrors `_get_user_tz` in `apps/sports/app.py`.
        """
        lib_loc = self.library_configs.get("location", {}).get("location", {})
        lat = float(lib_loc.get("latitude", 0.0)) if isinstance(lib_loc, dict) else 0.0
        lon = float(lib_loc.get("longitude", 0.0)) if isinstance(lib_loc, dict) else 0.0

        key = (lat, lon)
        if key == self._local_key:
            return self._local_entry

        self._local_key = key
        if lat == 0.0 and lon == 0.0:
            self._local_entry = None
            return None

        location_lib = LocationLibrary(self.library_configs.get("location", {}))
        tz_name = location_lib.get_timezone()
        if not tz_name:
            self._local_entry = None
            return None

        label = city_name(tz_name)
        try:
            city_country = await location_lib.get_city_country()
            city = city_country.get("city", "")
            if city:
                label = city
        except Exception as exc:
            logger.warning("Reverse geocode for local clock failed: %s", exc)

        self._local_entry = (tz_name, label)
        return self._local_entry

    # ── Rendering ──────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        if not self._entries:
            msg = "Loading..." if not self._fetched_once else "Add a city"
            self._draw_message(msg)
            return

        w, h = self.canvas.width, self.canvas.height
        # The local-time color doubles as the fallback tint for any city saved
        # without its own color. ``text_color`` is the pre-per-clock-color key,
        # migrated here so older instances keep their chosen color.
        default_color = parse_color(
            str(self.config.get("local_color") or self.config.get("text_color") or _DEFAULT_COLOR)
        )
        time_fmt = str(self.library_configs.get("location", {}).get("time_format", "12h"))

        now_utc = datetime.now(timezone.utc)
        home_zone = resolve_zone(self._home_tz) if self._home_tz else None
        home_date: date | None = now_utc.astimezone(home_zone).date() if home_zone else None

        rows: list[tuple[str, dict[str, Any], tuple[int, int, int]]] = []
        for tz_name, label, color in self._entries:
            info = current_time(tz_name, reference=now_utc)
            if info is not None:
                rows.append((label, info, parse_color(color) if color else default_color))

        if not rows:
            self._draw_message("No data")
            return

        cols = max(1, min(w // _MIN_CELL_W, len(rows)))
        rows_per_page = max(1, h // _MIN_CELL_H)
        per_page = cols * rows_per_page

        if len(rows) > per_page:
            now = time.monotonic()
            cycle_s = max(3.0, float(self.config.get("cycle_seconds", 8.0)))
            n_pages = math.ceil(len(rows) / per_page)
            if now - self._page_last_ts >= cycle_s:
                self._page_idx = (self._page_idx + 1) % n_pages
                self._page_last_ts = now
            self._page_idx = min(self._page_idx, n_pages - 1)
            start = self._page_idx * per_page
            page = rows[start:start + per_page]
        else:
            self._page_idx = 0
            page = rows

        n_rows_used = max(1, math.ceil(len(page) / cols))
        cell_w = w // cols
        cell_h = h // n_rows_used

        img = Image.new("RGB", (w, h))
        for i, (label, info, color) in enumerate(page):
            col, row = i % cols, i // cols
            x0 = col * cell_w
            y0 = row * cell_h
            actual_w = cell_w if col < cols - 1 else w - x0
            actual_h = cell_h if row < n_rows_used - 1 else h - y0
            self._draw_clock_cell(img, label, info, x0, y0, actual_w, actual_h, color, time_fmt, home_date)

        blit(self.canvas, img)

    def _draw_clock_cell(
        self,
        img: Image.Image,
        label: str,
        info: dict[str, Any],
        x0: int,
        y0: int,
        w: int,
        h: int,
        text_color: tuple[int, int, int],
        time_fmt: str,
        home_date: date | None,
    ) -> None:
        pad = 2
        max_w = max(6, w - 2 * pad)
        dt: datetime = info["datetime"]

        time_str, sample = _format_time(dt, time_fmt)
        time_size = _fit_size(sample, max(10, min(h // 2, 28)), max_w)
        label_size = _fit_size(label, max(7, min(h // 4, 14)), max_w)

        time_img = render_text(_clip_text(time_str, time_size, max_w), text_color, time_size)
        label_img = render_text(_clip_text(label, label_size, max_w), text_color, label_size)
        lines = [label_img, time_img]

        weekday = dt.strftime("%a")
        day_diff = (dt.date() - home_date).days if home_date is not None else 0
        extra_str = f"{weekday}  {day_diff:+d}d" if day_diff else weekday
        extra_size = max(6, label_size - 2)
        extra_img = render_text(_clip_text(extra_str, extra_size, max_w), _dim(text_color), extra_size)
        used_h = sum(li.height for li in lines) + 2 * len(lines)
        if used_h + extra_img.height <= h:
            lines.append(extra_img)

        total_h = sum(li.height for li in lines) + (len(lines) - 1) * 2
        y = y0 + max(0, (h - total_h) // 2)
        for li in lines:
            img.paste(li, (x0 + (w - li.width) // 2, y))
            y += li.height + 2

    def _draw_message(self, msg: str) -> None:
        draw_status_message(self.canvas, msg)
