"""Tests for library runtime status (budget/cost + cache) shown in settings UI."""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from types import SimpleNamespace

from api.routes import get_library_status, list_libraries
from libraries import LIBRARY_REGISTRY
from libraries.flightaware import library as fa_lib
from libraries.opensky import library as os_lib
from state import StateStore


def _request(tmp_path: Path) -> SimpleNamespace:
    store = StateStore(path=tmp_path / "state.json")
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(store=store)))


def _item(status: dict, section_label: str, item_label: str):
    section = next(s for s in status["sections"] if s["label"] == section_label)
    return next(i for i in section["items"] if i["label"] == item_label)


def test_only_flight_libraries_advertise_status() -> None:
    flagged = {lid for lid, cls in LIBRARY_REGISTRY.items() if cls.has_status}
    assert flagged == {"opensky", "flightaware"}


def test_flightaware_status_reports_cost_and_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(fa_lib, "_BUDGET_PATH", tmp_path / "budget.json")
    monkeypatch.setattr(fa_lib, "_CACHE_PATH", tmp_path / "cache.json")

    month = datetime.date.today().strftime("%Y-%m")
    (tmp_path / "budget.json").write_text(json.dumps({"month": month, "calls": 474}))
    now = time.time()
    (tmp_path / "cache.json").write_text(
        json.dumps({"DL699": {"fetched_at": now - 3600, "data": {"airline": "Delta"}}})
    )

    status = fa_lib.FlightAwareLibrary({}).get_status()

    # 474 calls of 800 budget at $0.005/call → $2.37 / $4.00
    assert _item(status, "Monthly budget", "API calls used")["value"] == "474 / 800"
    assert _item(status, "Monthly budget", "Estimated cost")["value"] == "$2.37 / $4.00"
    assert _item(status, "Enrichment cache", "Cached flights")["value"] == "1"
    assert _item(status, "Enrichment cache", "Cache duration")["value"] == "7 days"
    last = _item(status, "Enrichment cache", "Last cache update")
    assert last["kind"] == "timestamp"
    assert abs(last["value"] - (now - 3600)) < 2


def test_opensky_status_is_free_and_tracks_fetch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(os_lib, "_STATUS_PATH", tmp_path / "opensky_status.json")

    lib = os_lib.OpenSkyLibrary({})
    lib._save_status(flight_count=7)
    status = lib.get_status()

    assert "free" in status["note"].lower()
    assert _item(status, "Usage", "Estimated cost")["value"] == "Free (no cost)"
    assert _item(status, "Live data", "Flights in range")["value"] == "7"
    assert _item(status, "Live data", "Rate-limit status")["value"] == "OK"


def test_opensky_status_surfaces_throttle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(os_lib, "_STATUS_PATH", tmp_path / "opensky_status.json")

    lib = os_lib.OpenSkyLibrary({})
    lib._save_status(flight_count=3)  # establish a prior successful fetch
    lib._save_status(throttled_for=120)
    status = lib.get_status()

    assert "Throttled" in _item(status, "Live data", "Rate-limit status")["value"]
    # The earlier successful fetch is preserved through a throttle event.
    assert _item(status, "Live data", "Flights in range")["value"] == "3"
    retry = _item(status, "Live data", "Retrying")
    assert retry["kind"] == "timestamp"
    assert retry["value"] > time.time()


def test_status_endpoint_returns_none_for_plain_library(tmp_path) -> None:
    req = _request(tmp_path)
    assert get_library_status(req, "canvas_utils")["status"] is None
    libs = {l["id"]: l for l in list_libraries(req)}
    assert libs["flightaware"]["has_status"] is True
    assert libs["canvas_utils"]["has_status"] is False
