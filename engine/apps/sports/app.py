from __future__ import annotations

import datetime
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from canvas.base import Canvas
from app_base import DisplayApp
from grid import SizeConstraints
from marquee import Marquee
from libraries.canvas_utils.library import blit
from libraries.espn_sports.library import ESPNSportsLibrary, _LEAGUES
from libraries.location.library import LocationLibrary
from libraries.text_renderer.library import can_fit_text, render_text
from libraries.timezones.library import resolve_zone

from .cards import render_card
from .events import Celebration, GameSnapshot, detect_events, game_key, make_snapshot
from .model import CelebrationView, PkFlashView, _resolve_pks, build_game_view

logger = logging.getLogger(__name__)


_LEAGUE_IDS = [e["id"] for e in _LEAGUES]
_LEAGUE_LABELS = {e["id"]: e["label"] for e in _LEAGUES}

_UNIT_SECONDS: dict[str, float] = {
    "seconds": 1,
    "minutes": 60,
    "hours": 3600,
    "days": 86400,
    "months": 2592000,
    "years": 31536000,
}

_FPS = 30  # only used to convert legacy "frames_per_game" configs to seconds

_CELEBRATION_SECONDS = 60.0  # how long a scoring celebration stays on screen

# Keep "pre" games whose scheduled start has passed: ESPN can lag flipping a
# game to "in", and delayed kickoffs stay "pre" past start. Matches the 4h
# approximate game length used for completed games.
_PRE_START_GRACE_SECONDS = 4 * 3600

# "Next game per team" mode doesn't have a user-configured window, so the ESPN
# fetch itself needs to look far enough ahead to find each team's next game
# even across a bye week or short break between fixtures.
_NEXT_GAME_FETCH_DAYS = 30

# A game stuck reporting "in" for longer than any real match (extra time,
# rain delays, etc. included) is a stale/glitched ESPN feed, not a live game.
# Without this cap a live_game_mode spotlight (e.g. World Cup) can pin the
# scene on screen forever if ESPN never flips the game's state.
_MAX_LIVE_GAME_SECONDS = 8 * 3600
_ANIM_FRAMES = 8             # sprite animation cycle length
_ANIM_FPS = 8                # sprite frames per second

# A newly landed shootout kick blinks briefly to draw the eye, then settles
# into its stationary result color like the rest of the dots.
_PK_FLASH_SECONDS = 5.0      # how long a fresh shootout dot blinks
_PK_FLASH_HZ = 3             # blink toggles per second while flashing

# Shown in place of a card when the configured leagues/teams have nothing
# inside the upcoming and completed windows. Without it the module renders an
# all-black frame, which reads as a broken display rather than "no games".
_EMPTY_TEXT = "No games"
_EMPTY_COLOR: tuple[int, int, int] = (110, 110, 110)  # dim: it is a non-event
_EMPTY_FONT_MAX = 14

# render_frame() runs every frame for as long as the module is on screen, so
# the placeholder is composed once per canvas size rather than per frame (the
# same reasoning as connectivity.py's offline message: per-frame text layout
# competes with the rgbmatrix GPIO driver on the Pi).
_empty_cache: dict[tuple[int, int], Image.Image] = {}


_DEBUG_GAMES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "debug_games.json").read_text()
)
_DEBUG_GAME_BY_ID: dict[str, dict[str, Any]] = {g["id"]: g["game"] for g in _DEBUG_GAMES}
_DEBUG_GAME_IDS: list[str] = [g["id"] for g in _DEBUG_GAMES]
_DEBUG_GAME_LABELS: dict[str, str] = {g["id"]: g["label"] for g in _DEBUG_GAMES}


def _duration_to_seconds(d: Any) -> float:
    if isinstance(d, (int, float)):
        return float(d) * 3600  # backwards-compat: bare number treated as hours
    if isinstance(d, dict):
        # Old single-period format: {"value": N, "unit": "hours"}
        if "value" in d and "unit" in d:
            return float(d["value"]) * _UNIT_SECONDS.get(str(d["unit"]), 3600)
        # New multi-period format: {"days": 1, "hours": 5}
        return sum(
            float(v) * _UNIT_SECONDS.get(k, 0)
            for k, v in d.items()
            if k in _UNIT_SECONDS
        )
    return 0.0


def _empty_message_image(w: int, h: int) -> Image.Image:
    img = _empty_cache.get((w, h))
    if img is not None:
        return img
    text = _EMPTY_TEXT
    size = _EMPTY_FONT_MAX
    max_text_w = max(6, w - 4)
    while size > 6 and not can_fit_text(max_text_w, size, text):
        size -= 1
    while text and not can_fit_text(max_text_w, size, text):
        text = text[:-1]
    img = Image.new("RGB", (w, h))
    if text:
        text_img = render_text(text, _EMPTY_COLOR, size)
        img.paste(
            text_img,
            (max(0, (w - text_img.width) // 2), max(0, (h - text_img.height) // 2)),
        )
    _empty_cache[(w, h)] = img
    return img


class SportsApp(DisplayApp):
    id: ClassVar[str] = "sports"
    name: ClassVar[str] = "Sports Scores"
    description: ClassVar[str] = (
        "Live scores from the ESPN API — NFL, NBA, MLB, NHL, soccer, and more, "
        "rotating through active and upcoming games"
    )
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    libraries: ClassVar[list[str]] = ["espn_sports", "location"]
    # The tiered card layouts adapt down to a scores-only view below 48px wide
    # and a compact two-row view at 32px tall.
    size_constraints: ClassVar[SizeConstraints] = SizeConstraints(min_width=40, min_height=32)
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Sports Scores",
        "properties": {
            "leagues": {
                "type": "array",
                "title": "Leagues",
                "x-input-type": "multi-picker",
                "x-enum-labels": _LEAGUE_LABELS,
                "items": {"type": "string", "enum": _LEAGUE_IDS},
                "default": [],
            },
            "favorite_teams": {
                "type": "array",
                "title": "Favorite Teams",
                "description": (
                    "Also show these teams' games, even when their league isn't "
                    "selected above. Added to the selected leagues, never "
                    "subtracted from them: a selected league keeps showing all "
                    "of its games."
                ),
                "x-input-type": "team-picker",
                "items": {"type": "string"},
                "default": [],
            },
            "display_mode": {
                "type": "string",
                "title": "Display mode",
                "enum": ["paginate", "marquee", "staggered"],
                "default": "paginate",
            },
            "live_game_mode": {
                "type": "boolean",
                "title": "Live game spotlight",
                "description": (
                    "When a qualifying game is live, dedicate 3/4 of the screen "
                    "to it and cycle the other games through the remaining 1/4."
                ),
                "default": False,
            },
            "live_game_source": {
                "type": "string",
                "title": "Spotlight which live games",
                "description": "Which live games qualify for the spotlight.",
                "enum": ["any", "favorites"],
                "x-enum-labels": {"any": "Any live game", "favorites": "Favorite teams only"},
                "default": "favorites",
            },
            "scores_per_screen": {
                "type": "integer",
                "title": "Scores per screen",
                "default": 1,
                "minimum": 1,
                "maximum": 4,
            },
            "show_upcoming_games": {
                "type": "boolean",
                "title": "Show upcoming games",
                "default": True,
            },
            "upcoming_game_mode": {
                "type": "string",
                "title": "Upcoming games mode",
                "description": (
                    "\"Next game per team\" shows only each team's next "
                    "game — one per team in each selected league, plus one per "
                    "favorite team, and both games of a doubleheader when a "
                    "team plays twice on the same day. \"Time window\" shows "
                    "every upcoming game within the window below."
                ),
                "enum": ["next_game", "window"],
                "x-enum-labels": {"next_game": "Next game per team", "window": "Time window"},
                "default": "next_game",
            },
            "upcoming_game_window": {
                "type": "object",
                "title": "Upcoming game window",
                "x-input-type": "duration",
                "x-duration-units": ["days", "hours", "minutes"],
                "x-show-if": {"field": "upcoming_game_mode", "equals": "window"},
                "default": {"days": 1},
            },
            "completed_game_window": {
                "type": "object",
                "title": "Keep completed games for",
                "description": (
                    "How long a final score can stay on screen. It drops off "
                    "sooner at the start of the next day either team has a "
                    "game that is on screen too — games on the same day (a "
                    "doubleheader) stay up together for the rest of that day, "
                    "and a result is never retired with nothing to replace it."
                ),
                "x-input-type": "duration",
                "x-duration-units": ["days", "hours", "minutes"],
                "default": {"days": 1},
            },
            "seconds_per_score": {
                "type": "integer",
                "title": "Seconds per score card",
                "default": 5,
                "minimum": 1,
            },
            "marquee_speed": {
                "type": "number",
                "title": "Marquee scroll speed (px/frame)",
                "default": 1.5,
                "minimum": 0.5,
            },
            "stagger_delay": {
                "type": "integer",
                "title": "Stagger delay between slots (seconds)",
                "default": 2,
                "minimum": 1,
            },
            "refresh_interval": {
                "type": "number",
                "title": "Score data refresh interval (seconds)",
                "default": 60,
                "minimum": 10,
            },
            "live_refresh_interval": {
                "type": "number",
                "title": "Live game refresh interval (seconds)",
                "default": 15,
                "minimum": 5,
            },
            "debug_game": {
                "type": "string",
                "title": "Debug game",
                "enum": ["", *_DEBUG_GAME_IDS],
                "x-enum-labels": {"": "— select a game —", **_DEBUG_GAME_LABELS},
                "default": "",
                "x-dev-only": True,
            },
        },
        "required": ["leagues"],
    }

    def __init__(
        self,
        config: dict[str, Any],
        canvas: Canvas,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(config, canvas, global_config, library_configs)
        self._espn = ESPNSportsLibrary(self.library_configs.get("espn_sports", {}))
        self._user_tz: ZoneInfo | None = None
        self._user_tz_key: tuple[float, float, str] | None = None  # cached (lat, lon, tz) → tz
        self._games: list[dict[str, Any]] = []
        self._logos: dict[str, Image.Image | None] = {}

        # Paginate state
        self._page_idx = 0
        self._page_started_at = self._now()

        # Marquee state
        self._marquee_strip: Image.Image | None = None
        self._marquee = Marquee(direction="left", speed=1.5, loop=True)
        # Per-game-index celebration phase baked into the strip, so only the
        # cards whose pulse/anim phase changed get re-rendered and patched in.
        self._marquee_celeb_state: dict[int, tuple | None] = {}

        # Celebration state: previous fetch snapshots + active celebrations,
        # both keyed by events.game_key
        self._prev_snaps: dict[str, GameSnapshot] = {}
        self._celebrations: dict[str, Celebration] = {}

        # Penalty-shootout flash state, keyed by (game_key, side): the count of
        # kicks seen last fetch, and the (first_new_index, started_at) of the
        # most recent batch of kicks so their dots can blink briefly.
        self._pk_counts: dict[tuple[str, str], int] = {}
        self._pk_flash: dict[tuple[str, str], tuple[int, float]] = {}

        # Staggered state
        self._stagger_slot_idx: list[int] = []
        self._stagger_slot_started_at: list[float] = []

        # Live game spotlight state
        self._featured_idx = 0
        self._featured_started_at = self._now()
        self._sidebar_idx = 0
        self._sidebar_started_at = self._now()

        # World Cup logo slide-animation clock: the logo cycles in/out relative
        # to this start so the panel only occupies the screen briefly.
        self._wc_cycle_start = self._now()

    def _get_user_tz(self) -> ZoneInfo | None:
        """Return the user's timezone, re-computing only when the stored location changes."""
        loc_cfg = self.library_configs.get("location", {}).get("location", {})
        lat = float(loc_cfg.get("latitude", 0.0))
        lon = float(loc_cfg.get("longitude", 0.0))
        # The stored timezone is part of the key so a config update that only
        # adds/changes the timezone (same pin) invalidates the cache too.
        key = (lat, lon, str(loc_cfg.get("timezone") or ""))
        if key == self._user_tz_key:
            return self._user_tz
        self._user_tz_key = key
        if lat == 0.0 and lon == 0.0:
            self._user_tz = None
            return None
        location_lib = LocationLibrary(self.library_configs.get("location", {}))
        tz_str = location_lib.get_timezone()
        tz = resolve_zone(tz_str) if tz_str else None
        if tz is None:
            logger.warning(
                "No IANA timezone resolved for location (%.4f, %.4f) (got %r); "
                "pre-game times will show in UTC",
                lat, lon, tz_str,
            )
        self._user_tz = tz
        return self._user_tz

    @property
    def refresh_interval(self) -> float:
        """Poll fast while a game is live, slow otherwise.

        ``_fetch_loop`` re-reads this after every fetch, so the cadence
        tightens to ``live_refresh_interval`` only while a tracked game is in
        progress and relaxes to ``refresh_interval`` afterward, keeping API
        load bounded (one request per league). An in-flight celebration lives
        ``_CELEBRATION_SECONDS`` regardless of cadence, so relaxing the
        interval at the final whistle never cuts one short.
        """
        idle = float(self.config.get("refresh_interval", 60.0))
        live = max(5.0, float(self.config.get("live_refresh_interval", 15.0)))
        if any(g.get("is_live_shootout") for g in self._games):
            return min(5.0, live, idle)  # shootout kicks land fast — poll at 5s
        if any(g.get("state") == "in" for g in self._games):
            return min(live, idle)  # never slower than idle
        return idle

    def _get_leagues(self) -> list[str]:
        """The leagues the user selected, in config order.

        Only these: a favorite's own league is fetched too, but that happens
        inside ``fetch_scores`` (which keeps just the favorites' games out of
        a league nobody selected). Appending it here would instead pull in
        every game of that whole league.
        """
        raw = self.config.get("leagues", self.config.get("league", []))
        return [raw] if isinstance(raw, str) else list(raw)

    def _scores_per_screen(self) -> int:
        return max(1, min(4, int(self.config.get("scores_per_screen", 1))))

    def _active_slot_count(self) -> int:
        """Slots to show on screen at once: never more than the number of
        games, so a single game isn't duplicated to fill empty slots."""
        return min(self._scores_per_screen(), max(1, len(self._games)))

    def _seconds_per_score(self) -> float:
        # Support old "frames_per_game" field for backwards compat
        seconds = self.config.get(
            "seconds_per_score",
            max(1, int(self.config.get("frames_per_game", 150)) // _FPS),
        )
        return max(1.0, float(seconds))

    def _featured_live_games(self) -> list[dict[str, Any]]:
        """Live games eligible for the spotlight, in ``self._games`` order.

        Empty unless ``live_game_mode`` is on. ``live_game_source`` selects
        whether *any* live game qualifies, or only those matching
        ``favorite_teams`` (which also covers favorited World Cup teams).
        """
        if not self.config.get("live_game_mode", False):
            return []
        source = self.config.get("live_game_source", "favorites")
        favorite_teams = list(self.config.get("favorite_teams") or [])
        # No favorites configured → treat as "any"; filtering by an empty list
        # would silently suppress the spotlight for every user who hasn't set teams.
        if source == "favorites" and not favorite_teams:
            source = "any"
        result: list[dict[str, Any]] = []
        for game in self._games:
            if game.get("state") != "in":
                continue
            if source == "any" or self._espn._matches_favorites(game, favorite_teams):
                result.append(game)
        return result

    async def fetch_data(self) -> None:
        game = _DEBUG_GAME_BY_ID.get(self.config.get("debug_game", ""))
        if game:
            self._games = [dict(game)]
            new_logos = await self._espn.fetch_logos(self._games, (64, 64))
            self._logos.update(new_logos)
            self._marquee_strip = self._build_marquee_strip()
            return

        favorite_teams = list(self.config.get("favorite_teams") or [])

        days_ahead = 0
        if self.config.get("show_upcoming_games", True):
            if self.config.get("upcoming_game_mode", "next_game") == "next_game":
                days_ahead = _NEXT_GAME_FETCH_DAYS
            else:
                upcoming_secs = _duration_to_seconds(
                    self.config.get("upcoming_game_window", {"days": 1})
                )
                days_ahead = max(1, math.ceil(upcoming_secs / 86400))

        completed_secs = _duration_to_seconds(
            self.config.get("completed_game_window", {"days": 1})
        )
        days_behind = max(1, math.ceil(completed_secs / 86400)) if completed_secs > 0 else 0

        games = await self._espn.fetch_scores(
            self._get_leagues(),
            favorite_teams=favorite_teams if favorite_teams else None,
            days_ahead=days_ahead,
            days_behind=days_behind,
        )

        self._games = self._filter_by_time_window(self._dedupe_games(games))

        self._update_celebrations()
        self._update_pk_flashes()

        # Store logos at full display height so any layout can downscale cleanly
        new_logos = await self._espn.fetch_logos(self._games, (64, 64))
        self._logos.update(new_logos)

        # Rebuild marquee strip whenever data changes
        self._marquee_strip = self._build_marquee_strip()

    def _now(self) -> float:
        return time.monotonic()

    def _update_celebrations(self) -> None:
        """Diff the fresh fetch against the previous one to start celebrations."""
        now = self._now()
        for ev in detect_events(self._prev_snaps, self._games):
            self._celebrations[ev.game_key] = Celebration(ev.kind, ev.side, now)
        self._prev_snaps = {
            game_key(g): make_snapshot(g, self._prev_snaps.get(game_key(g)))
            for g in self._games
        }
        self._celebrations = {
            k: c
            for k, c in self._celebrations.items()
            if k in self._prev_snaps and now - c.started_at < _CELEBRATION_SECONDS
        }

    def _celebration_view(self, key: str) -> CelebrationView | None:
        """Resolve a game's active celebration to this instant's pulse/anim phase."""
        celeb = self._celebrations.get(key)
        if celeb is None:
            return None
        elapsed = self._now() - celeb.started_at
        if not 0 <= elapsed < _CELEBRATION_SECONDS:
            return None
        return CelebrationView(
            kind=celeb.kind,
            side=celeb.side,
            pulse_on=int(elapsed) % 2 == 0,
            anim_frame=int(elapsed * _ANIM_FPS) % _ANIM_FRAMES,
        )

    def _update_pk_flashes(self) -> None:
        """Diff each shootout's kick counts against the previous fetch so newly
        landed dots can blink. Like celebrations, nothing flashes on a game's
        first observation (the existing kicks are pre-existing, not "new")."""
        now = self._now()
        live: set[str] = set()
        for game in self._games:
            if game.get("sport") != "soccer":
                continue
            if not (game.get("is_live_shootout") or game.get("ended_in_shootout")):
                continue
            key = game_key(game)
            live.add(key)
            for side in ("away", "home"):
                count = len(_resolve_pks(game, side))
                fkey = (key, side)
                prev = self._pk_counts.get(fkey)
                if prev is not None and count > prev:
                    # One or more kicks landed since last fetch: blink every
                    # index from the old count up (covers reconstructed misses).
                    self._pk_flash[fkey] = (prev, now)
                self._pk_counts[fkey] = count
        # Drop state for games that are no longer live shootouts, and expire
        # flashes past their window.
        self._pk_counts = {k: v for k, v in self._pk_counts.items() if k[0] in live}
        self._pk_flash = {
            k: v
            for k, v in self._pk_flash.items()
            if k[0] in live and now - v[1] < _PK_FLASH_SECONDS
        }

    def _pk_flash_view(
        self, key: str, away_len: int, home_len: int
    ) -> PkFlashView | None:
        """Resolve a shootout's active flashes to this frame's blink phase."""
        now = self._now()

        def _indices(side: str, length: int) -> frozenset[int]:
            flash = self._pk_flash.get((key, side))
            if flash is None:
                return frozenset()
            from_idx, started = flash
            if now - started >= _PK_FLASH_SECONDS:
                return frozenset()
            return frozenset(i for i in range(length) if i >= from_idx)

        away = _indices("away", away_len)
        home = _indices("home", home_len)
        if not away and not home:
            return None
        # Shared blink phase so both rows toggle together.
        return PkFlashView(away=away, home=home, on=int(now * _PK_FLASH_HZ) % 2 == 0)

    def _dedupe_games(self, games: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop repeat entries for the same game.

        Selecting multiple leagues that overlap (e.g. two NCAAF conference
        filters) can return the same inter-conference matchup from each
        fetch, which would otherwise show the same game in two sections at
        once when scores_per_screen > 1.
        """
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for game in games:
            key = game_key(game)
            if key in seen:
                continue
            seen.add(key)
            result.append(game)
        return result

    @staticmethod
    def _parse_start(game: dict[str, Any]) -> datetime.datetime | None:
        start_raw = game.get("start_time")
        if not start_raw:
            return None
        try:
            return datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        except Exception:
            return None

    def _game_day(
        self, start: datetime.datetime, tz: datetime.tzinfo
    ) -> datetime.date:
        """The calendar day a game falls on, in the display's local timezone.

        "Same day" throughout this module means the same calendar day, not a
        24h span: an MLB doubleheader's two games share a day, while last
        night's game and this afternoon's do not.
        """
        return start.astimezone(tz).date()

    def _local_tz(self) -> datetime.tzinfo:
        """The timezone calendar days are measured in (UTC when unconfigured)."""
        return self._get_user_tz() or datetime.timezone.utc

    def _qualifying_teams(
        self, game: dict[str, Any], favorites_by_league: dict[str, set[str]]
    ) -> list[tuple[str, str]]:
        """The ``(league, abbr)`` teams in ``game`` this module is showing for."""
        league = game.get("league", "")
        # None unless this league was fetched only for its favorites.
        league_favorites = favorites_by_league.get(league)
        return [
            (league, abbr)
            for abbr in (game.get("home_abbr", ""), game.get("away_abbr", ""))
            if abbr and (league_favorites is None or abbr in league_favorites)
        ]

    def _favorites_by_league(self) -> dict[str, set[str]]:
        """Favorites grouped by league, for leagues not selected outright.

        A selected league qualifies every team in it, so only a league
        fetched purely to cover a favorite (mirroring ``fetch_scores``)
        narrows qualifying down to the favorites themselves - otherwise a
        favorite's opponent would count as a qualifying team and pull in a
        second, later favorite game as "their" next one.
        """
        selected_leagues = set(self._get_leagues())
        favorites_by_league: dict[str, set[str]] = {}
        for fav in self.config.get("favorite_teams") or []:
            parts = fav.split(":", 1)
            if len(parts) == 2 and parts[0] not in selected_leagues:
                favorites_by_league.setdefault(parts[0], set()).add(parts[1])
        return favorites_by_league

    def _next_game_per_team_keys(
        self, games: list[dict[str, Any]], now: datetime.datetime,
        tz: datetime.tzinfo | None = None,
    ) -> set[str]:
        """Game keys of each qualifying team's next "pre" game day.

        One game per team, except that a team playing twice on the same
        calendar day (a baseball doubleheader) keeps both: the cut is made on
        the soonest day a team plays, not on its single soonest game.

        Qualifying teams are the union the module is configured for: every
        team appearing in a selected league's games, plus every favorite
        (see ``_favorites_by_league``). A game shared by two qualifying teams
        (e.g. two favorites playing each other) is naturally included once.
        """
        tz = tz or self._local_tz()
        favorites_by_league = self._favorites_by_league()

        first_day: dict[tuple[str, str], datetime.date] = {}
        candidates: list[tuple[dict[str, Any], datetime.date, list[tuple[str, str]]]] = []
        for game in games:
            if game.get("state", "pre") != "pre":
                continue
            start = self._parse_start(game)
            if start is None:
                continue
            secs_until = (start - now).total_seconds()
            if secs_until < -_PRE_START_GRACE_SECONDS:
                continue
            teams = self._qualifying_teams(game, favorites_by_league)
            if not teams:
                continue
            day = self._game_day(start, tz)
            candidates.append((game, day, teams))
            for team_key in teams:
                current = first_day.get(team_key)
                if current is None or day < current:
                    first_day[team_key] = day

        return {
            game_key(game)
            for game, day, teams in candidates
            if any(first_day[team_key] == day for team_key in teams)
        }

    def _expired_final_keys(
        self, games: list[dict[str, Any]], now: datetime.datetime,
        tz: datetime.tzinfo | None = None,
    ) -> set[str]:
        """Game keys of finals whose day has passed.

        A final score stays up until the start of the next day either of its
        teams has a game - scheduled, under way or finished alike - even if
        the configured "keep completed games for" window would hold it longer.
        Expiring on the day boundary rather than at the next game's start
        keeps yesterday's result off the screen on game day, where it would
        sit confusingly alongside the game still to be played. Days are
        calendar days, so games sharing one never expire each other: both
        halves of a doubleheader stay up for the rest of that day.

        ``games`` must be the games the module is *already* showing (what
        ``_filter_by_time_window`` kept on its first pass), not the whole
        fetch. Only a game that is itself on screen may retire a final, which
        is what keeps this from blanking the display: the newer game that
        expires a result is always there to take its place. Feeding it the
        raw fetch instead would let a game the module never displays - an
        upcoming fixture when "show upcoming games" is off, or one beyond the
        upcoming window - silently delete the last result on screen.
        """
        tz = tz or self._local_tz()
        today = self._game_day(now, tz)

        # Per team, the latest day up to and including today that it has a
        # game on. Today counts from midnight, before any of it is played.
        latest_day: dict[tuple[str, str], datetime.date] = {}
        finals: list[tuple[dict[str, Any], datetime.date, list[tuple[str, str]]]] = []
        for game in games:
            start = self._parse_start(game)
            if start is None:
                continue
            league = game.get("league", "")
            teams = [
                (league, abbr)
                for abbr in (game.get("home_abbr", ""), game.get("away_abbr", ""))
                if abbr
            ]
            day = self._game_day(start, tz)
            if day <= today:
                for team_key in teams:
                    current = latest_day.get(team_key)
                    if current is None or day > current:
                        latest_day[team_key] = day
            if game.get("state", "pre") == "post":
                finals.append((game, day, teams))

        def _has_reached_a_later_game_day(
            day: datetime.date, teams: list[tuple[str, str]]
        ) -> bool:
            return any(
                latest_day.get(team_key) is not None and latest_day[team_key] > day
                for team_key in teams
            )

        return {
            game_key(game)
            for game, day, teams in finals
            if _has_reached_a_later_game_day(day, teams)
        }

    def _settle_stale_live_game(
        self, game: dict[str, Any], now: datetime.datetime
    ) -> dict[str, Any]:
        """Demote a game ESPN never flipped out of "in" to "post".

        A game stuck reporting "in" for longer than any real match is a
        glitched feed, not a live game, and would otherwise pin the screen
        forever. Settling it up front also lets the per-team passes below see
        the same states the filter acts on.
        """
        if game.get("state") != "in":
            return game
        start = self._parse_start(game)
        if start is None:
            return game
        if (now - start).total_seconds() <= _MAX_LIVE_GAME_SECONDS:
            return game
        return {**game, "state": "post"}

    def _within_windows(
        self,
        game: dict[str, Any],
        now: datetime.datetime,
        next_game_keys: set[str] | None,
        *,
        show_upcoming: bool,
        upcoming_secs: float,
        completed_secs: float,
    ) -> bool:
        """Whether ``game`` falls inside the windows the module displays.

        Everything except final expiry, which needs the full set of games
        this returns before it can tell which results have been superseded
        (see ``_expired_final_keys``).
        """
        state = game.get("state", "pre")
        start = self._parse_start(game)

        if state == "in":
            return True

        if state == "post":
            if completed_secs <= 0:
                return False
            if start is None:
                return True
            approx_end = start + datetime.timedelta(hours=4)
            return (now - approx_end).total_seconds() <= completed_secs

        if state == "pre" and show_upcoming:
            if next_game_keys is not None:
                return game_key(game) in next_game_keys
            if start is None:
                return True
            secs_until = (start - now).total_seconds()
            return -_PRE_START_GRACE_SECONDS <= secs_until <= upcoming_secs

        return False

    def _filter_by_time_window(
        self, games: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        now = datetime.datetime.now(datetime.timezone.utc)
        tz = self._local_tz()
        show_upcoming = bool(self.config.get("show_upcoming_games", True))
        next_game_mode = (
            show_upcoming
            and self.config.get("upcoming_game_mode", "next_game") == "next_game"
        )
        upcoming_secs = _duration_to_seconds(
            self.config.get("upcoming_game_window", {"days": 1})
        )
        completed_secs = _duration_to_seconds(
            self.config.get("completed_game_window", {"days": 1})
        )

        games = [self._settle_stale_live_game(game, now) for game in games]

        next_game_keys = (
            self._next_game_per_team_keys(games, now, tz) if next_game_mode else None
        )

        # Pass 1: the games the module shows, before any final is retired.
        shown = [
            game
            for game in games
            if self._within_windows(
                game,
                now,
                next_game_keys,
                show_upcoming=show_upcoming,
                upcoming_secs=upcoming_secs,
                completed_secs=completed_secs,
            )
        ]

        # Pass 2: retire the results the screen has moved past. Only the games
        # kept by pass 1 get a say, so whatever expires a final is on screen
        # in its place - a fixture the module isn't showing (upcoming games
        # switched off, or a game beyond the upcoming window) can no longer
        # take down the last result and leave the module blank.
        expired_final_keys = self._expired_final_keys(shown, now, tz)
        return [game for game in shown if game_key(game) not in expired_final_keys]

    def _init_stagger_state(self) -> None:
        n = self._active_slot_count()
        seconds_per_score = self._seconds_per_score()
        stagger_delay_s = max(1, int(self.config.get("stagger_delay", 2)))
        offset_s = min(float(stagger_delay_s), seconds_per_score / max(1, n))
        now = self._now()
        self._stagger_slot_idx = list(range(n))
        self._stagger_slot_started_at = [now - i * offset_s for i in range(n)]

    async def should_display(self) -> bool:
        return bool(self._games)

    async def on_activate(self) -> None:
        self._page_idx = 0
        self._page_started_at = self._now()
        self._wc_cycle_start = self._now()
        self._marquee.reset(self.canvas)
        self._marquee_strip = None
        self._init_stagger_state()
        await self.fetch_data()

    def _wc_reveal(self) -> float:
        """Current World Cup logo slide position (0=hidden .. 1=fully shown)."""
        from .cards import wc_logo_reveal
        return wc_logo_reveal(self._now() - self._wc_cycle_start)

    async def render_frame(self) -> None:
        if not self._games:
            # Nothing qualifies right now. A playlist entry with "skip if
            # hidden" set never reaches this (should_display() gates it), so
            # whoever gets here asked to keep the module in rotation - say why
            # it is empty rather than showing them an all-black panel.
            blit(self.canvas, _empty_message_image(self.canvas.width, self.canvas.height))
            return

        featured_games = self._featured_live_games()
        if featured_games:
            self._render_featured_frame(featured_games)
            return

        display_mode = self.config.get("display_mode", "paginate")

        if display_mode == "marquee":
            self._render_marquee_frame()
        elif display_mode == "staggered":
            self._render_staggered_frame()
        else:
            self._render_paginate_frame()

    def _render_paginate_frame(self) -> None:
        n = self._scores_per_screen()
        seconds_per_score = self._seconds_per_score()

        start = self._page_idx * n
        page_games = self._games[start : start + n]
        if not page_games:
            self._page_idx = 0
            page_games = self._games[:n]

        self._draw_games(page_games, n)

        if self._now() - self._page_started_at >= seconds_per_score:
            self._page_started_at = self._now()
            max_pages = max(1, math.ceil(len(self._games) / n))
            self._page_idx = (self._page_idx + 1) % max_pages

    def _build_marquee_strip(self) -> Image.Image | None:
        if not self._games:
            self._marquee_celeb_state = {}
            return None
        n = self._active_slot_count()
        card_w = self.canvas.width // n
        h = self.canvas.height
        strip = Image.new("RGB", (card_w * len(self._games), h), (0, 0, 0))
        self._marquee_celeb_state = {}
        for i, game in enumerate(self._games):
            card = self._render_slot_image(game, card_w, h)
            strip.paste(card, (i * card_w, 0))
            if i > 0:
                ImageDraw.Draw(strip).line([(i * card_w, 0), (i * card_w, h - 1)], fill=(35, 35, 35))
            self._marquee_celeb_state[i] = self._marquee_celeb_key(game)
        return strip

    def _marquee_celeb_key(self, game: dict[str, Any]) -> tuple | None:
        """Per-card render key: changes whenever the celebration pulse/anim or
        the shootout flash phase advances, so the strip patches only then."""
        key = game_key(game)
        celeb = self._celebration_view(key)
        celeb_part: tuple | None = (
            (celeb.kind, celeb.pulse_on, celeb.anim_frame) if celeb else None
        )
        flash_part: tuple | None = None
        if game.get("is_live_shootout") or game.get("ended_in_shootout"):
            flash = self._pk_flash_view(
                key, len(_resolve_pks(game, "away")), len(_resolve_pks(game, "home"))
            )
            if flash is not None:
                flash_part = (flash.away, flash.home, flash.on)
        if celeb_part is None and flash_part is None:
            return None
        return (celeb_part, flash_part)

    def _patch_marquee_celebrations(self) -> None:
        """Re-render only the cards whose celebration phase changed since the
        strip was built — a full per-frame strip rebuild would be wasteful."""
        strip = self._marquee_strip
        if strip is None:
            return
        n = self._scores_per_screen()
        card_w = self.canvas.width // n
        h = self.canvas.height
        for i, game in enumerate(self._games):
            key = self._marquee_celeb_key(game)
            if key == self._marquee_celeb_state.get(i):
                continue
            card = self._render_slot_image(game, card_w, h)
            strip.paste(card, (i * card_w, 0))
            if i > 0:  # the paste overwrote the column divider — redraw it
                ImageDraw.Draw(strip).line(
                    [(i * card_w, 0), (i * card_w, h - 1)], fill=(35, 35, 35)
                )
            self._marquee_celeb_state[i] = key

    def _render_marquee_frame(self) -> None:
        if self._marquee_strip is None:
            self._marquee_strip = self._build_marquee_strip()
        if self._marquee_strip is None:
            return

        self._patch_marquee_celebrations()
        self._marquee.speed = float(self.config.get("marquee_speed", 1.5))
        self._marquee.render(self.canvas, self._marquee_strip)

    def _resolve_stagger_indices(self, n: int, n_games: int) -> list[int]:
        """Map each slot's independent rotation index to a game index.

        Each slot advances on its own timer, so two slots' raw indices can
        land on the same game mod n_games (e.g. 3 games with 2 slots/screen).
        When there are at least as many games as slots, nudge a colliding
        slot forward to the next game not already shown elsewhere on screen
        this frame, so the same game never appears in two sections at once.
        """
        if n_games <= 0:
            return [0] * n
        used: set[int] = set()
        result: list[int] = []
        for i in range(n):
            idx = self._stagger_slot_idx[i] % n_games
            if n_games >= n:
                while idx in used:
                    idx = (idx + 1) % n_games
            used.add(idx)
            result.append(idx)
        return result

    def _render_staggered_frame(self) -> None:
        n = self._active_slot_count()
        seconds_per_score = self._seconds_per_score()
        n_games = len(self._games)

        # Lazily initialize stagger state when n changes or first run
        if len(self._stagger_slot_idx) != n:
            self._init_stagger_state()

        # Advance each slot's timer independently. Every slot's deadline moves
        # forward by whole ``seconds_per_score`` periods rather than being reset
        # to *now*, so its phase within the cycle is preserved: a slow frame
        # (data fetch, logo decode, a hitch on the Pi) that blows past several
        # slots' deadlines at once no longer collapses them onto a shared
        # deadline, which used to lock those slots into changing together for
        # the rest of the run.
        now = self._now()
        # When every game already fits on screen there is nothing to rotate to,
        # so only the timers move — otherwise slots would pointlessly swap games
        # with each other.
        rotating = n_games > n
        for i in range(n):
            elapsed = now - self._stagger_slot_started_at[i]
            if elapsed < seconds_per_score:
                continue
            steps = int(elapsed // seconds_per_score)
            self._stagger_slot_started_at[i] += steps * seconds_per_score
            if rotating:
                self._stagger_slot_idx[i] = (self._stagger_slot_idx[i] + steps) % n_games

        h = self.canvas.height
        w = self.canvas.width
        img = Image.new("RGB", (w, h), (0, 0, 0))

        game_indices = self._resolve_stagger_indices(n, n_games)

        x_start = 0
        wc_overlay: tuple[Image.Image, int] | None = None
        if n > 1:
            visible = [self._games[idx] for idx in game_indices]
            logo, logo_x, x_start = self._wc_logo_strip(visible, w, h)
            if logo is not None:
                wc_overlay = (logo, logo_x)

        card_w = (w - x_start) // n

        for i in range(n):
            game_idx = game_indices[i]
            game = self._games[game_idx]
            x_off = x_start + i * card_w
            actual_w = card_w if i < n - 1 else w - x_off
            if i > 0:
                ImageDraw.Draw(img).line([(x_off, 0), (x_off, h - 1)], fill=(35, 35, 35))
                x_off += 1
                actual_w -= 1
            card = self._render_slot_image(game, actual_w, h)
            img.paste(card, (x_off, 0))

        if wc_overlay is not None:
            logo, logo_x = wc_overlay
            img.paste(logo.convert("RGB"), (logo_x, (h - logo.height) // 2), logo.split()[3])

        blit(self.canvas, img)

    def _next_featured_game(self, featured_games: list[dict[str, Any]]) -> dict[str, Any]:
        """Cycle the spotlight slot through every qualifying live game."""
        now = self._now()
        if now - self._featured_started_at >= self._seconds_per_score():
            self._featured_started_at = now
            self._featured_idx += 1
        self._featured_idx %= len(featured_games)
        return featured_games[self._featured_idx]

    def _next_sidebar_game(self, others: list[dict[str, Any]]) -> dict[str, Any]:
        """Cycle the sidebar slot through every non-featured game."""
        now = self._now()
        if now - self._sidebar_started_at >= self._seconds_per_score():
            self._sidebar_started_at = now
            self._sidebar_idx += 1
        self._sidebar_idx %= len(others)
        return others[self._sidebar_idx]

    def _render_featured_frame(self, featured_games: list[dict[str, Any]]) -> None:
        """Spotlight a live game across the left 3/4 of the screen, cycling
        the rest of the games through the remaining 1/4."""
        w, h = self.canvas.width, self.canvas.height
        featured = self._next_featured_game(featured_games)
        others = [g for g in self._games if g is not featured]

        if not others:
            card = self._render_slot_image(featured, w, h)
            blit(self.canvas, card)
            return

        main_w = max(1, (w * 3) // 4)
        side_w = w - main_w

        img = Image.new("RGB", (w, h), (0, 0, 0))
        main_card = self._render_slot_image(featured, main_w, h)
        img.paste(main_card, (0, 0))

        other = self._next_sidebar_game(others)
        side_card = self._render_slot_image(other, side_w - 1, h)
        ImageDraw.Draw(img).line([(main_w, 0), (main_w, h - 1)], fill=(35, 35, 35))
        img.paste(side_card, (main_w + 1, 0))

        blit(self.canvas, img)

    # ── Drawing ────────────────────────────────────────────────────────────────

    def _wc_logo_strip(
        self, games: list[dict[str, Any]], w: int, h: int
    ) -> tuple[Image.Image | None, int, int]:
        """Return (logo_rgba, logo_x, content_x) for a screen-level WC logo panel.

        Only fires when every slot in ``games`` is a FIFA World Cup game and
        the screen is wide enough.  ``logo_x`` is the logo's left edge (negative
        while sliding in) and ``content_x`` the left margin the cards start at;
        both follow the slide animation.  Returns (None, 0, 0) when the panel
        does not apply — single-slot layouts included, since the card renderer
        handles the logo internally at full card width.
        """
        if not all(g.get("league") == "fifa.world" for g in games):
            return None, 0, 0
        from .cards import wc_panel
        panel = wc_panel(w, h, self._wc_reveal())
        if panel is None:
            return None, 0, 0
        logo, logo_x, content_x = panel
        return logo, logo_x, content_x

    def _draw_games(self, games: list[dict[str, Any]], n_cols: int) -> None:
        w, h = self.canvas.width, self.canvas.height
        img = Image.new("RGB", (w, h))
        n_cols = min(n_cols, max(1, len(games)))

        # Multi-slot WC layouts: place the logo once at screen level so every
        # slot gets an equal share of the remaining width.  Single-slot layouts
        # let the card renderer handle the logo internally.
        x_start = 0
        wc_overlay: tuple[Image.Image, int] | None = None
        if n_cols > 1:
            logo, logo_x, x_start = self._wc_logo_strip(games, w, h)
            if logo is not None:
                wc_overlay = (logo, logo_x)

        slot_w = (w - x_start) // n_cols

        for i, game in enumerate(games):
            x_off = x_start + i * slot_w
            actual_w = slot_w if i < n_cols - 1 else w - x_off
            if i > 0:
                ImageDraw.Draw(img).line([(x_off, 0), (x_off, h - 1)], fill=(35, 35, 35))
                x_off += 1
                actual_w -= 1
            card = self._render_slot_image(game, actual_w, h)
            img.paste(card, (x_off, 0))

        if wc_overlay is not None:
            logo, logo_x = wc_overlay
            img.paste(logo.convert("RGB"), (logo_x, (h - logo.height) // 2), logo.split()[3])

        blit(self.canvas, img)

    def _render_slot_image(self, game: dict[str, Any], w: int, h: int) -> Image.Image:
        """Render a single game as a PIL image at the given dimensions.

        Normalizes the raw game dict into a GameView (colors, logos, status
        text), then delegates to the tiered card layouts in cards.py.
        """
        loc_cfg = self.library_configs.get("location", {})
        key = game_key(game)
        pk_flash = None
        if game.get("is_live_shootout") or game.get("ended_in_shootout"):
            pk_flash = self._pk_flash_view(
                key, len(_resolve_pks(game, "away")), len(_resolve_pks(game, "home"))
            )
        try:
            view = build_game_view(
                game,
                self._logos,
                tz=self._get_user_tz(),
                time_format=str(loc_cfg.get("time_format", "12h")),
                celebration=self._celebration_view(key),
                pk_flash=pk_flash,
            )
            return render_card(view, w, h, wc_reveal=self._wc_reveal()).image
        except Exception:
            # One bad game must not blank the whole frame (the scene manager
            # catches render errors after the canvas is already cleared).
            logger.warning(
                "Failed to render card for %s %s @ %s",
                game.get("league"), game.get("away_abbr"), game.get("home_abbr"),
                exc_info=True,
            )
            return Image.new("RGB", (w, h), (0, 0, 0))
