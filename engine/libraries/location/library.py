from __future__ import annotations

import logging
from typing import Any, ClassVar

import httpx

from libraries.base import Library

logger = logging.getLogger(__name__)


class LocationLibrary(Library):
    id: ClassVar[str] = "location"
    name: ClassVar[str] = "Location/Time"
    description: ClassVar[str] = "Home location shared across apps — provides lat/lon, city, country, timezone, and time/date format preferences"
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">'
        '<path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z'
        "M12 11.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z\"/></svg>"
    )
    global_config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Location/Time",
        "properties": {
            "location": {
                "type": "object",
                "title": "Home Location",
                "x-input-type": "location",
                "default": {"latitude": 0.0, "longitude": 0.0, "name": "", "timezone": ""},
                "properties": {
                    "latitude": {"type": "number", "default": 0.0},
                    "longitude": {"type": "number", "default": 0.0},
                    "name": {"type": "string", "default": ""},
                    "timezone": {"type": "string", "default": ""},
                },
            },
            "time_format": {
                "type": "string",
                "title": "Time Format",
                "enum": ["12h", "24h"],
                "x-enum-labels": {"12h": "12-hour (3:30 PM)", "24h": "24-hour (15:30)"},
                "default": "12h",
            },
            "date_format": {
                "type": "string",
                "title": "Date Format",
                "enum": ["MM/DD/YYYY", "DD/MM/YYYY", "YYYY-MM-DD", "MMM D, YYYY"],
                "x-enum-labels": {
                    "MM/DD/YYYY": "MM/DD/YYYY (06/15/2025)",
                    "DD/MM/YYYY": "DD/MM/YYYY (15/06/2025)",
                    "YYYY-MM-DD": "YYYY-MM-DD (2025-06-15)",
                    "MMM D, YYYY": "MMM D, YYYY (Jun 15, 2025)",
                },
                "default": "MM/DD/YYYY",
            },
        },
    }

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._tf: Any = None

    def get_latitude(self) -> float:
        return float(self._config.get("location", {}).get("latitude", 0.0))

    def get_longitude(self) -> float:
        return float(self._config.get("location", {}).get("longitude", 0.0))

    def get_time_format(self) -> str:
        return str(self._config.get("time_format", "12h"))

    def get_date_format(self) -> str:
        return str(self._config.get("date_format", "MM/DD/YYYY"))

    def get_timezone(self) -> str | None:
        """The IANA timezone for the configured location.

        The map picker resolves this client-side (in the browser, via a pure
        JS lat/lon lookup with no native deps) and stores it alongside the
        coordinates, so this is normally just a dict read. `timezonefinder`
        is a server-side fallback for configs saved before that field
        existed — its native dependencies (numpy, h3, cffi) are more likely
        to be unavailable on a Raspberry Pi.
        """
        stored = self._config.get("location", {}).get("timezone")
        if stored:
            return str(stored)

        lat, lon = self.get_latitude(), self.get_longitude()
        if lat == 0.0 and lon == 0.0:
            return None
        tf = self._get_timezone_finder()
        if tf is None:
            return None
        try:
            return tf.timezone_at(lat=lat, lng=lon)
        except Exception as exc:
            logger.warning("Timezone lookup failed: %s", exc)
            return None

    async def get_city_country(self) -> dict[str, str]:
        lat, lon = self.get_latitude(), self.get_longitude()
        if lat == 0.0 and lon == 0.0:
            return {"city": "", "country": ""}
        try:
            url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers={"User-Agent": "LED-Dashboard/1.0"})
            data = resp.json()
            addr = data.get("address", {})
            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("municipality")
                or ""
            )
            return {"city": city, "country": addr.get("country", "")}
        except Exception as exc:
            logger.warning("Reverse geocode failed: %s", exc)
            return {"city": "", "country": ""}

    def as_dict(self) -> dict[str, Any]:
        return {
            "latitude": self.get_latitude(),
            "longitude": self.get_longitude(),
            "timezone": self.get_timezone(),
        }

    def _get_timezone_finder(self) -> Any:
        if self._tf is None:
            try:
                from timezonefinder import TimezoneFinder  # type: ignore[import]
                self._tf = TimezoneFinder()
            except Exception as exc:
                logger.warning("timezonefinder unavailable: %s", exc)
        return self._tf
