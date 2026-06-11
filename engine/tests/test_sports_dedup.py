"""SportsApp dedupes repeat games returned by overlapping league fetches.

E.g. an inter-conference NCAAF matchup can be returned once per selected
conference filter; without dedup it would show up in two sections at once
when scores_per_screen > 1.
"""

from __future__ import annotations

import asyncio
from typing import Any


def _make_app(config: dict[str, Any] | None = None, w: int = 320, h: int = 64):
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(w, h, _noop_broadcast)
    return SportsApp({"leagues": [], **(config or {})}, canvas, {}, {})


def _game(game_id: str, **extra: Any) -> dict[str, Any]:
    game = {
        "id": game_id,
        "sport": "football",
        "league": "college-football",
        "away_abbr": "GA", "home_abbr": "BAMA",
        "away_score": "0", "home_score": "0",
        "state": "in",
        "start_time": None,
    }
    game.update(extra)
    return game


def _patch_fetch(app: Any, games: list[dict[str, Any]]) -> None:
    async def fetch_scores(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [dict(g) for g in games]

    async def fetch_logos(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    app._espn.fetch_scores = fetch_scores
    app._espn.fetch_logos = fetch_logos


def test_fetch_data_dedupes_games_with_same_id():
    app = _make_app({"leagues": ["ncaaf-acc", "ncaaf-sec"]})
    game = _game("500")
    # Same inter-conference matchup returned once per overlapping league fetch.
    _patch_fetch(app, [game, dict(game)])

    asyncio.run(app.fetch_data())

    assert len(app._games) == 1
    assert app._games[0]["id"] == "500"


def test_dedupe_games_preserves_order_of_first_occurrence():
    app = _make_app()
    a, b, c = _game("1"), _game("2"), _game("1")

    result = app._dedupe_games([a, b, c])

    assert [g["id"] for g in result] == ["1", "2"]
    assert result[0] is a
