"""Blank-screen resilience: a transient ESPN failure or an in-limbo kickoff
must not leave the panel black.

Covers the library's last-known-good fallback for failed scoreboard fetches
and the time-window filter's grace period for games past their scheduled
start that ESPN hasn't flipped to "in" yet.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

from libraries.espn_sports.library import ESPNSportsLibrary


class _Resp:
    status_code = 200

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._data


class _StubClient:
    """Yields each queued item per get(): a payload dict or an Exception."""

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    async def get(self, url: str, params: dict[str, str] | None = None) -> _Resp:
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Resp(item)


def _espn_payload() -> dict[str, Any]:
    return {
        "events": [
            {
                "id": "1001",
                "status": {"type": {"shortDetail": "Sat 3:00 PM", "state": "pre"}},
                "competitions": [
                    {
                        "date": "2026-06-12T19:00:00Z",
                        "competitors": [
                            {
                                "homeAway": "home",
                                "score": "0",
                                "team": {"abbreviation": "USA", "displayName": "United States", "id": "1"},
                            },
                            {
                                "homeAway": "away",
                                "score": "0",
                                "team": {"abbreviation": "MEX", "displayName": "Mexico", "id": "2"},
                            },
                        ],
                    }
                ],
            }
        ]
    }


def test_fetch_failure_serves_cached_games() -> None:
    lib = ESPNSportsLibrary({})
    client = _StubClient([_espn_payload(), RuntimeError("timeout")])

    first = asyncio.run(lib._fetch_league(client, "fifa.world"))
    assert [g["home_abbr"] for g in first] == ["USA"]

    second = asyncio.run(lib._fetch_league(client, "fifa.world"))
    assert [g["home_abbr"] for g in second] == ["USA"]


def test_fetch_failure_without_cache_returns_empty() -> None:
    lib = ESPNSportsLibrary({})
    client = _StubClient([RuntimeError("timeout")])
    assert asyncio.run(lib._fetch_league(client, "fifa.world")) == []


def test_fetch_retries_once_after_transient_error() -> None:
    """A single dropped connection shouldn't fall back to cache/empty if a
    retry would have succeeded."""
    lib = ESPNSportsLibrary({})
    client = _StubClient([RuntimeError("connection reset"), _espn_payload()])
    games = asyncio.run(lib._fetch_league(client, "fifa.world"))
    assert [g["home_abbr"] for g in games] == ["USA"]


def test_fetch_failure_ignores_stale_cache() -> None:
    lib = ESPNSportsLibrary({})
    client = _StubClient([_espn_payload(), RuntimeError("timeout")])
    asyncio.run(lib._fetch_league(client, "fifa.world"))

    fetched_at, games = lib._scores_cache["fifa.world"]
    lib._scores_cache["fifa.world"] = (fetched_at - 16 * 60, games)

    assert asyncio.run(lib._fetch_league(client, "fifa.world")) == []


def _make_app() -> Any:
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(320, 64, _noop_broadcast)
    return SportsApp({"leagues": [], "upcoming_game_window": {"days": 1}}, canvas, {}, {})


def _pre_game(game_id: str, start: datetime.datetime) -> dict[str, Any]:
    return {"id": game_id, "state": "pre", "start_time": start.isoformat()}


def test_filter_keeps_pre_game_just_past_kickoff() -> None:
    app = _make_app()
    now = datetime.datetime.now(datetime.timezone.utc)
    games = [
        _pre_game("at_kickoff", now - datetime.timedelta(hours=1)),
        _pre_game("long_gone", now - datetime.timedelta(hours=5)),
        _pre_game("tomorrow", now + datetime.timedelta(hours=12)),
    ]
    kept = [g["id"] for g in app._filter_by_time_window(games)]
    assert kept == ["at_kickoff", "tomorrow"]
