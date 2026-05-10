from __future__ import annotations

import asyncio
import math
import time
from typing import Any, ClassVar

import httpx
from PIL import Image, ImageDraw

from canvas.base import Canvas
from plugin_base import DisplayApp
from apps._helpers import blit, load_font, parse_color


_OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)
_FLIGHTAWARE_BASE = "https://aeroapi.flightaware.com/aeroapi"


def _km_to_deg(km: float) -> float:
    return km / 111.0


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

    global_config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Flights — Global Settings",
        "properties": {
            "opensky_client_id": {
                "type": "string",
                "title": "OpenSky Client ID (optional)",
                "default": "",
            },
            "opensky_client_secret": {
                "type": "string",
                "title": "OpenSky Client Secret (optional)",
                "default": "",
            },
            "flightaware_api_key": {
                "type": "string",
                "title": "FlightAware AeroAPI Key (optional)",
                "default": "",
            },
        },
    }

    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Flights",
        "properties": {
            "location": {
                "type": "object",
                "title": "Location",
                "x-input-type": "location",
                "default": {"latitude": 0.0, "longitude": 0.0},
                "properties": {
                    "latitude": {"type": "number", "default": 0.0},
                    "longitude": {"type": "number", "default": 0.0},
                },
            },
            "radius_km": {
                "type": "number",
                "title": "Search radius (km)",
                "default": 50,
                "minimum": 1,
                "maximum": 500,
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
            "scene_duration": {
                "type": "number",
                "title": "Scene duration (s)",
                "default": 45,
            },
        },
        "required": ["location"],
    }

    def __init__(
        self,
        config: dict[str, Any],
        canvas: Canvas,
        global_config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(config, canvas, global_config)
        self._flights: list[dict[str, Any]] = []
        self._enriched: dict[str, dict[str, Any]] = {}
        self._fetched_once: bool = False
        self._card_idx: int = 0
        self._card_last_ts: float = 0.0
        self._opensky_token: str | None = None
        self._opensky_token_expiry: float = 0.0

    # ── Token management ───────────────────────────────────────────────────────

    async def _get_opensky_token(self) -> str | None:
        client_id = self.global_config.get("opensky_client_id", "").strip()
        client_secret = self.global_config.get("opensky_client_secret", "").strip()
        if not client_id or not client_secret:
            return None

        now = time.monotonic()
        if self._opensky_token and now < self._opensky_token_expiry - 60:
            return self._opensky_token

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    _OPENSKY_TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                )
            data = resp.json()
            token = data.get("access_token")
            expires_in = int(data.get("expires_in", 300))
            if token:
                self._opensky_token = token
                self._opensky_token_expiry = now + expires_in
                return token
        except Exception:
            pass

        self._opensky_token = None
        return None

    # ── Data fetching ──────────────────────────────────────────────────────────

    async def fetch_data(self) -> None:
        self._enriched = {}
        await self._fetch_flights()
        await self._enrich_flights()

    async def _fetch_flights(self) -> None:
        loc = self.config.get("location", {})
        lat = float(loc.get("latitude", 0.0) if isinstance(loc, dict) else 0.0)
        lon = float(loc.get("longitude", 0.0) if isinstance(loc, dict) else 0.0)
        radius_km = float(self.config.get("radius_km", 50.0))
        max_flights = int(self.config.get("max_flights", 10))
        d = _km_to_deg(radius_km)

        token = await self._get_opensky_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        params = {
            "lamin": lat - d,
            "lomin": lon - d,
            "lamax": lat + d,
            "lomax": lon + d,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://opensky-network.org/api/states/all",
                    params=params,
                    headers=headers,
                )
            data = resp.json()
        except Exception:
            return

        flights: list[dict[str, Any]] = []
        for state in data.get("states") or []:
            callsign = (state[1] or "").strip() or state[0] or "??????"
            alt_m: float | None = state[7]
            velocity: float | None = state[9]
            heading: float | None = state[10]
            f_lat: float | None = state[6]
            f_lon: float | None = state[5]

            alt_ft = round(alt_m * 3.281) if alt_m is not None else None
            spd_kt = round(velocity * 1.944) if velocity is not None else None
            dist_km = (
                math.sqrt((f_lat - lat) ** 2 + (f_lon - lon) ** 2) * 111.0
                if f_lat is not None and f_lon is not None
                else None
            )

            flights.append({
                "callsign": callsign[:8].upper(),
                "alt_ft": alt_ft,
                "spd_kt": spd_kt,
                "heading": heading,
                "dist_km": dist_km,
            })

        flights.sort(key=lambda f: f["dist_km"] if f["dist_km"] is not None else 9999)
        self._flights = flights[:max_flights]
        self._card_idx = 0
        self._card_last_ts = time.monotonic()
        self._fetched_once = True

    async def _enrich_flights(self) -> None:
        api_key = self.global_config.get("flightaware_api_key", "").strip()
        if not api_key or not self._flights:
            return

        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"x-apikey": api_key},
        ) as client:
            await asyncio.gather(
                *[self._fetch_enrichment(client, f["callsign"]) for f in self._flights],
                return_exceptions=True,
            )

    async def _fetch_enrichment(
        self, client: httpx.AsyncClient, callsign: str
    ) -> None:
        try:
            resp = await client.get(f"{_FLIGHTAWARE_BASE}/flights/{callsign}")
            if resp.status_code != 200:
                return
            data = resp.json()
            flights_list = data.get("flights", [])
            if not flights_list:
                return
            flight = flights_list[0]

            origin_obj = flight.get("origin") or {}
            dest_obj = flight.get("destination") or {}
            origin = origin_obj.get("code_iata") or origin_obj.get("code", "")
            dest = dest_obj.get("code_iata") or dest_obj.get("code", "")
            airline = flight.get("operator") or ""
            aircraft_type = flight.get("aircraft_type", "")

            self._enriched[callsign] = {
                "origin": origin.upper() if origin else "",
                "dest": dest.upper() if dest else "",
                "airline": airline,
                "aircraft_type": aircraft_type,
            }
        except Exception:
            pass

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

        font_size = max(8, inner_h // 3 - 1)
        font = load_font(font_size)

        dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        row_bbox = dummy_draw.textbbox((0, 0), "A", font=font)
        row_h = row_bbox[3] - row_bbox[1] + 1

        block_h = row_h * 3
        y0 = pad + max(0, (inner_h - block_h) // 2) - row_bbox[1]

        airline = enriched.get("airline", "")
        line1 = f"{flight['callsign']} {airline}" if airline else flight["callsign"]
        line1 = _clip_text(draw, line1, font, inner_w)

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
            draw.text((pad, y0 + i * row_h), line, font=font, fill=text_color)

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
