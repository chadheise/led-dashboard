from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, ClassVar

from PIL import Image

logger = logging.getLogger(__name__)

from canvas.base import Canvas
from app_base import DisplayApp
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import render_text
from libraries.opensky.library import OpenSkyLibrary
from libraries.flightaware.library import FlightAwareLibrary


def _clip_text(text: str, size: int, max_w: int) -> str:
    while text:
        if render_text(text, (255, 255, 255), size).width <= max_w:
            return text
        text = text[:-1]
    return ""


_UNIT_CYCLE_S: float = 4.0


def _build_stat_lines(flight: dict[str, Any], imperial: bool) -> list[str]:
    track = flight.get("track")
    trk_str = f"Trk: {track}deg" if track is not None else "Trk: ---"

    if imperial:
        alt = flight.get("alt_ft")
        spd = flight.get("spd_mph")
        vr = flight.get("vr_mph")
        alt_str = f"Alt: {alt} ft" if alt is not None else "Alt: ---"
        spd_str = f"Spd: {spd} mph" if spd is not None else "Spd: ---"
        vr_str = (f"Vr: {'+' if vr >= 0 else ''}{vr} mph" if vr is not None else "Vr: ---")
    else:
        alt = flight.get("alt_m")
        spd = flight.get("spd_kph")
        vr = flight.get("vr_kph")
        alt_str = f"Alt: {alt} m" if alt is not None else "Alt: ---"
        spd_str = f"Spd: {spd} kph" if spd is not None else "Spd: ---"
        vr_str = (f"Vr: {'+' if vr >= 0 else ''}{vr} kph" if vr is not None else "Vr: ---")

    return [alt_str, spd_str, trk_str, vr_str]


_DEBUG_FLIGHT: dict[str, Any] = {
    "callsign": "DL699",
    "alt_m": 789,
    "alt_ft": 2559,
    "spd_kph": 456,
    "spd_mph": 283,
    "track": 270,
    "vr_kph": 23,
    "vr_mph": 14,
    "spd_kt": None,
    "heading": 270,
    "dist_km": None,
}

_DEBUG_ENRICHED: dict[str, Any] = {
    "airline": "Delta Airlines",
    "origin": "JFK",
    "dest": "SEA",
    "aircraft_type": "Boeing 737-700",
    "operator_iata": "DL",
    "origin_name": "JFK Intl",
    "dest_name": "Seattle-Tacoma Intl",
}


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
    libraries: ClassVar[list[str]] = ["opensky", "flightaware", "location"]
    global_config_schema: ClassVar[dict[str, Any]] = {}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Flights",
        "properties": {
            "location": {
                "type": "object",
                "title": "Location",
                "x-input-type": "location",
                "x-radius-min": 1,
                "x-radius-max": 100,
                "x-default-from-library": {"library": "location", "path": "location"},
                "default": {"latitude": 0.0, "longitude": 0.0, "radius_km": 50.0},
                "properties": {
                    "latitude": {"type": "number", "default": 0.0},
                    "longitude": {"type": "number", "default": 0.0},
                    "radius_km": {
                        "type": "number",
                        "title": "Radius (km)",
                        "default": 50.0,
                        "minimum": 1,
                        "maximum": 100,
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
            "min_card_seconds": {
                "type": "number",
                "title": "Minimum seconds per card",
                "default": 5.0,
                "minimum": 1.0,
            },
            "max_card_seconds": {
                "type": "number",
                "title": "Maximum seconds per card",
                "default": 30.0,
                "minimum": 1.0,
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
                "default": 30,
                "minimum": 10,
            },
            "units": {
                "type": "string",
                "title": "Units",
                "enum": ["metric", "imperial", "metric+imperial"],
                "default": "metric+imperial",
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
        self._opensky = OpenSkyLibrary(self.library_configs.get("opensky", {}))
        self._flightaware = FlightAwareLibrary(self.library_configs.get("flightaware", {}))
        self._flights: list[dict[str, Any]] = []
        self._enriched: dict[str, dict[str, Any]] = {}
        self._logos: dict[str, Image.Image | None] = {}
        self._logos_fetched: set[str] = set()
        self._fetched_once: bool = False
        self._card_idx: int = 0
        self._card_last_ts: float = 0.0
        self._show_imperial: bool = False
        self._unit_ts: float = time.monotonic()
        self._is_active: bool = False

    async def should_display(self) -> bool:
        return not self._fetched_once or bool(self._flights)

    async def on_activate(self) -> None:
        self._is_active = True

    async def on_deactivate(self) -> None:
        self._is_active = False

    # ── Data fetching ──────────────────────────────────────────────────────────

    async def fetch_data(self) -> None:
        if self.config.get("debug", False):
            self._flights = [dict(_DEBUG_FLIGHT)]
            self._enriched = {"DL699": dict(_DEBUG_ENRICHED)}
            self._card_idx = 0
            self._card_last_ts = time.monotonic()
            self._fetched_once = True
            await self._fetch_logos()
            return

        loc = self.config.get("location", {})
        lat = float(loc.get("latitude", 0.0) if isinstance(loc, dict) else 0.0)
        lon = float(loc.get("longitude", 0.0) if isinstance(loc, dict) else 0.0)
        radius_km = float(
            loc.get("radius_km", self.config.get("radius_km", 50.0))
            if isinstance(loc, dict) else self.config.get("radius_km", 50.0)
        )

        if lat == 0.0 and lon == 0.0:
            lib_loc = self.library_configs.get("location", {}).get("location", {})
            if isinstance(lib_loc, dict):
                lat = float(lib_loc.get("latitude", 0.0))
                lon = float(lib_loc.get("longitude", 0.0))
        max_flights = int(self.config.get("max_flights", 10))

        now = time.monotonic()
        min_card_s = float(self.config.get("min_card_seconds", 5.0))
        opensky_result = await self._opensky.fetch_flights(lat, lon, radius_km, max_flights)
        self._fetched_once = True
        if opensky_result is not None:
            self._flights = opensky_result  # None means throttled/error — keep stale data

        elapsed = now - self._card_last_ts
        if elapsed >= min_card_s or not self._flights:
            self._card_idx = 0
            self._card_last_ts = now
        else:
            self._card_idx = min(self._card_idx, len(self._flights) - 1)

        callsigns = [f["callsign"] for f in self._flights]

        if self._is_active:
            tier = self._flightaware.budget_tier
            if tier == "disabled":
                # Budget exhausted: serve cache only
                enrich_callsigns: list[str] = []
            elif tier in ("conservative", "minimal"):
                # Budget tight: only enrich the currently displayed flight
                current_cs = (
                    self._flights[self._card_idx % len(self._flights)]["callsign"]
                    if self._flights else None
                )
                enrich_callsigns = [current_cs] if current_cs else []
            elif self.config.get("display_mode") == "table":
                # Table mode: all flights visible, enrich all (cache handles repeats)
                enrich_callsigns = callsigns
            else:
                # Card mode: enrich current card + next 2 (prefetch upcoming)
                n = len(self._flights)
                idxs = [(self._card_idx + i) % n for i in range(min(3, n))]
                enrich_callsigns = [self._flights[i]["callsign"] for i in idxs]

            new_enriched = await self._flightaware.enrich_flights(enrich_callsigns)
            # Merge: prefer fresh data, retain previously loaded enrichment for the rest
            self._enriched = {
                cs: new_enriched.get(cs) or self._enriched.get(cs, {})
                for cs in callsigns
            }
        else:
            # Off-screen: retain enrichment for flights still in range
            self._enriched = {cs: self._enriched.get(cs, {}) for cs in callsigns}

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
        max_card_s = float(self.config.get("max_card_seconds", 30.0))
        if now - self._card_last_ts >= max_card_s:
            self._card_idx = (self._card_idx + 1) % len(self._flights)
            self._card_last_ts = now

        units = self.config.get("units", "metric+imperial")
        if units == "metric+imperial":
            if now - self._unit_ts >= _UNIT_CYCLE_S:
                self._show_imperial = not self._show_imperial
                self._unit_ts = now
        else:
            self._show_imperial = units == "imperial"

        flight = self._flights[self._card_idx]
        enriched = self._enriched.get(flight["callsign"], {})

        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))

        w, h = self.canvas.width, self.canvas.height
        img = Image.new("RGB", (w, h))

        pad = 2
        inner_h = h - 2 * pad
        inner_w = w - 2 * pad

        # Divide available height into 5 equal slots; text is centered in each slot.
        slot_h = inner_h // 5
        font_size = max(6, slot_h - 2)
        logo_gap = 2
        stats_gap = 2

        def row_y(row: int, img_h: int) -> int:
            """Top-left y to vertically center img_h within slot `row`."""
            return pad + row * slot_h + (slot_h - img_h) // 2

        # Pre-compute stats width so text columns know how much space they have
        stat_strs = _build_stat_lines(flight, self._show_imperial)
        stat_imgs = [render_text(s, text_color, font_size) for s in stat_strs]
        stats_w = max((si.width for si in stat_imgs), default=0)

        # Logo: square spanning top 3 slots
        logo_dim = 3 * slot_h
        operator_iata = enriched.get("operator_iata", "") or ""
        raw_logo = self._logos.get(operator_iata) if operator_iata else None
        if raw_logo is not None:
            resized = raw_logo.resize((logo_dim, logo_dim), Image.LANCZOS)
            bg = Image.new("RGB", resized.size, (0, 0, 0))
            if resized.mode == "RGBA":
                bg.paste(resized.convert("RGB"), mask=resized.split()[3])
            else:
                bg.paste(resized.convert("RGB"))
            img.paste(bg, (pad, pad))
            mid_x = pad + logo_dim + logo_gap
        else:
            mid_x = pad

        # Middle text (rows 0-2): airline name, route, aircraft type
        mid_w = (w - pad - stats_w - stats_gap) - mid_x
        airline = enriched.get("airline", "") or ""
        origin = enriched.get("origin", "") or ""
        dest = enriched.get("dest", "") or ""
        aircraft_type = enriched.get("aircraft_type", "") or ""
        route = f"{origin}->{dest}" if origin and dest else ""

        for i, line in enumerate([airline, route, aircraft_type]):
            if line:
                clipped = _clip_text(line, font_size, mid_w)
                line_img = render_text(clipped, text_color, font_size)
                img.paste(line_img, (mid_x, row_y(i, line_img.height)))

        # Bottom text (rows 3-4): origin and destination airport names, left-aligned
        origin_name = enriched.get("origin_name", "") or ""
        dest_name = enriched.get("dest_name", "") or ""
        bottom_w = inner_w - stats_w - stats_gap

        for i, name in enumerate([origin_name, dest_name]):
            if name:
                clipped = _clip_text(name, font_size, bottom_w)
                name_img = render_text(clipped, text_color, font_size)
                img.paste(name_img, (pad, row_y(3 + i, name_img.height)))

        # Stats: right-aligned, vertically centered in rows 0-3
        for i, si in enumerate(stat_imgs):
            img.paste(si, (w - pad - si.width, row_y(i, si.height)))

        blit(self.canvas, img)

    def _draw_table(self) -> None:
        max_flights = int(self.config.get("max_flights", 10))
        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))
        font_size = 12

        glyph_h = render_text("A", (255, 255, 255), font_size).height
        row_h = glyph_h + 2

        img = Image.new("RGB", (self.canvas.width, self.canvas.height))

        for i, flight in enumerate(self._flights[:max_flights]):
            alt = f"{flight['alt_ft']:,}ft" if flight["alt_ft"] is not None else "   ---"
            spd = f"{flight['spd_kt']}kt" if flight["spd_kt"] is not None else "---"
            row = f"{flight['callsign']:<8}  {alt:>8}  {spd:>5}"
            row_img = render_text(row, text_color, font_size)
            y = i * row_h + 1
            if y + row_img.height <= img.height:
                img.paste(row_img, (2, y))

        blit(self.canvas, img)

    def _draw_no_flights(self) -> None:
        msg = "Loading..." if not self._fetched_once else "No flights nearby"
        msg_img = render_text(msg, (80, 80, 80), 14)
        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        x = (self.canvas.width - msg_img.width) // 2
        y = (self.canvas.height - msg_img.height) // 2
        img.paste(msg_img, (x, y))
        blit(self.canvas, img)
