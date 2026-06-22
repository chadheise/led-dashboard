"""Live game spotlight mode: when a qualifying game is live, dedicate the
left 3/4 of the screen to it and cycle the rest through the remaining 1/4.

``live_game_source`` is an either/or choice: "any" spotlights the first live
game regardless of favorites (this also covers World Cup matches whenever
``fifa.world`` is selected), while "favorites" only spotlights live games
that match ``favorite_teams``. When multiple games qualify, the spotlight
itself cycles through them, the same way the sidebar cycles through the rest.
"""

from __future__ import annotations

from typing import Any

from tests.framework import harness
from tests.framework.compare import assert_snapshot
from tests.framework.logos import fixture_logos_for_games

harness.load_suites()


def _make_app(config: dict[str, Any] | None = None, w: int = 320, h: int = 64):
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(w, h, _noop_broadcast)
    return SportsApp({"leagues": [], **(config or {})}, canvas, {}, {})


def _game_copy(fixture_id: str) -> dict[str, Any]:
    suite = harness.get_suite("sports")
    return dict(suite.fixtures[fixture_id])


def _pin_wc_logo_shown(app: Any) -> None:
    """Pin the World Cup logo slide animation to its fully-shown hold phase so
    snapshots that include a WC game stay deterministic. An elapsed offset
    inside the hold window always resolves to reveal == 1."""
    app._wc_cycle_start = app._now() - 5.0


# ── Selection logic ─────────────────────────────────────────────────────────


def test_featured_live_games_any_returns_all_live_games():
    soccer = _game_copy("soccer_long_note")  # fifa.world, in
    nfl = _game_copy("nfl_in_progress")  # nfl, in
    mlb_final = _game_copy("mlb_walkoff_final")  # mlb, post

    app = _make_app({"live_game_mode": True, "live_game_source": "any"})
    app._games = [soccer, nfl, mlb_final]

    assert app._featured_live_games() == [soccer, nfl]


def test_featured_live_games_favorites_filters_by_favorite_teams():
    kc_game = _game_copy("nfl_redzone_home_poss")  # nfl, away KC, in
    nba = _game_copy("nba_in_progress")
    nhl = _game_copy("nhl_in_progress")

    app = _make_app({
        "live_game_mode": True,
        "live_game_source": "favorites",
        "favorite_teams": ["nfl:KC"],
    })
    app._games = [kc_game, nba, nhl]

    assert app._featured_live_games() == [kc_game]


def test_featured_live_games_favorites_empty_when_no_favorite_live():
    nba = _game_copy("nba_in_progress")
    nhl = _game_copy("nhl_in_progress")

    app = _make_app({
        "live_game_mode": True,
        "live_game_source": "favorites",
        "favorite_teams": ["nfl:KC"],
    })
    app._games = [nba, nhl]

    assert app._featured_live_games() == []


def test_featured_live_games_favorites_no_teams_falls_back_to_any():
    """When live_game_source is 'favorites' but no teams are configured,
    every live game should qualify — filtering by an empty list would
    silently suppress the spotlight for newly created modules."""
    soccer = _game_copy("soccer_long_note")  # fifa.world, in
    nfl = _game_copy("nfl_in_progress")  # nfl, in

    app = _make_app({
        "live_game_mode": True,
        "live_game_source": "favorites",
        # no favorite_teams set
    })
    app._games = [soccer, nfl]

    assert app._featured_live_games() == [soccer, nfl]


def test_featured_live_games_disabled_returns_empty():
    soccer = _game_copy("soccer_long_note")

    app = _make_app({"live_game_mode": False, "live_game_source": "any"})
    app._games = [soccer]

    assert app._featured_live_games() == []


def test_featured_live_games_no_live_games_returns_empty():
    mlb_final = _game_copy("mlb_walkoff_final")  # post

    app = _make_app({"live_game_mode": True, "live_game_source": "any"})
    app._games = [mlb_final]

    assert app._featured_live_games() == []


# ── Spotlight rotation ──────────────────────────────────────────────────────


def test_next_featured_game_cycles_after_seconds_per_score():
    g1 = _game_copy("soccer_long_note")
    g2 = _game_copy("nfl_in_progress")
    featured_games = [g1, g2]

    app = _make_app({"live_game_mode": True, "live_game_source": "any", "seconds_per_score": 5})

    now = 1000.0
    app._now = lambda: now
    app._featured_started_at = now

    assert app._next_featured_game(featured_games) is g1

    now = 1003.0  # not yet 5s
    assert app._next_featured_game(featured_games) is g1

    now = 1005.0  # 5s elapsed -> advance
    assert app._next_featured_game(featured_games) is g2

    now = 1010.0  # wraps back around
    assert app._next_featured_game(featured_games) is g1


# ── Frame rendering ──────────────────────────────────────────────────────────


def test_live_game_mode_any_snapshot(snapshot_update: bool) -> None:
    from apps.sports.app import SportsApp

    games = [
        _game_copy("soccer_long_note"),
        _game_copy("nfl_in_progress"),
        _game_copy("mlb_in_progress"),
    ]

    def seed(app: Any) -> None:
        app._games = games
        app._logos = fixture_logos_for_games(games)
        _pin_wc_logo_shown(app)

    image = harness.render_app_frame(
        SportsApp,
        {"leagues": [], "live_game_mode": True, "live_game_source": "any"},
        320, 64,
        seed=seed,
    )
    assert_snapshot(image, "sports", "live_game_mode_any_320x64", snapshot_update)


def test_live_game_mode_favorite_team_snapshot(snapshot_update: bool) -> None:
    from apps.sports.app import SportsApp

    games = [
        _game_copy("nfl_redzone_home_poss"),
        _game_copy("nba_in_progress"),
        _game_copy("nhl_in_progress"),
    ]

    def seed(app: Any) -> None:
        app._games = games
        app._logos = fixture_logos_for_games(games)

    image = harness.render_app_frame(
        SportsApp,
        {
            "leagues": [],
            "favorite_teams": ["nfl:KC"],
            "live_game_mode": True,
            "live_game_source": "favorites",
        },
        320, 64,
        seed=seed,
    )
    assert_snapshot(image, "sports", "live_game_mode_favorite_team_320x64", snapshot_update)


def test_live_game_mode_single_game_full_width_snapshot(snapshot_update: bool) -> None:
    from apps.sports.app import SportsApp

    games = [_game_copy("soccer_long_note")]

    def seed(app: Any) -> None:
        app._games = games
        app._logos = fixture_logos_for_games(games)
        _pin_wc_logo_shown(app)

    image = harness.render_app_frame(
        SportsApp,
        {"leagues": [], "live_game_mode": True, "live_game_source": "any"},
        320, 64,
        seed=seed,
    )
    assert_snapshot(image, "sports", "live_game_mode_single_game_320x64", snapshot_update)


def test_live_game_mode_no_live_games_falls_back_to_paginate() -> None:
    from apps.sports.app import SportsApp

    games = [
        _game_copy("mlb_walkoff_final"),  # post
        _game_copy("nhl_shootout_final"),  # post
    ]

    def seed(app: Any) -> None:
        app._games = games
        app._logos = fixture_logos_for_games(games)

    base_config = {"leagues": [], "display_mode": "paginate", "scores_per_screen": 2}

    plain = harness.render_app_frame(SportsApp, base_config, 320, 64, seed=seed)
    spotlight = harness.render_app_frame(
        SportsApp,
        {**base_config, "live_game_mode": True, "live_game_source": "any"},
        320, 64,
        seed=seed,
    )

    assert spotlight.tobytes() == plain.tobytes()
