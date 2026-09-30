"""Flight Tracker snapshot suite: each card kind, table mode, empty input."""

from __future__ import annotations

import time
from typing import Any

from tests.framework import harness
from tests.framework.logos import make_fixture_logo

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

_TRACKED_CANCELLED: dict[str, Any] = {
    "found": True,
    "ident": "WN2020",
    "origin": "DEN", "dest": "MDW",
    "origin_name": "Denver Intl", "dest_name": "Chicago Midway Intl",
    "airline": "Southwest Airlines", "operator_iata": "WN", "aircraft_type": "Boeing 737-700",
    "status": "Cancelled", "cancelled": True,
    "scheduled_off": "2026-06-18T15:00:00Z", "estimated_off": None, "actual_off": None,
    "scheduled_on": "2026-06-18T17:20:00Z", "estimated_on": None, "actual_on": None,
    "departure_delay": None, "arrival_delay": None, "progress_percent": 0,
    "live": None, "icao24": "",
}

_TRACKED_NOT_FOUND: dict[str, Any] = {"found": False, "ident": "ZZ000"}

# Gate/terminal/baggage variants (AeroAPI "when known" fields). Each reuses a
# phase's base data and adds the fields the schedule row surfaces for that phase:
# origin terminal/gate before departure, destination terminal/gate once airborne,
# and destination gate + baggage belt on arrival.
_TRACKED_SCHEDULED_GATE: dict[str, Any] = {
    **_TRACKED_SCHEDULED,
    "terminal_origin": "4", "gate_origin": "B22",
    "terminal_dest": "S", "gate_dest": "A7",
}

_TRACKED_AIRBORNE_GATE: dict[str, Any] = {
    **_TRACKED_AIRBORNE,
    "terminal_dest": "5", "gate_dest": "68A",
}

_TRACKED_LANDED_GATE_BAG: dict[str, Any] = {
    **_TRACKED_LANDED_ONTIME,
    "terminal_dest": "3", "gate_dest": "12", "baggage_claim": "7",
}


# ── Flighty-source records (already in normalized _tracked shape, keyed by the
# synthesized "ident|owner|date" the app builds) ─────────────────────────────
_FLIGHTY_OWN: dict[str, Any] = {
    "found": True, "ident": "DL2543", "number": "DL2543", "owner": "me",
    "origin": "DEN", "dest": "SEA", "airline": "DL", "operator_iata": "DL",
    "aircraft_type": "BCS3", "status": "", "cancelled": False,
    "scheduled_off": "2026-06-18T00:42:00Z", "estimated_off": "2026-06-18T00:42:00Z",
    "actual_off": None,
    "scheduled_on": "2026-06-18T03:30:00Z", "estimated_on": "2026-06-18T03:30:00Z",
    "actual_on": None,
    "departure_delay": 0, "arrival_delay": 0, "progress_percent": None,
    "live": None, "icao24": "",
    "gate_origin": "", "gate_dest": "", "terminal_origin": "Main",
    "terminal_dest": "Main", "baggage_claim": "", "date": "2026-06-18",
}

_FLIGHTY_FRIEND: dict[str, Any] = {
    "found": True, "ident": "DL2437", "number": "DL2437", "owner": "friend",
    "origin": "JFK", "dest": "MSP", "airline": "DL", "operator_iata": "DL",
    "aircraft_type": "B739", "status": "", "cancelled": False,
    "scheduled_off": "2026-06-18T21:05:00Z", "estimated_off": "2026-06-18T21:17:00Z",
    "actual_off": None,
    "scheduled_on": "2026-06-19T00:40:00Z", "estimated_on": "2026-06-19T00:52:00Z",
    "actual_on": None,
    "departure_delay": 720, "arrival_delay": 720, "progress_percent": None,
    "live": None, "icao24": "",
    "gate_origin": "B6", "gate_dest": "F6", "terminal_origin": "4",
    "terminal_dest": "1", "baggage_claim": "10", "date": "2026-06-18",
}


def _seed_flighty(order_labels: list[tuple[str, dict[str, Any], str]]):
    """Seed the app as if the Flighty source imported these flights.

    ``order_labels`` is a list of (key, tracked, owner_label); own flights use an
    empty label (card shows the airline/ident), friends use their name.
    """
    def seed(app: Any) -> None:
        app.config["source"] = "flighty"
        app._tracked = {k: dict(t) for k, t, _ in order_labels}
        app._flighty_order = [k for k, _, _ in order_labels]
        app._flighty_labels = {k: lbl for k, _, lbl in order_labels}
        app._live_overrides = {}
        app._logos = {"DL": make_fixture_logo("DL", "c8102e")}
        app._logos_fetched = {"DL"}
        app._fetched_once = True
        app._card_idx = 0
        app._card_last_ts = time.monotonic()
        app._unit_ts = time.monotonic()

    return seed


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
    logo_codes: dict[str, str] | None = None,
):
    """Seed app state for a snapshot fixture.

    logo_codes maps an airline IATA code -> color hex for generated placeholder
    logos, mirroring the Flights Overhead suite so logo rendering is covered
    offline.
    """
    flights = _flights_config(flight_numbers, labels)

    def seed(app: Any) -> None:
        app._tracked = {k: dict(v) for k, v in tracked.items()}
        app._live_overrides = {}
        codes = logo_codes or {}
        app._logos = {iata: make_fixture_logo(iata, color) for iata, color in codes.items()}
        app._logos_fetched = set(codes)
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
            "seed": _seed({"DL699": _TRACKED_SCHEDULED}, ["DL699"], logo_codes={"DL": "c8102e"}),
        },
        "card_scheduled_labeled": {
            "config": {"display_mode": "cards", "flights": _flights_config(["DL699"]), "units": "imperial"},
            "seed": _seed(
                {"DL699": _TRACKED_SCHEDULED}, ["DL699"],
                labels={"DL699": "Bob's flight"}, logo_codes={"DL": "c8102e"},
            ),
        },
        # No logo available -> the generic plane icon fallback is drawn instead.
        "card_scheduled_no_logo": {
            "config": {"display_mode": "cards", "flights": _flights_config(["DL699"]), "units": "imperial"},
            "seed": _seed({"DL699": _TRACKED_SCHEDULED}, ["DL699"]),
        },
        "card_airborne": {
            "config": {"display_mode": "cards", "flights": _flights_config(["UA1542"]), "units": "imperial"},
            "seed": _seed({"UA1542": _TRACKED_AIRBORNE}, ["UA1542"], logo_codes={"UA": "003087"}),
        },
        "card_airborne_metric": {
            "config": {"display_mode": "cards", "flights": _flights_config(["UA1542"]), "units": "metric"},
            "seed": _seed({"UA1542": _TRACKED_AIRBORNE}, ["UA1542"], logo_codes={"UA": "003087"}),
        },
        "card_landed_ontime": {
            "config": {"display_mode": "cards", "flights": _flights_config(["AA100"]), "units": "imperial"},
            "seed": _seed({"AA100": _TRACKED_LANDED_ONTIME}, ["AA100"], logo_codes={"AA": "0078d2"}),
        },
        "card_landed_delayed": {
            "config": {"display_mode": "cards", "flights": _flights_config(["BA286"]), "units": "imperial"},
            "seed": _seed({"BA286": _TRACKED_LANDED_DELAYED}, ["BA286"], logo_codes={"BA": "075aaa"}),
        },
        "card_cancelled": {
            "config": {"display_mode": "cards", "flights": _flights_config(["WN2020"]), "units": "imperial"},
            "seed": _seed({"WN2020": _TRACKED_CANCELLED}, ["WN2020"], logo_codes={"WN": "f9b612"}),
        },
        "card_not_found": {
            "config": {"display_mode": "cards", "flights": _flights_config(["ZZ000"])},
            "seed": _seed({"ZZ000": _TRACKED_NOT_FOUND}, ["ZZ000"]),
        },
        # Gate/terminal/baggage on the schedule row, one per flight phase.
        "card_scheduled_gate": {
            "config": {"display_mode": "cards", "flights": _flights_config(["DL699"]), "units": "imperial"},
            "seed": _seed({"DL699": _TRACKED_SCHEDULED_GATE}, ["DL699"], logo_codes={"DL": "c8102e"}),
        },
        "card_airborne_gate": {
            "config": {"display_mode": "cards", "flights": _flights_config(["UA1542"]), "units": "imperial"},
            "seed": _seed({"UA1542": _TRACKED_AIRBORNE_GATE}, ["UA1542"], logo_codes={"UA": "003087"}),
        },
        "card_landed_gate_bag": {
            "config": {"display_mode": "cards", "flights": _flights_config(["AA100"]), "units": "imperial"},
            "seed": _seed({"AA100": _TRACKED_LANDED_GATE_BAG}, ["AA100"], logo_codes={"AA": "0078d2"}),
        },
        # Flighty source: an own flight (no owner label) and a friend's flight
        # (labeled with the friend's name), the latter with full gate/terminal/bag.
        "flighty_own": {
            "config": {"display_mode": "cards", "source": "flighty", "units": "imperial"},
            "seed": _seed_flighty([("DL2543|me|2026-06-18", _FLIGHTY_OWN, "")]),
        },
        "flighty_friend": {
            "config": {"display_mode": "cards", "source": "flighty", "units": "imperial"},
            "seed": _seed_flighty([("DL2437|friend|2026-06-18", _FLIGHTY_FRIEND, "Sam")]),
        },
        "flighty_table": {
            "config": {"display_mode": "table", "source": "flighty"},
            "seed": _seed_flighty([
                ("DL2543|me|2026-06-18", _FLIGHTY_OWN, ""),
                ("DL2437|friend|2026-06-18", _FLIGHTY_FRIEND, "Sam"),
            ]),
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
