from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image

from canvas.base import Canvas
from app_base import DisplayApp
from grid import SizeConstraints
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import render_text, can_fit_text, draw_status_message
from libraries.open_meteo.library import (
    OpenMeteoLibrary,
    aqi_color,
    aqi_label,
    condition_for_code,
    condition_label,
    weather_icon_img,
)

logger = logging.getLogger(__name__)

_VIEWS: tuple[str, ...] = ("current", "daily_forecast", "weekly_forecast")

# Height of the color-coded AQI bar drawn under each forecast column when the
# panel is too short to print the number (plus 1px of breathing room above it).
_AQI_BAR_H = 2
# Below this panel height the forecast views fall back to the bar; above it the
# numeric AQI fits under the temperatures without squeezing out the icon.
_AQI_TEXT_MIN_H = 48
# Prefixed to the numeric footer on columns wide enough to carry it, matching how
# the current view spells out the reading in its detail row.
_AQI_PREFIX = "AQI "
# Breathing room between the temps and the AQI line below them, so the two rows
# of numbers read as separate readings rather than one block.
_AQI_TEXT_GAP = 4


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


_DETAIL_SEP = "  "

# Separators for the weekly view's "lo - hi" range, widest first. Columns too
# narrow for even the tightest one stack the temps instead.
_TEMP_RANGE_SEPS = (" - ", "-")


def _temp_str(value: float) -> str:
    return f"{round(value)}°"


def _temp_range_text(lo: float, hi: float, sep: str) -> str:
    return f"{_temp_str(lo)}{sep}{_temp_str(hi)}"


def _sep_ink_cx(sep: str, size: int) -> float:
    """Centre of the separator's *ink*, in its own render.

    Not the middle of the render: the glyph's advance carries a blank trailing
    column, so centring by width would leave the dash a pixel off.
    """
    img = render_text(sep, (255, 255, 255), size)
    box = img.getbbox()
    return (box[0] + box[2] - 1) / 2 if box else (img.width - 1) / 2


def _temp_range_width(lo: float, hi: float, sep: str, size: int) -> int:
    """Column width a dash-centred range needs: the wider end counted twice.

    The separator is pinned to the column centre, so whichever end is wider sets
    the reach on both sides of it.
    """
    ends = max(render_text(_temp_str(v), (255, 255, 255), size).width for v in (lo, hi))
    return 2 * ends + render_text(sep, (255, 255, 255), size).width


def _temp_range_sep(days: list[dict[str, Any]], size: int, max_w: int) -> str | None:
    """Widest separator that spells every day's range inside `max_w`, else None.

    Decided once for the whole row so neighbouring columns space their ranges
    alike, and None whenever a day is missing either end of its range.
    """
    pairs = [(d.get("temp_min"), d.get("temp_max")) for d in days]
    if any(lo is None or hi is None for lo, hi in pairs):
        return None
    return next(
        (
            sep
            for sep in _TEMP_RANGE_SEPS
            if all(_temp_range_width(lo, hi, sep, size) <= max_w for lo, hi in pairs)
        ),
        None,
    )


def _join_details(items: list[str], idx: int | None) -> tuple[str, tuple[int, int] | None]:
    """Join a detail row, reporting where item `idx` lands in the joined string.

    The span is None when that item is not in `items` — the callers trim the row
    to fit, so the highlighted item may have been dropped entirely.
    """
    joined = _DETAIL_SEP.join(items)
    if idx is None or idx >= len(items):
        return joined, None
    start = len(_DETAIL_SEP.join(items[:idx])) + (len(_DETAIL_SEP) if idx else 0)
    return joined, (start, start + len(items[idx]))


def _tint_run(
    img: Image.Image, text: str, start: int, end: int, color: tuple[int, int, int], size: int
) -> None:
    """Recolor `text[start:end]` in an already-rendered `text` image, in place.

    Re-rendering the *whole* string in the new color and pasting back only that
    horizontal slice keeps the glyph geometry identical to `img`, so the two
    colors line up exactly — cheaper to reason about than laying out separately
    rendered runs with a guessed inter-word gap. The slice bounds come from
    prefix renders, which share the full string's left bearing; the separator
    swept in at the left edge is blank in both renders.
    """
    tinted = render_text(text, color, size)
    x0 = render_text(text[:start], color, size).width if start else 0
    x1 = min(render_text(text[:end], color, size).width, tinted.width, img.width)
    if x1 <= x0:
        return
    img.paste(tinted.crop((x0, 0, x1, tinted.height)), (x0, 0))


def _dim(color: tuple[int, int, int], factor: float = 0.6) -> tuple[int, int, int]:
    return tuple(max(0, int(c * factor)) for c in color)  # type: ignore[return-value]


def _format_hour_label(iso_time: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_time)
    except (TypeError, ValueError):
        return "--"
    hour = dt.hour % 12 or 12
    return f"{hour}{'AM' if dt.hour < 12 else 'PM'}"


def _format_day_label(iso_date: str, *, short: bool) -> str:
    try:
        d = datetime.fromisoformat(iso_date)
    except (TypeError, ValueError):
        return "--"
    return d.strftime("%a")[:2] if short else d.strftime("%a")


def _build_debug_weather() -> dict[str, Any]:
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hourly_codes = [0, 0, 1, 1, 2, 2, 3, 61, 61, 80, 2, 1, 0, 0, 1, 2, 3, 3, 95, 61, 71, 71, 2, 1]
    # Walks every AQI band so debug mode exercises the full color ramp.
    hourly_aqi = [18, 34, 47, 62, 88, 105, 133, 158, 184, 215, 268, 320]
    hourly = [
        {
            "time": (now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M"),
            "temperature": 58 + (i % 12),
            "weather_code": hourly_codes[i % len(hourly_codes)],
            "aqi": hourly_aqi[i % len(hourly_aqi)],
        }
        for i in range(48)
    ]
    daily_codes = [0, 2, 61, 71, 95, 3, 1]
    daily_aqi = [42, 78, 120, 165, 240, 310, 55]
    today = now.date()
    daily = [
        {
            "date": (today + timedelta(days=d)).isoformat(),
            "weather_code": daily_codes[d],
            "temp_max": 75 - d,
            "temp_min": 55 + d,
            "aqi": daily_aqi[d],
        }
        for d in range(len(daily_codes))
    ]
    return {
        "timezone": None,
        "current": {
            "temperature": 72.0,
            "feels_like": 70.0,
            "humidity": 48,
            "wind_speed": 6.0,
            "weather_code": 2,
            "is_day": True,
            "aqi": 42,
        },
        "hourly": hourly,
        "daily": daily,
    }


class WeatherApp(DisplayApp):
    id: ClassVar[str] = "weather"
    name: ClassVar[str] = "Weather"
    description: ClassVar[str] = (
        "Current conditions, today's hourly outlook, and a 7-day forecast for "
        "your location, with scalable condition icons via Open-Meteo"
    )
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    libraries: ClassVar[list[str]] = ["open_meteo", "location"]
    size_constraints: ClassVar[SizeConstraints] = SizeConstraints(min_width=64, min_height=32)
    global_config_schema: ClassVar[dict[str, Any]] = {}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Weather",
        "properties": {
            "location": {
                "type": "object",
                "title": "Location",
                "x-input-type": "location",
                "x-default-from-library": {"library": "location", "path": "location"},
                "default": {"latitude": 0.0, "longitude": 0.0},
                "properties": {
                    "latitude": {"type": "number", "default": 0.0},
                    "longitude": {"type": "number", "default": 0.0},
                },
            },
            "display_mode": {
                "type": "string",
                "title": "Display mode",
                "enum": ["cycle", "current", "daily_forecast", "weekly_forecast"],
                "x-enum-labels": {
                    "cycle": "Cycle through all views",
                    "current": "Current weather",
                    "daily_forecast": "Today's forecast",
                    "weekly_forecast": "7-day forecast",
                },
                "default": "cycle",
            },
            "units": {
                "type": "string",
                "title": "Temperature units",
                "enum": ["fahrenheit", "celsius"],
                "x-enum-labels": {"fahrenheit": "Fahrenheit (°F)", "celsius": "Celsius (°C)"},
                "default": "fahrenheit",
            },
            "show_air_quality": {
                "type": "boolean",
                "title": "Show air quality (AQI)",
                "description": (
                    "Adds the US EPA air quality index to every view, color coded "
                    "from green (good) to red and purple (unhealthy)"
                ),
                "default": False,
            },
            "cycle_seconds": {
                "type": "number",
                "title": "Seconds per view (cycle mode)",
                "default": 10,
                "minimum": 3,
            },
            "text_color": {
                "type": "string",
                "title": "Text color",
                "x-input-type": "color",
                "default": "#C8C8C8",
            },
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 600,
                "minimum": 60,
            },
            "debug": {
                "type": "boolean",
                "title": "Debug mode (static data)",
                "default": False,
            },
        },
        "required": ["location"],
    }

    def __init__(
        self,
        config: dict[str, Any],
        canvas: Canvas,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(config, canvas, global_config, library_configs)
        self._open_meteo = OpenMeteoLibrary(self.library_configs.get("open_meteo", {}))
        self._data: dict[str, Any] = {}
        self._fetched_once: bool = False
        self._view_idx: int = 0
        self._view_last_ts: float = time.monotonic()
        self._anim_start: float | None = None
        self._anim_t: float = 0.0

    # ── Data fetching ──────────────────────────────────────────────────────────

    async def fetch_data(self) -> None:
        if self.config.get("debug", False):
            self._data = _build_debug_weather()
            self._fetched_once = True
            return

        loc = self.config.get("location", {})
        lat = float(loc.get("latitude", 0.0) if isinstance(loc, dict) else 0.0)
        lon = float(loc.get("longitude", 0.0) if isinstance(loc, dict) else 0.0)
        if lat == 0.0 and lon == 0.0:
            lib_loc = self.library_configs.get("location", {}).get("location", {})
            if isinstance(lib_loc, dict):
                lat = float(lib_loc.get("latitude", 0.0))
                lon = float(lib_loc.get("longitude", 0.0))

        unit = self.config.get("units", "fahrenheit")
        self._data = await self._open_meteo.fetch_weather(
            lat, lon, unit, include_air_quality=self._show_air_quality()
        )
        self._fetched_once = True

    def _show_air_quality(self) -> bool:
        return bool(self.config.get("show_air_quality", False))

    def _hourly_from_now(self) -> list[dict[str, Any]]:
        hourly = self._data.get("hourly", [])
        if not hourly:
            return []

        now = datetime.now()
        tz_name = self._data.get("timezone")
        if tz_name:
            try:
                now = datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
            except ZoneInfoNotFoundError:
                pass
        now = now.replace(minute=0, second=0, microsecond=0)

        for i, entry in enumerate(hourly):
            try:
                dt = datetime.fromisoformat(entry.get("time", ""))
            except (TypeError, ValueError):
                continue
            if dt >= now:
                return hourly[i:]
        return []

    # ── Rendering ──────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        # Icon-animation clock: 0.0 on the first rendered frame (which keeps
        # single-frame snapshot renders deterministic), wall-time thereafter.
        now = time.monotonic()
        if self._anim_start is None:
            self._anim_start = now
        self._anim_t = now - self._anim_start

        if not self._fetched_once:
            self._draw_message("Loading...")
            return
        if not self._data or not self._data.get("current"):
            self._draw_message("Weather unavailable")
            return

        mode = self.config.get("display_mode", "cycle")
        if mode == "cycle":
            mode = self._cycled_view()

        if mode == "daily_forecast":
            self._draw_daily_forecast()
        elif mode == "weekly_forecast":
            self._draw_weekly_forecast()
        else:
            self._draw_current()

    def _cycled_view(self) -> str:
        now = time.monotonic()
        cycle_s = max(3.0, float(self.config.get("cycle_seconds", 10.0)))
        if now - self._view_last_ts >= cycle_s:
            self._view_idx = (self._view_idx + 1) % len(_VIEWS)
            self._view_last_ts = now
        return _VIEWS[self._view_idx]

    def _unit_symbol(self) -> str:
        return "F" if self.config.get("units", "fahrenheit") == "fahrenheit" else "C"

    def _draw_current(self) -> None:
        w, h = self.canvas.width, self.canvas.height
        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))
        unit = self._unit_symbol()

        current = self._data.get("current", {})
        condition = condition_for_code(current.get("weather_code"))
        night = not current.get("is_day", True)

        img = Image.new("RGB", (w, h))
        pad = 2

        icon_size = max(14, min(h - 2 * pad, w // 3))
        icon = weather_icon_img(condition, icon_size, night=night, t=self._anim_t)
        img.paste(icon, (pad, (h - icon_size) // 2))

        text_x = pad + icon_size + 4
        avail_w = max(8, w - text_x - pad)

        temp = current.get("temperature")
        temp_str = f"{round(temp)}°{unit}" if temp is not None else f"--°{unit}"
        temp_size = max(10, min(h // 2, 28))
        temp_img = render_text(_clip_text(temp_str, temp_size, avail_w), text_color, temp_size)

        label_size = max(7, temp_size // 2)
        label_img = render_text(_clip_text(condition_label(condition), label_size, avail_w), text_color, label_size)

        lines = [temp_img, label_img]

        details: list[str] = []
        aqi = current.get("aqi") if self._show_air_quality() else None
        aqi_idx: int | None = None
        feels = current.get("feels_like")
        if feels is not None:
            details.append(f"Feels {round(feels)}°")
        humidity = current.get("humidity")
        if humidity is not None:
            details.append(f"Hum {round(humidity)}%")
        if aqi is not None:
            aqi_idx = len(details)
            details.append(f"AQI {round(aqi)}")
        wind = current.get("wind_speed")
        if wind is not None:
            details.append(f"Wind {round(wind)}")

        if details:
            detail_size = max(6, label_size - 2)
            # Try the fullest combination that fits the available width; a
            # partial join (e.g. "Feels 70°  Hum") reads worse than a shorter
            # but complete one, so prefer dropping whole items over clipping.
            # Where there is room, the AQI item also spells out its category.
            candidates: list[tuple[str, tuple[int, int] | None]] = []
            for n in range(len(details), 0, -1):
                if aqi_idx is not None and aqi_idx < n:
                    named = details[:n]
                    named[aqi_idx] = f"AQI {round(aqi)} {aqi_label(aqi)}"
                    candidates.append(_join_details(named, aqi_idx))
                candidates.append(_join_details(details[:n], aqi_idx))
            chosen, aqi_span = next(
                ((c, s) for c, s in candidates if can_fit_text(avail_w, detail_size, c)), ("", None)
            )
            if chosen:
                detail_img = render_text(chosen, text_color, detail_size)
                if aqi_span is not None:
                    _tint_run(detail_img, chosen, *aqi_span, aqi_color(aqi), detail_size)
                used_h = sum(li.height for li in lines) + 2 * len(lines)
                if used_h + detail_img.height <= h:
                    lines.append(detail_img)

        total_h = sum(li.height for li in lines) + (len(lines) - 1) * 2
        y = max(0, (h - total_h) // 2)
        for li in lines:
            img.paste(li, (text_x, y))
            y += li.height + 2

        blit(self.canvas, img)

    # ── Air-quality footer (forecast columns) ──────────────────────────────────

    def _aqi_footer_plan(
        self, entries: list[dict[str, Any]], h: int, col_max_w: int
    ) -> tuple[str, int, int, str]:
        """Decide how each column shows its AQI: (mode, height, size, prefix).

        ``mode`` is "text" (the number, color coded), "bar" (a color-coded bar,
        for panels too short to spare a text line without evicting the weather
        icon), or "none". ``height`` is the vertical space the caller must
        reserve at the bottom of the column, gap included. ``prefix`` labels the
        number where the widest reading still fits the column with it.
        """
        if not self._show_air_quality():
            return ("none", 0, 0, "")
        if not any(entry.get("aqi") is not None for entry in entries):
            return ("none", 0, 0, "")
        if h < _AQI_TEXT_MIN_H:
            return ("bar", _AQI_BAR_H + 1, 0, "")
        size = _fit_size("199", min(h // 8, 9), col_max_w)
        # One decision for every column, so the label never comes and goes
        # between neighbours with different digit counts.
        widest = max(
            (str(round(e["aqi"])) for e in entries if e.get("aqi") is not None),
            key=lambda s: render_text(s, (255, 255, 255), size).width,
        )
        prefix = _AQI_PREFIX if can_fit_text(col_max_w, size, _AQI_PREFIX + widest) else ""
        height = render_text("199", (255, 255, 255), size).height + _AQI_TEXT_GAP
        return ("text", height, size, prefix)

    def _draw_aqi_footer(
        self,
        img: Image.Image,
        plan: tuple[str, int, int, str],
        aqi: float | None,
        cx: int,
        col_w: int,
    ) -> None:
        """Draw one column's AQI indicator, bottom-anchored and centred on `cx`."""
        mode, _, size, prefix = plan
        if mode == "none" or aqi is None:
            return

        color = aqi_color(aqi)
        if mode == "bar":
            bar_w = max(4, min(col_w - 4, 16))
            x0 = cx - bar_w // 2
            y0 = img.height - _AQI_BAR_H - 1
            img.paste(color, (x0, y0, x0 + bar_w, y0 + _AQI_BAR_H))
            return

        text = _clip_text(f"{prefix}{round(aqi)}", size, max(6, col_w - 2))
        aqi_img = render_text(text, color, size)
        img.paste(aqi_img, (cx - aqi_img.width // 2, img.height - aqi_img.height - 1))

    def _draw_temp_range(
        self,
        img: Image.Image,
        lo: float,
        hi: float,
        sep: str,
        size: int,
        color: tuple[int, int, int],
        cx: int,
        y: int,
    ) -> None:
        """Draw "lo° - hi°" on one line, the low dimmed like the stacked layout
        dims it. The caller has already checked it fits.

        `cx` pins the separator, not the string: the dash lands on the column
        centre and stays lined up with its neighbours' whatever the two ends
        measure. Rendered as one string and tinted, not as three pasted runs —
        the renderer crops each image to its ink, so a separately drawn
        separator would ride up to the top of the line instead of sitting on
        the digits' centre line.
        """
        low_str = _temp_str(lo)
        text = _temp_range_text(lo, hi, sep)
        range_img = render_text(text, color, size)
        _tint_run(range_img, text, 0, len(low_str), _dim(color), size)
        low_w = render_text(low_str, color, size).width
        img.paste(range_img, (round(cx - low_w - _sep_ink_cx(sep, size)), y))

    def _draw_daily_forecast(self) -> None:
        w, h = self.canvas.width, self.canvas.height
        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))

        slots = self._hourly_from_now()
        n = max(3, min(6, w // 20))
        step = 3
        picks = slots[: n * step : step][:n]
        if not picks:
            self._draw_message("No forecast data")
            return

        img = Image.new("RGB", (w, h))
        slot_w = w // len(picks)
        col_pad = 2
        col_max_w = max(6, slot_w - col_pad)

        label_size = _fit_size("12PM", min(h // 6, 12), col_max_w)
        label_h = render_text("9AM", text_color, label_size).height
        temp_size = _fit_size("100°", min(h // 6, 14), col_max_w)
        temp_h = render_text("100°", text_color, temp_size).height
        aqi_plan = self._aqi_footer_plan(picks, h, col_max_w)

        # Label at top, temp anchored to the bottom (above the AQI footer, when
        # shown); the icon gets exactly the measured space between them and is
        # dropped when too small to read.
        temp_y = h - temp_h - 1 - aqi_plan[1]
        icon_top = label_h + 3
        icon_size = min(temp_y - 2 - icon_top, slot_w - 4)
        show_icon = icon_size >= 8
        # Centre the icon in its band (it may be width-capped below band height)
        icon_y = icon_top + max(0, (temp_y - 2 - icon_top - icon_size) // 2)

        for i, entry in enumerate(picks):
            x0 = i * slot_w
            col_w = slot_w if i < len(picks) - 1 else w - x0
            cx = x0 + col_w // 2
            max_w = max(6, col_w - col_pad)

            label = _clip_text(_format_hour_label(entry.get("time", "")), label_size, max_w)
            label_img = render_text(label, text_color, label_size)
            img.paste(label_img, (cx - label_img.width // 2, 1))

            if show_icon:
                condition = condition_for_code(entry.get("weather_code"))
                icon = weather_icon_img(condition, icon_size, t=self._anim_t)
                img.paste(icon, (cx - icon_size // 2, icon_y))

            temp = entry.get("temperature")
            temp_str = f"{round(temp)}°" if temp is not None else "--°"
            temp_img = render_text(_clip_text(temp_str, temp_size, max_w), text_color, temp_size)
            img.paste(temp_img, (cx - temp_img.width // 2, temp_y))

            self._draw_aqi_footer(img, aqi_plan, entry.get("aqi"), cx, col_w)

        blit(self.canvas, img)

    def _draw_weekly_forecast(self) -> None:
        w, h = self.canvas.width, self.canvas.height
        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))

        daily = self._data.get("daily", [])
        if not daily:
            self._draw_message("No forecast data")
            return

        max_cols = max(3, w // 18)
        days = daily[: min(len(daily), max_cols, 7)]

        img = Image.new("RGB", (w, h))
        slot_w = w // len(days)
        col_pad = 2
        col_max_w = max(6, slot_w - col_pad)
        short_labels = slot_w < 22
        day_sample = "Mo" if short_labels else "Mon"

        label_size = _fit_size(day_sample, min(h // 7, 11), col_max_w)
        label_h = render_text(day_sample, text_color, label_size).height
        temp_size = _fit_size("100°", min(h // 8, 10), col_max_w)
        temp_h = render_text("100°", text_color, temp_size).height
        aqi_plan = self._aqi_footer_plan(days, h, col_max_w)
        aqi_h = aqi_plan[1]
        range_sep = _temp_range_sep(days, temp_size, col_max_w)

        # Label at top, temps anchored to the bottom above the AQI footer, icon
        # in the measured middle. The temps share one line as a "lo - hi" range;
        # columns too narrow to spell that stack hi over lo with a 1px gap, and
        # degrade explicitly from there: drop the lo before the icon, and the
        # icon before the hi.
        icon_top = label_h + 3
        stacked = range_sep is None and h - 1 - aqi_h - 2 * temp_h - 1 - 2 - icon_top >= 8
        temps_h = (2 * temp_h + 1) if stacked else temp_h
        temp_y = h - temps_h - 1 - aqi_h
        icon_size = min(temp_y - 2 - icon_top, slot_w - 4)
        show_icon = icon_size >= 8
        # Centre the icon in its band (it may be width-capped below band height)
        icon_y = icon_top + max(0, (temp_y - 2 - icon_top - icon_size) // 2)

        for i, entry in enumerate(days):
            x0 = i * slot_w
            col_w = slot_w if i < len(days) - 1 else w - x0
            cx = x0 + col_w // 2
            max_w = max(6, col_w - col_pad)

            label = _clip_text(_format_day_label(entry.get("date", ""), short=short_labels), label_size, max_w)
            label_img = render_text(label, text_color, label_size)
            img.paste(label_img, (cx - label_img.width // 2, 1))

            if show_icon:
                condition = condition_for_code(entry.get("weather_code"))
                icon = weather_icon_img(condition, icon_size, t=self._anim_t)
                img.paste(icon, (cx - icon_size // 2, icon_y))

            hi = entry.get("temp_max")
            lo = entry.get("temp_min")
            y = temp_y
            if range_sep is not None:
                self._draw_temp_range(img, lo, hi, range_sep, temp_size, text_color, cx, y)
            else:
                if hi is not None:
                    hi_img = render_text(_clip_text(f"{round(hi)}°", temp_size, max_w), text_color, temp_size)
                    img.paste(hi_img, (cx - hi_img.width // 2, y))
                    y += temp_h + 1
                if stacked and lo is not None:
                    lo_img = render_text(_clip_text(f"{round(lo)}°", temp_size, max_w), _dim(text_color), temp_size)
                    img.paste(lo_img, (cx - lo_img.width // 2, y))

            self._draw_aqi_footer(img, aqi_plan, entry.get("aqi"), cx, col_w)

        blit(self.canvas, img)

    def _draw_message(self, msg: str) -> None:
        draw_status_message(self.canvas, msg)
