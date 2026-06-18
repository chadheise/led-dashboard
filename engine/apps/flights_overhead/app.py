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
from libraries.text_renderer.library import render_text, draw_status_message
from libraries.opensky.library import OpenSkyLibrary
from libraries.flightaware.library import FlightAwareLibrary, iata_from_callsign
from apps.flights_overhead.icons import render_category_icon


def _clip_text(text: str, size: int, max_w: int) -> str:
    while text:
        if render_text(text, (255, 255, 255), size).width <= max_w:
            return text
        text = text[:-1]
    return ""


_UNIT_CYCLE_S: float = 4.0



def _build_stat_lines(flight: dict[str, Any], imperial: bool) -> list[str]:
    track = flight.get("track")
    trk_str = f"Trk: {track} deg" if track is not None else "Trk: ---"

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


class FlightsOverheadApp(DisplayApp):
    id: ClassVar[str] = "flights_overhead"
    name: ClassVar[str] = "Flights Overhead"
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
        "title": "Flights Overhead",
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
        icao24_map = {f["callsign"]: f.get("icao24", "") for f in self._flights}

        if self._is_active:
            tier = self._flightaware.budget_tier
            if tier in ("conservative", "minimal"):
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

            new_enriched = await self._flightaware.enrich_flights(enrich_callsigns, icao24_map)
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
        from_enrichment = {
            e["operator_iata"]
            for e in self._enriched.values()
            if e.get("operator_iata")
        }
        from_callsigns = {
            iata
            for f in self._flights
            if (iata := iata_from_callsign(f.get("callsign", ""))) is not None
        }
        needed = (from_enrichment | from_callsigns) - self._logos_fetched

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
        logo_gap = 2
        stats_gap = 2

        # Pick the largest font whose *measured* glyph height fits five rows;
        # if even the smallest font can't, show fewer rows instead of letting
        # the rows overlap.
        n_rows = 5
        font_size = 7
        size_cap = max(7, inner_h // 5 - 2)
        for size in (15, 12, 9, 8, 7):
            if size > size_cap:
                continue
            if 5 * (render_text("Ag", text_color, size).height + 1) - 1 <= inner_h:
                font_size = size
                break
        else:
            glyph_h = render_text("Ag", text_color, 7).height
            n_rows = max(2, (inner_h + 1) // (glyph_h + 1))
        slot_h = inner_h // n_rows

        def row_y(row: int, img_h: int) -> int:
            """Top-left y to vertically center img_h within slot `row`."""
            return pad + row * slot_h + (slot_h - img_h) // 2

        # Stats column: colon-aligned. Dropped entirely when it would consume
        # more than half the card (narrow panels) — airline and route win.
        stat_strs = _build_stat_lines(flight, self._show_imperial)[:n_rows]

        # Split "Label: value" → ("Label:", " value") for stable colon alignment
        stat_parts: list[tuple[str, str]] = []
        for s in stat_strs:
            if ": " in s:
                idx = s.index(": ")
                stat_parts.append((s[: idx + 1], s[idx + 1:]))
            else:
                stat_parts.append((s, ""))

        # Worst-case values sized to real flight maxima — keeps the colon column
        # stable as values update, without adding unnecessary extra space
        _worst_vals = [
            " 45000 ft", " 700 mph", " +100 mph",  # imperial
            " 13700 m", " 1100 kph", " +160 kph",  # metric
            " 359 deg", " ---",
        ]
        label_imgs = [render_text(lbl, text_color, font_size) for lbl, _ in stat_parts]
        value_imgs = [render_text(val, text_color, font_size) if val else None
                      for _, val in stat_parts]
        label_col_w = max((li.width for li in label_imgs), default=0)
        value_col_w = max(
            max((render_text(v, text_color, font_size).width for v in _worst_vals), default=0),
            max((vi.width for vi in value_imgs if vi is not None), default=0),
        )
        stats_w = label_col_w + value_col_w
        if stats_w > inner_w // 2:
            stat_parts = []
            label_imgs = []
            value_imgs = []
            label_col_w = 0
            value_col_w = 0
            stats_w = 0

        # Logo: square spanning the top rows, capped so text keeps room.
        logo_dim = min(min(3, n_rows) * slot_h, w // 4)
        operator_iata = (
            enriched.get("operator_iata", "")
            or iata_from_callsign(flight.get("callsign", ""))
            or ""
        )
        raw_logo = self._logos.get(operator_iata) if operator_iata else None
        if logo_dim >= 8:
            if raw_logo is not None:
                resized = raw_logo.resize((logo_dim, logo_dim), Image.LANCZOS)
                bg = Image.new("RGB", resized.size, (0, 0, 0))
                if resized.mode == "RGBA":
                    bg.paste(resized.convert("RGB"), mask=resized.split()[3])
                else:
                    bg.paste(resized.convert("RGB"))
                img.paste(bg, (pad, pad))
            else:
                fallback = render_category_icon(flight.get("category"), logo_dim)
                bg = Image.new("RGB", (logo_dim, logo_dim), (0, 0, 0))
                bg.paste(fallback.convert("RGB"), mask=fallback.split()[3])
                img.paste(bg, (pad, pad))
            mid_x = pad + logo_dim + logo_gap
        else:
            mid_x = pad

        # Middle text: airline name, route, aircraft type (as many as fit).
        # Fall back to the callsign (always present from OpenSky) when no
        # enrichment is available, so a flight is never shown as bare stats.
        mid_w = max(0, (w - pad - stats_w - (stats_gap if stats_w else 0)) - mid_x)
        airline = enriched.get("airline", "") or flight.get("callsign", "") or ""
        origin = enriched.get("origin", "") or ""
        dest = enriched.get("dest", "") or ""
        aircraft_type = enriched.get("aircraft_type", "") or ""
        route = f"{origin}->{dest}" if origin and dest else ""

        for i, line in enumerate([airline, route, aircraft_type][: min(3, n_rows)]):
            if line and mid_w > 0:
                clipped = _clip_text(line, font_size, mid_w)
                line_img = render_text(clipped, text_color, font_size)
                img.paste(line_img, (mid_x, row_y(i, line_img.height)))

        # Bottom text (rows 3-4, full-height cards only): airport names
        if n_rows == 5:
            origin_name = enriched.get("origin_name", "") or ""
            dest_name = enriched.get("dest_name", "") or ""
            bottom_w = inner_w - stats_w - (stats_gap if stats_w else 0)

            for i, name in enumerate([origin_name, dest_name]):
                if name and bottom_w > 0:
                    clipped = _clip_text(name, font_size, bottom_w)
                    name_img = render_text(clipped, text_color, font_size)
                    img.paste(name_img, (pad, row_y(3 + i, name_img.height)))

        # Stats: colon-aligned — labels right-aligned to colon column,
        # values right-aligned to the canvas edge
        if stat_parts:
            colon_x = w - pad - value_col_w
            for i, (li, vi) in enumerate(zip(label_imgs, value_imgs)):
                img.paste(li, (colon_x - li.width, row_y(i, li.height)))
                if vi is not None:
                    img.paste(vi, (w - pad - vi.width, row_y(i, vi.height)))

        blit(self.canvas, img)

    def _draw_table(self) -> None:
        max_flights = int(self.config.get("max_flights", 10))
        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))
        max_w = self.canvas.width - 4

        def _rows(with_alt: bool, with_spd: bool) -> list[str]:
            rows = []
            for flight in self._flights[:max_flights]:
                parts = [f"{flight['callsign']:<8}"]
                if with_alt:
                    alt = f"{flight['alt_ft']:,}ft" if flight["alt_ft"] is not None else "   ---"
                    parts.append(f"{alt:>8}")
                if with_spd:
                    spd = f"{flight['spd_kt']}kt" if flight["spd_kt"] is not None else "---"
                    parts.append(f"{spd:>5}")
                rows.append("  ".join(parts))
            return rows

        # Shrink the font, then drop the rightmost columns, until the widest
        # row actually fits — never clip mid-column.
        rows: list[str] = []
        font_size = 12
        for columns in ((True, True), (True, False), (False, False)):
            candidate_rows = _rows(*columns)
            widest = max(candidate_rows, key=lambda r: render_text(r, text_color, 12).width)
            font_size = next(
                (s for s in (12, 9, 8, 7) if render_text(widest, text_color, s).width <= max_w),
                None,
            )
            if font_size is not None:
                rows = candidate_rows
                break
        if font_size is None:
            font_size, rows = 7, _rows(False, False)

        glyph_h = render_text("A", (255, 255, 255), font_size).height
        row_h = glyph_h + 2

        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        for i, row in enumerate(rows):
            row_img = render_text(row, text_color, font_size)
            y = i * row_h + 1
            if y + row_img.height <= img.height:
                img.paste(row_img, (2, y))

        blit(self.canvas, img)

    def _draw_no_flights(self) -> None:
        msg = "Loading..." if not self._fetched_once else "No flights nearby"
        draw_status_message(self.canvas, msg)
