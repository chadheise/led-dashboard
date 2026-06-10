"""App-level celebration wiring: fetch diffing, expiry, and marquee patching.

Card-level celebration rendering is covered by the snapshot/layout suites via
the ``*_celebration`` fixtures; these tests cover the SportsApp state machine
around them. ``app._now`` is monkeypatched everywhere for determinism.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.snaptest import harness
from tests.snaptest.compare import assert_snapshot
from tests.snaptest.logos import fixture_logos_for_games

harness.load_suites()


def _make_app(config: dict[str, Any] | None = None, w: int = 320, h: int = 64):
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(w, h, _noop_broadcast)
    return SportsApp({"leagues": [], **(config or {})}, canvas, {}, {})


def _soccer_game(home_score: str) -> dict[str, Any]:
    return {
        "id": "401",
        "sport": "soccer",
        "league": "eng.1",
        "away_abbr": "MCI", "home_abbr": "ARS",
        "away_name": "Manchester City", "home_name": "Arsenal",
        "away_location": "Manchester", "home_location": "London",
        "away_nickname": "City", "home_nickname": "Arsenal",
        "away_score": "1", "home_score": home_score,
        "away_color": "6cabdd", "home_color": "ef0107",
        "away_alt_color": "1c2c5b", "home_alt_color": "023474",
        "away_logo_url": None, "home_logo_url": None,
        "status": "67'", "state": "in",
        "series_summary": None, "start_time": None,
        "away_rank": None, "home_rank": None,
        "away_conf": None, "home_conf": None,
        "situation": {},
        "away_id": "382", "home_id": "359",
        "away_record": None, "home_record": None,
        "match_note": "",
        "away_goals": ["23'"], "home_goals": [],
        "away_points": None, "home_points": None,
    }


def _patch_fetch(app: Any, payloads: list[list[dict[str, Any]]]) -> None:
    calls = iter(payloads)

    async def fetch_scores(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [dict(g) for g in next(calls)]

    async def fetch_logos(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    app._espn.fetch_scores = fetch_scores
    app._espn.fetch_logos = fetch_logos


def test_fetch_diff_starts_celebration_and_expires():
    app = _make_app()
    _patch_fetch(app, [[_soccer_game("1")], [_soccer_game("2")]])

    now = 100.0
    app._now = lambda: now

    asyncio.run(app.fetch_data())
    assert app._celebrations == {}  # first observation never celebrates

    now = 160.0
    asyncio.run(app.fetch_data())
    assert "401" in app._celebrations
    celeb = app._celebrations["401"]
    assert (celeb.kind, celeb.side, celeb.started_at) == ("goal", "home", 160.0)

    # Active inside the window, with 1 Hz pulse and advancing animation.
    now = 162.5
    view = app._celebration_view("401")
    assert view is not None and view.pulse_on and view.anim_frame == 4
    now = 163.5
    view = app._celebration_view("401")
    assert view is not None and not view.pulse_on

    # Gone after 60 seconds.
    now = 160.0 + 60.0
    assert app._celebration_view("401") is None


def test_vanished_game_prunes_celebration():
    app = _make_app()
    _patch_fetch(app, [[_soccer_game("1")], [_soccer_game("2")], []])
    now = 100.0
    app._now = lambda: now

    asyncio.run(app.fetch_data())
    now = 160.0
    asyncio.run(app.fetch_data())
    assert "401" in app._celebrations
    now = 220.0
    asyncio.run(app.fetch_data())
    assert app._celebrations == {}


def test_paginate_celebration_frame_snapshot(snapshot_update: bool):
    """One full paginate frame with a live celebration, both pulse phases."""
    from apps.sports.app import SportsApp

    suite = harness.get_suite("sports")
    games = [dict(suite.fixtures["nfl_in_progress"]), _soccer_game("2")]

    from apps.sports.events import Celebration

    for phase_now, tag in ((10.5, "on"), (11.5, "off")):
        def seed(app: Any) -> None:
            app._games = games
            app._logos = fixture_logos_for_games(games)
            app._celebrations = {"401": Celebration("goal", "home", 10.0)}
            app._now = lambda: phase_now

        image = harness.render_app_frame(
            SportsApp,
            {"leagues": [], "display_mode": "paginate", "scores_per_screen": 2},
            320, 64,
            seed=seed,
        )
        assert_snapshot(image, "sports", f"frame_celebration_pulse_{tag}_320x64", snapshot_update)


def test_marquee_strip_patches_on_pulse_change():
    from apps.sports.events import Celebration

    app = _make_app({"display_mode": "marquee", "scores_per_screen": 2})
    games = [_soccer_game("2"), dict(_soccer_game("1"), id="402", home_abbr="LIV")]
    app._games = games
    app._logos = {}
    app._celebrations = {"401": Celebration("goal", "home", 0.0)}

    now = 0.5
    app._now = lambda: now
    asyncio.run(app.render_frame())
    strip_on = app._marquee_strip.copy()

    # Crossing the 1 Hz boundary patches the celebrating card in place.
    now = 1.5
    asyncio.run(app.render_frame())
    strip_off = app._marquee_strip
    card_w = app.canvas.width // 2
    h = app.canvas.height
    assert strip_on.crop((0, 0, card_w, h)).tobytes() != strip_off.crop(
        (0, 0, card_w, h)
    ).tobytes()
    # The non-celebrating card is untouched, and the divider stays intact.
    assert strip_on.crop((card_w + 1, 0, card_w * 2, h)).tobytes() == strip_off.crop(
        (card_w + 1, 0, card_w * 2, h)
    ).tobytes()
    assert strip_off.getpixel((card_w, 0)) == (35, 35, 35)


def test_marquee_strip_unchanged_within_pulse_phase():
    from apps.sports.events import Celebration

    app = _make_app({"display_mode": "marquee"})
    app._games = [_soccer_game("2")]
    app._logos = {}
    app._celebrations = {"401": Celebration("goal", "home", 0.0)}

    render_calls = 0
    original = app._render_slot_image

    def counting_render(*args: Any, **kwargs: Any):
        nonlocal render_calls
        render_calls += 1
        return original(*args, **kwargs)

    app._render_slot_image = counting_render

    now = 0.01
    app._now = lambda: now
    asyncio.run(app.render_frame())  # builds the strip
    builds = render_calls
    now = 0.05  # same pulse second, same anim frame
    asyncio.run(app.render_frame())
    assert render_calls == builds  # no re-render without a phase change
