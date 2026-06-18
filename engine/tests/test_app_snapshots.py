"""Golden-snapshot tests for every non-sports app.

Each app registers a suite of config fixtures (display modes, data states)
rendered headlessly at the standard size matrix and compared pixel-for-pixel
against committed PNGs under ``tests/snapshots/{app}/``. Sports has its own
test module with extra layout assertions.
"""

from __future__ import annotations

import pytest

from tests.snaptest import harness
from tests.snaptest.compare import assert_snapshot

harness.load_suites()

_APP_IDS = [
    "stocks",
    "text",
    "flights_overhead",
    "flight_tracker",
    "spotify",
    "weather",
    "countdown",
    "world_clock",
]

CASES = [
    (app_id, fixture_id, w, h)
    for app_id in _APP_IDS
    for (fixture_id, w, h) in harness.all_cases(app_id)
]


@pytest.mark.parametrize(
    "app_id,fixture_id,w,h",
    CASES,
    ids=[f"{app_id}-{harness.case_id(f, w, h)}" for app_id, f, w, h in CASES],
)
def test_app_snapshot(app_id: str, fixture_id: str, w: int, h: int, snapshot_update: bool) -> None:
    result = harness.render_case(app_id, fixture_id, w, h)
    assert result.image.size == (w, h)
    assert_snapshot(result.image, app_id, harness.case_id(fixture_id, w, h), snapshot_update)
