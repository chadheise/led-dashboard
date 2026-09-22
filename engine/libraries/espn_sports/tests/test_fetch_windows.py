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

A month is not always under that cap. College football carries every division
on a Saturday, and a month of them runs past 500 events, at which point ESPN
serves a silently truncated response - whole days of it simply missing, with
no indication of which. Any month that comes back at the cap is therefore
re-asked one day at a time, where no league comes close to it.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import contextmanager
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


def _day_bounds(token: str) -> tuple[datetime, datetime]:
    start = datetime(int(token[:4]), int(token[4:6]), int(token[6:]), tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


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
        if not re.fullmatch(r"\d{6}|\d{8}", dates):
            # The endpoint's own answer to a range or any other shape.
            raise RuntimeError(f"HTTP 400: Failed to get events endpoint (dates={dates})")
        start, end = _month_bounds(dates) if len(dates) == 6 else _day_bounds(dates)
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
    # A month (YYYYMM) or a single day (YYYYMMDD) - never a range.
    assert all(re.fullmatch(r"\d{6}|\d{8}", c["dates"]) for c in recorder.calls)


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


# A mid-month day, so a short span around it can't straddle a month boundary
# and split the dense slate across two (individually uncapped) responses.
_FROZEN_NOW = datetime(2026, 9, 19, 20, 0, tzinfo=timezone.utc)


@contextmanager
def _frozen_clock() -> Any:
    """Pin the fetch's idea of today, so the span under test is fixed."""
    from libraries.espn_sports import library

    class _Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return _FROZEN_NOW if tz else _FROZEN_NOW.replace(tzinfo=None)

    real = library.datetime
    library.datetime = _Clock  # type: ignore[misc]
    try:
        yield
    finally:
        library.datetime = real  # type: ignore[misc]


def _dense_month_events() -> list[dict[str, Any]]:
    """More events in this month than one response can carry.

    Modelled on a college-football month: a slate heavy enough to run past
    the cap, and one just-finished game that the display needs - listed
    first, so a response truncated from either end can drop it.
    """
    events = [_event("final", _FROZEN_NOW - timedelta(hours=6), "post", "UGA", "BAMA")]
    # Enough to push the month past the cap within the fetched span alone.
    events += [
        _event(f"pad{i}", _FROZEN_NOW + timedelta(hours=1 + (i % 40)), "pre", "SEA", "SF")
        for i in range(_SCOREBOARD_EVENT_LIMIT + 50)
    ]
    return events


def test_a_month_over_the_event_cap_is_re_asked_day_by_day() -> None:
    """The regression: a capped month is silently short, and the games it
    drops can be the ones that just finished."""
    lib = _library()
    recorder = _Recorder(_dense_month_events())
    lib._get_scoreboard = recorder  # type: ignore[method-assign]

    with _frozen_clock():
        games = asyncio.run(lib._fetch_league(object(), "college-football", 2, 1))

    day_calls = [c["dates"] for c in recorder.calls if len(c["dates"]) == 8]
    # The span is today-1 .. today+2, so four days and not the whole month.
    assert day_calls == ["20260918", "20260919", "20260920", "20260921"]
    assert "final" in {g["id"] for g in games}


def test_the_day_re_ask_covers_the_near_days_not_the_whole_look_ahead() -> None:
    """A league dense enough to cap a month plays a full slate every week, so
    only its near days can reach the screen - and one request per day of a
    month-long look-ahead, every refresh, is work the Pi has to do between
    frames. The far end of the span rides on the month response, which in the
    seasons that need a long look-ahead (a post-season of scattered bowls) is
    nowhere near the cap and so isn't truncated at all."""
    from libraries.espn_sports.library import _REFINE_AHEAD_DAYS

    lib = _library()
    recorder = _Recorder(_dense_month_events())
    lib._get_scoreboard = recorder  # type: ignore[method-assign]

    with _frozen_clock():
        asyncio.run(lib._fetch_league(object(), "college-football", 30, 1))

    day_calls = [c["dates"] for c in recorder.calls if len(c["dates"]) == 8]
    assert len(day_calls) <= _REFINE_AHEAD_DAYS + 2
    assert _FROZEN_NOW.strftime("%Y%m%d") in day_calls
    # The month it truncated is still asked for, so nothing past the re-asked
    # days is simply absent.
    assert "202609" in [c["dates"] for c in recorder.calls]


def test_a_capped_month_whose_day_windows_all_fail_keeps_what_it_had() -> None:
    """A truncated month still carries real games: losing the day re-ask must
    not cost the display what the month did return."""
    lib = _library()
    served = _Recorder(_dense_month_events())

    async def days_fail(client: Any, url: str, params: dict[str, str]) -> dict[str, Any]:
        if len(params["dates"]) == 8:
            raise RuntimeError("day window failed")
        return await served(client, url, params)

    lib._get_scoreboard = days_fail  # type: ignore[method-assign]

    with _frozen_clock():
        games = asyncio.run(lib._fetch_league(object(), "college-football", 2, 1))

    assert len(games) == _SCOREBOARD_EVENT_LIMIT


def test_day_windows_cover_only_the_requested_span() -> None:
    from datetime import date

    from libraries.espn_sports.library import _day_windows

    windows = _day_windows("202609", date(2026, 9, 28), date(2026, 10, 3))

    assert windows == ["20260928", "20260929", "20260930"]


def test_a_refresh_after_a_capped_month_still_falls_back_when_the_days_fail() -> None:
    """Skipping the month it already knows is truncated must not cost the
    league its "serve the last good fetch" safety net."""
    lib = _library()
    recorder = _Recorder(_dense_month_events())
    lib._get_scoreboard = recorder  # type: ignore[method-assign]

    with _frozen_clock():
        first = asyncio.run(lib._fetch_league(object(), "college-football", 2, 1))
        lib._scores_cache["college-football"] = (datetime.now(timezone.utc).timestamp(), first)

        async def always_fails(*_a: Any, **_k: Any) -> dict[str, Any]:
            raise RuntimeError("ESPN down")

        lib._get_scoreboard = always_fails  # type: ignore[method-assign]
        games = asyncio.run(lib._fetch_league(object(), "college-football", 2, 1))

    assert [g["id"] for g in games] == [g["id"] for g in first]
