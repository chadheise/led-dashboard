"""Flights snapshot suite: card and table modes, with/without enrichment."""

from __future__ import annotations

import time
from typing import Any

from tests.snaptest import harness
from tests.snaptest.logos import make_fixture_logo

_FLIGHT_DL = {
    "callsign": "DL699",
    "alt_m": 789, "alt_ft": 2559,
    "spd_kph": 456, "spd_mph": 283, "spd_kt": 246,
    "track": 270, "vr_kph": 23, "vr_mph": 14,
    "heading": 270, "dist_km": None,
}

_FLIGHT_UA = {
    "callsign": "UA1542",
    "alt_m": 10668, "alt_ft": 35000,
    "spd_kph": 880, "spd_mph": 547, "spd_kt": 475,
    "track": 92, "vr_kph": 0, "vr_mph": 0,
    "heading": 92, "dist_km": 12.4,
}

_FLIGHT_GA = {
    "callsign": "N456SW",
    "alt_m": 1219, "alt_ft": 4000,
    "spd_kph": 215, "spd_mph": 134, "spd_kt": None,
    "track": None, "vr_kph": -5, "vr_mph": -3,
    "heading": 180, "dist_km": 3.1,
}

_ENRICHED_DL = {
    "airline": "Delta Airlines",
    "origin": "JFK", "dest": "SEA",
    "aircraft_type": "Boeing 737-700",
    "operator_iata": "DL",
    "origin_name": "JFK Intl",
    "dest_name": "Seattle-Tacoma Intl",
}


def _seed(flights: list[dict[str, Any]], enriched: dict[str, dict[str, Any]], *, logos: bool):
    def seed(app: Any) -> None:
        app._flights = [dict(f) for f in flights]
        app._enriched = {k: dict(v) for k, v in enriched.items()}
        if logos:
            app._logos = {"DL": make_fixture_logo("DL", "c8102e")}
        app._fetched_once = True
        # Pin rotation/cycling timers to "just now" so frame 0 shows card 0
        # in its initial unit system.
        app._card_last_ts = time.monotonic()
        app._unit_ts = time.monotonic()

    return seed


def _fixtures() -> dict[str, dict[str, Any]]:
    return {
        "card_enriched_logo": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_DL], {"DL699": _ENRICHED_DL}, logos=True),
        },
        "card_enriched_metric": {
            "config": {"display_mode": "cards", "units": "metric"},
            "seed": _seed([_FLIGHT_DL], {"DL699": _ENRICHED_DL}, logos=False),
        },
        "card_unenriched": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_GA], {}, logos=False),
        },
        "table_3_flights": {
            "config": {"display_mode": "table"},
            "seed": _seed([_FLIGHT_DL, _FLIGHT_UA, _FLIGHT_GA], {}, logos=False),
        },
        "no_flights": {
            "config": {"display_mode": "cards"},
            "seed": _seed([], {}, logos=False),
        },
    }


def _register() -> None:
    from apps.flights.app import FlightsApp

    harness.register(
        harness.SnapshotSuite(
            app_id="flights",
            fixtures=_fixtures(),
            sizes=harness.CORE_SIZES,
            render=harness.app_case_render(FlightsApp),
        )
    )


_register()
