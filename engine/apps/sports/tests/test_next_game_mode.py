"""``next_game`` upcoming-games mode: instead of showing every game
inside a time window, keep only each qualifying team's soonest upcoming
game day - one game per team, except that a team playing twice on the same
calendar day (a doubleheader) keeps both. Qualifying teams are every team
in a selected league plus every favorite - only a league fetched purely to
cover a favorite (its league isn't selected) is limited to the favorites
themselves.
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
        # A day after kc_soon, so LV's next game day is kc_soon's, not this
        # one - same-day games for a team would both be kept (doubleheader).
        _pre_game("lv_soon", "nfl", "LV", "DEN", now + datetime.timedelta(days=3)),
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
    """A module showing "NCAAF Top 25 + a few favorite teams" fetches the
    top-25 slate (league id ``ncaaf-top25``) plus the favorites' own league —
    so every top-25 team's next game must survive alongside the favorite's,
    instead of the favorites list emptying the top-25 slate.
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
        # In the favorite's own (unselected) league but not favorited: it
        # doesn't qualify, and in production the library already drops it
        # from that league's fetch.
        _pre_game("cfb_other", "college-football", "DUKE", "WAKE", now + datetime.timedelta(days=1)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"top25_soon", "uga_soon"}


def test_next_game_mode_favorite_does_not_narrow_its_selected_league() -> None:
    """Selecting a league and favoriting a team in it is additive: every NFL
    team still gets its next game, not just the favorite's."""
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app({"leagues": ["nfl"], "favorite_teams": ["nfl:KC"]})
    games = [
        _pre_game("kc_soon", "nfl", "KC", "LV", now + datetime.timedelta(days=2)),
        _pre_game("kc_later", "nfl", "KC", "DEN", now + datetime.timedelta(days=9)),
        _pre_game("den_soon", "nfl", "DEN", "MIA", now + datetime.timedelta(days=1)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    # kc_soon is KC's and LV's next game; den_soon is DEN's and MIA's.
    assert kept == {"kc_soon", "den_soon"}


def _game(
    game_id: str,
    league: str,
    away: str,
    home: str,
    start: datetime.datetime,
    state: str,
) -> dict[str, Any]:
    return {
        "id": game_id,
        "league": league,
        "away_abbr": away,
        "home_abbr": home,
        "state": state,
        "start_time": start.isoformat(),
    }


def _utc_day(day: datetime.date, hour: int) -> datetime.datetime:
    """A fixed hour on a given UTC calendar day, so "same day" is unambiguous."""
    return datetime.datetime(
        day.year, day.month, day.day, hour, tzinfo=datetime.timezone.utc
    )


def test_next_game_mode_keeps_both_halves_of_a_doubleheader() -> None:
    """A team playing twice on one calendar day (baseball doubleheader) shows
    both games, rather than only the earlier one."""
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app({"favorite_teams": ["mlb:SEA"]})
    game_day = (now + datetime.timedelta(days=2)).date()
    games = [
        _pre_game("dh_1", "mlb", "SEA", "OAK", _utc_day(game_day, 17)),
        _pre_game("dh_2", "mlb", "SEA", "OAK", _utc_day(game_day, 21)),
        _pre_game("next_day", "mlb", "SEA", "TEX", _utc_day(game_day, 17)
                  + datetime.timedelta(days=1)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"dh_1", "dh_2"}


def test_next_game_mode_same_day_is_calendar_day_not_24_hours() -> None:
    """Two games less than 24h apart but on different calendar days are not a
    doubleheader - only the soonest shows."""
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app({"favorite_teams": ["mlb:SEA"]})
    day = (now + datetime.timedelta(days=2)).date()
    games = [
        _pre_game("tonight", "mlb", "SEA", "OAK", _utc_day(day, 23)),
        # 18 hours later, but the next calendar day.
        _pre_game("tomorrow", "mlb", "SEA", "OAK", _utc_day(day, 23)
                  + datetime.timedelta(hours=18)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"tonight"}


def test_past_game_drops_once_the_team_has_a_live_game() -> None:
    """A final stops showing as soon as one of its teams starts a later game,
    even though the completed-game window is still wide open."""
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app(
        {"favorite_teams": ["mlb:SEA"], "completed_game_window": {"days": 7}}
    )
    live_start = now - datetime.timedelta(hours=1)
    games = [
        _game("yesterday", "mlb", "SEA", "OAK", live_start - datetime.timedelta(days=1), "post"),
        _game("today_live", "mlb", "SEA", "TEX", live_start, "in"),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"today_live"}


def test_past_game_drops_once_the_team_has_a_newer_final() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app(
        {"favorite_teams": ["mlb:SEA"], "completed_game_window": {"days": 7}}
    )
    older_day = (now - datetime.timedelta(days=3)).date()
    games = [
        _game("older", "mlb", "SEA", "OAK", _utc_day(older_day, 2), "post"),
        _game("newer", "mlb", "SEA", "TEX", _utc_day(older_day, 2)
              + datetime.timedelta(days=1), "post"),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"newer"}


def test_doubleheader_finals_do_not_supersede_each_other() -> None:
    """Both halves of a doubleheader keep showing for the rest of the day: the
    second game doesn't push the first one's final off the display."""
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app(
        {"favorite_teams": ["mlb:SEA"], "completed_game_window": {"days": 7}}
    )
    day = (now - datetime.timedelta(days=2)).date()
    games = [
        _game("dh_1", "mlb", "SEA", "OAK", _utc_day(day, 17), "post"),
        _game("dh_2", "mlb", "SEA", "OAK", _utc_day(day, 21), "post"),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"dh_1", "dh_2"}


def test_doubleheader_finals_drop_together_on_the_next_game_day() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app(
        {"favorite_teams": ["mlb:SEA"], "completed_game_window": {"days": 7}}
    )
    day = (now - datetime.timedelta(days=2)).date()
    games = [
        _game("dh_1", "mlb", "SEA", "OAK", _utc_day(day, 17), "post"),
        _game("dh_2", "mlb", "SEA", "OAK", _utc_day(day, 21), "post"),
        _game("next_day", "mlb", "SEA", "TEX", _utc_day(day, 17)
              + datetime.timedelta(days=1), "post"),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"next_day"}


def test_upcoming_game_does_not_supersede_a_past_game() -> None:
    """Only a game under way or finished retires an older result - a scheduled
    game still leaves the last final on screen."""
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app(
        {"favorite_teams": ["nfl:SEA"], "completed_game_window": {"days": 7}}
    )
    games = [
        _game("last_week", "nfl", "SEA", "ARI", now - datetime.timedelta(days=2), "post"),
        _pre_game("next_week", "nfl", "SEA", "SF", now + datetime.timedelta(days=5)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"last_week", "next_week"}


def test_another_teams_newer_game_leaves_a_final_alone() -> None:
    """Supersession is per team: an unrelated team playing later doesn't pull
    down a final between two teams that haven't played since."""
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app({"leagues": ["nfl"], "completed_game_window": {"days": 7}})
    games = [
        _game("sun_game", "nfl", "SEA", "ARI", now - datetime.timedelta(days=2), "post"),
        _game("mon_game", "nfl", "KC", "LV", now - datetime.timedelta(hours=2), "post"),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"sun_game", "mon_game"}


def test_doubleheader_day_shows_finished_live_and_next_game() -> None:
    """The shape of a real doubleheader day: game one's final and game two in
    progress both stay up, alongside the team's next scheduled game."""
    now = datetime.datetime.now(datetime.timezone.utc)
    app = _make_app(
        {"favorite_teams": ["mlb:SEA"], "completed_game_window": {"days": 7}}
    )
    live_start = now - datetime.timedelta(hours=1)
    # Midnight on the live game's own day: same calendar day, already played.
    game_one = _utc_day(live_start.date(), 0)
    games = [
        _game("dh_1", "mlb", "SEA", "OAK", game_one, "post"),
        _game("dh_2", "mlb", "SEA", "OAK", live_start, "in"),
        _pre_game("tomorrow", "mlb", "SEA", "TEX", live_start + datetime.timedelta(days=1)),
    ]
    kept = {g["id"] for g in app._filter_by_time_window(games)}
    assert kept == {"dh_1", "dh_2", "tomorrow"}
