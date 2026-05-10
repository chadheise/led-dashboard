from __future__ import annotations

import logging
import math
import time
from typing import Any, ClassVar

import httpx

from libraries.base import Library

logger = logging.getLogger(__name__)

_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)


def _km_to_deg(km: float) -> float:
    return km / 111.0


class OpenSkyLibrary(Library):
    id: ClassVar[str] = "opensky"
    name: ClassVar[str] = "OpenSky Network"
    description: ClassVar[str] = "Real-time aircraft positions via the OpenSky Network API"
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">'
        '<path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 00-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22'
        'l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/></svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "OpenSky Network",
        "properties": {
            "opensky_client_id": {
                "type": "string",
                "title": "Client ID (optional)",
                "default": "",
            },
            "opensky_client_secret": {
                "type": "string",
                "title": "Client Secret (optional)",
                "default": "",
            },
        },
    }

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._token: str | None = None
        self._token_expiry: float = 0.0

    async def fetch_flights(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        max_flights: int = 10,
    ) -> list[dict[str, Any]]:
        d = _km_to_deg(radius_km)
        token = await self._get_token()
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
            if resp.status_code != 200:
                logger.warning("OpenSky returned HTTP %d", resp.status_code)
                return []
            if not resp.content:
                return []
            data = resp.json()
        except Exception as exc:
            logger.warning("OpenSky fetch failed: %s", exc)
            return []

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
        result = flights[:max_flights]
        logger.info("OpenSky: %d flights in range (showing %d)", len(flights), len(result))
        return result

    async def _get_token(self) -> str | None:
        client_id = self._config.get("opensky_client_id", "").strip()
        client_secret = self._config.get("opensky_client_secret", "").strip()
        if not client_id or not client_secret:
            return None

        now = time.monotonic()
        if self._token and now < self._token_expiry - 60:
            return self._token

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    _TOKEN_URL,
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
                self._token = token
                self._token_expiry = now + expires_in
                return token
        except Exception:
            pass

        self._token = None
        return None
