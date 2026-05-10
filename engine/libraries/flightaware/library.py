from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import Any, ClassVar

import httpx
from PIL import Image

from libraries.base import Library

logger = logging.getLogger(__name__)

_AEROAPI_BASE = "https://aeroapi.flightaware.com/aeroapi"


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
            },
        },
    }

    async def enrich_flights(
        self, callsigns: list[str]
    ) -> dict[str, dict[str, Any]]:
        api_key = self._config.get("flightaware_api_key", "").strip()
        if not api_key or not callsigns:
            return {}

        enriched: dict[str, dict[str, Any]] = {}
        logger.info("FlightAware: enriching %d flights", len(callsigns))

        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"x-apikey": api_key},
        ) as client:
            results = await asyncio.gather(
                *[self._fetch_enrichment(client, cs) for cs in callsigns],
                return_exceptions=True,
            )

        for callsign, result in zip(callsigns, results):
            if isinstance(result, dict):
                enriched[callsign] = result

        logger.info("FlightAware: enriched %d/%d flights", len(enriched), len(callsigns))
        return enriched

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
