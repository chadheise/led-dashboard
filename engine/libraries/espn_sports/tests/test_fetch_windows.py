"""Scoreboard date windows: recent games must survive a wide look-ahead.

ESPN's scoreboard truncates a response to a couple dozen events unless
``limit`` asks for more. "Next game per team" mode looks 30 days ahead, and
folding that look-ahead into one date range with the recent window let the
upcoming fixtures crowd the just-finished games out of the truncated
response - a favorite team's final score silently stopped appearing while
its next scheduled game kept showing.

So the fetch asks for the full slate (``limit``) and splits the range into a
recent window (through today) and a look-ahead window, merged and deduped.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any


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


# What ESPN returns for a range when the request doesn't say otherwise.
_DEFAULT_RESPONSE_CAP = 25


class _Recorder:
    """Stands in for ``_get_scoreboard``, serving events by requested range.

    Models the endpoint's truncation: a response carries at most ``limit``
    events, defaulting to a couple dozen. Which end of an over-long range is
    dropped isn't contractual, so the fake keeps the tail - the pessimistic
    case for a display that wants the games that just finished.
    """

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.calls: list[dict[str, str]] = []

    async def __call__(
        self, _client: Any, _url: str, params: dict[str, str]
    ) -> dict[str, Any]:
        self.calls.append(dict(params))
        start_raw, _, end_raw = params["dates"].partition("-")
        start = datetime.strptime(start_raw, "%Y%m%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(end_raw, "%Y%m%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        matched = [
            e
            for e in self._events
            if start <= datetime.fromisoformat(
                e["competitions"][0]["date"].replace("Z", "+00:00")
            ) < end
        ]
        limit = int(params.get("limit", _DEFAULT_RESPONSE_CAP))
        return {"events": matched[-limit:]}


def _fetch(library: Any, *, days_ahead: int, days_behind: int) -> list[dict[str, Any]]:
    return asyncio.run(
        library._fetch_league(object(), "nfl", days_ahead, days_behind)
    )


def _library() -> Any:
    from libraries.espn_sports.library import ESPNSportsLibrary

    return ESPNSportsLibrary({})


def test_recent_and_lookahead_windows_are_fetched_separately() -> None:
    lib = _library()
    recorder = _Recorder([])
    lib._get_scoreboard = recorder  # type: ignore[method-assign]

    _fetch(lib, days_ahead=30, days_behind=1)

    today = datetime.now(timezone.utc).date()
    ranges = [c["dates"] for c in recorder.calls]
    assert ranges == [
        f"{today - timedelta(days=1):%Y%m%d}-{today:%Y%m%d}",
        f"{today:%Y%m%d}-{today + timedelta(days=30):%Y%m%d}",
    ]


def test_every_request_asks_for_the_full_slate() -> None:
    """Without ``limit`` ESPN truncates the response and silently drops games."""
    lib = _library()
    recorder = _Recorder([])
    lib._get_scoreboard = recorder  # type: ignore[method-assign]

    _fetch(lib, days_ahead=30, days_behind=1)

    assert recorder.calls, "expected at least one scoreboard request"
    assert all(int(call["limit"]) >= 1000 for call in recorder.calls)


def test_completed_game_survives_a_truncating_month_long_lookahead() -> None:
    """The regression: a final from a few hours ago, 30 days of fixtures ahead."""
    lib = _library()
    now = datetime.now(timezone.utc)
    events = [_event("final", now - timedelta(hours=6), "post", "SEA", "ARI")]
    # A month of upcoming fixtures, far more than one response returns.
    events += [
        _event(f"up{i}", now + timedelta(days=1 + i // 2, hours=i), "pre", "SEA", "SF")
        for i in range(40)
    ]
    lib._get_scoreboard = _Recorder(events)  # type: ignore[method-assign]

    games = _fetch(lib, days_ahead=30, days_behind=1)

    assert "final" in {g["id"] for g in games}
    assert games[0]["id"] == "final"  # recent window first, so it paginates first
    assert games[0]["state"] == "post"
    assert (games[0]["away_score"], games[0]["home_score"]) == ("24", "10")


def test_a_game_in_both_windows_is_returned_once() -> None:
    lib = _library()
    now = datetime.now(timezone.utc)
    # Today's game falls in the recent window and the look-ahead window alike.
    lib._get_scoreboard = _Recorder(  # type: ignore[method-assign]
        [_event("today", now, "in", "SEA", "ARI")]
    )

    games = _fetch(lib, days_ahead=7, days_behind=1)

    assert [g["id"] for g in games] == ["today"]


def test_no_lookahead_still_makes_a_single_request() -> None:
    lib = _library()
    recorder = _Recorder([])
    lib._get_scoreboard = recorder  # type: ignore[method-assign]

    _fetch(lib, days_ahead=0, days_behind=1)

    today = datetime.now(timezone.utc).date()
    assert [c["dates"] for c in recorder.calls] == [
        f"{today - timedelta(days=1):%Y%m%d}-{today:%Y%m%d}"
    ]


def test_one_failed_window_does_not_lose_the_other() -> None:
    lib = _library()
    now = datetime.now(timezone.utc)
    served = _Recorder([_event("final", now - timedelta(hours=6), "post", "SEA", "ARI")])

    async def flaky(client: Any, url: str, params: dict[str, str]) -> dict[str, Any]:
        if params["dates"].endswith(f"{(now + timedelta(days=30)).date():%Y%m%d}"):
            raise RuntimeError("look-ahead window failed")
        return await served(client, url, params)

    lib._get_scoreboard = flaky  # type: ignore[method-assign]

    games = _fetch(lib, days_ahead=30, days_behind=1)

    assert [g["id"] for g in games] == ["final"]


def test_all_windows_failing_falls_back_to_the_cached_games() -> None:
    lib = _library()
    lib._scores_cache["nfl"] = (datetime.now(timezone.utc).timestamp(), [{"id": "cached"}])

    async def always_fails(_client: Any, _url: str, _params: dict[str, str]) -> dict[str, Any]:
        raise RuntimeError("ESPN down")

    lib._get_scoreboard = always_fails  # type: ignore[method-assign]

    assert [g["id"] for g in _fetch(lib, days_ahead=30, days_behind=1)] == ["cached"]
