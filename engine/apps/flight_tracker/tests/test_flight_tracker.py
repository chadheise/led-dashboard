"""Flight Tracker config parsing + timezone-aware flight-instance selection.

Covers the three behaviours that were buggy in real use:
  * flexible flight-number parsing (ICAO/IATA, with or without spaces),
  * per-flight labels (with backward-compat for the legacy single-label config),
  * date matching that interprets the user's locally-picked date in their
    timezone so evening flights aren't missed by an off-by-one UTC date.
"""

from __future__ import annotations

import datetime
from typing import Any

from apps.flight_tracker.app import FlightTrackerApp
from canvas.simulator import SimulatorCanvas
from libraries.flightaware.library import _select_flight_instance


def _app(config: dict[str, Any]) -> FlightTrackerApp:
    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(64, 32, _noop_broadcast)
    return FlightTrackerApp(config, canvas, {}, {})


# ── Flight-number parsing (req 2) ──────────────────────────────────────────────

def test_flight_numbers_normalize_spaces_and_case():
    app = _app({"flights": [
        {"number": "dl 1070", "label": ""},
        {"number": " DAL1070 ", "label": ""},
        {"number": "ua\t  100", "label": ""},
    ]})
    assert app._flight_numbers() == ["DL1070", "DAL1070", "UA100"]


def test_flight_numbers_drop_blanks_no_cap():
    app = _app({"flights": [{"number": n} for n in
                            ["AA1", "", "  ", "AA2", "AA3", "AA4", "AA5", "AA6"]]})
    assert app._flight_numbers() == ["AA1", "AA2", "AA3", "AA4", "AA5", "AA6"]


# ── Per-flight labels (req 3) ──────────────────────────────────────────────────

def test_per_flight_labels():
    app = _app({"flights": [
        {"number": "DL699", "label": "Bob"},
        {"number": "UA100", "label": "Amy"},
    ]})
    assert app._labels() == {"DL699": "Bob", "UA100": "Amy"}


def test_legacy_config_backward_compatible():
    # Module instances saved before per-flight labels: flight_numbers[] + label.
    app = _app({"flight_numbers": ["dl699", "ua100"], "label": "Trip"})
    assert app._flight_numbers() == ["DL699", "UA100"]
    # Legacy single label applies to the first flight only.
    assert app._labels() == {"DL699": "Trip", "UA100": ""}


# ── Timezone-aware date matching (req 4) ───────────────────────────────────────

# An evening flight in Los Angeles: 23:00 PDT on Jun 17 == 06:00 UTC on Jun 18.
_EVENING_FLIGHT = {"scheduled_off": "2026-06-18T06:00:00Z"}
_NEXT_DAY_FLIGHT = {"scheduled_off": "2026-06-19T06:00:00Z"}


def test_date_match_uses_user_timezone():
    # User picks the local departure date (Jun 17); UTC date is Jun 18.
    chosen = _select_flight_instance(
        [_EVENING_FLIGHT, _NEXT_DAY_FLIGHT], "2026-06-17", tz="America/Los_Angeles"
    )
    assert chosen is _EVENING_FLIGHT


def test_date_match_falls_back_within_one_day_without_tz():
    # No timezone available: the ±1 day fallback still finds the evening flight
    # instead of reporting "not available".
    chosen = _select_flight_instance([_EVENING_FLIGHT], "2026-06-17", tz=None)
    assert chosen is _EVENING_FLIGHT


def test_date_match_returns_none_when_no_instance_within_tolerance():
    chosen = _select_flight_instance([_EVENING_FLIGHT], "2026-06-25", tz="America/Los_Angeles")
    assert chosen is None


def test_no_date_picks_soonest_non_cancelled():
    base = datetime.datetime.now(datetime.timezone.utc)

    def future(days: int) -> str:
        return (base + datetime.timedelta(days=days)).strftime("%Y-%m-%dT10:00:00Z")

    flights = [
        {"scheduled_off": future(2), "cancelled": True},
        {"scheduled_off": future(1)},
        {"scheduled_off": future(3)},
    ]
    chosen = _select_flight_instance(flights, None)
    assert chosen is flights[1]
