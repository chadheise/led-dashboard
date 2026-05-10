from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import httpx

from libraries.base import Library


_SPORT_MAP: dict[str, str] = {
    "nfl": "football",
    "nba": "basketball",
    "mlb": "baseball",
    "nhl": "hockey",
}


class ESPNSportsLibrary(Library):
    id: ClassVar[str] = "espn_sports"
    name: ClassVar[str] = "ESPN Sports"
    description: ClassVar[str] = "Live game scores for NFL, NBA, MLB, and NHL via the ESPN API"
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M7 3v8a5 5 0 0010 0V3H7z"/>'
        '<path d="M7 6H5a1.5 1.5 0 000 3h2"/>'
        '<path d="M17 6h2a1.5 1.5 0 010 3h-2"/>'
        '<line x1="12" y1="16" x2="12" y2="20"/>'
        '<line x1="9" y1="20" x2="15" y2="20"/></svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {}

    async def fetch_scores(self, leagues: list[str]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[self._fetch_league(client, lg) for lg in leagues],
                return_exceptions=True,
            )
        all_games: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, list):
                all_games.extend(result)
        return all_games

    @staticmethod
    async def _fetch_league(
        client: httpx.AsyncClient, league: str
    ) -> list[dict[str, Any]]:
        sport = _SPORT_MAP.get(league, "football")
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
        try:
            resp = await client.get(url)
            data = resp.json()
        except Exception:
            return []
        games: list[dict[str, Any]] = []
        for event in data.get("events", []):
            comp = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue
            home = next(
                (c for c in competitors if c.get("homeAway") == "home"), competitors[0]
            )
            away = next(
                (c for c in competitors if c.get("homeAway") == "away"), competitors[1]
            )
            status_type = event.get("status", {}).get("type", {})
            games.append({
                "home_abbr": home.get("team", {}).get("abbreviation", "???"),
                "away_abbr": away.get("team", {}).get("abbreviation", "???"),
                "home_score": home.get("score", "-"),
                "away_score": away.get("score", "-"),
                "status": status_type.get("shortDetail", "Scheduled"),
                "state": status_type.get("state", "pre"),
            })
        return games
