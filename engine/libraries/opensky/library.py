from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any, ClassVar

import httpx

from libraries.base import Library

logger = logging.getLogger(__name__)

_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)

_STATUS_PATH = Path("data/opensky_status.json")

# Module-level defaults — also used as schema defaults
_DEFAULT_BACKOFF_BASE: int = 60    # seconds before first retry after 429
_DEFAULT_BACKOFF_MAX: int = 180    # cap in seconds
_BACKOFF_FACTOR: float = 2.0


def _km_to_deg(km: float) -> float:
    return km / 111.0


class OpenSkyLibrary(Library):
    id: ClassVar[str] = "opensky"
    name: ClassVar[str] = "OpenSky Network"
    has_status: ClassVar[bool] = True
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
                "x-no-reset": True,
            },
            "opensky_client_secret": {
                "type": "string",
                "title": "Client Secret (optional)",
                "default": "",
                "x-no-reset": True,
            },
            "backoff_base_seconds": {
                "type": "integer",
                "title": "Throttle backoff — initial (seconds)",
                "description": (
                    "How long to wait after the first 429 rate-limit response before retrying. "
                    "Doubles on each consecutive throttle up to the maximum."
                ),
                "default": _DEFAULT_BACKOFF_BASE,
                "minimum": 10,
                "maximum": 300,
            },
            "backoff_max_seconds": {
                "type": "integer",
                "title": "Throttle backoff — maximum (seconds)",
                "description": (
                    "Cap on the wait between throttled retries. "
                    "Stale flight positions are shown on-screen during this window."
                ),
                "default": _DEFAULT_BACKOFF_MAX,
                "minimum": 30,
                "maximum": 900,
            },
        },
    }

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._throttled_until: float = 0.0
        self._backoff_interval: float = self._backoff_base

    @property
    def _backoff_base(self) -> float:
        return float(self._config.get("backoff_base_seconds", _DEFAULT_BACKOFF_BASE))

    @property
    def _backoff_max(self) -> float:
        return float(self._config.get("backoff_max_seconds", _DEFAULT_BACKOFF_MAX))

    # ── Status (settings UI) ──────────────────────────────────────────────────

    def _save_status(
        self, *, flight_count: int | None = None, throttled_for: float | None = None
    ) -> None:
        """Persist a small status snapshot so the settings UI can read live
        usage even though it runs in a separate library instance.

        Timestamps are wall-clock (``time.time()``) so they survive restarts and
        are comparable across processes — unlike the monotonic clock used for
        throttle bookkeeping.
        """
        now = time.time()
        try:
            prev: dict[str, Any] = {}
            if _STATUS_PATH.exists():
                prev = json.loads(_STATUS_PATH.read_text())
            payload = {
                "last_fetch_at": now if throttled_for is None else prev.get("last_fetch_at"),
                "flight_count": flight_count
                if flight_count is not None
                else prev.get("flight_count"),
                "throttled_until": now + throttled_for if throttled_for else 0,
            }
            _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _STATUS_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.rename(_STATUS_PATH)
        except Exception as exc:
            logger.warning("OpenSky: status save failed: %s", exc)

    def get_status(self) -> dict[str, Any]:
        last_fetch: float | None = None
        flight_count: int | None = None
        throttled_until: float = 0.0
        try:
            if _STATUS_PATH.exists():
                data = json.loads(_STATUS_PATH.read_text())
                last_fetch = data.get("last_fetch_at")
                flight_count = data.get("flight_count")
                throttled_until = float(data.get("throttled_until") or 0)
        except Exception as exc:
            logger.warning("OpenSky: status load failed: %s", exc)

        throttled = throttled_until > time.time()
        live_items: list[dict[str, Any]] = [
            {"label": "Last successful fetch", "value": last_fetch, "kind": "timestamp"},
            {
                "label": "Flights in range",
                "value": str(flight_count) if flight_count is not None else "—",
            },
            {
                "label": "Rate-limit status",
                "value": "Throttled — serving stale data" if throttled else "OK",
            },
        ]
        if throttled:
            live_items.append(
                {"label": "Retrying", "value": throttled_until, "kind": "timestamp"}
            )

        return {
            "note": "OpenSky Network is free to use — there is no per-call cost.",
            "sections": [
                {
                    "label": "Usage",
                    "items": [{"label": "Estimated cost", "value": "Free (no cost)"}],
                },
                {"label": "Live data", "items": live_items},
            ],
        }

    async def fetch_flights(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        max_flights: int = 10,
    ) -> list[dict[str, Any]] | None:
        """Return fresh flights, [] if none in range, or None if throttled/errored (use stale data)."""
        now = time.monotonic()
        if now < self._throttled_until:
            logger.info(
                "OpenSky: rate-limited, serving stale data (%.0fs remaining)",
                self._throttled_until - now,
            )
            return None

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
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                backoff = (
                    min(float(retry_after), self._backoff_max)
                    if retry_after and retry_after.isdigit()
                    else self._backoff_interval
                )
                self._throttled_until = time.monotonic() + backoff
                self._backoff_interval = min(self._backoff_interval * _BACKOFF_FACTOR, self._backoff_max)
                logger.warning(
                    "OpenSky: throttled (429), backing off %.0fs (showing stale data)", backoff
                )
                self._save_status(throttled_for=backoff)
                return None
            if resp.status_code != 200:
                logger.warning("OpenSky: HTTP %d, serving stale data", resp.status_code)
                return None
            if not resp.content:
                return []
            data = resp.json()
        except Exception as exc:
            logger.warning("OpenSky fetch failed: %s", exc)
            return None

        # Successful response — reset backoff to configured base
        self._backoff_interval = self._backoff_base

        flights: list[dict[str, Any]] = []
        for state in data.get("states") or []:
            callsign = (state[1] or "").strip() or state[0] or "??????"
            alt_m: float | None = state[7]
            velocity: float | None = state[9]
            heading: float | None = state[10]
            f_lat: float | None = state[6]
            f_lon: float | None = state[5]

            vr_ms: float | None = state[11]

            alt_ft = round(alt_m * 3.281) if alt_m is not None else None
            alt_m_rounded = round(alt_m) if alt_m is not None else None
            spd_kt = round(velocity * 1.944) if velocity is not None else None
            spd_kph = round(velocity * 3.6) if velocity is not None else None
            spd_mph = round(velocity * 2.237) if velocity is not None else None
            track_deg = round(heading) if heading is not None else None
            vr_kph = round(vr_ms * 3.6) if vr_ms is not None else None
            vr_mph = round(vr_ms * 2.237) if vr_ms is not None else None
            dist_km = (
                math.sqrt((f_lat - lat) ** 2 + (f_lon - lon) ** 2) * 111.0
                if f_lat is not None and f_lon is not None
                else None
            )

            flights.append({
                "callsign": callsign[:8].upper(),
                "alt_ft": alt_ft,
                "alt_m": alt_m_rounded,
                "spd_kt": spd_kt,
                "spd_kph": spd_kph,
                "spd_mph": spd_mph,
                "track": track_deg,
                "vr_kph": vr_kph,
                "vr_mph": vr_mph,
                "heading": heading,
                "dist_km": dist_km,
            })

        flights.sort(key=lambda f: f["dist_km"] if f["dist_km"] is not None else 9999)
        result = flights[:max_flights]
        logger.info("OpenSky: %d flights in range (showing %d)", len(flights), len(result))
        self._save_status(flight_count=len(flights))
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
