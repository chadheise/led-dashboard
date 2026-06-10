from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image

from canvas.base import Canvas
from app_base import DisplayApp
from grid import SizeConstraints
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import render_text, can_fit_text
from libraries.open_meteo.library import OpenMeteoLibrary, condition_for_code, condition_label, weather_icon_img

logger = logging.getLogger(__name__)

_VIEWS: tuple[str, ...] = ("current", "daily_forecast", "weekly_forecast")


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
    hourly = [
        {
            "time": (now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M"),
            "temperature": 58 + (i % 12),
            "weather_code": hourly_codes[i % len(hourly_codes)],
        }
        for i in range(48)
    ]
    daily_codes = [0, 2, 61, 71, 95, 3, 1]
    today = now.date()
    daily = [
        {
            "date": (today + timedelta(days=d)).isoformat(),
            "weather_code": daily_codes[d],
            "temp_max": 75 - d,
            "temp_min": 55 + d,
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
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">'
        '<path d="M6.5 20q-1.875 0-3.187-1.312Q2 17.375 2 15.5q0-1.65 '
        '1.025-2.925T5.5 11.05Q5.9 9.4 7.275 8.325T10.5 7.25q1.125 0 '
        '2.05.475t1.55 1.275q.3-.075.6-.112.3-.038.6-.038 1.65 0 2.825 '
        '1.175T19.3 12.85q1.55.175 2.625 1.3T23 16.7q0 1.5-1.05 '
        '2.55T19.4 20H6.5Z"/></svg>'
    )
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
        self._data = await self._open_meteo.fetch_weather(lat, lon, unit)
        self._fetched_once = True

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
        feels = current.get("feels_like")
        if feels is not None:
            details.append(f"Feels {round(feels)}°")
        humidity = current.get("humidity")
        if humidity is not None:
            details.append(f"Hum {round(humidity)}%")
        wind = current.get("wind_speed")
        if wind is not None:
            details.append(f"Wind {round(wind)}")

        if details:
            detail_size = max(6, label_size - 2)
            # Try the fullest combination that fits the available width; a
            # partial join (e.g. "Feels 70°  Hum") reads worse than a shorter
            # but complete one, so prefer dropping whole items over clipping.
            candidates = ["  ".join(details[:n]) for n in range(len(details), 0, -1)]
            chosen = next((c for c in candidates if can_fit_text(avail_w, detail_size, c)), "")
            if chosen:
                detail_img = render_text(chosen, text_color, detail_size)
                used_h = sum(li.height for li in lines) + 2 * len(lines)
                if used_h + detail_img.height <= h:
                    lines.append(detail_img)

        total_h = sum(li.height for li in lines) + (len(lines) - 1) * 2
        y = max(0, (h - total_h) // 2)
        for li in lines:
            img.paste(li, (text_x, y))
            y += li.height + 2

        blit(self.canvas, img)

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

        # Label at top, temp anchored to the bottom; the icon gets exactly the
        # measured space between them and is dropped when too small to read.
        temp_y = h - temp_h - 1
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

        # Label at top, temps anchored to the bottom (hi over lo with a 1px
        # gap), icon in the measured middle. Degrade explicitly: drop the lo
        # temp before the icon, and the icon before the hi temp.
        icon_top = label_h + 3
        show_lo = h - 1 - 2 * temp_h - 1 - 2 - icon_top >= 8
        temps_h = (2 * temp_h + 1) if show_lo else temp_h
        temp_y = h - temps_h - 1
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
            if hi is not None:
                hi_img = render_text(_clip_text(f"{round(hi)}°", temp_size, max_w), text_color, temp_size)
                img.paste(hi_img, (cx - hi_img.width // 2, y))
                y += temp_h + 1
            if show_lo and lo is not None:
                lo_img = render_text(_clip_text(f"{round(lo)}°", temp_size, max_w), _dim(text_color), temp_size)
                img.paste(lo_img, (cx - lo_img.width // 2, y))

        blit(self.canvas, img)

    def _draw_message(self, msg: str) -> None:
        w, h = self.canvas.width, self.canvas.height
        max_w = max(6, w - 4)
        size = _fit_size(msg, min(14, h), max_w)
        msg_img = render_text(_clip_text(msg, size, max_w), (80, 80, 80), size)
        img = Image.new("RGB", (w, h))
        x = (w - msg_img.width) // 2
        y = (h - msg_img.height) // 2
        img.paste(msg_img, (max(0, x), max(0, y)))
        blit(self.canvas, img)
