"""ESPN scoreboard responses with null/missing fields must not crash a fetch.

ESPN returns ``"curatedRank": null`` (rather than omitting the key) for
international/World Cup teams, and can return ``"status": null`` for some
events. ``dict.get(key, default)`` only falls back to ``default`` when the
key is *absent*, not when its value is ``null`` — so naive
``.get("curatedRank", {}).get("current")`` chains raise ``AttributeError``
on these payloads. A single such event used to crash ``_fetch_league`` for
the *whole* league, which ``fetch_scores``'s ``return_exceptions=True`` +
``isinstance(result, list)`` filter then silently dropped, leaving zero
games for that league for the fetch cycle.
"""

from __future__ import annotations

import asyncio
from typing import Any


class _FakeResponse:
    status_code = 200

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._data


class _FakeClient:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    async def get(self, url: str, params: dict[str, str] | None = None) -> _FakeResponse:
        return _FakeResponse(self._data)


def _competitor(home_away: str, abbr: str, score: str = "0", curated_rank: Any = None) -> dict[str, Any]:
    return {
        "homeAway": home_away,
        "team": {"abbreviation": abbr, "displayName": abbr},
        "score": score,
        "curatedRank": curated_rank,
    }


def test_fetch_league_handles_null_curated_rank_and_status() -> None:
    from libraries.espn_sports.library import ESPNSportsLibrary

    data = {
        "events": [
            {
                "id": "1",
                "status": None,
                "competitions": [
                    {
                        "competitors": [
                            _competitor("home", "FRA"),
                            _competitor("away", "GER"),
                        ],
                    }
                ],
            }
        ]
    }

    games = asyncio.run(ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world"))

    assert len(games) == 1
    game = games[0]
    assert game["home_rank"] is None
    assert game["away_rank"] is None
    assert game["status"] == "Scheduled"
    assert game["state"] == "pre"


def test_fetch_league_skips_malformed_event_but_returns_others() -> None:
    from libraries.espn_sports.library import ESPNSportsLibrary

    data = {
        "events": [
            # Malformed: competitors are not dicts, so `.get("homeAway")` blows up.
            {
                "id": "bad",
                "status": {"type": {"shortDetail": "Final", "state": "post"}},
                "competitions": [{"competitors": [1, 2]}],
            },
            # Well-formed event after the malformed one.
            {
                "id": "good",
                "status": {"type": {"shortDetail": "Final", "state": "post"}},
                "competitions": [
                    {
                        "competitors": [
                            _competitor("home", "BOS", score="3"),
                            _competitor("away", "NYY", score="1"),
                        ],
                    }
                ],
            },
        ]
    }

    games = asyncio.run(ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "mlb"))

    assert [g["id"] for g in games] == ["good"]


def test_flag_league_maps_saudi_arabia_to_flag() -> None:
    """ESPN abbreviates Saudi Arabia as the FIFA code ``KSA`` (not ``SAU``);
    the flag lookup must recognize it so a flag is shown next to the team."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    data = {
        "events": [
            {
                "id": "1",
                "status": {"type": {"shortDetail": "Scheduled", "state": "pre"}},
                "competitions": [
                    {
                        "competitors": [
                            _competitor("home", "KSA"),
                            _competitor("away", "ARG"),
                        ],
                    }
                ],
            }
        ]
    }

    games = asyncio.run(ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world"))

    assert games[0]["home_logo_url"] == "https://flagcdn.com/w80/sa.png"
    assert games[0]["away_logo_url"] == "https://flagcdn.com/w80/ar.png"
