"""A national-team card must say whether the men's or women's side is playing.

The USMNT and USWNT share a flag and the abbreviation "USA", so the gender
tag in the footer is the only thing telling their games apart. It shrinks
("Women's" -> "W") and outlasts the match note, but is never dropped.
"""

from __future__ import annotations

from apps.sports.model import build_game_view
from apps.sports.tests.fixtures import all_fixtures
from apps.sports.widgets import _soccer_labels
from tests.framework.clock import FIXED_NOW
from tests.framework.logos import fixture_logos


def _view(fixture_id: str, **overrides):
    game = {**all_fixtures()[fixture_id], **overrides}
    return build_game_view(game, fixture_logos(game), now=FIXED_NOW)


def test_gender_reaches_the_view() -> None:
    assert _view("uswnt_friendly_live").gender == "women"
    assert _view("usmnt_gold_cup_final").gender == "men"
    assert _view("epl_in_progress").gender == ""


def test_every_label_carries_the_gender_tag() -> None:
    labels = _soccer_labels(_view("usmnt_gold_cup_final"))
    assert labels[0] == "Men's Quarterfinal"
    assert labels[-1] == "M"
    assert all(label.startswith(("Men's", "M")) for label in labels)

    labels = _soccer_labels(_view("uswnt_friendly_live"))
    assert labels == ["Women's", "W"]


def test_club_games_are_unlabelled() -> None:
    assert _soccer_labels(_view("epl_in_progress", match_note="")) == []
