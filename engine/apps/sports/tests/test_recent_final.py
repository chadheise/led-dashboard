"""A favorite team's just-finished game must reach the display.

End-to-end over ``fetch_data``: an NFL favorite whose game ended a few hours
ago, with the default "next game per team" mode looking a month ahead. ESPN
returns only part of an over-long span, so the fetch asks a calendar month at
a time - otherwise the month of upcoming fixtures crowds the final score out
of the response and the module shows nothing but the next scheduled game.
"""

from __future__ import annotations

import asyncio
import datetime
import re
from typing import Any

_DEFAULT_RESPONSE_CAP = 25  # what ESPN returns when a request omits `limit`


def _event(event_id: str, start: datetime.datetime, state: str, away: str, home: str,
           away_score: str = "0", home_score: str = "0") -> dict[str, Any]:
    return {
        "id": event_id,
        "status": {"type": {"state": state, "shortDetail": "Final" if state == "post" else "Sun"}},
        "competitions": [
            {
                "date": start.strftime("%Y-%m-%dT%H:%MZ"),
                "competitors": [
                    {"homeAway": "away", "team": {"id": "1", "abbreviation": away}, "score": away_score},
                    {"homeAway": "home", "team": {"id": "2", "abbreviation": home}, "score": home_score},
                ],
            }
        ],
    }


def _nfl_season(now: datetime.datetime) -> list[dict[str, Any]]:
    """One just-finished Seahawks game plus a month of upcoming fixtures."""
    events = [_event("sea_final", now - datetime.timedelta(hours=6), "post", "SEA", "ARI", "27", "17")]
    for week in range(1, 5):
        kickoff = now + datetime.timedelta(days=7 * week)
        events.append(_event(f"sea_w{week}", kickoff, "pre", "SEA", "SF"))
        # The rest of the league's slate that week, filling the response.
        for i in range(15):
            events.append(
                _event(f"w{week}_g{i}", kickoff + datetime.timedelta(hours=i), "pre", f"A{i}", f"B{i}")
            )
    return events


async def _espn_scoreboard(events: list[dict[str, Any]]):
    async def get(_client: Any, _url: str, params: dict[str, str]) -> dict[str, Any]:
        # ESPN's `dates` takes one YYYYMM; a range is rejected outright.
        dates = params["dates"]
        assert re.fullmatch(r"\d{6}", dates), f"unsupported dates value: {dates}"
        year, month = int(dates[:4]), int(dates[4:])
        start = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(
            year + (month == 12), (month % 12) + 1, 1, tzinfo=datetime.timezone.utc
        )
        matched = [
            e
            for e in events
            if start
            <= datetime.datetime.fromisoformat(
                e["competitions"][0]["date"].replace("Z", "+00:00")
            )
            < end
        ]
        limit = int(params.get("limit", _DEFAULT_RESPONSE_CAP))
        return {"events": matched[-limit:]}

    return get


def _make_app() -> Any:
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    return SportsApp(
        {"leagues": [], "favorite_teams": ["nfl:SEA"]},
        SimulatorCanvas(320, 64, _noop_broadcast),
        {},
        {},
    )


def test_favorite_teams_recent_final_shows_alongside_its_next_game() -> None:
    app = _make_app()
    now = datetime.datetime.now(datetime.timezone.utc)

    async def run() -> None:
        app._espn._get_scoreboard = await _espn_scoreboard(_nfl_season(now))  # type: ignore[method-assign]

        async def no_logos(_games: Any, _size: Any) -> dict[str, Any]:
            return {}

        app._espn.fetch_logos = no_logos  # type: ignore[method-assign]
        await app.fetch_data()

    asyncio.run(run())

    shown = {g["id"]: g for g in app._games}
    assert "sea_final" in shown, "the game that just finished is missing from the display"
    assert shown["sea_final"]["state"] == "post"
    assert (shown["sea_final"]["away_score"], shown["sea_final"]["home_score"]) == ("27", "17")
    # Still only each favorite's single soonest upcoming game, as configured -
    # and the soonest one, not whichever fixture happened to fit in the response.
    assert set(shown) == {"sea_final", "sea_w1"}
