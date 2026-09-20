"""The reported NCAAF failure, end to end: fetch through to the card list.

With college football selected and "next game per team", the module showed
none of the day's final scores and filled up with fixtures five weeks out.
Two faults met:

* A month of college football runs past ESPN's 500-event response cap, and a
  capped response is silently short - the day carrying the just-finished
  games can simply be absent from it.
* Every team in the response qualifies for a "next game", including teams the
  feed only ever shows once (an FCS visitor, a non-conference opponent in a
  conference feed). That lone far-off appearance reads as "their next game".

This exercises the pair together, through ``SportsApp.fetch_data`` with only
ESPN's HTTP responses faked, so neither can come back unnoticed.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

from libraries.espn_sports.library import _SCOREBOARD_EVENT_LIMIT
from tests.framework.clock import frozen_time

# A Saturday night, with the day's games already final. It is the first
# Saturday of a five-Saturday month, so the month's remaining slate alone runs
# past the cap: a truncated response that keeps what it can of the rest of the
# month has no room left for today, which is the shape of the reported fault.
_NOW = datetime.datetime(2026, 10, 3, 23, 0, tzinfo=datetime.timezone.utc)
_SATURDAYS = [datetime.date(2026, 10, 3) + datetime.timedelta(days=7 * i) for i in range(5)]

# Enough games per Saturday that a month of them is over the cap, the way a
# real college-football month is.
_GAMES_PER_SATURDAY = 130


def _event(event_id: str, start: datetime.datetime, state: str, away: str, home: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "status": {"type": {"state": state, "shortDetail": state}},
        "competitions": [
            {
                "date": start.strftime("%Y-%m-%dT%H:%MZ"),
                "competitors": [
                    {"homeAway": "away", "team": {"id": f"a{event_id}", "abbreviation": away}, "score": "17"},
                    {"homeAway": "home", "team": {"id": f"h{event_id}", "abbreviation": home}, "score": "24"},
                ],
            }
        ],
    }


def _season() -> list[dict[str, Any]]:
    """A slate every Saturday, plus FCS visitors seen once, weeks out."""
    events: list[dict[str, Any]] = []
    for week, day in enumerate(_SATURDAYS):
        kickoff = datetime.datetime.combine(
            day, datetime.time(16, 0), tzinfo=datetime.timezone.utc
        )
        for i in range(_GAMES_PER_SATURDAY):
            # Rotate the pairings so a team's opponent changes week to week.
            away = f"T{(2 * i + week) % (2 * _GAMES_PER_SATURDAY):03d}"
            home = f"T{(2 * i + 1 + week) % (2 * _GAMES_PER_SATURDAY):03d}"
            state = "post" if kickoff < _NOW - datetime.timedelta(hours=4) else "pre"
            events.append(_event(f"w{week}g{i}", kickoff, state, away, home))
    # Each FCS side appears exactly once all season, weeks out - inside the
    # month the fetch asks for, so only the horizon keeps it off the screen.
    for i, day in enumerate(_SATURDAYS[3:]):
        kickoff = datetime.datetime.combine(
            day, datetime.time(23, 0), tzinfo=datetime.timezone.utc
        )
        events.append(_event(f"fcs{i}", kickoff, "pre", f"FCS{i}", f"T{i:03d}"))
    return events


class _CappedESPN:
    """Serves the slate, truncating any response past the event cap.

    Which end ESPN drops isn't contractual; this keeps the tail, the
    pessimistic case for a display that wants what just finished.
    """

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.windows: list[str] = []

    async def __call__(self, _client: Any, _url: str, params: dict[str, str]) -> dict[str, Any]:
        token = params["dates"]
        self.windows.append(token)
        if len(token) == 6:
            prefix = f"{token[:4]}-{token[4:]}"
        else:
            prefix = f"{token[:4]}-{token[4:6]}-{token[6:]}"
        matched = [
            e for e in self._events if e["competitions"][0]["date"].startswith(prefix)
        ]
        return {"events": matched[-_SCOREBOARD_EVENT_LIMIT:]}


# One fetch of a full college-football slate costs a second or two (a card
# and a marquee strip per game), and every test here wants the same one.
_fetched: dict[str, Any] = {}


def _run_fetch(config: dict[str, Any]) -> Any:
    if not config and "app" in _fetched:
        return _fetched["app"]
    app = _fetch_fresh(config)
    if not config:
        _fetched["app"] = app
    return app


def _fetch_fresh(config: dict[str, Any]) -> Any:
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    app = SportsApp(
        {"leagues": ["college-football"], "upcoming_game_mode": "next_game", **config},
        SimulatorCanvas(320, 64, _noop_broadcast),
        {},
        {},
    )
    espn = _CappedESPN(_season())
    app._espn._get_scoreboard = espn  # type: ignore[method-assign]

    async def fetch_logos(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {}

    app._espn.fetch_logos = fetch_logos  # type: ignore[method-assign]

    with frozen_time("apps.sports.app.datetime.datetime", _NOW), \
            frozen_time("libraries.espn_sports.library.datetime", _NOW):
        asyncio.run(app.fetch_data())
    return app


def test_todays_final_scores_survive_a_capped_month() -> None:
    app = _run_fetch({})

    finals = [g for g in app._games if g["state"] == "post"]
    assert len(finals) == _GAMES_PER_SATURDAY, "today's finals must all be shown"
    assert app._games[0]["state"] == "post", "the rotation must lead with them"


def test_no_fixture_weeks_away_reaches_the_screen() -> None:
    from apps.sports.app import _NEXT_GAME_MAX_DAYS

    app = _run_fetch({})
    horizon = _NOW + datetime.timedelta(days=_NEXT_GAME_MAX_DAYS + 1)

    upcoming = [g for g in app._games if g["state"] == "pre"]
    assert upcoming, "next-game mode must still show the games to come"
    for game in upcoming:
        start = datetime.datetime.fromisoformat(game["start_time"])
        assert start < horizon, f"{game['id']} is {(start - _NOW).days} days out"
    assert not [g for g in app._games if g["id"].startswith("fcs")]


def test_each_team_gets_one_upcoming_game() -> None:
    app = _run_fetch({})

    upcoming = [g for g in app._games if g["state"] == "pre"]
    # Next Saturday's slate, once each - not that one and the one after.
    assert len(upcoming) == _GAMES_PER_SATURDAY
    starts = {g["start_time"] for g in upcoming}
    assert len(starts) == 1
