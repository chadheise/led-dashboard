"""Startup prefetch of Flight Tracker flights.

Flight Tracker follows a handful of specific flights; Flights Overhead can
enrich many aircraft and drain the shared AeroAPI budget. At startup the engine
warms the tracking cache for the tracked flights first so they get their basic
info even when the budget is tight.
"""
from __future__ import annotations

import asyncio

import main
from state import Module, StateStore


def _store(tmp_path) -> StateStore:
    return StateStore(path=tmp_path / "state.json")


def test_flight_tracker_idents_collects_and_normalizes(tmp_path):
    store = _store(tmp_path)
    store.save_module(Module(name="Trip", app_id="flight_tracker", config={
        "flights": [
            {"number": "dl 1070", "date": "2026-07-10"},
            {"number": "UA100", "date": ""},
            {"number": "", "date": ""},  # blank dropped
        ]
    }))
    # A second module with an overlapping flight (deduped) + a legacy config.
    store.save_module(Module(name="Legacy", app_id="flight_tracker", config={
        "flight_numbers": ["dl1070", "aa9"],
    }))
    # A non-flight-tracker module is ignored.
    store.save_module(Module(name="Msg", app_id="text", config={"message": "hi"}))

    idents = set(main._flight_tracker_idents(store))
    assert idents == {
        ("DL1070", "2026-07-10"),
        ("UA100", None),
        ("DL1070", None),
        ("AA9", None),
    }


def test_prefetch_noop_without_api_key(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save_module(Module(name="Trip", app_id="flight_tracker", config={
        "flights": [{"number": "DL1070", "date": ""}]
    }))

    calls: list[str] = []

    class _FakeFA:
        def __init__(self, config):
            self.has_api_key = False
            self.budget_tier = "normal"

        async def track_flight(self, ident, date=None, tz=None):
            calls.append(ident)

    monkeypatch.setattr(main, "_flight_tracker_idents", lambda s: [("DL1070", None)])
    import libraries.flightaware.library as fa_lib
    monkeypatch.setattr(fa_lib, "FlightAwareLibrary", _FakeFA)

    asyncio.run(main._prefetch_flight_tracker(store))
    assert calls == []  # no key -> nothing fetched


def test_prefetch_fetches_each_flight_until_budget_exhausted(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save_module(Module(name="Trip", app_id="flight_tracker", config={
        "flights": [{"number": "DL1070"}]
    }))

    calls: list[str] = []

    class _FakeFA:
        tier = "normal"

        def __init__(self, config):
            self.has_api_key = True

        @property
        def budget_tier(self):
            return _FakeFA.tier

        async def track_flight(self, ident, date=None, tz=None):
            calls.append(ident)

    class _FakeLoc:
        def __init__(self, config):
            pass

        def get_timezone(self):
            return "America/Los_Angeles"

    monkeypatch.setattr(
        main, "_flight_tracker_idents",
        lambda s: [("DL1070", None), ("UA100", None), ("AA9", None)],
    )
    import libraries.flightaware.library as fa_lib
    import libraries.location.library as loc_lib
    monkeypatch.setattr(fa_lib, "FlightAwareLibrary", _FakeFA)
    monkeypatch.setattr(loc_lib, "LocationLibrary", _FakeLoc)

    asyncio.run(main._prefetch_flight_tracker(store))
    assert calls == ["DL1070", "UA100", "AA9"]

    # When the budget is exhausted, prefetch stops early.
    calls.clear()
    _FakeFA.tier = "disabled"
    asyncio.run(main._prefetch_flight_tracker(store))
    assert calls == []
