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
from libraries.timezones.library import resolve_zone

from .cards import render_card
from .events import Celebration, GameSnapshot, detect_events, game_key, make_snapshot
from .model import CelebrationView, build_game_view

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
_ANIM_FRAMES = 8             # sprite animation cycle length
_ANIM_FPS = 8                # sprite frames per second

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


class SportsApp(DisplayApp):
    id: ClassVar[str] = "sports"
    name: ClassVar[str] = "Sports Scores"
    description: ClassVar[str] = (
        "Live scores from the ESPN API — NFL, NBA, MLB, NHL, soccer, and more, "
        "rotating through active and upcoming games"
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
                "description": "Only show games for these teams. If empty, all teams are shown.",
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
            "upcoming_game_window": {
                "type": "object",
                "title": "Upcoming game window",
                "x-input-type": "duration",
                "x-duration-units": ["days", "hours", "minutes"],
                "default": {"days": 1},
            },
            "completed_game_window": {
                "type": "object",
                "title": "Keep completed games for",
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
        self._marquee_celeb_state: dict[int, tuple[str, bool, int] | None] = {}

        # Celebration state: previous fetch snapshots + active celebrations,
        # both keyed by events.game_key
        self._prev_snaps: dict[str, GameSnapshot] = {}
        self._celebrations: dict[str, Celebration] = {}

        # Staggered state
        self._stagger_slot_idx: list[int] = []
        self._stagger_slot_started_at: list[float] = []

        # Live game spotlight state
        self._featured_idx = 0
        self._featured_started_at = self._now()
        self._sidebar_idx = 0
        self._sidebar_started_at = self._now()

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
        if any(g.get("state") == "in" for g in self._games):
            return min(live, idle)  # never slower than idle
        return idle

    def _get_leagues(self) -> list[str]:
        raw = self.config.get("leagues", self.config.get("league", []))
        if isinstance(raw, str):
            return [raw]
        return list(raw)

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

    def _filter_by_time_window(
        self, games: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        now = datetime.datetime.now(datetime.timezone.utc)
        show_upcoming = bool(self.config.get("show_upcoming_games", True))
        upcoming_secs = _duration_to_seconds(
            self.config.get("upcoming_game_window", {"days": 1})
        )
        completed_secs = _duration_to_seconds(
            self.config.get("completed_game_window", {"days": 1})
        )

        result: list[dict[str, Any]] = []
        for game in games:
            state = game.get("state", "pre")

            if state == "in":
                result.append(game)
                continue

            start_raw = game.get("start_time")
            start: datetime.datetime | None = None
            if start_raw:
                try:
                    start = datetime.datetime.fromisoformat(
                        start_raw.replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            if state == "post":
                if completed_secs <= 0:
                    continue
                if start is None:
                    result.append(game)
                    continue
                approx_end = start + datetime.timedelta(hours=4)
                elapsed = (now - approx_end).total_seconds()
                if elapsed <= completed_secs:
                    result.append(game)

            elif state == "pre" and show_upcoming:
                if start is None:
                    result.append(game)
                    continue
                secs_until = (start - now).total_seconds()
                if -_PRE_START_GRACE_SECONDS <= secs_until <= upcoming_secs:
                    result.append(game)

        return result

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
        self._marquee.reset(self.canvas)
        self._marquee_strip = None
        self._init_stagger_state()
        await self.fetch_data()

    async def render_frame(self) -> None:
        if not self._games:
            return  # blank canvas — scene manager has already cleared it

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

    def _marquee_celeb_key(self, game: dict[str, Any]) -> tuple[str, bool, int] | None:
        view = self._celebration_view(game_key(game))
        if view is None:
            return None
        return (view.kind, view.pulse_on, view.anim_frame)

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

        # Advance each slot's timer independently
        now = self._now()
        for i in range(n):
            if now - self._stagger_slot_started_at[i] >= seconds_per_score:
                self._stagger_slot_started_at[i] = now
                self._stagger_slot_idx[i] = (self._stagger_slot_idx[i] + n) % max(1, n_games)

        card_w = self.canvas.width // n
        h = self.canvas.height
        w = self.canvas.width
        img = Image.new("RGB", (w, h), (0, 0, 0))

        game_indices = self._resolve_stagger_indices(n, n_games)

        for i in range(n):
            game_idx = game_indices[i]
            game = self._games[game_idx]
            x_off = i * card_w
            actual_w = card_w if i < n - 1 else w - x_off
            if i > 0:
                ImageDraw.Draw(img).line([(x_off, 0), (x_off, h - 1)], fill=(35, 35, 35))
                x_off += 1
                actual_w -= 1
            card = self._render_slot_image(game, actual_w, h)
            img.paste(card, (x_off, 0))

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

    def _draw_games(self, games: list[dict[str, Any]], n_cols: int) -> None:
        w, h = self.canvas.width, self.canvas.height
        img = Image.new("RGB", (w, h))
        n_cols = min(n_cols, max(1, len(games)))
        slot_w = w // n_cols

        for i, game in enumerate(games):
            x_off = i * slot_w
            actual_w = slot_w if i < n_cols - 1 else w - x_off
            if i > 0:
                ImageDraw.Draw(img).line([(x_off, 0), (x_off, h - 1)], fill=(35, 35, 35))
                x_off += 1
                actual_w -= 1
            card = self._render_slot_image(game, actual_w, h)
            img.paste(card, (x_off, 0))

        blit(self.canvas, img)

    def _render_slot_image(self, game: dict[str, Any], w: int, h: int) -> Image.Image:
        """Render a single game as a PIL image at the given dimensions.

        Normalizes the raw game dict into a GameView (colors, logos, status
        text), then delegates to the tiered card layouts in cards.py.
        """
        loc_cfg = self.library_configs.get("location", {})
        try:
            view = build_game_view(
                game,
                self._logos,
                tz=self._get_user_tz(),
                time_format=str(loc_cfg.get("time_format", "12h")),
                celebration=self._celebration_view(game_key(game)),
            )
            return render_card(view, w, h).image
        except Exception:
            # One bad game must not blank the whole frame (the scene manager
            # catches render errors after the canvas is already cleared).
            logger.warning(
                "Failed to render card for %s %s @ %s",
                game.get("league"), game.get("away_abbr"), game.get("home_abbr"),
                exc_info=True,
            )
            return Image.new("RGB", (w, h), (0, 0, 0))
