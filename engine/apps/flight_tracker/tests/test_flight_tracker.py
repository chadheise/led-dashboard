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

import asyncio

from zoneinfo import ZoneInfo

from apps.flight_tracker.app import (
    FlightTrackerApp,
    _fmt_time,
    _phase,
    _within_lookup_window,
)
from canvas.simulator import SimulatorCanvas
from libraries.flightaware.library import _select_flight_instance


def _app(config: dict[str, Any], library_configs: dict[str, Any] | None = None) -> FlightTrackerApp:
    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(64, 32, _noop_broadcast)
    return FlightTrackerApp(config, canvas, {}, library_configs or {})


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


# ── Auto-hide gate (should_display) ────────────────────────────────────────────

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _iso(delta: datetime.timedelta) -> str:
    return (_NOW + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hours(h: float) -> datetime.timedelta:
    return datetime.timedelta(hours=h)


def _should_display(app: FlightTrackerApp) -> bool:
    return asyncio.run(app.should_display())


def test_auto_hide_hidden_before_first_fetch():
    # Stay hidden until the initial background fetch resolves, so a not-found
    # flight never flashes its "not available" card before we know to skip it.
    app = _app({"flights": [{"number": "DL1"}]})
    assert app._fetched_once is False
    assert _should_display(app) is False


def test_auto_hide_skips_when_no_active_flights():
    app = _app({"flights": [{"number": "DL1"}]})
    app._fetched_once = True
    # Departs in 5 hours: outside the 2-hour pre-departure window.
    app._tracked = {"DL1": {"found": True, "scheduled_off": _iso(_hours(5))}}
    assert _should_display(app) is False


def test_auto_hide_shows_flight_departing_within_2h():
    app = _app({"flights": [{"number": "DL1"}]})
    app._fetched_once = True
    app._tracked = {"DL1": {"found": True, "scheduled_off": _iso(_hours(1))}}
    assert _should_display(app) is True


def test_auto_hide_prefers_estimated_departure():
    # Scheduled 5h out but estimated pulled in to 1.5h -> active.
    app = _app({"flights": [{"number": "DL1"}]})
    app._fetched_once = True
    app._tracked = {
        "DL1": {
            "found": True,
            "scheduled_off": _iso(_hours(5)),
            "estimated_off": _iso(_hours(1.5)),
        }
    }
    assert _should_display(app) is True


def test_auto_hide_shows_airborne_flight():
    app = _app({"flights": [{"number": "DL1"}]})
    app._fetched_once = True
    # Departed 3h ago, no landing yet -> still in the air, still active.
    app._tracked = {
        "DL1": {"found": True, "scheduled_off": _iso(_hours(-3)), "actual_off": _iso(_hours(-3))}
    }
    assert _should_display(app) is True


def test_phase_active_while_airborne_with_future_eta():
    # A live ETA (estimated_on) should not be mistaken for an actual landing --
    # otherwise an in-flight aircraft is misclassified as "recently_landed" and
    # never gets its OpenSky live position polled (alt/spd/track stay blank).
    tracked = {
        "found": True,
        "actual_off": _iso(_hours(-1)),
        "estimated_on": _iso(_hours(2)),
        "actual_on": None,
    }
    assert _phase(tracked) == "active"


def test_auto_hide_shows_recently_landed_flight():
    app = _app({"flights": [{"number": "DL1"}]})
    app._fetched_once = True
    app._tracked = {"DL1": {"found": True, "actual_on": _iso(_hours(-1))}}
    assert _should_display(app) is True


def test_auto_hide_skips_long_landed_flight():
    app = _app({"flights": [{"number": "DL1"}]})
    app._fetched_once = True
    app._tracked = {"DL1": {"found": True, "actual_on": _iso(_hours(-3))}}
    assert _should_display(app) is False


def test_auto_hide_shows_if_any_flight_active():
    app = _app({"flights": [{"number": "DL1"}, {"number": "UA2"}]})
    app._fetched_once = True
    app._tracked = {
        "DL1": {"found": True, "scheduled_off": _iso(_hours(5))},
        "UA2": {"found": True, "actual_on": _iso(_hours(-1))},
    }
    assert _should_display(app) is True


def test_auto_hide_skips_not_found_flight():
    app = _app({"flights": [{"number": "DL1"}]})
    app._fetched_once = True
    app._tracked = {"DL1": {"found": False, "ident": "DL1"}}
    assert _should_display(app) is False


def test_initial_fetch_runs_while_inactive_then_gates_on_active():
    # The module isn't on-screen yet (inactive) but must still do one initial
    # fetch so the auto-hide gate has real data before it could ever be shown.
    app = _app({"flights": [{"number": "DL1"}]})
    assert app._is_active is False and app._fetched_once is False
    # No API key configured -> fetch resolves immediately via the has_api_key
    # branch, but only because the initial-load gate let it run while inactive.
    asyncio.run(app.fetch_data())
    assert app._fetched_once is True
    # Once every flight is resolved, subsequent inactive fetches return early
    # (no re-polling) and preserve the resolved data.
    app._tracked = {"DL1": {"found": False, "ident": "DL1"}}
    asyncio.run(app.fetch_data())
    assert app._tracked == {"DL1": {"found": False, "ident": "DL1"}}


# ── Resolve-or-keep-polling gate (req: new/changed flights must load) ────────────


class _FakeFlightAware:
    """Minimal stand-in for FlightAwareLibrary driving the fetch gate tests."""

    def __init__(self, results: dict[str, dict[str, Any] | None]) -> None:
        self.has_api_key = True
        self.budget_tier = "normal"
        self._results = results
        self.calls: list[str] = []

    async def track_flight(self, ident, date=None, tz=None):
        self.calls.append(ident)
        return self._results.get(ident)

    async def fetch_logo(self, iata):
        return None


def _fake_app(config: dict[str, Any], results: dict[str, Any]) -> FlightTrackerApp:
    app = _app(config)
    app._flightaware = _FakeFlightAware(results)  # type: ignore[assignment]

    class _Loc:
        def get_timezone(self):
            return None

    app._location = _Loc()  # type: ignore[assignment]
    return app


def test_all_flights_resolved_reflects_tracked():
    app = _app({"flights": [{"number": "DL1"}, {"number": "UA2"}]})
    assert app._all_flights_resolved() is False
    app._tracked = {"DL1": {"found": True}}
    assert app._all_flights_resolved() is False  # UA2 still missing
    app._tracked["UA2"] = {"found": False}
    assert app._all_flights_resolved() is True


def test_unresolved_flight_keeps_polling_while_inactive():
    # Budget was exhausted on the first poll (no result), so the flight never
    # resolved. A later inactive fetch must retry rather than give up, so the
    # flight loads once the budget frees up.
    app = _fake_app({"flights": [{"number": "DL1"}]}, results={})
    app._flightaware.budget_tier = "disabled"  # nothing gets polled
    asyncio.run(app.fetch_data())
    assert app._fetched_once is True
    assert app._all_flights_resolved() is False

    # Budget frees up; the still-inactive module retries and now resolves.
    app._flightaware.budget_tier = "normal"
    app._flightaware._results["DL1"] = {"found": True, "scheduled_off": _iso(_hours(5))}
    asyncio.run(app.fetch_data())
    assert app._tracked.get("DL1") == {"found": True, "scheduled_off": _iso(_hours(5))}


def test_resolved_flights_stop_background_polling_while_inactive():
    app = _fake_app(
        {"flights": [{"number": "DL1"}]},
        results={"DL1": {"found": True, "scheduled_off": _iso(_hours(5))}},
    )
    asyncio.run(app.fetch_data())
    assert app._all_flights_resolved() is True
    first_calls = list(app._flightaware.calls)
    # Now inactive + resolved -> no further polling until the module activates.
    asyncio.run(app.fetch_data())
    assert app._flightaware.calls == first_calls


def test_removed_flight_pruned_from_tracked():
    app = _fake_app(
        {"flights": [{"number": "DL1"}, {"number": "UA2"}]},
        results={
            "DL1": {"found": True, "scheduled_off": _iso(_hours(5))},
            "UA2": {"found": True, "scheduled_off": _iso(_hours(5))},
        },
    )
    asyncio.run(app.fetch_data())
    assert set(app._tracked) == {"DL1", "UA2"}

    # User removes UA2 from the config; its stale tracked state must be dropped.
    app.config["flights"] = [{"number": "DL1"}]
    asyncio.run(app.fetch_data())
    assert set(app._tracked) == {"DL1"}


# ── Timezone + time-format aware times (req 1) ─────────────────────────────────

_LOC_NY_12H = {
    "location": {
        "location": {"latitude": 40.0, "longitude": -74.0, "timezone": "America/New_York"},
        "time_format": "12h",
    }
}
_LOC_NY_24H = {
    "location": {
        "location": {"latitude": 40.0, "longitude": -74.0, "timezone": "America/New_York"},
        "time_format": "24h",
    }
}


def test_fmt_time_converts_to_timezone_12h():
    ny = ZoneInfo("America/New_York")
    # 14:00 UTC == 10:00 AM EDT (summer).
    assert _fmt_time("2026-06-18T14:00:00Z", ny, "12h") == "10:00 AM"
    # Midnight UTC == 8:00 PM EDT the previous evening.
    assert _fmt_time("2026-06-18T00:00:00Z", ny, "12h") == "8:00 PM"


def test_fmt_time_converts_to_timezone_24h():
    ny = ZoneInfo("America/New_York")
    assert _fmt_time("2026-06-18T14:00:00Z", ny, "24h") == "10:00"


def test_fmt_time_defaults_to_utc_when_no_timezone():
    assert _fmt_time("2026-06-18T14:00:00Z", None, "24h") == "14:00"
    assert _fmt_time(None, None, "24h") == "--:--"


def test_status_row_time_uses_location_settings():
    app = _app({"flights": [{"number": "DL1"}]}, library_configs=_LOC_NY_12H)
    tracked = {"found": True, "scheduled_off": "2026-06-18T14:00:00Z", "departure_delay": 0}
    rows = app._status_rows(tracked, "scheduled", (200, 200, 200))
    assert rows[0][0] == "Dep 10:00 AM"

    app24 = _app({"flights": [{"number": "DL1"}]}, library_configs=_LOC_NY_24H)
    rows24 = app24._status_rows(tracked, "scheduled", (200, 200, 200))
    assert rows24[0][0] == "Dep 10:00"


# ── Far-future flights are hidden, not shown as "not available" (req 2) ─────────

def test_within_lookup_window():
    today = datetime.date(2026, 6, 10)
    assert _within_lookup_window(None, today) is True          # no date -> always
    assert _within_lookup_window("2026-06-10", today) is True  # today
    assert _within_lookup_window("2026-06-12", today) is True   # +2 days (edge)
    assert _within_lookup_window("2026-06-13", today) is False  # +3 days -> hidden
    assert _within_lookup_window("2026-08-01", today) is False  # well into the future
    assert _within_lookup_window("garbage", today) is True      # unparseable -> keep


def test_far_future_flight_not_polled():
    far = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    app = _fake_app({"flights": [{"number": "DL1", "date": far}]}, results={})
    asyncio.run(app.fetch_data())
    # The far-future flight is never polled (no schedule data that far out)...
    assert app._flightaware.calls == []
    # ...and it doesn't hold background polling open.
    assert app._all_flights_resolved() is True


def test_near_and_far_flights_only_near_polled():
    now = datetime.datetime.now(datetime.timezone.utc)
    near = now.strftime("%Y-%m-%d")
    far = (now + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    app = _fake_app(
        {"flights": [{"number": "DL1", "date": near}, {"number": "UA2", "date": far}]},
        results={"DL1": {"found": True, "scheduled_off": _iso(_hours(5))}},
    )
    asyncio.run(app.fetch_data())
    assert app._flightaware.calls == ["DL1"]  # only the in-window flight


def test_should_display_false_when_only_far_future_flights():
    # A module whose only flight is dated beyond the lookup window is in the
    # "no flights in range" state -> the auto-hide gate hides it in a playlist.
    far = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    app = _app({"flights": [{"number": "DL1", "date": far}]})
    app._fetched_once = True
    # Even if (stale) tracked data made it look active, an out-of-range flight
    # is excluded from the shared visibility set.
    app._tracked = {"DL1": {"found": True, "scheduled_off": _iso(_hours(1))}}
    assert app._flights_in_range() == []
    assert _should_display(app) is False


def test_should_display_true_for_in_range_active_flight():
    near = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    app = _app({"flights": [{"number": "DL1", "date": near}]})
    app._fetched_once = True
    app._tracked = {"DL1": {"found": True, "scheduled_off": _iso(_hours(1))}}
    assert app._flights_in_range() == ["DL1"]
    assert _should_display(app) is True
