from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, ClassVar

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

from canvas.base import Canvas
from plugin_base import DisplayApp
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import load_font
from libraries.opensky.library import OpenSkyLibrary
from libraries.flightaware.library import FlightAwareLibrary


def _clip_text(draw: ImageDraw.ImageDraw, text: str, font: Any, max_w: int) -> str:
    while text:
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_w:
            return text
        text = text[:-1]
    return ""


class FlightsApp(DisplayApp):
    id: ClassVar[str] = "flights"
    name: ClassVar[str] = "Flights"
    description: ClassVar[str] = (
        "Aircraft overhead via OpenSky Network — cycling cards with airline, "
        "route, and aircraft type via FlightAware AeroAPI enrichment"
    )
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">'
        '<path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 00-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22'
        "l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z\"/></svg>"
    )
    libraries: ClassVar[list[str]] = ["opensky", "flightaware"]
    global_config_schema: ClassVar[dict[str, Any]] = {}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Flights",
        "properties": {
            "location": {
                "type": "object",
                "title": "Location",
                "x-input-type": "location",
                "default": {"latitude": 0.0, "longitude": 0.0, "radius_km": 50.0},
                "properties": {
                    "latitude": {"type": "number", "default": 0.0},
                    "longitude": {"type": "number", "default": 0.0},
                    "radius_km": {
                        "type": "number",
                        "title": "Radius (km)",
                        "default": 50.0,
                        "minimum": 1,
                        "maximum": 500,
                    },
                },
            },
            "max_flights": {
                "type": "integer",
                "title": "Max flights to track",
                "default": 10,
                "minimum": 1,
                "maximum": 20,
            },
            "display_mode": {
                "type": "string",
                "title": "Display mode",
                "enum": ["cards", "table"],
                "default": "cards",
            },
            "cycle_seconds": {
                "type": "number",
                "title": "Seconds per flight card",
                "default": 3.0,
                "minimum": 0.5,
            },
            "text_color": {
                "type": "string",
                "title": "Text color",
                "x-input-type": "color",
                "default": "#C8C8C8",
            },
            "show_border": {
                "type": "boolean",
                "title": "Show card border",
                "default": True,
            },
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 30,
                "minimum": 10,
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
        self._opensky = OpenSkyLibrary(self.library_configs.get("opensky", {}))
        self._flightaware = FlightAwareLibrary(self.library_configs.get("flightaware", {}))
        self._flights: list[dict[str, Any]] = []
        self._enriched: dict[str, dict[str, Any]] = {}
        self._logos: dict[str, Image.Image | None] = {}
        self._logos_fetched: set[str] = set()
        self._fetched_once: bool = False
        self._card_idx: int = 0
        self._card_last_ts: float = 0.0

    # ── Data fetching ──────────────────────────────────────────────────────────

    async def fetch_data(self) -> None:
        loc = self.config.get("location", {})
        lat = float(loc.get("latitude", 0.0) if isinstance(loc, dict) else 0.0)
        lon = float(loc.get("longitude", 0.0) if isinstance(loc, dict) else 0.0)
        radius_km = float(
            loc.get("radius_km", self.config.get("radius_km", 50.0))
            if isinstance(loc, dict) else self.config.get("radius_km", 50.0)
        )
        max_flights = int(self.config.get("max_flights", 10))

        self._flights = await self._opensky.fetch_flights(lat, lon, radius_km, max_flights)
        self._card_idx = 0
        self._card_last_ts = time.monotonic()
        self._fetched_once = True

        callsigns = [f["callsign"] for f in self._flights]
        self._enriched = await self._flightaware.enrich_flights(callsigns)
        await self._fetch_logos()

    async def _fetch_logos(self) -> None:
        needed = {
            e["operator_iata"]
            for e in self._enriched.values()
            if e.get("operator_iata")
        } - self._logos_fetched

        if not needed:
            return

        results = await asyncio.gather(
            *[self._flightaware.fetch_logo(code) for code in needed],
            return_exceptions=True,
        )
        for iata, result in zip(needed, results):
            self._logos_fetched.add(iata)
            self._logos[iata] = result if isinstance(result, Image.Image) else None

    # ── Rendering ──────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        if not self._flights:
            self._draw_no_flights()
            return
        if self.config.get("display_mode", "cards") == "table":
            self._draw_table()
        else:
            self._draw_card()

    def _draw_card(self) -> None:
        now = time.monotonic()
        cycle_seconds = float(self.config.get("cycle_seconds", 3.0))
        if now - self._card_last_ts >= cycle_seconds:
            self._card_idx = (self._card_idx + 1) % len(self._flights)
            self._card_last_ts = now

        flight = self._flights[self._card_idx]
        enriched = self._enriched.get(flight["callsign"], {})

        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))
        show_border = bool(self.config.get("show_border", True))

        w, h = self.canvas.width, self.canvas.height
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)

        if show_border:
            draw.rectangle([(0, 0), (w - 1, h - 1)], outline=(80, 80, 80))

        pad = 3 if show_border else 1
        inner_w = w - 2 * pad
        inner_h = h - 2 * pad

        operator_iata = enriched.get("operator_iata", "")
        raw_logo = self._logos.get(operator_iata) if operator_iata else None
        logo_size = inner_h
        logo_gap = 3
        min_text_w = 30
        show_logo = raw_logo is not None and (inner_w - logo_size - logo_gap) >= min_text_w
        if show_logo:
            resized = raw_logo.resize((logo_size, logo_size), Image.LANCZOS)
            bg = Image.new("RGB", resized.size, (0, 0, 0))
            bg.paste(resized.convert("RGB"), mask=resized.split()[3])
            img.paste(bg, (pad, pad))
            text_x = pad + logo_size + logo_gap
            text_w = inner_w - logo_size - logo_gap
        else:
            text_x = pad
            text_w = inner_w

        font_size = max(8, inner_h // 3 - 1)
        font = load_font(font_size)

        dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        row_bbox = dummy_draw.textbbox((0, 0), "A", font=font)
        row_h = row_bbox[3] - row_bbox[1] + 1

        block_h = row_h * 3
        y0 = pad + max(0, (inner_h - block_h) // 2) - row_bbox[1]

        airline = enriched.get("airline", "")
        line1 = f"{flight['callsign']} {airline}" if airline else flight["callsign"]
        line1 = _clip_text(draw, line1, font, text_w)

        origin = enriched.get("origin", "")
        dest = enriched.get("dest", "")
        if origin and dest:
            line2 = f"{origin}->{dest}"
        elif flight["alt_ft"] is not None:
            line2 = f"Alt: {flight['alt_ft']:,}ft"
        else:
            line2 = "Alt: ---"

        aircraft_type = enriched.get("aircraft_type", "")
        if aircraft_type:
            line3 = aircraft_type
        elif flight["spd_kt"] is not None:
            line3 = f"{flight['spd_kt']}kt"
        else:
            line3 = "---"

        for i, line in enumerate((line1, line2, line3)):
            draw.text((text_x, y0 + i * row_h), line, font=font, fill=text_color)

        blit(self.canvas, img)

    def _draw_table(self) -> None:
        max_flights = int(self.config.get("max_flights", 10))
        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))
        font = load_font(12)

        dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bbox = dummy_draw.textbbox((0, 0), "A", font=font)
        row_h = bbox[3] - bbox[1] + 2

        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        draw = ImageDraw.Draw(img)

        for i, flight in enumerate(self._flights[:max_flights]):
            y = i * row_h + 2 - bbox[1]
            alt = f"{flight['alt_ft']:,}ft" if flight["alt_ft"] is not None else "   ---"
            spd = f"{flight['spd_kt']}kt" if flight["spd_kt"] is not None else "---"
            row = f"{flight['callsign']:<8}  {alt:>8}  {spd:>5}"
            draw.text((2, y), row, font=font, fill=text_color)

        blit(self.canvas, img)

    def _draw_no_flights(self) -> None:
        font = load_font(14)
        msg = "Loading..." if not self._fetched_once else "No flights nearby"

        dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bbox = dummy_draw.textbbox((0, 0), msg, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        draw = ImageDraw.Draw(img)
        x = (self.canvas.width - tw) // 2
        y = (self.canvas.height - th) // 2 - bbox[1]
        draw.text((x, y), msg, font=font, fill=(80, 80, 80))
        blit(self.canvas, img)
