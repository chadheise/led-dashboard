from __future__ import annotations

import math
from typing import Any, ClassVar

import httpx
from PIL import Image, ImageDraw

from canvas.base import Canvas
from plugin_base import DisplayPlugin
from plugins._helpers import blit, load_font


def _km_to_deg(km: float) -> float:
    return km / 111.0


class FlightsPlugin(DisplayPlugin):
    id: ClassVar[str] = "flights"
    name: ClassVar[str] = "Nearby Flights"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Nearby Flights",
        "properties": {
            "latitude": {"type": "number", "title": "Latitude"},
            "longitude": {"type": "number", "title": "Longitude"},
            "radius_km": {
                "type": "number",
                "title": "Search radius (km)",
                "default": 50,
                "minimum": 1,
                "maximum": 500,
            },
            "max_rows": {
                "type": "integer",
                "title": "Max rows to display",
                "default": 4,
                "minimum": 1,
                "maximum": 8,
            },
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 30,
                "minimum": 10,
            },
            "scene_duration": {
                "type": "number",
                "title": "Scene duration (s)",
                "default": 45,
            },
        },
        "required": ["latitude", "longitude"],
    }

    def __init__(self, config: dict[str, Any], canvas: Canvas) -> None:
        super().__init__(config, canvas)
        self._flights: list[dict[str, Any]] = []

    async def fetch_data(self) -> None:
        lat = float(self.config.get("latitude", 0.0))
        lon = float(self.config.get("longitude", 0.0))
        radius_km = float(self.config.get("radius_km", 50.0))
        d = _km_to_deg(radius_km)

        url = "https://opensky-network.org/api/states/all"
        params = {
            "lamin": lat - d,
            "lomin": lon - d,
            "lamax": lat + d,
            "lomax": lon + d,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
            data = resp.json()
        except Exception:
            return

        flights: list[dict[str, Any]] = []
        for state in data.get("states") or []:
            callsign = (state[1] or "").strip() or state[0] or "??????"
            alt_m: float | None = state[7]  # geo_altitude in metres
            velocity: float | None = state[9]  # m/s
            heading: float | None = state[10]

            alt_ft = round(alt_m * 3.281) if alt_m is not None else None
            spd_kt = round(velocity * 1.944) if velocity is not None else None

            # Rough distance from centre
            f_lat: float | None = state[6]
            f_lon: float | None = state[5]
            dist_km: float | None = None
            if f_lat is not None and f_lon is not None:
                dist_km = math.sqrt((f_lat - lat) ** 2 + (f_lon - lon) ** 2) * 111.0

            flights.append(
                {
                    "callsign": callsign[:8].upper(),
                    "alt_ft": alt_ft,
                    "spd_kt": spd_kt,
                    "heading": heading,
                    "dist_km": dist_km,
                }
            )

        # Sort by distance
        flights.sort(key=lambda f: f["dist_km"] if f["dist_km"] is not None else 9999)
        self._flights = flights

    async def render_frame(self) -> None:
        if not self._flights:
            self._draw_no_flights()
            return
        self._draw_table()

    def _draw_table(self) -> None:
        max_rows = int(self.config.get("max_rows", 4))
        font = load_font(12)

        dummy = Image.new("RGB", (1, 1))
        bbox = ImageDraw.Draw(dummy).textbbox((0, 0), "A", font=font)
        row_h = bbox[3] - bbox[1] + 2

        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        draw = ImageDraw.Draw(img)

        for i, flight in enumerate(self._flights[:max_rows]):
            y = i * row_h + 2
            alt = f"{flight['alt_ft']:,}ft" if flight["alt_ft"] is not None else "   ---"
            spd = f"{flight['spd_kt']}kt" if flight["spd_kt"] is not None else "---"
            row = f"{flight['callsign']:<8}  {alt:>8}  {spd:>5}"
            draw.text((2, y), row, font=font, fill=(180, 180, 180))

        blit(self.canvas, img)

    def _draw_no_flights(self) -> None:
        font = load_font(14)
        msg = "No flights nearby"
        dummy = Image.new("RGB", (1, 1))
        bbox = ImageDraw.Draw(dummy).textbbox((0, 0), msg, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        draw = ImageDraw.Draw(img)
        x = (self.canvas.width - tw) // 2
        y = (self.canvas.height - th) // 2 - bbox[1]
        draw.text((x, y), msg, font=font, fill=(80, 80, 80))
        blit(self.canvas, img)
