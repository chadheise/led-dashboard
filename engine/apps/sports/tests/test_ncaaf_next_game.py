"""The reported NCAAF failure, end to end: fetch through to the card list.

The setup is the one it was reported against - the NCAAF Top 25 feed with
favorite teams. None of the day's final scores reached the screen, and
fixtures five weeks out (10/16, 10/23) sat there instead. Two faults met:

* A month of college football runs past ESPN's 500-event response cap - every
  division plays the same Saturday - and a capped response is silently short,
  so the day whose scores had just gone final could simply be absent from it.
* Every team in the response could claim a "next game", including teams the
  feed only ever shows in passing. A Top 25 feed carries the unranked
  opponent of each ranked team, and each of those appears in it about once a
  season. That lone fixture, weeks out, read as "their next game" - though
  the ranked team on the other side of it plays on Saturday.

Both are exercised here through ``SportsApp.fetch_data`` with only ESPN's
HTTP responses faked, so neither can come back unnoticed.
"""

from __future__ import annotations

import asyncio
import datetime
from collections import Counter
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
_RANKED = {f"T{i:03d}": i + 1 for i in range(25)}

# A favorite on a bye, playing a ranked team a fortnight out - its one
# appearance in the Top 25 feed, exactly like the unranked opponents that no
# longer reach the screen. Being favorited is the difference.
_FAVORITE = "UW"
_FAVORITE_DAY = _SATURDAYS[2]


def _event(
    event_id: str, start: datetime.datetime, state: str, away: str, home: str
) -> dict[str, Any]:
    def _competitor(side: str, abbr: str, score: str) -> dict[str, Any]:
        rank = _RANKED.get(abbr)
        return {
            "homeAway": side,
            "team": {"id": f"{side}{event_id}", "abbreviation": abbr},
            "score": score,
            "curatedRank": {"current": rank} if rank else {},
        }

    return {
        "id": event_id,
        "status": {"type": {"state": state, "shortDetail": state}},
        "competitions": [
            {
                "date": start.strftime("%Y-%m-%dT%H:%MZ"),
                "competitors": [
                    _competitor("away", away, "17"),
                    _competitor("home", home, "24"),
                ],
            }
        ],
    }


def _season() -> list[dict[str, Any]]:
    """A full slate every Saturday, ranked teams scattered through it."""
    events: list[dict[str, Any]] = []
    for week, day in enumerate(_SATURDAYS):
        kickoff = datetime.datetime.combine(
            day, datetime.time(16, 0), tzinfo=datetime.timezone.utc
        )
        # Rotate the pairings so a ranked team faces a different opponent each
        # week - which is what makes an unranked team's appearance in the Top
        # 25 feed a one-off.
        rotation = [f"T{(i + week) % (2 * _GAMES_PER_SATURDAY):03d}" for i in range(2 * _GAMES_PER_SATURDAY)]
        state = "post" if kickoff < _NOW - datetime.timedelta(hours=4) else "pre"
        for i in range(_GAMES_PER_SATURDAY):
            events.append(
                _event(f"w{week}g{i}", kickoff, state, rotation[2 * i], rotation[2 * i + 1])
            )
    # The favorite's single appearance, against a ranked team.
    events.append(
        _event(
            "favorite_after_bye",
            datetime.datetime.combine(
                _FAVORITE_DAY, datetime.time(23, 0), tzinfo=datetime.timezone.utc
            ),
            "pre",
            _FAVORITE,
            "T001",
        )
    )
    return events


def _is_top25(event: dict[str, Any]) -> bool:
    return any(
        c["team"]["abbreviation"] in _RANKED
        for c in event["competitions"][0]["competitors"]
    )


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


# One fetch of a full college-football slate costs a second or two (a card and
# a marquee strip per game), and every test here wants the same one.
_fetched: dict[str, Any] = {}


def _run_fetch() -> Any:
    """The reported configuration: the Top 25 feed plus a favorite team."""
    if "app" in _fetched:
        return _fetched["app"]

    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    app = SportsApp(
        {
            "leagues": ["ncaaf-top25"],
            "favorite_teams": [f"college-football:{_FAVORITE}"],
            "upcoming_game_mode": "next_game",
        },
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
    _fetched["app"] = app
    return app


def _day(game: dict[str, Any]) -> datetime.date:
    return datetime.datetime.fromisoformat(game["start_time"]).date()


def test_todays_final_scores_survive_a_capped_month() -> None:
    app = _run_fetch()

    expected = {
        e["id"]
        for e in _season()
        if _is_top25(e) and e["competitions"][0]["date"].startswith("2026-10-03")
    }
    finals = {g["id"] for g in app._games if g["state"] == "post"}
    assert finals == expected, "every one of today's Top 25 results must be shown"
    assert app._games[0]["state"] == "post", "the rotation must lead with them"


def test_only_the_soonest_fixtures_reach_the_screen() -> None:
    """Every ranked team plays next Saturday, so that is every one of their
    next games - and the Saturdays after it belong to nobody yet."""
    app = _run_fetch()

    upcoming = [g for g in app._games if g["state"] == "pre"]
    league_games = [g for g in upcoming if g["id"] != "favorite_after_bye"]
    assert league_games, "next-game mode must still show the games to come"
    assert {_day(g) for g in league_games} == {_SATURDAYS[1]}


def test_no_team_appears_in_two_upcoming_games() -> None:
    """One upcoming card per team - the complaint that started this.

    The single exception is whoever a favorite plays later: showing the
    favorite's game necessarily shows its opponent, who already has a card
    of its own for the game it plays first.
    """
    app = _run_fetch()

    upcoming = [g for g in app._games if g["state"] == "pre"]
    counts = Counter(
        abbr for g in upcoming for abbr in (g["home_abbr"], g["away_abbr"])
    )
    repeated = {abbr for abbr, n in counts.items() if n > 1}
    exempt = next(g for g in upcoming if g["id"] == "favorite_after_bye")
    assert repeated <= {exempt["home_abbr"], exempt["away_abbr"]}


def test_a_favorite_on_a_bye_still_shows_its_next_game() -> None:
    """The one fixture shown though its opponent plays first, because it was
    asked for by name - and asked for against the base league, while the Top
    25 feed labels the same game with its own id."""
    app = _run_fetch()

    favorite = [g for g in app._games if _FAVORITE in (g["home_abbr"], g["away_abbr"])]
    assert [g["id"] for g in favorite] == ["favorite_after_bye"]
    assert _day(favorite[0]) == _FAVORITE_DAY
