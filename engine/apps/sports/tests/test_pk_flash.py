"""App-level penalty-shootout flash wiring: fetch diffing, blink phase, expiry.

A newly landed shootout kick blinks for a few seconds, then settles into its
stationary result color. These tests cover the SportsApp state machine that
tracks kick counts and resolves the per-frame blink; the dot rendering itself
is covered by the widget/snapshot suites. ``app._now`` is monkeypatched
everywhere for determinism.
"""

from __future__ import annotations

import asyncio
from typing import Any

from apps.sports.app import _PK_FLASH_SECONDS


def _make_app(config: dict[str, Any] | None = None, w: int = 320, h: int = 64):
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(w, h, _noop_broadcast)
    return SportsApp({"leagues": [], **(config or {})}, canvas, {}, {})


def _shootout_game(away_pks: list[bool], home_pks: list[bool]) -> dict[str, Any]:
    return {
        "id": "700",
        "sport": "soccer",
        "league": "fifa.world",
        "away_abbr": "EGY", "home_abbr": "AUS",
        "away_name": "Egypt", "home_name": "Australia",
        "away_location": "", "home_location": "",
        "away_nickname": "", "home_nickname": "",
        "away_score": "1", "home_score": "1",
        "away_color": "c8102e", "home_color": "00843d",
        "away_alt_color": "ffffff", "home_alt_color": "ffcd00",
        "away_logo_url": None, "home_logo_url": None,
        "status": "AET-pens", "state": "in",
        "series_summary": None, "start_time": None,
        "away_rank": None, "home_rank": None,
        "away_conf": None, "home_conf": None,
        "situation": {},
        "away_id": "20", "home_id": "10",
        "away_record": None, "home_record": None,
        "match_note": "",
        "away_goals": [], "home_goals": [],
        "away_points": None, "home_points": None,
        "away_pks": away_pks, "home_pks": home_pks,
        "is_live_shootout": True, "ended_in_shootout": False,
    }


def _patch_fetch(app: Any, payloads: list[list[dict[str, Any]]]) -> None:
    calls = iter(payloads)

    async def fetch_scores(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [dict(g) for g in next(calls)]

    async def fetch_logos(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    app._espn.fetch_scores = fetch_scores
    app._espn.fetch_logos = fetch_logos


def test_shootout_start_shows_circles_without_flashing():
    """Circles must render as soon as penalties begin (no kicks yet), and the
    initial state must not flash anything — there is no *new* kick."""
    app = _make_app()
    _patch_fetch(app, [[_shootout_game([], [])]])
    app._now = lambda: 100.0

    asyncio.run(app.fetch_data())
    assert app._pk_flash == {}
    assert app._pk_flash_view("700", 0, 0) is None


def test_new_kick_flashes_then_settles():
    app = _make_app()
    _patch_fetch(app, [[_shootout_game([], [])], [_shootout_game([True], [])]])

    now = 100.0
    app._now = lambda: now
    asyncio.run(app.fetch_data())  # first observation: 0 kicks, no flash

    now = 105.0
    asyncio.run(app.fetch_data())  # away scores their first kick
    assert app._pk_flash[("700", "away")] == (0, 105.0)

    # Inside the window the newest away dot blinks; home has nothing.
    view = app._pk_flash_view("700", 1, 0)
    assert view is not None
    assert view.away == frozenset({0})
    assert view.home == frozenset()

    # After the window it settles to stationary (no flash view at all).
    now = 105.0 + _PK_FLASH_SECONDS
    assert app._pk_flash_view("700", 1, 0) is None


def test_blink_phase_toggles_over_time():
    app = _make_app()
    _patch_fetch(app, [[_shootout_game([], [])], [_shootout_game([True], [])]])
    now = 100.0
    app._now = lambda: now
    asyncio.run(app.fetch_data())
    now = 100.0
    asyncio.run(app.fetch_data())

    now = 100.0
    on_a = app._pk_flash_view("700", 1, 0).on
    now = 100.0 + 1.0 / 3  # one blink period at 3 Hz
    on_b = app._pk_flash_view("700", 1, 0).on
    assert on_a != on_b


def test_reconstructed_misses_flash_together():
    """When a later scored kick reveals earlier missed kicks, every index added
    since the last fetch blinks — not just the newest."""
    app = _make_app()
    _patch_fetch(app, [
        [_shootout_game([True], [])],            # away 1 kick known
        [_shootout_game([True], [False, True])],  # home reveals a miss + a score
    ])
    now = 100.0
    app._now = lambda: now
    asyncio.run(app.fetch_data())
    now = 105.0
    asyncio.run(app.fetch_data())

    view = app._pk_flash_view("700", 1, 2)
    assert view is not None
    assert view.away == frozenset()          # away unchanged
    assert view.home == frozenset({0, 1})    # both new home dots blink


def test_vanished_game_prunes_flash_state():
    app = _make_app()
    _patch_fetch(app, [
        [_shootout_game([], [])],
        [_shootout_game([True], [])],
        [],
    ])
    now = 100.0
    app._now = lambda: now
    asyncio.run(app.fetch_data())
    now = 105.0
    asyncio.run(app.fetch_data())
    assert ("700", "away") in app._pk_flash

    now = 110.0
    asyncio.run(app.fetch_data())
    assert app._pk_flash == {}
    assert app._pk_counts == {}
