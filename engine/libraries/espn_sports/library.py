from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar

import httpx
from PIL import Image

from libraries.base import Library

logger = logging.getLogger(__name__)


_LEAGUES_FILE = Path(__file__).parent / "leagues.json"
_LEAGUES: list[dict[str, str]] = json.loads(_LEAGUES_FILE.read_text())
_LEAGUE_BY_ID: dict[str, dict[str, str]] = {e["id"]: e for e in _LEAGUES}

# Leagues where team logos are replaced with national flags
_FLAG_LEAGUES: set[str] = {e["id"] for e in _LEAGUES if e.get("use_flags")}

# ESPN/FIFA abbreviation → ISO 3166-1 alpha-2 code for flagcdn.com
_FIFA_FLAGS: dict[str, str] = {
    k: v for k, v in json.loads(
        (Path(__file__).parent / "fifa_flags.json").read_text()
    ).items()
    if k != "comment"
}

_FLAGCDN_BASE = "https://flagcdn.com/w80/{code}.png"

_LOGO_TTL_SECONDS: float = 30 * 24 * 3600   # 30 days
_TEAMS_TTL_SECONDS: float = 30 * 24 * 3600  # 30 days

# How long the last successful scoreboard fetch may stand in for a failed one.
# Long enough to ride out transient API errors between 60s refresh cycles,
# short enough that a real outage doesn't show hours-stale live scores.
_SCORES_FALLBACK_TTL_SECONDS: float = 15 * 60

# Connect fast-fails so an unreachable host doesn't tie up the gather, while
# read gets extra headroom for large multi-day payloads (e.g. a 14+ day
# World Cup date range) that can take longer than a typical single-day fetch.
_SCOREBOARD_TIMEOUT = httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0)

# One immediate retry absorbs a one-off connection blip (reset, DNS hiccup)
# without waiting a full refresh cycle and falling back to cached/empty games.
_FETCH_RETRIES = 1
_FETCH_RETRY_DELAY_SECONDS = 0.25


def _flag_url(abbr: str) -> str | None:
    code = _FIFA_FLAGS.get(abbr.upper())
    return _FLAGCDN_BASE.format(code=code) if code else None


class ESPNSportsLibrary(Library):
    id: ClassVar[str] = "espn_sports"
    name: ClassVar[str] = "ESPN Sports"
    description: ClassVar[str] = (
        "Live game scores for NFL, NBA, MLB, NHL, soccer, and more via the ESPN API"
    )
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 554 137" fill="currentColor">'
        '<path d="M181.064.348c-20.608-.027-34.256 10.836-36.176 27.079a1600.065 1600.065 0 0 1-1.384 11.257H411.64'
        "s.504-3.957.896-7.133C414.552 15.188 407.6.35 382.312.35v.002S191.928.36 181.064.348z"
        "M17.424.353l-4.706 38.331h121.6l4.688-38.33H17.422h.002z"
        "m408.184 0l-4.696 38.331h131.824s.16-1.386.744-5.898C556.688 7.626 540.456.353 524.784.353h-99.176z"
        "m-6.512 52.926l-10.272 83.656 45.48-.016 10.28-83.624-45.488-.018v.002z"
        "m86.4 0l-10.288 83.656 45.48-.016 10.28-83.624-45.472-.018v.002z"
        "m-494.552.012L.654 136.939h121.592l4.48-36.288-76.138-.008 1.926-15.648h76.108l3.896-31.702H10.95l-.006-.002z"
        "m130.776 0c-3.336 21.832 7.592 31.701 23.08 31.701 8.424 0 61.52-.024 61.52-.024l-1.92 15.672"
        "-88.488.008-4.456 36.288s96.336.032 100.24 0c3.224-.232 25.76-.848 33.432-19.28"
        " 2.488-5.984 4.688-27.44 5.304-31.944 3.544-26.16-14.568-32.397-28.832-32.397"
        "-7.864 0-84.352-.024-99.88-.024z"
        'm141.552 0L273 136.939h45.456l6.4-51.944h57.096c16.192 0 24.896-8.706 26.512-20.397'
        'a430.97 430.97 0 0 0 1.4-11.305H283.272v-.002z"/>'
        '</svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {}

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._logo_cache: dict[str, Image.Image | None] = {}
        # league id → (fetched_at, games): fallback when a fetch fails
        self._scores_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        # Reused across fetch cycles so the ~60s refresh loop doesn't pay a
        # fresh TCP/TLS handshake to ESPN every time.
        self._client: httpx.AsyncClient | None = None
        data_dir = Path(__file__).parent.parent.parent / "data" / "espn_sports"
        self._logo_dir = data_dir / "logos"
        self._logo_dir.mkdir(parents=True, exist_ok=True)
        self._teams_dir = data_dir / "teams"
        self._teams_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def fetch_scores(
        self,
        leagues: list[str],
        favorite_teams: list[str] | None = None,
        days_ahead: int = 1,
        days_behind: int = 1,
    ) -> list[dict[str, Any]]:
        client = self._get_client()
        results = await asyncio.gather(
            *[self._fetch_league(client, lg, days_ahead, days_behind) for lg in leagues],
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
        # Map each URL to (league, abbr) using the first game that mentions it.
        url_to_meta: dict[str, tuple[str, str]] = {}
        for game in games:
            league = game.get("league", "unknown")
            for url_key, abbr_key in [("home_logo_url", "home_abbr"), ("away_logo_url", "away_abbr")]:
                url = game.get(url_key)
                abbr = game.get(abbr_key, "")
                if url and url not in url_to_meta:
                    url_to_meta[url] = (league, abbr)

        if not url_to_meta:
            return {}

        results = await asyncio.gather(
            *[self.fetch_logo(url, target_size, league, abbr)
              for url, (league, abbr) in url_to_meta.items()],
            return_exceptions=True,
        )
        return {
            url: (img if isinstance(img, Image.Image) else None)
            for url, img in zip(url_to_meta.keys(), results)
        }

    async def fetch_logo(
        self,
        url: str,
        target_size: tuple[int, int],
        league: str = "unknown",
        team_abbr: str = "",
    ) -> Image.Image | None:
        if url in self._logo_cache:
            img = self._logo_cache[url]
            if img is None:
                return None
            return self._scale_down(img, target_size)

        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", team_abbr) if team_abbr else None
        if not safe_name:
            safe_name = hashlib.sha256(url.encode()).hexdigest()[:12]
        league_dir = self._logo_dir / league
        league_dir.mkdir(parents=True, exist_ok=True)
        cache_path = league_dir / f"{safe_name}.png"
        now = time.time()

        if cache_path.exists():
            age = now - cache_path.stat().st_mtime
            if age < _LOGO_TTL_SECONDS:
                try:
                    img = Image.open(cache_path).convert("RGBA")
                    self._logo_cache[url] = img
                    return self._scale_down(img, target_size)
                except Exception:
                    pass  # fall through to re-download

        downloaded = await self._download_logo(url)
        if downloaded is not None:
            try:
                downloaded.save(cache_path, format="PNG")
            except Exception:
                pass
            self._logo_cache[url] = downloaded
            return self._scale_down(downloaded, target_size)

        # Download failed — use stale disk file as fallback
        if cache_path.exists():
            try:
                img = Image.open(cache_path).convert("RGBA")
                self._logo_cache[url] = img
                return self._scale_down(img, target_size)
            except Exception:
                pass

        self._logo_cache[url] = None
        return None

    @staticmethod
    def _scale_down(img: Image.Image, target_size: tuple[int, int]) -> Image.Image:
        """Scale img to fit within target_size, preserving aspect ratio. Never upscales."""
        iw, ih = img.size
        tw, th = target_size
        if iw <= tw and ih <= th:
            return img
        scale = min(tw / iw, th / ih)
        return img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=_SCOREBOARD_TIMEOUT)
        return self._client

    @staticmethod
    async def _get_scoreboard(
        client: httpx.AsyncClient, url: str, params: dict[str, str]
    ) -> dict[str, Any]:
        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(_FETCH_RETRIES + 1):
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_exc = exc
                if attempt < _FETCH_RETRIES:
                    await asyncio.sleep(_FETCH_RETRY_DELAY_SECONDS)
        raise last_exc

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

    async def _fetch_league(
        self,
        client: httpx.AsyncClient,
        league: str,
        days_ahead: int = 1,
        days_behind: int = 1,
    ) -> list[dict[str, Any]]:
        entry = _LEAGUE_BY_ID.get(league, {"sport": "football", "league": league})
        sport = entry["sport"]
        league_path = entry["league"]
        use_flags: bool = league in _FLAG_LEAGUES
        filter_mode: str | None = entry.get("filter")  # e.g. "top25"
        url = (
            f"https://site.api.espn.com/apis/site/v2/sports"
            f"/{sport}/{league_path}/scoreboard"
        )
        params: dict[str, str] = {}
        groups = entry.get("groups")
        if groups:
            params["groups"] = groups
        # Without an explicit date range, ESPN's scoreboard endpoint only
        # returns a narrow default window (often just "today"), which can
        # hide most of a tournament's upcoming fixtures (e.g. World Cup).
        today = datetime.now(timezone.utc).date()
        start_date = today - timedelta(days=max(0, days_behind))
        end_date = today + timedelta(days=max(0, days_ahead))
        params["dates"] = f"{start_date:%Y%m%d}-{end_date:%Y%m%d}"
        try:
            data = await self._get_scoreboard(client, url, params)
        except Exception as exc:
            # A transient API failure must not blank the display: serve the
            # last successful fetch for this league while it is still fresh.
            cached = self._scores_cache.get(league)
            if cached is not None and time.time() - cached[0] < _SCORES_FALLBACK_TTL_SECONDS:
                logger.warning(
                    "Scoreboard fetch failed for %s (%s); serving cached games", league, exc
                )
                return [dict(g) for g in cached[1]]
            logger.warning(
                "Scoreboard fetch failed for %s (%s); no fresh cache available", league, exc
            )
            return []

        games: list[dict[str, Any]] = []
        for event in data.get("events", []):
            try:
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
                status_type = (event.get("status") or {}).get("type") or {}

                home_team = home.get("team", {})
                away_team = away.get("team", {})

                series = comp.get("series", {})
                series_summary = series.get("summary") if series else None

                # Team ranking (for NCAAF top-25 filtering)
                home_rank_raw = (home.get("curatedRank") or {}).get("current")
                away_rank_raw = (away.get("curatedRank") or {}).get("current")
                home_rank: int | None = int(home_rank_raw) if home_rank_raw else None
                away_rank: int | None = int(away_rank_raw) if away_rank_raw else None

                # Conference (for display and post-fetch filtering)
                home_groups = home_team.get("groups", [])
                away_groups = away_team.get("groups", [])
                home_conf: str | None = home_groups[0].get("name") if home_groups else None
                away_conf: str | None = away_groups[0].get("name") if away_groups else None

                # In-game situational data (football: down/distance/possession; baseball: runners/outs)
                situation = comp.get("situation") or {}

                # Most recent play, when the scoreboard includes one (live games).
                # Normalized defensively — celebration detection degrades gracefully
                # when ESPN omits it for a sport or game.
                lp = situation.get("lastPlay") or {}
                last_play: dict[str, str] | None = None
                if lp:
                    last_play = {
                        "id": str(lp.get("id") or ""),
                        "type_text": str(((lp.get("type") or {}).get("text")) or ""),
                        "text": str(lp.get("text") or ""),
                        "team_id": str(((lp.get("team") or {}).get("id")) or ""),
                    }

                # Team records (for football display)
                home_record: str | None = next(
                    (r.get("summary") for r in home.get("records", []) if r.get("name") == "overall"),
                    None,
                )
                away_record: str | None = next(
                    (r.get("summary") for r in away.get("records", []) if r.get("name") == "overall"),
                    None,
                )

                # Match context note (soccer: group name or knockout round)
                notes = comp.get("notes") or []
                match_note: str = notes[0].get("headline", "") if notes else ""

                # Soccer: goal times from match details and group standings points
                home_goals: list[str] = []
                away_goals: list[str] = []
                home_points: int | None = None
                away_points: int | None = None
                if sport == "soccer":
                    ht_id = home_team.get("id", "")
                    at_id = away_team.get("id", "")
                    for detail in comp.get("details") or []:
                        d_type = ((detail.get("type") or {}).get("text") or "").lower()
                        if "goal" not in d_type and "penalty" not in d_type:
                            continue
                        clock_val = ((detail.get("clock") or {}).get("displayValue") or "")
                        scoring_id = ((detail.get("team") or {}).get("id") or "")
                        is_og = "own" in d_type
                        is_pk = "penalty" in d_type and not is_og
                        if is_og:
                            if scoring_id == ht_id:
                                away_goals.append(f"{clock_val}(OG)")
                            elif scoring_id == at_id:
                                home_goals.append(f"{clock_val}(OG)")
                        elif is_pk:
                            if scoring_id == ht_id:
                                home_goals.append(f"{clock_val}(PK)")
                            elif scoring_id == at_id:
                                away_goals.append(f"{clock_val}(PK)")
                        else:
                            if scoring_id == ht_id:
                                home_goals.append(clock_val)
                            elif scoring_id == at_id:
                                away_goals.append(clock_val)
                    for stat in home.get("statistics") or []:
                        if str(stat.get("name", "")).lower() in ("points", "pts"):
                            try:
                                home_points = int(float(str(stat.get("value", stat.get("displayValue", "")))))
                            except (ValueError, TypeError):
                                pass
                    for stat in away.get("statistics") or []:
                        if str(stat.get("name", "")).lower() in ("points", "pts"):
                            try:
                                away_points = int(float(str(stat.get("value", stat.get("displayValue", "")))))
                            except (ValueError, TypeError):
                                pass

                games.append(
                    {
                        "id": str(event.get("id") or ""),
                        "league": league,
                        "sport": sport,
                        "home_abbr": home_team.get("abbreviation", "???"),
                        "away_abbr": away_team.get("abbreviation", "???"),
                        "home_name": home_team.get("displayName", ""),
                        "away_name": away_team.get("displayName", ""),
                        "home_location": home_team.get("location", ""),
                        "away_location": away_team.get("location", ""),
                        "home_nickname": home_team.get("name", ""),
                        "away_nickname": away_team.get("name", ""),
                        "home_score": home.get("score", "-"),
                        "away_score": away.get("score", "-"),
                        "home_color": home_team.get("color", "444444"),
                        "away_color": away_team.get("color", "444444"),
                        "home_alt_color": home_team.get("alternateColor", "aaaaaa"),
                        "away_alt_color": away_team.get("alternateColor", "aaaaaa"),
                        "home_logo_url": _flag_url(home_team.get("abbreviation", "")) if use_flags else home_team.get("logo"),
                        "away_logo_url": _flag_url(away_team.get("abbreviation", "")) if use_flags else away_team.get("logo"),
                        "status": status_type.get("shortDetail", "Scheduled"),
                        "state": status_type.get("state", "pre"),
                        "series_summary": series_summary,
                        "start_time": comp.get("date"),
                        "home_rank": home_rank,
                        "away_rank": away_rank,
                        "home_conf": home_conf,
                        "away_conf": away_conf,
                        "situation": situation,
                        "last_play": last_play,
                        "home_id": home_team.get("id", ""),
                        "away_id": away_team.get("id", ""),
                        "home_record": home_record,
                        "away_record": away_record,
                        "match_note": match_note,
                        "home_goals": home_goals,
                        "away_goals": away_goals,
                        "home_points": home_points,
                        "away_points": away_points,
                    }
                )
            except Exception as exc:
                logger.warning("Skipping malformed %s event: %s", league, exc)
                continue
        if filter_mode == "top25":
            games = [
                g for g in games
                if (g.get("home_rank") or 999) <= 25
                or (g.get("away_rank") or 999) <= 25
            ]
        self._scores_cache[league] = (time.time(), games)
        return games
