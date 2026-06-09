from __future__ import annotations

import asyncio
import datetime
import json
import logging
import time
from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar

import httpx
from PIL import Image

from libraries.base import Library

logger = logging.getLogger(__name__)

_AEROAPI_BASE = "https://aeroapi.flightaware.com/aeroapi"

_CACHE_PATH = Path("data/flightaware_cache.json")
_BUDGET_PATH = Path("data/flightaware_budget.json")

# Module-level defaults — also used as schema defaults
_DEFAULT_CACHE_TTL_DAYS: int = 7
_DEFAULT_MONTHLY_BUDGET: int = 800  # ~$4 at $0.005/call


class FlightAwareLibrary(Library):
    id: ClassVar[str] = "flightaware"
    name: ClassVar[str] = "FlightAware AeroAPI"
    description: ClassVar[str] = "Flight enrichment (route, airline, aircraft type) via FlightAware AeroAPI"
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="2" y1="12" x2="22" y2="12"/>'
        '<path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "FlightAware AeroAPI",
        "properties": {
            "flightaware_api_key": {
                "type": "string",
                "title": "AeroAPI Key (optional)",
                "default": "",
                "x-no-reset": True,
            },
            "cache_ttl_days": {
                "type": "number",
                "title": "Enrichment cache TTL (days)",
                "description": (
                    "How long to cache flight route data before re-fetching. "
                    "Route/airline info rarely changes — longer values save more API calls."
                ),
                "default": _DEFAULT_CACHE_TTL_DAYS,
                "minimum": 1,
                "maximum": 90,
            },
            "monthly_budget": {
                "type": "integer",
                "title": "Monthly API call budget",
                "description": (
                    "Maximum FlightAware API calls per month. "
                    "At ~$0.005/call on the free tier, $5 = 1000 calls. "
                    "Default 800 leaves a $1 safety margin."
                ),
                "default": _DEFAULT_MONTHLY_BUDGET,
                "minimum": 100,
                "maximum": 10000,
            },
        },
    }

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # callsign → (fetched_at_wall_time, enrichment_dict)
        self._enrichment_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._budget_month: str = ""
        self._budget_calls: int = 0
        self._load_disk_cache()
        self._load_budget()

    # ── Config properties ─────────────────────────────────────────────────────

    @property
    def _cache_ttl(self) -> float:
        """Cache TTL in seconds, read from config."""
        return float(self._config.get("cache_ttl_days", _DEFAULT_CACHE_TTL_DAYS)) * 24 * 3600

    @property
    def _budget_limit(self) -> int:
        """Monthly call budget, read from config."""
        return int(self._config.get("monthly_budget", _DEFAULT_MONTHLY_BUDGET))

    # ── Disk cache ────────────────────────────────────────────────────────────

    def _load_disk_cache(self) -> None:
        try:
            if _CACHE_PATH.exists():
                raw = json.loads(_CACHE_PATH.read_text())
                now = time.time()
                self._enrichment_cache = {
                    cs: (entry["fetched_at"], entry["data"])
                    for cs, entry in raw.items()
                    if now - entry["fetched_at"] < self._cache_ttl
                }
                logger.info(
                    "FlightAware: loaded %d cached enrichments from disk",
                    len(self._enrichment_cache),
                )
        except Exception as exc:
            logger.warning("FlightAware: cache load failed: %s", exc)

    def _save_disk_cache(self) -> None:
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            now = time.time()
            payload = {
                cs: {"fetched_at": ts, "data": d}
                for cs, (ts, d) in self._enrichment_cache.items()
                if now - ts < self._cache_ttl
            }
            tmp = _CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.rename(_CACHE_PATH)
        except Exception as exc:
            logger.warning("FlightAware: cache save failed: %s", exc)

    # ── Monthly budget ────────────────────────────────────────────────────────

    def _load_budget(self) -> None:
        current_month = datetime.date.today().strftime("%Y-%m")
        self._budget_month = current_month
        self._budget_calls = 0
        try:
            if _BUDGET_PATH.exists():
                data = json.loads(_BUDGET_PATH.read_text())
                if data.get("month") == current_month:
                    self._budget_calls = int(data.get("calls", 0))
                    logger.info(
                        "FlightAware: %d/%d API calls used this month",
                        self._budget_calls, self._budget_limit,
                    )
        except Exception as exc:
            logger.warning("FlightAware: budget load failed: %s", exc)

    @property
    def budget_tier(self) -> str:
        limit = self._budget_limit
        ratio = self._budget_calls / limit
        if ratio >= 1.0:
            return "disabled"
        if ratio >= 0.95:
            return "minimal"
        if ratio >= 0.80:
            return "conservative"
        return "normal"

    def _charge_budget(self, count: int) -> None:
        if count <= 0:
            return
        prev_tier = self.budget_tier
        self._budget_calls += count
        new_tier = self.budget_tier
        if new_tier != prev_tier:
            logger.warning(
                "FlightAware: budget tier changed %s → %s (%d/%d calls this month)",
                prev_tier, new_tier, self._budget_calls, self._budget_limit,
            )
        try:
            _BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _BUDGET_PATH.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"month": self._budget_month, "calls": self._budget_calls})
            )
            tmp.rename(_BUDGET_PATH)
        except Exception as exc:
            logger.warning("FlightAware: budget save failed: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────────

    async def enrich_flights(
        self, callsigns: list[str]
    ) -> dict[str, dict[str, Any]]:
        api_key = self._config.get("flightaware_api_key", "").strip()
        if not api_key or not callsigns:
            return {}

        # Budget exhausted: return only cache hits, no HTTP calls until next month
        if self.budget_tier == "disabled":
            logger.warning("FlightAware: monthly budget exhausted, serving cache only")
            now = time.time()
            return {
                cs: self._enrichment_cache[cs][1]
                for cs in callsigns
                if cs in self._enrichment_cache
                and now - self._enrichment_cache[cs][0] < self._cache_ttl
            }

        now = time.time()
        result: dict[str, dict[str, Any]] = {}
        to_fetch: list[str] = []

        for cs in callsigns:
            entry = self._enrichment_cache.get(cs)
            if entry is not None and (now - entry[0]) < self._cache_ttl:
                result[cs] = entry[1]  # cache hit — no HTTP call
            else:
                to_fetch.append(cs)

        if not to_fetch:
            logger.debug("FlightAware: all %d flights served from cache", len(result))
            return result

        logger.info(
            "FlightAware: enriching %d new / %d from cache",
            len(to_fetch), len(result),
        )

        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"x-apikey": api_key},
        ) as client:
            responses = await asyncio.gather(
                *[self._fetch_enrichment(client, cs) for cs in to_fetch],
                return_exceptions=True,
            )

        # Charge for all attempted requests (conservative: counts even failures)
        self._charge_budget(len(to_fetch))

        disk_dirty = False
        for callsign, response in zip(to_fetch, responses):
            if isinstance(response, dict):
                self._enrichment_cache[callsign] = (now, response)
                result[callsign] = response
                disk_dirty = True

        if disk_dirty:
            self._save_disk_cache()

        logger.info("FlightAware: enriched %d/%d flights", len(result), len(callsigns))
        return result

    async def fetch_logo(self, iata: str) -> Image.Image | None:
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(
                    f"https://www.gstatic.com/flights/airline_logos/70px/{iata}.png"
                )
                if resp.status_code == 200:
                    logger.info("Logo fetched for %s", iata)
                    return Image.open(BytesIO(resp.content)).convert("RGBA")
                logger.debug("No logo for %s: HTTP %d", iata, resp.status_code)
        except Exception as exc:
            logger.debug("Logo fetch failed for %s: %s", iata, exc)
        return None

    @staticmethod
    async def _fetch_enrichment(
        client: httpx.AsyncClient, callsign: str
    ) -> dict[str, Any] | None:
        try:
            resp = await client.get(f"{_AEROAPI_BASE}/flights/{callsign}")
            if resp.status_code != 200:
                logger.warning(
                    "FlightAware %s: HTTP %d — %s",
                    callsign, resp.status_code, resp.text[:300],
                )
                return None
            data = resp.json()
            flights_list = data.get("flights", [])
            if not flights_list:
                logger.debug("FlightAware %s: no flights in response", callsign)
                return None
            flight = flights_list[0]

            origin_obj = flight.get("origin") or {}
            dest_obj = flight.get("destination") or {}
            origin = origin_obj.get("code_iata") or origin_obj.get("code", "")
            dest = dest_obj.get("code_iata") or dest_obj.get("code", "")
            origin_name = origin_obj.get("name", "")
            dest_name = dest_obj.get("name", "")
            airline = flight.get("operator") or ""
            operator_iata = flight.get("operator_iata") or ""
            aircraft_type = flight.get("aircraft_type", "")

            logger.info(
                "FlightAware %s: %s→%s %s(%s) %s",
                callsign, origin, dest, airline, operator_iata, aircraft_type,
            )
            return {
                "origin": origin.upper() if origin else "",
                "dest": dest.upper() if dest else "",
                "origin_name": origin_name,
                "dest_name": dest_name,
                "airline": airline,
                "operator_iata": operator_iata.upper(),
                "aircraft_type": aircraft_type,
            }
        except Exception as exc:
            logger.warning("FlightAware enrichment failed for %s: %s", callsign, exc)
            return None
