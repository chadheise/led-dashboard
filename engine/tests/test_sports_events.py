"""Unit tests for scoring-event detection (apps/sports/events.py).

Each test simulates successive fetch_data snapshots: build the previous
snapshot dict from fetch N, then run detect_events against fetch N+1.
"""

from __future__ import annotations

from typing import Any

from apps.sports.events import (
    GameSnapshot,
    detect_events,
    game_key,
    make_snapshot,
)


def _soccer(away_score="0", home_score="0", state="in", **extra: Any) -> dict[str, Any]:
    game = {
        "id": "401",
        "sport": "soccer",
        "league": "eng.1",
        "away_abbr": "MCI", "home_abbr": "ARS",
        "away_score": away_score, "home_score": home_score,
        "state": state,
        "away_goals": [], "home_goals": [],
        "away_id": "382", "home_id": "359",
    }
    game.update(extra)
    return game


def _football(away_score="0", home_score="0", state="in", **extra: Any) -> dict[str, Any]:
    game = {
        "id": "402",
        "sport": "football",
        "league": "nfl",
        "away_abbr": "KC", "home_abbr": "NE",
        "away_score": away_score, "home_score": home_score,
        "state": state,
        "away_id": "12", "home_id": "17",
    }
    game.update(extra)
    return game


def _baseball(away_score="0", home_score="0", state="in", **extra: Any) -> dict[str, Any]:
    game = {
        "id": "403",
        "sport": "baseball",
        "league": "mlb",
        "away_abbr": "NYY", "home_abbr": "BOS",
        "away_score": away_score, "home_score": home_score,
        "state": state,
        "away_id": "10", "home_id": "2",
    }
    game.update(extra)
    return game


def _snaps(*games: dict[str, Any]) -> dict[str, GameSnapshot]:
    return {game_key(g): make_snapshot(g) for g in games}


def _detect(prev_game: dict[str, Any], new_game: dict[str, Any]):
    return detect_events(_snaps(prev_game), [new_game])


# ── Gating ─────────────────────────────────────────────────────────────────────


def test_first_observation_never_fires():
    assert detect_events({}, [_soccer(home_score="3")]) == []


def test_pre_to_in_transition_is_silent():
    # A goal "already on the board" when the game first goes live: no event.
    assert _detect(_soccer(state="pre"), _soccer(home_score="1")) == []


def test_post_games_do_not_fire():
    assert _detect(_soccer(state="post"), _soccer(home_score="1", state="post")) == []


def test_goal_at_final_whistle_fires():
    # in → post with a score bump (stoppage-time winner) still celebrates.
    events = _detect(_soccer(), _soccer(home_score="1", state="post"))
    assert [(e.kind, e.side) for e in events] == [("goal", "home")]


def test_unknown_sport_ignored():
    prev = _soccer()
    prev["sport"] = "basketball"
    new = dict(prev, home_score="50")
    assert _detect(prev, new) == []


# ── Soccer ─────────────────────────────────────────────────────────────────────


def test_soccer_home_goal():
    events = _detect(_soccer(), _soccer(home_score="1"))
    assert [(e.kind, e.side) for e in events] == [("goal", "home")]


def test_soccer_away_goal():
    events = _detect(_soccer(), _soccer(away_score="1"))
    assert [(e.kind, e.side) for e in events] == [("goal", "away")]


def test_soccer_two_goals_one_window_single_event():
    events = _detect(_soccer(), _soccer(home_score="2"))
    assert [(e.kind, e.side) for e in events] == [("goal", "home")]


def test_soccer_both_teams_score():
    events = _detect(_soccer(), _soccer(away_score="1", home_score="1"))
    assert {(e.kind, e.side) for e in events} == {("goal", "away"), ("goal", "home")}


def test_soccer_score_flap_no_duplicate():
    # 1 → 0 (ESPN correction) → 1 again: max-score guard suppresses a repeat.
    g1 = _soccer(home_score="1")
    snaps = _snaps(g1)
    g2 = _soccer(home_score="0")
    assert detect_events(snaps, [g2]) == []
    snaps = {game_key(g2): make_snapshot(g2, snaps[game_key(g2)])}
    assert snaps["401"].home_max_score == 1
    g3 = _soccer(home_score="1")
    assert detect_events(snaps, [g3]) == []


def test_soccer_goal_count_fallback_when_score_unparseable():
    prev = _soccer(away_score="-", home_score="-", home_goals=["12'"])
    new = _soccer(away_score="-", home_score="-", home_goals=["12'", "55'"])
    events = _detect(prev, new)
    assert [(e.kind, e.side) for e in events] == [("goal", "home")]


def test_soccer_unparseable_scores_no_crash_no_event():
    assert _detect(_soccer(), _soccer(away_score="-", home_score="-")) == []


# ── Football ───────────────────────────────────────────────────────────────────


def test_football_touchdown_deltas():
    for delta in (6, 7, 8):
        events = _detect(_football(), _football(home_score=str(delta)))
        assert [(e.kind, e.side) for e in events] == [("touchdown", "home")], delta


def test_football_field_goal_delta():
    events = _detect(_football(away_score="7"), _football(away_score="10"))
    assert [(e.kind, e.side) for e in events] == [("field_goal", "away")]


def test_football_small_deltas_silent():
    for delta in (1, 2):
        assert _detect(_football(), _football(home_score=str(delta))) == [], delta


def test_football_pick_six_single_touchdown_event():
    lp = {"id": "9", "type_text": "Interception Return Touchdown", "text": "", "team_id": "17"}
    events = _detect(_football(), _football(home_score="6", last_play=lp))
    assert [(e.kind, e.side) for e in events] == [("touchdown", "home")]


def test_football_interception_via_last_play():
    lp = {"id": "5", "type_text": "Pass Interception Return", "text": "intercepted by Jones", "team_id": "17"}
    events = _detect(_football(), _football(last_play=lp))
    assert [(e.kind, e.side) for e in events] == [("interception", "home")]


def test_football_interception_same_play_id_no_repeat():
    lp = {"id": "5", "type_text": "Pass Interception Return", "text": "", "team_id": "17"}
    prev = _football(last_play=lp)
    assert _detect(prev, _football(last_play=lp)) == []


def test_football_interception_side_from_possession_fallback():
    lp = {"id": "5", "type_text": "Pass Interception Return", "text": "", "team_id": ""}
    situation = {"possession": {"$ref": "http://x/v2/sports/football/leagues/nfl/teams/12"}}
    events = _detect(_football(), _football(last_play=lp, situation=situation))
    assert [(e.kind, e.side) for e in events] == [("interception", "away")]


def test_football_no_last_play_no_interception():
    # No score change and no lastPlay: silently undetectable, by design.
    assert _detect(_football(), _football()) == []


def test_football_field_goal_via_last_play():
    lp = {"id": "7", "type_text": "Field Goal Good", "text": "", "team_id": "12"}
    events = _detect(_football(), _football(away_score="3", last_play=lp))
    assert [(e.kind, e.side) for e in events] == [("field_goal", "away")]


# ── Baseball ───────────────────────────────────────────────────────────────────


def test_baseball_home_run_text_variants():
    for text in ("Judge homered to left (412 feet).", "home run to center", "grand slam!"):
        lp = {"id": "3", "type_text": "Play Result", "text": text, "team_id": ""}
        events = _detect(_baseball(), _baseball(away_score="1", last_play=lp))
        assert [(e.kind, e.side) for e in events] == [("home_run", "away")], text


def test_baseball_side_from_team_id_when_no_delta():
    lp = {"id": "3", "type_text": "", "text": "homers", "team_id": "2"}
    events = _detect(_baseball(), _baseball(last_play=lp))
    assert [(e.kind, e.side) for e in events] == [("home_run", "home")]


def test_baseball_same_play_id_no_repeat():
    lp = {"id": "3", "type_text": "", "text": "homers to right", "team_id": "2"}
    prev = _baseball(home_score="1", last_play=lp)
    assert _detect(prev, _baseball(home_score="1", last_play=lp)) == []


def test_baseball_non_homer_run_silent():
    lp = {"id": "4", "type_text": "Play Result", "text": "singled to left, run scored", "team_id": "2"}
    assert _detect(_baseball(), _baseball(home_score="1", last_play=lp)) == []


def test_baseball_no_last_play_silent():
    assert _detect(_baseball(), _baseball(home_score="4")) == []


# ── Keys and snapshots ─────────────────────────────────────────────────────────


def test_game_key_falls_back_to_composite():
    game = _soccer()
    game["id"] = ""
    game["start_time"] = "2026-06-10T19:00:00Z"
    assert game_key(game) == "eng.1:MCI@ARS:2026-06-10T19:00:00Z"


def test_snapshot_carries_max_score_forward():
    snap1 = make_snapshot(_soccer(home_score="2"))
    snap2 = make_snapshot(_soccer(home_score="0"), snap1)
    assert snap2.home_max_score == 2
    assert snap2.home_score == 0
