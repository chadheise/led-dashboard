"""Golden-snapshot tests for the sports app card renderer.

Every fixture game is rendered at the full size matrix and compared
pixel-for-pixel against the committed PNG under ``tests/snapshots/sports/``.
Re-bless intentional visual changes with ``pytest --snapshot-update``.
"""

from __future__ import annotations

import pytest

from tests.framework import harness
from tests.framework.compare import assert_snapshot

harness.load_suites()

CASES = harness.all_cases("sports")


@pytest.mark.parametrize(
    "fixture_id,w,h", CASES, ids=[harness.case_id(*case) for case in CASES]
)
def test_sports_card_snapshot(fixture_id: str, w: int, h: int, snapshot_update: bool) -> None:
    result = harness.render_case("sports", fixture_id, w, h)
    assert result.image.size == (w, h)
    assert_snapshot(result.image, "sports", harness.case_id(fixture_id, w, h), snapshot_update)
