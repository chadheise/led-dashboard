"""`limit` is a tuning parameter, not a requirement.

ESPN's scoreboard truncates a response unless ``limit`` asks for more, so the
fetch asks for the full slate. But the endpoint caps the value it accepts and
rejects the request outright rather than clamping it - and because the fetch
sent ``limit`` unconditionally, a refusal failed every date window of every
league at once. `fetch_scores` then returned no games and the sports module
showed an empty screen during a full slate of fixtures.

So a total failure now retries without ``limit``, and remembers the refusal
so the doomed request isn't repeated every refresh cycle (re-probing later,
in case the refusal was a coincidental outage or has been fixed).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from libraries.espn_sports.library import (
    _LIMIT_REPROBE_SECONDS,
    ESPNSportsLibrary,
    ScoresUnavailable,
)


def _event(event_id: str, start: datetime, state: str = "pre") -> dict[str, Any]:
    return {
        "id": event_id,
        "status": {"type": {"state": state, "shortDetail": state}},
        "competitions": [
            {
                "date": start.strftime("%Y-%m-%dT%H:%MZ"),
                "competitors": [
                    {"homeAway": "away", "team": {"id": "1", "abbreviation": "SEA"}, "score": "24"},
                    {"homeAway": "home", "team": {"id": "2", "abbreviation": "ARI"}, "score": "10"},
                ],
            }
        ],
    }


class _LimitRefusingEndpoint:
    """Serves the slate, but 400s any request carrying ``limit``."""

    def __init__(self, events: list[dict[str, Any]], *, refuse: bool = True) -> None:
        self._events = events
        self.refuse = refuse
        self.calls: list[dict[str, str]] = []

    async def __call__(
        self, _client: Any, _url: str, params: dict[str, str]
    ) -> dict[str, Any]:
        self.calls.append(dict(params))
        if self.refuse and "limit" in params:
            raise RuntimeError("400 Bad Request: invalid limit")
        return {"events": list(self._events)}

    @property
    def calls_with_limit(self) -> int:
        return sum(1 for call in self.calls if "limit" in call)


def _library(endpoint: Any) -> Any:
    lib = ESPNSportsLibrary({})
    lib._get_scoreboard = endpoint  # type: ignore[method-assign]
    return lib


def _fetch(lib: Any) -> list[dict[str, Any]]:
    return asyncio.run(lib._fetch_league(object(), "nfl", 30, 1))


def test_a_refused_limit_still_returns_the_games() -> None:
    """The headline regression: no scores at all while games were on."""
    now = datetime.now(timezone.utc)
    endpoint = _LimitRefusingEndpoint([_event("upcoming", now + timedelta(days=3))])

    games = _fetch(_library(endpoint))

    assert [g["id"] for g in games] == ["upcoming"]
    assert endpoint.calls_with_limit, "expected the full slate to be tried first"


def test_the_refusal_is_remembered_so_it_is_not_repeated_every_cycle() -> None:
    """A doomed request per league per refresh cycle is pure waste."""
    now = datetime.now(timezone.utc)
    endpoint = _LimitRefusingEndpoint([_event("upcoming", now + timedelta(days=3))])
    lib = _library(endpoint)

    _fetch(lib)
    first_round = endpoint.calls_with_limit
    endpoint.calls.clear()

    assert [g["id"] for g in _fetch(lib)] == ["upcoming"]
    assert first_round > 0
    assert endpoint.calls_with_limit == 0
    assert endpoint.calls, "the fetch still has to happen, just without `limit`"


def test_limit_is_re_probed_after_the_backoff_window() -> None:
    """The refusal may have been a coincidental outage, or may be fixed."""
    now = datetime.now(timezone.utc)
    endpoint = _LimitRefusingEndpoint([_event("upcoming", now + timedelta(days=3))])
    lib = _library(endpoint)

    _fetch(lib)
    assert lib._limit_refused_at is not None
    lib._limit_refused_at -= _LIMIT_REPROBE_SECONDS + 1
    endpoint.calls.clear()
    endpoint.refuse = False  # the cap has been raised, or the blip has passed

    assert [g["id"] for g in _fetch(lib)] == ["upcoming"]
    assert endpoint.calls_with_limit, "expected `limit` to be tried again"
    assert lib._limit_refused_at is None


def test_a_real_outage_still_surfaces_as_unavailable() -> None:
    """Dropping `limit` must not paper over a genuine failure."""

    async def dead(_client: Any, _url: str, _params: dict[str, str]) -> dict[str, Any]:
        raise RuntimeError("Network unreachable")

    with pytest.raises(ScoresUnavailable):
        _fetch(_library(dead))


def test_fetch_scores_reports_which_leagues_could_not_be_reached() -> None:
    async def dead(_client: Any, _url: str, _params: dict[str, str]) -> dict[str, Any]:
        raise RuntimeError("Network unreachable")

    lib = _library(dead)
    games = asyncio.run(lib.fetch_scores(["nfl", "mlb"]))

    assert games == []
    assert sorted(lib.last_fetch_failures) == ["mlb", "nfl"]


def test_fetch_scores_reports_no_failures_when_a_league_is_simply_idle() -> None:
    """An offseason league answers successfully with an empty slate - that is
    not a failure, and must not be reported as one."""
    lib = _library(_LimitRefusingEndpoint([], refuse=False))

    assert asyncio.run(lib.fetch_scores(["nfl"])) == []
    assert lib.last_fetch_failures == []
