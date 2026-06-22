"""Integration snapshots: full SportsApp frames with multiple cards per screen.

Covers the slot-splitting and column-divider logic in paginate mode, which the
per-card snapshots don't reach. Data is seeded directly — no network.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.framework import harness
from tests.framework.compare import assert_snapshot
from tests.framework.logos import fixture_logos_for_games

harness.load_suites()

_FRAME_CASES = [
    ("paginate_2up", 2, ["nfl_in_progress", "mlb_in_progress"]),
    ("paginate_4up", 4, ["nfl_in_progress", "mlb_in_progress", "nba_in_progress", "nhl_in_progress"]),
    ("wc_2up", 2, ["fifa_wc_group_in_progress", "fifa_wc_knockout_in_progress"]),
    ("wc_3up", 3, ["fifa_wc_group_in_progress", "fifa_wc_knockout_in_progress", "fifa_wc_halftime"]),
]


@pytest.mark.parametrize("name,per_screen,fixture_ids", _FRAME_CASES,
                         ids=[c[0] for c in _FRAME_CASES])
def test_sports_frame_snapshot(
    name: str, per_screen: int, fixture_ids: list[str], snapshot_update: bool
) -> None:
    from apps.sports.app import SportsApp

    suite = harness.get_suite("sports")
    games = [dict(suite.fixtures[fixture_id]) for fixture_id in fixture_ids]

    def seed(app: Any) -> None:
        app._games = games
        app._logos = fixture_logos_for_games(games)
        # Pin the World Cup logo slide animation to its fully-shown hold phase so
        # these slot-splitting snapshots are deterministic (and unchanged): an
        # elapsed offset inside the hold window always resolves to reveal == 1.
        app._wc_cycle_start = app._now() - 5.0

    image = harness.render_app_frame(
        SportsApp,
        {"leagues": [], "display_mode": "paginate", "scores_per_screen": per_screen},
        320, 64,
        seed=seed,
    )
    assert_snapshot(image, "sports", f"frame_{name}_320x64", snapshot_update)
