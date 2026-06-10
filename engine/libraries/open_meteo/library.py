from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, ClassVar

import httpx
from PIL import Image

from libraries.base import Library

logger = logging.getLogger(__name__)

_API_URL = "https://api.open-meteo.com/v1/forecast"
_CACHE_TTL_SECONDS: float = 15 * 60

# WMO weather interpretation codes (https://open-meteo.com/en/docs) collapsed
# into a small set of icon/label categories.
_CONDITION_BY_CODE: dict[int, str] = {
    0: "clear",
    1: "clear",
    2: "partly_cloudy",
    3: "cloudy",
    45: "fog", 48: "fog",
    51: "rain", 53: "rain", 55: "rain",
    56: "rain", 57: "rain",
    61: "rain", 63: "rain", 65: "rain",
    66: "rain", 67: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow",
    80: "rain", 81: "rain", 82: "rain",
    85: "snow", 86: "snow",
    95: "thunderstorm", 96: "thunderstorm", 99: "thunderstorm",
}

_CONDITION_LABELS: dict[str, str] = {
    "clear": "Clear",
    "partly_cloudy": "Pt Cloudy",
    "cloudy": "Cloudy",
    "fog": "Fog",
    "rain": "Rain",
    "snow": "Snow",
    "thunderstorm": "Storms",
}


def condition_for_code(code: int | None) -> str:
    """Map a WMO weather code to one of our icon/label categories."""
    if code is None:
        return "cloudy"
    return _CONDITION_BY_CODE.get(int(code), "cloudy")


def condition_label(condition: str) -> str:
    return _CONDITION_LABELS.get(condition, "Unknown")


# ── Animated weather icons ──────────────────────────────────────────────────
#
# Full-color animated icons from the free amCharts SVG weather-icons set,
# pre-baked into PNG sprite strips by `tools/bake_icons.py` (one square frame
# per animation step, side by side). Frames are sliced and resized lazily and
# cached per (icon, size) so the render loop just indexes a list.

_ICONS_DIR = Path(__file__).parent / "icons"
_ICONS_META: dict[str, Any] = json.loads((_ICONS_DIR / "meta.json").read_text(encoding="utf-8"))

_DAY_ICON_BY_CONDITION: dict[str, str] = {
    "clear": "day",
    "partly_cloudy": "cloudy-day-3",
    "cloudy": "cloudy",
    "fog": "fog",
    "rain": "rainy-6",
    "snow": "snowy-6",
    "thunderstorm": "thunder",
}
_NIGHT_ICON_BY_CONDITION: dict[str, str] = {"clear": "night", "partly_cloudy": "cloudy-night-3"}

_strip_cache: dict[str, list[Image.Image]] = {}
_frame_cache: dict[tuple[str, int], list[Image.Image]] = {}


def _icon_frames(name: str, size: int) -> list[Image.Image]:
    """The icon's animation frames at `size`, composited onto black RGB."""
    cached = _frame_cache.get((name, size))
    if cached is not None:
        return cached

    full = _strip_cache.get(name)
    if full is None:
        strip = Image.open(_ICONS_DIR / f"{name}.png").convert("RGBA")
        side = strip.height
        full = [strip.crop((i * side, 0, (i + 1) * side, side)) for i in range(strip.width // side)]
        _strip_cache[name] = full

    frames: list[Image.Image] = []
    for frame in full:
        if frame.width != size:
            frame = frame.resize((size, size), Image.LANCZOS)
        composited = Image.new("RGB", (size, size), (0, 0, 0))
        composited.paste(frame, (0, 0), frame)
        frames.append(composited)
    _frame_cache[(name, size)] = frames
    return frames


def weather_icon_img(
    condition: str,
    size: int,
    color: tuple[int, int, int] | None = None,
    *,
    night: bool = False,
    t: float = 0.0,
) -> Image.Image:
    """A size x size frame of the condition's animated icon at elapsed time `t`.

    Pass a monotonically growing `t` (seconds) across successive renders to
    animate; t=0 always yields the first frame, keeping single-frame renders
    (e.g. snapshot tests) deterministic. `color` is accepted for call-site
    compatibility but ignored — the artwork is full-color.
    """
    size = max(8, int(size))
    name = (night and _NIGHT_ICON_BY_CONDITION.get(condition)) or _DAY_ICON_BY_CONDITION.get(condition, "cloudy")
    frames = _icon_frames(name, size)
    idx = int(t * float(_ICONS_META["fps"])) % len(frames)
    return frames[idx]


# ── Library class ───────────────────────────────────────────────────────────


class OpenMeteoLibrary(Library):
    id: ClassVar[str] = "open_meteo"
    name: ClassVar[str] = "Open-Meteo"
    description: ClassVar[str] = (
        "Free weather forecasts from Open-Meteo — current conditions, hourly, "
        "and 7-day outlook with no API key required"
    )
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">'
        '<path d="M6.5 20q-1.875 0-3.187-1.312Q2 17.375 2 15.5q0-1.65 '
        '1.025-2.925T5.5 11.05Q5.9 9.4 7.275 8.325T10.5 7.25q1.125 0 '
        '2.05.475t1.55 1.275q.3-.075.6-.112.3-.038.6-.038 1.65 0 2.825 '
        '1.175T19.3 12.85q1.55.175 2.625 1.3T23 16.7q0 1.5-1.05 '
        '2.55T19.4 20H6.5Z"/></svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {}

    condition_for_code = staticmethod(condition_for_code)
    condition_label = staticmethod(condition_label)
    weather_icon_img = staticmethod(weather_icon_img)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._cache: dict[tuple[float, float, str], tuple[float, dict[str, Any]]] = {}

    async def fetch_weather(self, lat: float, lon: float, unit: str = "fahrenheit") -> dict[str, Any]:
        """Fetch current conditions plus hourly/daily forecasts for (lat, lon).

        Returns a normalized dict: {"timezone", "current", "hourly", "daily"}.
        Results are cached in-memory for a short TTL; on request failure the
        last good cached value is returned (or {} if nothing has ever loaded).
        """
        unit = unit if unit in ("fahrenheit", "celsius") else "fahrenheit"
        key = (round(lat, 2), round(lon, 2), unit)
        now = time.monotonic()

        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
                "hourly": "temperature_2m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "temperature_unit": unit,
                "wind_speed_unit": "mph" if unit == "fahrenheit" else "kmh",
                "timezone": "auto",
                "forecast_days": 7,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(_API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            parsed = self._parse(data)
            self._cache[key] = (now, parsed)
            return parsed
        except Exception as exc:
            logger.warning("Open-Meteo fetch failed for (%s, %s): %s", lat, lon, exc)
            return cached[1] if cached is not None else {}

    @staticmethod
    def _parse(data: dict[str, Any]) -> dict[str, Any]:
        current_raw = data.get("current") or {}
        current = {
            "temperature": current_raw.get("temperature_2m"),
            "feels_like": current_raw.get("apparent_temperature"),
            "humidity": current_raw.get("relative_humidity_2m"),
            "wind_speed": current_raw.get("wind_speed_10m"),
            "weather_code": current_raw.get("weather_code"),
            "is_day": bool(current_raw.get("is_day", 1)),
        }

        hourly_raw = data.get("hourly") or {}
        hourly = [
            {"time": t, "temperature": temp, "weather_code": code}
            for t, temp, code in zip(
                hourly_raw.get("time", []),
                hourly_raw.get("temperature_2m", []),
                hourly_raw.get("weather_code", []),
            )
        ]

        daily_raw = data.get("daily") or {}
        daily = [
            {"date": d, "weather_code": code, "temp_max": tmax, "temp_min": tmin}
            for d, code, tmax, tmin in zip(
                daily_raw.get("time", []),
                daily_raw.get("weather_code", []),
                daily_raw.get("temperature_2m_max", []),
                daily_raw.get("temperature_2m_min", []),
            )
        ]

        return {
            "timezone": data.get("timezone"),
            "current": current,
            "hourly": hourly,
            "daily": daily,
        }
