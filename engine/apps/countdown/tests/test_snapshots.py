"""Golden-snapshot tests for the countdown app."""
from __future__ import annotations

import pytest

from tests.framework import harness
from tests.framework.compare import assert_snapshot

harness.load_suites()

CASES = harness.all_cases("countdown")


@pytest.mark.parametrize(
    "fixture_id,w,h",
    CASES,
    ids=[harness.case_id(f, w, h) for f, w, h in CASES],
)
def test_snapshot(fixture_id: str, w: int, h: int, snapshot_update: bool) -> None:
    result = harness.render_case("countdown", fixture_id, w, h)
    assert result.image.size == (w, h)
    assert_snapshot(result.image, "countdown", harness.case_id(fixture_id, w, h), snapshot_update)
