"""STACKED cards must not crash when one row's logo shrank its score.

A 3-digit score beside a logo (HOU 101) is fitted smaller than a 2-digit score
whose row dropped its logo (LAL 98). Forcing the wider shared score column
onto the logo row left its name 0px wide -> LayoutOverflow -> blank card.
"""

from __future__ import annotations

from apps.sports.tests.fixtures import _game
from tests.framework import harness

harness.load_suites()


def test_three_digit_score_beside_logo_renders() -> None:
    game = _game(
        "nba", "basketball",
        ("LAL", "Los Angeles", "Lakers"), ("HOU", "Houston", "Rockets"),
        away_score="98", home_score="101", status="Q4 2:00", state="in",
    )
    result = harness.get_suite("sports").render(game, 64, 64)
    names = {box.name for box in result.boxes}
    assert {"away.score", "home.score", "home.logo"} <= names
    assert names & {"home.name", "home.abbr"}
