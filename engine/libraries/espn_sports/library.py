from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar

import httpx
from PIL import Image

from libraries.base import Library


_LEAGUES_FILE = Path(__file__).parent / "leagues.json"
_LEAGUES: list[dict[str, str]] = json.loads(_LEAGUES_FILE.read_text())
_LEAGUE_BY_ID: dict[str, dict[str, str]] = {e["id"]: e for e in _LEAGUES}

_LOGO_TTL_SECONDS: float = 30 * 24 * 3600   # 30 days
_TEAMS_TTL_SECONDS: float = 30 * 24 * 3600  # 30 days


class ESPNSportsLibrary(Library):
    id: ClassVar[str] = "espn_sports"
    name: ClassVar[str] = "ESPN Sports"
    description: ClassVar[str] = (
        "Live game scores for NFL, NBA, MLB, NHL, soccer, and more via the ESPN API"
    )
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

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._logo_cache: dict[str, Image.Image | None] = {}
        data_dir = Path(__file__).parent.parent.parent / "data"
        self._logo_dir = data_dir / "logos"
        self._logo_dir.mkdir(parents=True, exist_ok=True)
        self._teams_dir = data_dir / "teams"
        self._teams_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def fetch_scores(
        self,
        leagues: list[str],
        favorite_teams: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[self._fetch_league(client, lg) for lg in leagues],
                return_exceptions=True,
            )
        all_games: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, list):
                all_games.extend(result)

        if favorite_teams:
            all_games = [
                g for g in all_games if self._matches_favorites(g, favorite_teams)
            ]
        return all_games

    async def fetch_teams(self, league: str) -> list[dict[str, Any]]:
        # Disk-backed cache: safe filename from league id (e.g. "eng.1" → "eng_1")
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", league)
        cache_path = self._teams_dir / f"{safe}.json"
        now = time.time()
        if cache_path.exists() and (now - cache_path.stat().st_mtime) < _TEAMS_TTL_SECONDS:
            try:
                cached = json.loads(cache_path.read_text())
                if cached:
                    return cached
            except Exception:
                pass

        teams = await self._fetch_teams_fresh(league)

        try:
            cache_path.write_text(json.dumps(teams))
        except Exception:
            pass
        return teams

    async def _fetch_teams_fresh(self, league: str) -> list[dict[str, Any]]:
        if league == "college-football":
            return await self._fetch_ncaaf_teams()
        entry = _LEAGUE_BY_ID.get(league, {"sport": "football", "league": league})
        base_url = (
            f"https://site.api.espn.com/apis/site/v2/sports"
            f"/{entry['sport']}/{entry['league']}/teams"
        )
        teams: list[dict[str, Any]] = []
        page = 1
        async with httpx.AsyncClient(timeout=10.0) as client:
            while True:
                try:
                    resp = await client.get(base_url, params={"limit": 50, "page": page})
                    data = resp.json()
                except Exception:
                    break
                page_teams = (
                    data.get("sports", [{}])[0]
                    .get("leagues", [{}])[0]
                    .get("teams", [])
                )
                if not page_teams:
                    break
                for item in page_teams:
                    t = item.get("team", {})
                    logos = t.get("logos", [])
                    teams.append(
                        {
                            "id": t.get("id", ""),
                            "abbreviation": t.get("abbreviation", ""),
                            "display_name": t.get("displayName", ""),
                            "logo_url": logos[0].get("href") if logos else None,
                            "color": t.get("color", ""),
                            "conference": None,
                        }
                    )
                if len(page_teams) < 50:
                    break
                page += 1
        return sorted(teams, key=lambda t: t["display_name"])

    async def _fetch_ncaaf_teams(self) -> list[dict[str, Any]]:
        """
        Fetch FBS teams with accurate conference assignments by:
        1. Pulling all teams from the site API (id → team data map).
        2. Using the standings endpoint per conference (works for 10/11 FBS conferences).
        3. Using the ESPN core API for Sun Belt (standings endpoint returns nothing for it).
        Returns only FBS teams — non-FBS teams don't appear in the college-football scoreboard.
        """
        _NCAAF_CONFERENCES_FILE = Path(__file__).parent / "ncaaf_conferences.json"
        conferences: list[dict[str, str]] = json.loads(_NCAAF_CONFERENCES_FILE.read_text())

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Fetch all teams and conference data concurrently
            teams_task = asyncio.create_task(self._fetch_all_ncaaf_team_data(client))
            conf_tasks = [
                asyncio.create_task(self._fetch_conf_abbrs(client, c["id"], c["name"]))
                for c in conferences
            ]
            id_to_team, conf_results = await asyncio.gather(
                teams_task,
                asyncio.gather(*conf_tasks, return_exceptions=True),
            )

        # Build abbreviation → conference map from standings (most conferences)
        abbr_to_conf: dict[str, str] = {}
        for result in conf_results:
            if isinstance(result, dict):
                abbr_to_conf.update(result)

        # Sun Belt: standings returns nothing, so use core API team IDs
        sun_belt_conf = next((c for c in conferences if c["name"] == "Sun Belt"), None)
        if sun_belt_conf:
            async with httpx.AsyncClient(timeout=10.0) as client:
                sun_belt_ids = await self._fetch_conf_team_ids_core(client, sun_belt_conf["id"])
            for tid in sun_belt_ids:
                team = id_to_team.get(tid)
                if team and team["abbreviation"] not in abbr_to_conf:
                    abbr_to_conf[team["abbreviation"]] = "Sun Belt"

        # Assign conference and return only FBS teams (those with a conference assignment)
        fbs_teams: list[dict[str, Any]] = []
        for team in id_to_team.values():
            abbr = team["abbreviation"]
            conf = abbr_to_conf.get(abbr)
            if conf is None:
                continue  # non-FBS — skip
            fbs_teams.append({**team, "conference": conf})

        return sorted(fbs_teams, key=lambda t: (t["conference"], t["display_name"]))

    @staticmethod
    async def _fetch_all_ncaaf_team_data(
        client: httpx.AsyncClient,
    ) -> dict[str, dict[str, Any]]:
        """Return {team_id: team_dict} for all teams in the college-football endpoint."""
        base = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams"
        id_to_team: dict[str, dict[str, Any]] = {}
        page = 1
        while True:
            try:
                resp = await client.get(base, params={"limit": 50, "page": page})
                data = resp.json()
            except Exception:
                break
            page_teams = (
                data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
            )
            if not page_teams:
                break
            for item in page_teams:
                t = item.get("team", {})
                tid = t.get("id", "")
                logos = t.get("logos", [])
                id_to_team[tid] = {
                    "id": tid,
                    "abbreviation": t.get("abbreviation", ""),
                    "display_name": t.get("displayName", ""),
                    "logo_url": logos[0].get("href") if logos else None,
                    "color": t.get("color", ""),
                    "conference": None,
                }
            if len(page_teams) < 50:
                break
            page += 1
        return id_to_team

    @staticmethod
    async def _fetch_conf_abbrs(
        client: httpx.AsyncClient, group_id: str, conf_name: str
    ) -> dict[str, str]:
        """Return {abbreviation: conf_name} from the standings endpoint for one conference."""
        url = (
            "https://site.api.espn.com/apis/v2/sports/football"
            f"/college-football/standings?group={group_id}"
        )
        try:
            resp = await client.get(url)
            data = resp.json()
        except Exception:
            return {}
        entries = data.get("standings", {}).get("entries", [])
        return {e["team"]["abbreviation"]: conf_name for e in entries if "team" in e}

    @staticmethod
    async def _fetch_conf_team_ids_core(
        client: httpx.AsyncClient, group_id: str
    ) -> list[str]:
        """Return team IDs for a conference via the ESPN core API (used for Sun Belt)."""
        url = (
            "https://sports.core.api.espn.com/v2/sports/football"
            f"/leagues/college-football/seasons/2025/types/2/groups/{group_id}/teams?limit=50"
        )
        try:
            resp = await client.get(url)
            data = resp.json()
        except Exception:
            return []
        ids: list[str] = []
        for item in data.get("items", []):
            ref = item.get("$ref", "")
            m = re.search(r"/teams/(\d+)", ref)
            if m:
                ids.append(m.group(1))
        return ids

    async def fetch_logos(
        self,
        games: list[dict[str, Any]],
        target_size: tuple[int, int],
    ) -> dict[str, Image.Image | None]:
        urls = {
            url
            for game in games
            for url in [game.get("home_logo_url"), game.get("away_logo_url")]
            if url
        }
        if not urls:
            return {}
        results = await asyncio.gather(
            *[self.fetch_logo(u, target_size) for u in urls],
            return_exceptions=True,
        )
        return {
            url: (img if isinstance(img, Image.Image) else None)
            for url, img in zip(urls, results)
        }

    async def fetch_logo(
        self, url: str, target_size: tuple[int, int]
    ) -> Image.Image | None:
        if url in self._logo_cache:
            img = self._logo_cache[url]
            if img is None:
                return None
            return img.resize(target_size, Image.LANCZOS)

        cache_path = self._logo_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.png"
        now = time.time()

        if cache_path.exists():
            age = now - cache_path.stat().st_mtime
            if age < _LOGO_TTL_SECONDS:
                try:
                    img = Image.open(cache_path).convert("RGBA")
                    self._logo_cache[url] = img
                    return img.resize(target_size, Image.LANCZOS)
                except Exception:
                    pass  # fall through to re-download

        downloaded = await self._download_logo(url)
        if downloaded is not None:
            try:
                downloaded.save(cache_path, format="PNG")
            except Exception:
                pass
            self._logo_cache[url] = downloaded
            return downloaded.resize(target_size, Image.LANCZOS)

        # Download failed — use stale disk file as fallback
        if cache_path.exists():
            try:
                img = Image.open(cache_path).convert("RGBA")
                self._logo_cache[url] = img
                return img.resize(target_size, Image.LANCZOS)
            except Exception:
                pass

        self._logo_cache[url] = None
        return None

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _download_logo(url: str) -> Image.Image | None:
        try:
            async with httpx.AsyncClient(
                timeout=5.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return Image.open(BytesIO(resp.content)).convert("RGBA")
        except Exception:
            pass
        return None

    @staticmethod
    def _matches_favorites(game: dict[str, Any], favorites: list[str]) -> bool:
        league = game.get("league", "")
        for fav in favorites:
            parts = fav.split(":", 1)
            if len(parts) != 2:
                continue
            fav_league, fav_abbr = parts
            if fav_league == league and fav_abbr in (
                game.get("home_abbr", ""),
                game.get("away_abbr", ""),
            ):
                return True
        return False

    @staticmethod
    async def _fetch_league(
        client: httpx.AsyncClient,
        league: str,
    ) -> list[dict[str, Any]]:
        entry = _LEAGUE_BY_ID.get(league, {"sport": "football", "league": league})
        sport = entry["sport"]
        league_path = entry["league"]
        filter_mode: str | None = entry.get("filter")  # e.g. "top25"
        url = (
            f"https://site.api.espn.com/apis/site/v2/sports"
            f"/{sport}/{league_path}/scoreboard"
        )
        params: dict[str, str] = {}
        groups = entry.get("groups")
        if groups:
            params["groups"] = groups
        try:
            resp = await client.get(url, params=params)
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

            home_team = home.get("team", {})
            away_team = away.get("team", {})

            series = comp.get("series", {})
            series_summary = series.get("summary") if series else None

            # Team ranking (for NCAAF top-25 filtering)
            home_rank_raw = home.get("curatedRank", {}).get("current")
            away_rank_raw = away.get("curatedRank", {}).get("current")
            home_rank: int | None = int(home_rank_raw) if home_rank_raw else None
            away_rank: int | None = int(away_rank_raw) if away_rank_raw else None

            # Conference (for display and post-fetch filtering)
            home_groups = home_team.get("groups", [])
            away_groups = away_team.get("groups", [])
            home_conf: str | None = home_groups[0].get("name") if home_groups else None
            away_conf: str | None = away_groups[0].get("name") if away_groups else None

            games.append(
                {
                    "league": league,
                    "sport": sport,
                    "home_abbr": home_team.get("abbreviation", "???"),
                    "away_abbr": away_team.get("abbreviation", "???"),
                    "home_name": home_team.get("displayName", ""),
                    "away_name": away_team.get("displayName", ""),
                    "home_score": home.get("score", "-"),
                    "away_score": away.get("score", "-"),
                    "home_color": home_team.get("color", "444444"),
                    "away_color": away_team.get("color", "444444"),
                    "home_logo_url": home_team.get("logo"),
                    "away_logo_url": away_team.get("logo"),
                    "status": status_type.get("shortDetail", "Scheduled"),
                    "state": status_type.get("state", "pre"),
                    "series_summary": series_summary,
                    "start_time": comp.get("date"),
                    "home_rank": home_rank,
                    "away_rank": away_rank,
                    "home_conf": home_conf,
                    "away_conf": away_conf,
                }
            )
        if filter_mode == "top25":
            games = [
                g for g in games
                if (g.get("home_rank") or 999) <= 25
                or (g.get("away_rank") or 999) <= 25
            ]
        return games
