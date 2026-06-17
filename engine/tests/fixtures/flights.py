"""Flights snapshot suite: card and table modes, with/without enrichment."""

from __future__ import annotations

import time
from typing import Any

from tests.snaptest import harness
from tests.snaptest.logos import make_fixture_logo

# ── Flights (one per distinct ADS-B category icon) ────────────────────────────

_FLIGHT_DL = {
    "callsign": "DL699",
    "alt_m": 789, "alt_ft": 2559,
    "spd_kph": 456, "spd_mph": 283, "spd_kt": 246,
    "track": 270, "vr_kph": 23, "vr_mph": 14,
    "heading": 270, "dist_km": None, "category": 4,   # large → airplane_jet
}

_FLIGHT_UA = {
    "callsign": "UA1542",
    "alt_m": 10668, "alt_ft": 35000,
    "spd_kph": 880, "spd_mph": 547, "spd_kt": 475,
    "track": 92, "vr_kph": 0, "vr_mph": 0,
    "heading": 92, "dist_km": 12.4, "category": 4,    # large → airplane_jet
}

_FLIGHT_GA = {
    "callsign": "N456SW",
    "alt_m": 1219, "alt_ft": 4000,
    "spd_kph": 215, "spd_mph": 134, "spd_kt": None,
    "track": None, "vr_kph": -5, "vr_mph": -3,
    "heading": 180, "dist_km": 3.1, "category": 2,    # light → airplane_small
}

# Category 0/None — unknown, defaults to airplane_jet
_FLIGHT_UNKNOWN_CAT = {
    "callsign": "UNK001",
    "alt_m": 3000, "alt_ft": 9843,
    "spd_kph": 350, "spd_mph": 217, "spd_kt": 189,
    "track": 180, "vr_kph": 0, "vr_mph": 0,
    "heading": 180, "dist_km": 20.0, "category": None,
}

# Category 2 — light (< 15,500 lbs), small prop plane
_FLIGHT_LIGHT = {
    "callsign": "N12345",
    "alt_m": 610, "alt_ft": 2000,
    "spd_kph": 185, "spd_mph": 115, "spd_kt": 100,
    "track": 90, "vr_kph": 3, "vr_mph": 2,
    "heading": 90, "dist_km": 5.0, "category": 2,
}

# Category 4 — large commercial narrowbody jet
_FLIGHT_LARGE_JET = {
    "callsign": "UAL123",
    "alt_m": 10668, "alt_ft": 35000,
    "spd_kph": 900, "spd_mph": 559, "spd_kt": 486,
    "track": 270, "vr_kph": 0, "vr_mph": 0,
    "heading": 270, "dist_km": 30.0, "category": 4,
}

# Category 6 — heavy widebody jet
_FLIGHT_HEAVY = {
    "callsign": "BAW286",
    "alt_m": 11000, "alt_ft": 36089,
    "spd_kph": 920, "spd_mph": 572, "spd_kt": 497,
    "track": 45, "vr_kph": 0, "vr_mph": 0,
    "heading": 45, "dist_km": 50.0, "category": 6,
}

# Category 7 — high performance (fighter jets, aerobatics)
_FLIGHT_HP = {
    "callsign": "RAPT01",
    "alt_m": 9144, "alt_ft": 30000,
    "spd_kph": 1200, "spd_mph": 746, "spd_kt": 648,
    "track": 0, "vr_kph": 150, "vr_mph": 93,
    "heading": 0, "dist_km": 8.0, "category": 7,
}

# Category 8 — rotorcraft (helicopter)
_FLIGHT_HELO = {
    "callsign": "N123HX",
    "alt_m": 305, "alt_ft": 1000,
    "spd_kph": 180, "spd_mph": 112, "spd_kt": 97,
    "track": 45, "vr_kph": 5, "vr_mph": 3,
    "heading": 45, "dist_km": 2.0, "category": 8,
}

# Category 9 — glider / sailplane
_FLIGHT_GLIDER = {
    "callsign": "N99GLD",
    "alt_m": 1829, "alt_ft": 6000,
    "spd_kph": 130, "spd_mph": 81, "spd_kt": 70,
    "track": 225, "vr_kph": -2, "vr_mph": -1,
    "heading": 225, "dist_km": 7.0, "category": 9,
}

# Category 10 — lighter-than-air (hot air balloon, blimp)
_FLIGHT_BALLOON = {
    "callsign": "N99BAL",
    "alt_m": 500, "alt_ft": 1640,
    "spd_kph": 20, "spd_mph": 12, "spd_kt": 11,
    "track": 315, "vr_kph": 1, "vr_mph": 1,
    "heading": 315, "dist_km": 4.0, "category": 10,
}

# Category 11 — parachutist / skydiver
_FLIGHT_PARA = {
    "callsign": "PARA01",
    "alt_m": 3658, "alt_ft": 12000,
    "spd_kph": 190, "spd_mph": 118, "spd_kt": 103,
    "track": 180, "vr_kph": -180, "vr_mph": -112,
    "heading": 180, "dist_km": 1.5, "category": 11,
}

# Category 12 — ultralight / hang-glider / paraglider
_FLIGHT_ULTRALIGHT = {
    "callsign": "N99ULT",
    "alt_m": 457, "alt_ft": 1500,
    "spd_kph": 70, "spd_mph": 43, "spd_kt": 38,
    "track": 135, "vr_kph": 0, "vr_mph": 0,
    "heading": 135, "dist_km": 3.0, "category": 12,
}

# Category 13 — reserved (unknown/no category broadcast)
_FLIGHT_RESERVED = {
    "callsign": "RES001",
    "alt_m": 2000, "alt_ft": 6562,
    "spd_kph": 300, "spd_mph": 186, "spd_kt": 162,
    "track": 90, "vr_kph": 0, "vr_mph": 0,
    "heading": 90, "dist_km": 15.0, "category": 13,
}

# Category 14 — unmanned aerial vehicle (drone)
_FLIGHT_DRONE = {
    "callsign": "DRONE1",
    "alt_m": 120, "alt_ft": 394,
    "spd_kph": 80, "spd_mph": 50, "spd_kt": 43,
    "track": 0, "vr_kph": 0, "vr_mph": 0,
    "heading": 0, "dist_km": 0.5, "category": 14,
}

# Category 15 — space / trans-atmospheric vehicle
_FLIGHT_SPACE = {
    "callsign": "SPACE1",
    "alt_m": 80000, "alt_ft": 262467,
    "spd_kph": 7000, "spd_mph": 4350, "spd_kt": 3780,
    "track": 90, "vr_kph": 500, "vr_mph": 311,
    "heading": 90, "dist_km": 100.0, "category": 15,
}

# Category 16 — surface vehicle (emergency: fire truck, ambulance)
_FLIGHT_EMERGENCY_VEH = {
    "callsign": "FIRE01",
    "alt_m": 0, "alt_ft": 0,
    "spd_kph": 80, "spd_mph": 50, "spd_kt": 43,
    "track": 270, "vr_kph": 0, "vr_mph": 0,
    "heading": 270, "dist_km": 1.0, "category": 16,
}

# Category 18 — point obstacle (tower, tethered balloon)
_FLIGHT_OBSTACLE = {
    "callsign": "OBST01",
    "alt_m": 300, "alt_ft": 984,
    "spd_kph": 0, "spd_mph": 0, "spd_kt": 0,
    "track": None, "vr_kph": 0, "vr_mph": 0,
    "heading": None, "dist_km": 2.5, "category": 18,
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
        app._card_last_ts = time.monotonic()
        app._unit_ts = time.monotonic()

    return seed


def _fixtures() -> dict[str, dict[str, Any]]:
    return {
        # ── enriched / logo tests ───────────────────────────────────────────
        "card_enriched_logo": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_DL], {"DL699": _ENRICHED_DL}, logos=True),
        },
        "card_enriched_metric": {
            "config": {"display_mode": "cards", "units": "metric"},
            "seed": _seed([_FLIGHT_DL], {"DL699": _ENRICHED_DL}, logos=False),
        },
        # ── one fixture per distinct aircraft-category icon ─────────────────
        "card_airplane_jet": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_LARGE_JET], {}, logos=False),
        },
        "card_airplane_small": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_LIGHT], {}, logos=False),
        },
        "card_airplane_hp": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_HP], {}, logos=False),
        },
        "card_helicopter": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_HELO], {}, logos=False),
        },
        "card_glider": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_GLIDER], {}, logos=False),
        },
        "card_balloon": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_BALLOON], {}, logos=False),
        },
        "card_parachute": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_PARA], {}, logos=False),
        },
        "card_ultralight": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_ULTRALIGHT], {}, logos=False),
        },
        "card_drone": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_DRONE], {}, logos=False),
        },
        "card_rocket": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_SPACE], {}, logos=False),
        },
        "card_surface_vehicle": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_EMERGENCY_VEH], {}, logos=False),
        },
        "card_obstacle": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_OBSTACLE], {}, logos=False),
        },
        "card_unknown_category": {
            "config": {"display_mode": "cards", "units": "imperial"},
            "seed": _seed([_FLIGHT_RESERVED], {}, logos=False),
        },
        # ── legacy unenriched / table / empty ──────────────────────────────
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
