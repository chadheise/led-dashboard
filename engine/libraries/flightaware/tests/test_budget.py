"""FlightAware monthly-budget accounting + configurable reset day.

Covers the bug where the API budget never reset after a new month began, and
the new ``budget_reset_day`` setting that resets usage on a chosen day of the
month (e.g. the 7th) to match the FlightAware billing cycle.
"""

from __future__ import annotations

import datetime
import json

import pytest

from libraries.flightaware import library as fa_lib
from libraries.flightaware.library import FlightAwareLibrary


@pytest.fixture(autouse=True)
def _isolate_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(fa_lib, "_BUDGET_PATH", tmp_path / "budget.json")
    # Keep the other on-disk caches out of the real data dir too.
    monkeypatch.setattr(fa_lib, "_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(fa_lib, "_ROUTES_CACHE_PATH", tmp_path / "routes.json")
    monkeypatch.setattr(fa_lib, "_LOGO_META_PATH", tmp_path / "logo_meta.json")
    monkeypatch.setattr(fa_lib, "_TRACKING_CACHE_PATH", tmp_path / "tracking.json")
    return tmp_path


def _period_key(reset_day: int, today: datetime.date) -> str:
    return FlightAwareLibrary({"budget_reset_day": reset_day})._budget_period_key(today)


# ── Period boundaries ──────────────────────────────────────────────────────────

def test_period_key_default_is_first_of_calendar_month():
    key = _period_key(1, datetime.date(2026, 7, 15))
    assert key == "2026-07-01"


def test_period_key_before_reset_day_belongs_to_previous_month():
    # Reset on the 7th; the 3rd is still in the period that started Jun 7.
    assert _period_key(7, datetime.date(2026, 7, 3)) == "2026-06-07"
    # On/after the 7th, the period is the current month's.
    assert _period_key(7, datetime.date(2026, 7, 7)) == "2026-07-07"
    assert _period_key(7, datetime.date(2026, 7, 20)) == "2026-07-07"


def test_period_key_clamps_reset_day_to_short_month():
    # Reset day 31 falls back to Feb's last day (28 in 2026).
    assert _period_key(31, datetime.date(2026, 2, 15)) == "2026-01-31"
    assert _period_key(31, datetime.date(2026, 3, 1)) == "2026-02-28"


def test_period_key_january_rolls_to_previous_year():
    assert _period_key(7, datetime.date(2026, 1, 3)) == "2025-12-07"


# ── Reset behaviour ─────────────────────────────────────────────────────────────

def test_stale_period_budget_file_resets_to_zero(_isolate_budget):
    # A budget file from a prior period must not count against the new period.
    fa_lib._BUDGET_PATH.write_text(json.dumps({"period": "2026-05-07", "calls": 500}))
    lib = FlightAwareLibrary({"budget_reset_day": 7})
    assert lib._budget_calls == 0
    assert lib.budget_tier == "normal"


def test_current_period_budget_file_is_honoured(_isolate_budget):
    today = datetime.date.today()
    period = FlightAwareLibrary({"budget_reset_day": 7})._budget_period_key(today)
    fa_lib._BUDGET_PATH.write_text(json.dumps({"period": period, "calls": 500}))
    lib = FlightAwareLibrary({"budget_reset_day": 7})
    assert lib._budget_calls == 500


def test_legacy_month_budget_file_honoured_for_current_month(_isolate_budget):
    month = datetime.date.today().strftime("%Y-%m")
    fa_lib._BUDGET_PATH.write_text(json.dumps({"month": month, "calls": 123}))
    lib = FlightAwareLibrary({})
    assert lib._budget_calls == 123


def test_rollover_resets_running_budget(_isolate_budget, monkeypatch):
    lib = FlightAwareLibrary({"budget_reset_day": 7})
    lib._charge_budget(800)
    assert lib.budget_tier == "disabled"

    # Simulate crossing into the next billing period without a restart.
    next_period = "2999-01-07"
    monkeypatch.setattr(lib, "_budget_period_key", lambda today=None: next_period)
    # The next budget read notices the new period and zeroes usage.
    assert lib.budget_tier == "normal"
    assert lib._budget_calls == 0
    # And the reset is persisted.
    saved = json.loads(fa_lib._BUDGET_PATH.read_text())
    assert saved == {"period": next_period, "calls": 0}


def test_charge_persists_period_format(_isolate_budget):
    lib = FlightAwareLibrary({"budget_reset_day": 7})
    lib._charge_budget(3)
    saved = json.loads(fa_lib._BUDGET_PATH.read_text())
    assert saved["calls"] == 3
    assert saved["period"] == lib._budget_period
