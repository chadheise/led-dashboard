"""Soccer score reconciliation with the goal-minute list.

Regression coverage for a celebration-timing bug: ESPN exposes a goal in the
``details[]`` goal-minute list a poll or two before the ``score`` field
catches up — and it's that list advancing which fires the goal celebration.
Reading the lagging ``score`` field alone pulsed the *previous* score under a
live celebration. The score view now tracks ``max(score, goal_count)`` so it
updates the instant the goal lands, exactly once.
"""

from __future__ import annotations

from typing import Any

from apps.sports.model import build_game_view


def _soccer_game(**extra: Any) -> dict[str, Any]:
    game = {
        "id": "401",
        "sport": "soccer",
        "state": "in",
        "home_abbr": "ARS", "away_abbr": "MCI",
        "home_score": "0", "away_score": "0",
        "home_goals": [], "away_goals": [],
    }
    game.update(extra)
    return game


def _scores(game: dict[str, Any]) -> tuple[str, str]:
    view = build_game_view(game, {})
    return view.home.score, view.away.score


def test_goal_minute_leads_score_field():
    # The goal minute appears but the score field is still stale: the view
    # should already show the updated score so the celebration doesn't pulse
    # the previous one.
    home, away = _scores(_soccer_game(home_score="0", home_goals=["80'"]))
    assert (home, away) == ("1", "0")


def test_score_field_catching_up_does_not_double_count():
    # Once the score field catches up, the value is unchanged (no +2).
    home, away = _scores(_soccer_game(home_score="1", home_goals=["80'"]))
    assert (home, away) == ("1", "0")


def test_score_field_leading_goal_list_is_respected():
    # The reverse lag (score field first) also resolves to the same value.
    home, away = _scores(_soccer_game(home_score="1", home_goals=[]))
    assert (home, away) == ("1", "0")


def test_own_goal_counts_for_benefiting_side():
    # Own goals are recorded in the benefiting team's list, so they count too.
    home, away = _scores(_soccer_game(away_score="0", away_goals=["12'(og)"]))
    assert (home, away) == ("0", "1")


def test_unparseable_score_falls_back_to_goal_count():
    home, away = _scores(_soccer_game(home_score="-", home_goals=["5'", "60'"]))
    assert home == "2"


def test_unparseable_score_without_goals_is_preserved():
    home, _ = _scores(_soccer_game(home_score="-", home_goals=[]))
    assert home == "-"


def test_pregame_has_no_score():
    home, away = _scores(_soccer_game(state="pre", home_goals=["5'"]))
    assert (home, away) == ("", "")


def test_non_soccer_score_is_untouched_by_goal_list():
    game = {
        "id": "9", "sport": "football", "state": "in",
        "home_abbr": "KC", "away_abbr": "SF",
        "home_score": "14", "away_score": "10",
    }
    home, away = _scores(game)
    assert (home, away) == ("14", "10")
