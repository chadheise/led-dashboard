"""Flight Tracker snapshot suite: each card kind, table mode, empty input."""

from __future__ import annotations

import time
from typing import Any

from tests.snaptest import harness

_TRACKED_SCHEDULED: dict[str, Any] = {
    "found": True,
    "ident": "DL699",
    "origin": "JFK", "dest": "SEA",
    "origin_name": "JFK Intl", "dest_name": "Seattle-Tacoma Intl",
    "airline": "Delta Air Lines", "operator_iata": "DL", "aircraft_type": "Boeing 737-700",
    "status": "Scheduled",
    "scheduled_off": "2026-06-18T14:00:00Z", "estimated_off": "2026-06-18T14:12:00Z",
    "actual_off": None,
    "scheduled_on": "2026-06-18T22:30:00Z", "estimated_on": None, "actual_on": None,
    "departure_delay": 720, "arrival_delay": None, "progress_percent": 0,
    "live": None, "icao24": "",
}

_TRACKED_AIRBORNE: dict[str, Any] = {
    "found": True,
    "ident": "UA1542",
    "origin": "ORD", "dest": "LAX",
    "origin_name": "Chicago O'Hare Intl", "dest_name": "Los Angeles Intl",
    "airline": "United Airlines", "operator_iata": "UA", "aircraft_type": "Boeing 737-900",
    "status": "En Route",
    "scheduled_off": "2026-06-18T10:00:00Z", "estimated_off": "2026-06-18T10:05:00Z",
    "actual_off": "2026-06-18T10:07:00Z",
    "scheduled_on": "2026-06-18T12:30:00Z", "estimated_on": "2026-06-18T12:42:00Z",
    "actual_on": None,
    "departure_delay": 420, "arrival_delay": 720, "progress_percent": 62,
    "live": {
        "lat": 39.5, "lon": -104.0, "alt_ft": 36000, "gs_kt": 470,
        "heading": 245, "updated_at": "2026-06-18T11:30:00Z",
    },
    "icao24": "a1b2c3",
}

_TRACKED_LANDED_ONTIME: dict[str, Any] = {
    "found": True,
    "ident": "AA100",
    "origin": "JFK", "dest": "LHR",
    "origin_name": "JFK Intl", "dest_name": "London Heathrow",
    "airline": "American Airlines", "operator_iata": "AA", "aircraft_type": "Boeing 777-300ER",
    "status": "Landed",
    "scheduled_off": "2026-06-17T22:00:00Z", "estimated_off": "2026-06-17T22:00:00Z",
    "actual_off": "2026-06-17T22:01:00Z",
    "scheduled_on": "2026-06-18T09:50:00Z", "estimated_on": "2026-06-18T09:50:00Z",
    "actual_on": "2026-06-18T09:48:00Z",
    "departure_delay": 60, "arrival_delay": 0, "progress_percent": 100,
    "live": None, "icao24": "",
}

_TRACKED_LANDED_DELAYED: dict[str, Any] = {
    "found": True,
    "ident": "BA286",
    "origin": "LHR", "dest": "JFK",
    "origin_name": "London Heathrow", "dest_name": "JFK Intl",
    "airline": "British Airways", "operator_iata": "BA", "aircraft_type": "Boeing 777-200",
    "status": "Landed",
    "scheduled_off": "2026-06-18T11:00:00Z", "estimated_off": "2026-06-18T11:35:00Z",
    "actual_off": "2026-06-18T11:38:00Z",
    "scheduled_on": "2026-06-18T13:50:00Z", "estimated_on": "2026-06-18T14:25:00Z",
    "actual_on": "2026-06-18T14:22:00Z",
    "departure_delay": 2280, "arrival_delay": 1920, "progress_percent": 100,
    "live": None, "icao24": "",
}

_TRACKED_NOT_FOUND: dict[str, Any] = {"found": False, "ident": "ZZ000"}


def _flights_config(
    flight_numbers: list[str], labels: dict[str, str] | None = None
) -> list[dict[str, str]]:
    labels = labels or {}
    return [{"number": fn, "label": labels.get(fn, "")} for fn in flight_numbers]


def _seed(
    tracked: dict[str, dict[str, Any]],
    flight_numbers: list[str],
    *,
    labels: dict[str, str] | None = None,
):
    flights = _flights_config(flight_numbers, labels)

    def seed(app: Any) -> None:
        app._tracked = {k: dict(v) for k, v in tracked.items()}
        app._live_overrides = {}
        app._fetched_once = True
        app._card_idx = 0
        app._card_last_ts = time.monotonic()
        app._unit_ts = time.monotonic()
        app.config["flights"] = flights

    return seed


def _fixtures() -> dict[str, dict[str, Any]]:
    return {
        "card_scheduled": {
            "config": {"display_mode": "cards", "flights": _flights_config(["DL699"]), "units": "imperial"},
            "seed": _seed({"DL699": _TRACKED_SCHEDULED}, ["DL699"]),
        },
        "card_scheduled_labeled": {
            "config": {"display_mode": "cards", "flights": _flights_config(["DL699"]), "units": "imperial"},
            "seed": _seed({"DL699": _TRACKED_SCHEDULED}, ["DL699"], labels={"DL699": "Bob's flight"}),
        },
        "card_airborne": {
            "config": {"display_mode": "cards", "flights": _flights_config(["UA1542"]), "units": "imperial"},
            "seed": _seed({"UA1542": _TRACKED_AIRBORNE}, ["UA1542"]),
        },
        "card_landed_ontime": {
            "config": {"display_mode": "cards", "flights": _flights_config(["AA100"]), "units": "imperial"},
            "seed": _seed({"AA100": _TRACKED_LANDED_ONTIME}, ["AA100"]),
        },
        "card_landed_delayed": {
            "config": {"display_mode": "cards", "flights": _flights_config(["BA286"]), "units": "imperial"},
            "seed": _seed({"BA286": _TRACKED_LANDED_DELAYED}, ["BA286"]),
        },
        "card_not_found": {
            "config": {"display_mode": "cards", "flights": _flights_config(["ZZ000"])},
            "seed": _seed({"ZZ000": _TRACKED_NOT_FOUND}, ["ZZ000"]),
        },
        "table_multi": {
            "config": {"display_mode": "table", "flights": _flights_config(["DL699", "UA1542", "AA100", "ZZ000"])},
            "seed": _seed(
                {
                    "DL699": _TRACKED_SCHEDULED,
                    "UA1542": _TRACKED_AIRBORNE,
                    "AA100": _TRACKED_LANDED_ONTIME,
                    "ZZ000": _TRACKED_NOT_FOUND,
                },
                ["DL699", "UA1542", "AA100", "ZZ000"],
            ),
        },
        "table_labeled": {
            "config": {"display_mode": "table", "flights": _flights_config(["DL699", "UA1542"])},
            "seed": _seed(
                {"DL699": _TRACKED_SCHEDULED, "UA1542": _TRACKED_AIRBORNE},
                ["DL699", "UA1542"],
                labels={"DL699": "Bob", "UA1542": "Amy"},
            ),
        },
        "no_flights": {
            "config": {"display_mode": "cards", "flights": []},
            "seed": _seed({}, []),
        },
    }


def _register() -> None:
    from apps.flight_tracker.app import FlightTrackerApp

    harness.register(
        harness.SnapshotSuite(
            app_id="flight_tracker",
            fixtures=_fixtures(),
            sizes=harness.CORE_SIZES,
            render=harness.app_case_render(FlightTrackerApp),
        )
    )


_register()
