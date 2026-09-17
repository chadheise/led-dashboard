"""Scoreboard date windows: what ESPN's ``dates`` parameter actually accepts.

``dates`` takes a single YYYY, YYYYMM or YYYYMMDD. It does *not* take a
YYYYMMDD-YYYYMMDD range: the endpoint answers HTTP 400 ("Failed to get events
endpoint") for every league. The fetch used to send exactly that range, so
every window of every league failed at once and the module showed "Scores
unavailable" through a full slate of games. `_Recorder` below rejects a range
the way the endpoint does, so that can't pass silently again.

So the fetch asks one month at a time, merged and deduped, and asks for the
full slate with ``limit`` - which the endpoint honours up to 500 and quietly
ignores above that, serving its small default instead.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from libraries.espn_sports.library import _SCOREBOARD_EVENT_LIMIT


def _event(event_id: str, start: datetime, state: str, away: str, home: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "status": {"type": {"state": state, "shortDetail": state}},
        "competitions": [
            {
                "date": start.strftime("%Y-%m-%dT%H:%MZ"),
                "competitors": [
                    {"homeAway": "away", "team": {"id": "1", "abbreviation": away}, "score": "24"},
                    {"homeAway": "home", "team": {"id": "2", "abbreviation": home}, "score": "10"},
                ],
            }
        ],
    }


# What ESPN returns when the request doesn't ask for more, and the largest
# `limit` it honours before falling back to that default.
_DEFAULT_RESPONSE_CAP = 25
_MAX_ACCEPTED_LIMIT = 500


def _month_bounds(token: str) -> tuple[datetime, datetime]:
    year, month = int(token[:4]), int(token[4:])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=timezone.utc)
    return start, end


class _Recorder:
    """Stands in for ``_get_scoreboard``, serving events by requested month.

    Models the two ways the endpoint punishes a bad request: a ``dates`` range
    fails outright, and a ``limit`` above the cap is ignored in favour of the
    small default. Which end of an over-long response is dropped isn't
    contractual, so the fake keeps the tail - the pessimistic case for a
    display that wants the games that just finished.
    """

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.calls: list[dict[str, str]] = []

    async def __call__(
        self, _client: Any, _url: str, params: dict[str, str]
    ) -> dict[str, Any]:
        self.calls.append(dict(params))
        dates = params["dates"]
        if not re.fullmatch(r"\d{6}", dates):
            # The endpoint's own answer to a range or any other shape.
            raise RuntimeError(f"HTTP 400: Failed to get events endpoint (dates={dates})")
        start, end = _month_bounds(dates)
        matched = [
            e
            for e in self._events
            if start <= datetime.fromisoformat(
                e["competitions"][0]["date"].replace("Z", "+00:00")
            ) < end
        ]
        asked = int(params.get("limit", 0))
        limit = asked if 0 < asked <= _MAX_ACCEPTED_LIMIT else _DEFAULT_RESPONSE_CAP
        return {"events": matched[-limit:]}


def _fetch(library: Any, *, days_ahead: int, days_behind: int) -> list[dict[str, Any]]:
    return asyncio.run(
        library._fetch_league(object(), "nfl", days_ahead, days_behind)
    )


def _library() -> Any:
    from libraries.espn_sports.library import ESPNSportsLibrary

    return ESPNSportsLibrary({})


def _months_spanning(start: datetime, end: datetime) -> list[str]:
    tokens: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        tokens.append(f"{year:04d}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return tokens


def test_every_month_the_span_touches_is_fetched() -> None:
    lib = _library()
    recorder = _Recorder([])
    lib._get_scoreboard = recorder  # type: ignore[method-assign]

    _fetch(lib, days_ahead=30, days_behind=1)

    now = datetime.now(timezone.utc)
    assert [c["dates"] for c in recorder.calls] == _months_spanning(
        now - timedelta(days=1), now + timedelta(days=30)
    )


def test_dates_is_never_sent_as_a_range() -> None:
    """The regression: a range is rejected by every league at once."""
    lib = _library()
    recorder = _Recorder([])
    lib._get_scoreboard = recorder  # type: ignore[method-assign]

    _fetch(lib, days_ahead=30, days_behind=1)

    assert recorder.calls, "expected at least one scoreboard request"
    assert all(re.fullmatch(r"\d{6}", c["dates"]) for c in recorder.calls)


def test_every_request_asks_for_the_full_slate_within_the_cap() -> None:
    """Too small and ESPN truncates; above 500 it ignores `limit` entirely."""
    lib = _library()
    recorder = _Recorder([])
    lib._get_scoreboard = recorder  # type: ignore[method-assign]

    _fetch(lib, days_ahead=30, days_behind=1)

    assert recorder.calls, "expected at least one scoreboard request"
    assert _SCOREBOARD_EVENT_LIMIT <= _MAX_ACCEPTED_LIMIT
    assert all(
        100 <= int(call["limit"]) <= _MAX_ACCEPTED_LIMIT for call in recorder.calls
    )


def test_completed_game_survives_a_month_long_lookahead() -> None:
    """A final from a few hours ago, 30 days of fixtures ahead."""
    lib = _library()
    now = datetime.now(timezone.utc)
    events = [_event("final", now - timedelta(hours=6), "post", "SEA", "ARI")]
    # A month of upcoming fixtures, far more than the default response returns.
    events += [
        _event(f"up{i}", now + timedelta(days=1 + i // 2, hours=i), "pre", "SEA", "SF")
        for i in range(40)
    ]
    lib._get_scoreboard = _Recorder(events)  # type: ignore[method-assign]

    games = _fetch(lib, days_ahead=30, days_behind=1)

    by_id = {g["id"]: g for g in games}
    assert "final" in by_id
    assert by_id["final"]["state"] == "post"
    assert (by_id["final"]["away_score"], by_id["final"]["home_score"]) == ("24", "10")


def test_a_game_in_two_fetched_months_is_returned_once() -> None:
    lib = _library()
    now = datetime.now(timezone.utc)
    game = _event("today", now, "in", "SEA", "ARI")
    recorder = _Recorder([game])
    # Serve the same game from every month, the way an overlapping span would.
    recorder._events = [game]

    async def every_month(client: Any, url: str, params: dict[str, str]) -> dict[str, Any]:
        await recorder(client, url, params)
        return {"events": [game]}

    lib._get_scoreboard = every_month  # type: ignore[method-assign]

    games = _fetch(lib, days_ahead=40, days_behind=1)

    assert [g["id"] for g in games] == ["today"]


def test_no_lookahead_still_makes_a_single_request() -> None:
    lib = _library()
    recorder = _Recorder([])
    lib._get_scoreboard = recorder  # type: ignore[method-assign]

    _fetch(lib, days_ahead=0, days_behind=1)

    now = datetime.now(timezone.utc)
    assert [c["dates"] for c in recorder.calls] == _months_spanning(
        now - timedelta(days=1), now
    )


def test_one_failed_month_does_not_lose_the_other() -> None:
    lib = _library()
    now = datetime.now(timezone.utc)
    served = _Recorder([_event("final", now - timedelta(hours=6), "post", "SEA", "ARI")])
    months = _months_spanning(now - timedelta(days=1), now + timedelta(days=40))
    assert len(months) > 1, "span must straddle a month boundary for this test"

    async def flaky(client: Any, url: str, params: dict[str, str]) -> dict[str, Any]:
        if params["dates"] == months[-1]:
            raise RuntimeError("look-ahead month failed")
        return await served(client, url, params)

    lib._get_scoreboard = flaky  # type: ignore[method-assign]

    games = _fetch(lib, days_ahead=40, days_behind=1)

    assert [g["id"] for g in games] == ["final"]


def test_all_windows_failing_falls_back_to_the_cached_games() -> None:
    lib = _library()
    lib._scores_cache["nfl"] = (datetime.now(timezone.utc).timestamp(), [{"id": "cached"}])

    async def always_fails(_client: Any, _url: str, _params: dict[str, str]) -> dict[str, Any]:
        raise RuntimeError("ESPN down")

    lib._get_scoreboard = always_fails  # type: ignore[method-assign]

    assert [g["id"] for g in _fetch(lib, days_ahead=30, days_behind=1)] == ["cached"]
