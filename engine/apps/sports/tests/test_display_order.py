"""The order the cards rotate through games.

The module restarts at its first card every time the playlist brings it back
on screen, so with a league-sized slate - a Saturday of college football runs
to a hundred-odd games - only the front of the list is ever actually seen.
ESPN's payload order is neither documented nor chronological once a fetch
spans several date windows, which left today's final scores sitting behind
next month's fixtures, out of reach. So the module orders games itself: live
first, then the most recent results, then the soonest fixtures.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any


def _make_app(config: dict[str, Any] | None = None) -> Any:
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(320, 64, _noop_broadcast)
    return SportsApp({"leagues": ["college-football"], **(config or {})}, canvas, {}, {})


_NOW = datetime.datetime(2026, 9, 19, 22, 0, tzinfo=datetime.timezone.utc)


def _game(game_id: str, state: str, start: datetime.datetime, **extra: Any) -> dict[str, Any]:
    game = {
        "id": game_id,
        "sport": "football",
        "league": "college-football",
        "away_abbr": f"A{game_id}",
        "home_abbr": f"H{game_id}",
        "state": state,
        "start_time": start.isoformat(),
    }
    game.update(extra)
    return game


def test_live_then_recent_results_then_soonest_fixtures() -> None:
    app = _make_app()
    games = [
        _game("next_week", "pre", _NOW + datetime.timedelta(days=7)),
        _game("yesterday", "post", _NOW - datetime.timedelta(days=1)),
        _game("tomorrow", "pre", _NOW + datetime.timedelta(days=1)),
        _game("live", "in", _NOW - datetime.timedelta(hours=1)),
        _game("earlier_today", "post", _NOW - datetime.timedelta(hours=8)),
    ]

    ordered = [g["id"] for g in app._display_order(games)]

    assert ordered == ["live", "earlier_today", "yesterday", "tomorrow", "next_week"]


def test_games_that_tie_keep_the_order_they_were_fetched_in() -> None:
    """A slate that all kicks off at once must not shuffle between refreshes,
    or the rotation would restart somewhere different every minute."""
    app = _make_app()
    noon = _NOW - datetime.timedelta(hours=10)
    games = [_game(f"g{i}", "post", noon) for i in range(5)]

    assert [g["id"] for g in app._display_order(games)] == [f"g{i}" for i in range(5)]


def test_a_game_without_a_start_time_still_sorts() -> None:
    app = _make_app()
    games = [
        _game("undated", "pre", _NOW),
        _game("dated", "pre", _NOW + datetime.timedelta(days=1)),
    ]
    games[0]["start_time"] = None

    ordered = [g["id"] for g in app._display_order(games)]

    # The dated fixture leads; an undated one has nothing to place it by.
    assert ordered == ["dated", "undated"]


def test_fetch_data_leads_with_the_games_that_just_finished() -> None:
    """End to end: whatever order ESPN served, the first card is today's."""
    app = _make_app({"completed_game_window": {"days": 1}})
    served = [
        _game("next_week", "pre", _NOW + datetime.timedelta(days=6)),
        _game("just_finished", "post", _NOW - datetime.timedelta(hours=5)),
    ]

    async def fetch_scores(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [dict(g) for g in served]

    async def fetch_logos(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {}

    app._espn.fetch_scores = fetch_scores
    app._espn.fetch_logos = fetch_logos

    from tests.framework.clock import frozen_time

    with frozen_time("apps.sports.app.datetime.datetime", _NOW):
        asyncio.run(app.fetch_data())

    assert [g["id"] for g in app._games][0] == "just_finished"
