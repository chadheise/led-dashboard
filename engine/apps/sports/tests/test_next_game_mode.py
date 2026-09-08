"""``next_game`` upcoming-games mode: instead of showing every game
inside a time window, keep only each qualifying team's single soonest
upcoming game. Qualifying teams are the configured favorites, or (with no
favorites set) every team appearing among the fetched games.
"""

from __future__ import annotations

import datetime
from typing import Any


def _make_app(config: dict[str, Any] | None = None) -> Any:
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(320, 64, _noop_broadcast)
    base = {"leagues": [], "upcoming_game_mode": "next_game"}
    return SportsApp({**base, **(config or {})}, canvas, {}, {})


def _pre_game(
    game_id: str,
    league: str,
    away: str,
    home: str,
    start: datetime.datetime,
) -> dict[str, Any]:
    return {
        "id": game_id,
        "league": league,
        "away_abbr": away,
        "home_abbr": home,
        "state": "pre",
        "start_time": start.isoformat(),
    }


def test_next_game_mode_keeps_only_soonest_game_per_favorite_team() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app({"favorite_teams": ["nfl:KC", "nfl:NE"]})
    games = [
        _pre_game("kc_soon", "nfl", "KC", "LV", now + datetime.timedelta(days=2)),
        _pre_game("kc_later", "nfl", "KC", "DEN", now + datetime.timedelta(days=9)),
        _pre_game("ne_soon", "nfl", "NE", "MIA", now + datetime.timedelta(days=1)),
        _pre_game("other_team", "nfl", "LV", "DEN", now + datetime.timedelta(days=1)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"kc_soon", "ne_soon"}


def test_next_game_mode_dedupes_when_two_favorites_play_each_other() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app({"favorite_teams": ["nfl:KC", "nfl:NE"]})
    games = [
        _pre_game("kc_vs_ne", "nfl", "NE", "KC", now + datetime.timedelta(days=3)),
        _pre_game("kc_later", "nfl", "KC", "DEN", now + datetime.timedelta(days=9)),
        _pre_game("ne_later", "nfl", "NE", "MIA", now + datetime.timedelta(days=9)),
    ]
    kept = [g["id"] for g in app._filter_by_time_window(games)]
    assert kept == ["kc_vs_ne"]


def test_next_game_mode_with_no_favorites_keeps_one_per_team_in_league() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app()
    games = [
        _pre_game("kc_soon", "nfl", "KC", "LV", now + datetime.timedelta(days=2)),
        _pre_game("kc_later", "nfl", "KC", "DEN", now + datetime.timedelta(days=9)),
        _pre_game("lv_soon", "nfl", "LV", "DEN", now + datetime.timedelta(days=2)),
        _pre_game("den_only", "nfl", "DEN", "MIA", now + datetime.timedelta(days=1)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    # kc_soon covers both KC and LV's next game; den_only covers DEN's (its
    # earliest); kc_later is superseded by kc_soon for KC.
    assert kept == {"kc_soon", "den_only"}


def test_next_game_mode_still_respects_live_and_completed_windows() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app({"favorite_teams": ["nfl:KC"]})
    live = {
        "id": "kc_live",
        "league": "nfl",
        "away_abbr": "KC",
        "home_abbr": "LV",
        "state": "in",
        "start_time": (now - datetime.timedelta(hours=1)).isoformat(),
    }
    completed = {
        "id": "kc_done",
        "league": "nfl",
        "away_abbr": "KC",
        "home_abbr": "DEN",
        "state": "post",
        "start_time": (now - datetime.timedelta(days=3)).isoformat(),
    }
    upcoming = _pre_game("kc_next", "nfl", "KC", "MIA", now + datetime.timedelta(days=4))
    kept = {g["id"] for g in app._filter_by_time_window([live, completed, upcoming])}
    assert kept == {"kc_live", "kc_next"}


def test_next_game_mode_is_the_default_when_unspecified() -> None:
    """upcoming_game_mode defaults to "next_game", so an app built without it
    only keeps each favorite's soonest game even with a wide window configured."""
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(320, 64, _noop_broadcast)
    app = SportsApp(
        {
            "leagues": [],
            "favorite_teams": ["nfl:KC"],
            "upcoming_game_window": {"days": 30},
        },
        canvas, {}, {},
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    games = [
        _pre_game("kc_soon", "nfl", "KC", "LV", now + datetime.timedelta(hours=6)),
        _pre_game("kc_later", "nfl", "KC", "DEN", now + datetime.timedelta(days=9)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"kc_soon"}


def test_window_mode_must_be_explicitly_selected() -> None:
    """Setting upcoming_game_mode to "window" restores every game within the
    configured window, instead of just each favorite's soonest game."""
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(320, 64, _noop_broadcast)
    app = SportsApp(
        {
            "leagues": [],
            "favorite_teams": ["nfl:KC"],
            "upcoming_game_mode": "window",
            "upcoming_game_window": {"days": 30},
        },
        canvas, {}, {},
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    games = [
        _pre_game("kc_soon", "nfl", "KC", "LV", now + datetime.timedelta(hours=6)),
        _pre_game("kc_later", "nfl", "KC", "DEN", now + datetime.timedelta(days=9)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"kc_soon", "kc_later"}


def test_next_game_mode_keeps_league_games_alongside_favorites() -> None:
    """Favorites qualify per league, not globally. A module showing "NCAAF
    Top 25 + a few favorite teams" fetches the top-25 slate (league id
    ``ncaaf-top25``, no favorites of its own) plus the favorites' base
    league — so every top-25 team's next game must survive alongside the
    favorite's, instead of the favorites list emptying the top-25 slate.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app(
        {
            "leagues": ["ncaaf-top25"],
            "favorite_teams": ["college-football:UGA"],
        }
    )
    games = [
        _pre_game("top25_soon", "ncaaf-top25", "OSU", "MICH", now + datetime.timedelta(days=2)),
        _pre_game("top25_later", "ncaaf-top25", "MICH", "OSU", now + datetime.timedelta(days=9)),
        _pre_game("uga_soon", "college-football", "UGA", "VAN", now + datetime.timedelta(days=1)),
        _pre_game("uga_later", "college-football", "UGA", "AUB", now + datetime.timedelta(days=8)),
        # Same league as the favorite but not favorited: doesn't qualify (in
        # production the library already drops it from that league's fetch).
        _pre_game("cfb_other", "college-football", "DUKE", "WAKE", now + datetime.timedelta(days=1)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"top25_soon", "uga_soon"}
