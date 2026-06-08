from __future__ import annotations

import logging
import math
import time
from typing import Any, ClassVar

import httpx
from PIL import Image, ImageDraw

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


# ── Procedural icon drawing ─────────────────────────────────────────────────
#
# Icons are drawn with simple PIL primitives, scaled to the requested pixel
# size, rather than loaded from bitmap assets — this lets them render crisply
# at any resolution the LED panel needs (the project has no icon-asset
# pipeline, and a vector approach matches `arrow_img` in text_renderer).


def _sun(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple[int, int, int], *, rays: bool) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    if rays:
        gap = r * 0.35
        length = r * 0.65
        width = max(1, round(r * 0.28))
        for deg in (0, 45, 90, 135, 180, 225, 270, 315):
            rad = math.radians(deg)
            x0 = cx + (r + gap) * math.cos(rad)
            y0 = cy + (r + gap) * math.sin(rad)
            x1 = cx + (r + gap + length) * math.cos(rad)
            y1 = cy + (r + gap + length) * math.sin(rad)
            draw.line([(x0, y0), (x1, y1)], fill=color, width=width)


def _moon(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple[int, int, int]) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    cut = r * 0.85
    draw.ellipse([cx - r + cut, cy - r, cx + r + cut, cy + r], fill=(0, 0, 0))


def _cloud(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    """A puffy cloud whose bounding box is roughly w wide by h tall, centered at (cx, cy)."""
    top = cy - h * 0.20
    bottom = cy + h * 0.50
    draw.rounded_rectangle([cx - w / 2, top, cx + w / 2, bottom], radius=h * 0.35, fill=color)
    r1 = h * 0.45
    draw.ellipse([cx - w * 0.22 - r1, top - r1 * 0.85, cx - w * 0.22 + r1, top + r1 * 1.05], fill=color)
    r2 = h * 0.58
    draw.ellipse([cx + w * 0.10 - r2, top - r2 * 1.05, cx + w * 0.10 + r2, top + r2 * 0.75], fill=color)


def _rain_drops(draw: ImageDraw.ImageDraw, cx: float, top: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    width = max(1, round(h * 0.16))
    drop = h * 0.85
    for i, dx in enumerate((-w * 0.26, 0.0, w * 0.26)):
        x = cx + dx
        y0 = top + (h * 0.18 if i == 1 else 0.0)
        draw.line([(x, y0), (x - drop * 0.35, y0 + drop)], fill=color, width=width)


def _snow_flakes(draw: ImageDraw.ImageDraw, cx: float, top: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    r = max(1.0, h * 0.16)
    for i, dx in enumerate((-w * 0.26, 0.0, w * 0.26)):
        x = cx + dx
        y = top + (h * 0.55 if i == 1 else h * 0.30)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _bolt(draw: ImageDraw.ImageDraw, cx: float, top: float, h: float, color: tuple[int, int, int]) -> None:
    w = h * 0.65
    pts = [
        (cx + w * 0.20, top),
        (cx - w * 0.30, top + h * 0.55),
        (cx - w * 0.02, top + h * 0.55),
        (cx - w * 0.20, top + h * 1.05),
        (cx + w * 0.32, top + h * 0.40),
        (cx + w * 0.05, top + h * 0.40),
    ]
    draw.polygon(pts, fill=color)


def _fog_lines(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, color: tuple[int, int, int]) -> None:
    width = max(1, round(w * 0.05))
    spacing = max(2.0, w * 0.16)
    for i in range(3):
        y = cy + (i - 1) * spacing
        draw.line([(cx - w / 2, y), (cx + w / 2, y)], fill=color, width=width)


def weather_icon_img(condition: str, size: int, color: tuple[int, int, int], *, night: bool = False) -> Image.Image:
    """Draw a small weather-condition icon, scaled to fill a size x size square."""
    size = max(8, int(size))
    img = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = size / 2.0

    if condition in ("clear", "partly_cloudy"):
        if condition == "clear":
            sun_cx, sun_cy, sun_r = cx, size * 0.42, size * 0.30
        else:
            sun_cx, sun_cy, sun_r = size * 0.62, size * 0.36, size * 0.20
        if night:
            _moon(draw, sun_cx, sun_cy, sun_r, color)
        else:
            _sun(draw, sun_cx, sun_cy, sun_r, color, rays=(condition == "clear" and size >= 14))
        if condition == "partly_cloudy":
            _cloud(draw, size * 0.44, size * 0.62, size * 0.62, size * 0.34, color)
        return img

    if condition in ("cloudy", "fog"):
        _cloud(draw, cx, size * 0.50, size * 0.74, size * 0.40, color)
        if condition == "fog":
            _fog_lines(draw, cx, size * 0.84, size * 0.7, color)
        return img

    # Precipitation conditions: cloud body with an accent below it.
    _cloud(draw, cx, size * 0.36, size * 0.7, size * 0.32, color)
    accent_top = size * 0.58
    accent_h = size * 0.34
    if condition == "rain":
        _rain_drops(draw, cx, accent_top, size * 0.6, accent_h, color)
    elif condition == "snow":
        _snow_flakes(draw, cx, accent_top, size * 0.6, accent_h, color)
    elif condition == "thunderstorm":
        _bolt(draw, cx, accent_top - size * 0.04, accent_h, color)
    return img


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
