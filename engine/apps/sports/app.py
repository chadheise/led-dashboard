from __future__ import annotations

import datetime
import math
from typing import Any, ClassVar

from PIL import Image, ImageDraw

from canvas.base import Canvas
from app_base import DisplayApp
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import render_text
from libraries.espn_sports.library import ESPNSportsLibrary, _LEAGUES


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

_FPS = 30  # assumed display frame rate for seconds → frames conversion


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


def _paste(
    img: Image.Image,
    text_img: Image.Image,
    x: int,
    y: int,
    anchor: str,
) -> None:
    """Paste a rendered text image onto img at (x, y) using a two-char PIL anchor."""
    w, h = text_img.size
    px = x - {"l": 0, "m": w // 2, "r": w}[anchor[0]]
    py = y - {"t": 0, "m": h // 2, "b": h}[anchor[1]]
    img.paste(text_img, (px, py))


_BLACK_THRESHOLD = 30  # max channel value below which a color is considered black


def _brighten(color: tuple[int, int, int], minimum: int = 100) -> tuple[int, int, int]:
    """Scale color up so its brightest channel is at least `minimum`."""
    r, g, b = color
    peak = max(r, g, b)
    if peak == 0:
        return (minimum, minimum, minimum)
    if peak < minimum:
        scale = minimum / peak
        return (min(255, int(r * scale)), min(255, int(g * scale)), min(255, int(b * scale)))
    return (r, g, b)


def _team_color(primary_hex: str, alt_hex: str) -> tuple[int, int, int]:
    """Return a visible team color, falling back to the alternate if the primary is black."""
    color = parse_color(primary_hex or "000000")
    if max(color) < _BLACK_THRESHOLD:
        color = parse_color(alt_hex or "aaaaaa")
    return _brighten(color)




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
    libraries: ClassVar[list[str]] = ["espn_sports"]
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
        self._games: list[dict[str, Any]] = []
        self._logos: dict[str, Image.Image | None] = {}

        # Paginate state
        self._page_idx = 0
        self._frame_count = 0

        # Marquee state
        self._marquee_strip: Image.Image | None = None
        self._marquee_offset: float = 0.0

        # Staggered state
        self._stagger_slot_idx: list[int] = []
        self._stagger_slot_counter: list[int] = []

    def _get_leagues(self) -> list[str]:
        raw = self.config.get("leagues", self.config.get("league", []))
        if isinstance(raw, str):
            return [raw]
        return list(raw)

    def _scores_per_screen(self) -> int:
        return max(1, min(4, int(self.config.get("scores_per_screen", 1))))

    def _frames_per_score(self) -> int:
        # Support old "frames_per_game" field for backwards compat
        seconds = int(self.config.get(
            "seconds_per_score",
            max(1, int(self.config.get("frames_per_game", 150)) // _FPS),
        ))
        return max(1, seconds) * _FPS

    def _get_logo(self, url: str | None, size: int) -> Image.Image | None:
        """Return the logo for url scaled to size×size, or None. Never upscales."""
        if not url:
            return None
        logo = self._logos.get(url)
        if logo is None:
            return None
        if logo.size == (size, size):
            return logo
        if size > logo.size[0]:
            return logo  # return native size rather than upscaling
        return logo.resize((size, size), Image.LANCZOS)

    async def fetch_data(self) -> None:
        favorite_teams = list(self.config.get("favorite_teams") or [])

        games = await self._espn.fetch_scores(
            self._get_leagues(),
            favorite_teams=favorite_teams if favorite_teams else None,
        )

        self._games = self._filter_by_time_window(games)

        # Store logos at full display height so any layout can downscale cleanly
        new_logos = await self._espn.fetch_logos(self._games, (64, 64))
        self._logos.update(new_logos)

        # Rebuild marquee strip whenever data changes
        self._marquee_strip = self._build_marquee_strip()

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
                if 0 <= secs_until <= upcoming_secs:
                    result.append(game)

        return result

    def _init_stagger_state(self) -> None:
        n = self._scores_per_screen()
        frames_per_score = self._frames_per_score()
        stagger_delay_s = max(1, int(self.config.get("stagger_delay", 2)))
        stagger_offset = min(stagger_delay_s * _FPS, frames_per_score // max(1, n))
        self._stagger_slot_idx = list(range(n))
        self._stagger_slot_counter = [i * stagger_offset for i in range(n)]

    async def on_activate(self) -> None:
        self._page_idx = 0
        self._frame_count = 0
        self._marquee_offset = 0.0
        self._marquee_strip = None
        self._init_stagger_state()
        await self.fetch_data()

    async def render_frame(self) -> None:
        if not self._games:
            return  # blank canvas — scene manager has already cleared it

        display_mode = self.config.get("display_mode", "paginate")

        if display_mode == "marquee":
            self._render_marquee_frame()
        elif display_mode == "staggered":
            self._render_staggered_frame()
        else:
            self._render_paginate_frame()

    def _render_paginate_frame(self) -> None:
        n = self._scores_per_screen()
        frames_per_score = self._frames_per_score()

        start = self._page_idx * n
        page_games = self._games[start : start + n]
        if not page_games:
            self._page_idx = 0
            page_games = self._games[:n]

        self._draw_games(page_games, n)

        self._frame_count += 1
        if self._frame_count >= frames_per_score:
            self._frame_count = 0
            max_pages = max(1, math.ceil(len(self._games) / n))
            self._page_idx = (self._page_idx + 1) % max_pages

    def _render_game_card(self, game: dict[str, Any], card_w: int, n_cols: int) -> Image.Image:
        """Render a single game as a standalone card image."""
        h = self.canvas.height
        card = Image.new("RGB", (card_w, h), (0, 0, 0))
        self._draw_game_slot(card, game, 0, card_w, n_cols)
        return card

    def _build_marquee_strip(self) -> Image.Image | None:
        if not self._games:
            return None
        n = self._scores_per_screen()
        card_w = self.canvas.width // n
        h = self.canvas.height
        strip = Image.new("RGB", (card_w * len(self._games), h), (0, 0, 0))
        for i, game in enumerate(self._games):
            card = self._render_game_card(game, card_w, n)
            strip.paste(card, (i * card_w, 0))
            if i > 0:
                ImageDraw.Draw(strip).line([(i * card_w, 0), (i * card_w, h - 1)], fill=(35, 35, 35))
        return strip

    def _render_marquee_frame(self) -> None:
        if self._marquee_strip is None:
            self._marquee_strip = self._build_marquee_strip()
        if self._marquee_strip is None:
            return

        strip = self._marquee_strip
        strip_w = strip.width
        cw = self.canvas.width
        ch = self.canvas.height
        speed = float(self.config.get("marquee_speed", 1.5))

        off = int(self._marquee_offset)
        img = Image.new("RGB", (cw, ch), (0, 0, 0))
        img.paste(strip, (off, 0))
        # Wrap: show start of strip when the end has scrolled into view
        if off < 0:
            img.paste(strip, (off + strip_w, 0))

        blit(self.canvas, img)

        self._marquee_offset -= speed
        if self._marquee_offset <= -strip_w:
            self._marquee_offset = 0.0

    def _render_staggered_frame(self) -> None:
        n = self._scores_per_screen()
        frames_per_score = self._frames_per_score()
        n_games = len(self._games)

        # Lazily initialize stagger state when n changes or first run
        if len(self._stagger_slot_idx) != n:
            self._init_stagger_state()

        # Advance each slot's counter independently
        for i in range(n):
            self._stagger_slot_counter[i] += 1
            if self._stagger_slot_counter[i] >= frames_per_score:
                self._stagger_slot_counter[i] = 0
                self._stagger_slot_idx[i] = (self._stagger_slot_idx[i] + n) % max(1, n_games)

        # Draw current state: each slot shows its game
        card_w = self.canvas.width // n
        h = self.canvas.height
        w = self.canvas.width
        img = Image.new("RGB", (w, h), (0, 0, 0))

        for i in range(n):
            game_idx = self._stagger_slot_idx[i] % max(1, n_games)
            game = self._games[game_idx]
            x_off = i * card_w
            actual_w = card_w if i < n - 1 else w - x_off
            if i > 0:
                ImageDraw.Draw(img).line([(x_off, 0), (x_off, h - 1)], fill=(35, 35, 35))
                x_off += 1
                actual_w -= 1
            self._draw_game_slot(img, game, x_off, actual_w, n)

        blit(self.canvas, img)

    # ── Drawing ────────────────────────────────────────────────────────────────

    def _draw_games(self, games: list[dict[str, Any]], n_cols: int) -> None:
        w, h = self.canvas.width, self.canvas.height
        img = Image.new("RGB", (w, h))
        slot_w = w // n_cols

        for i, game in enumerate(games):
            x_off = i * slot_w
            actual_w = slot_w if i < n_cols - 1 else w - x_off
            if i > 0:
                ImageDraw.Draw(img).line([(x_off, 0), (x_off, h - 1)], fill=(35, 35, 35))
                x_off += 1
                actual_w -= 1
            self._draw_game_slot(img, game, x_off, actual_w, n_cols)

        blit(self.canvas, img)

    # ── Layout constants (relative to display height) ──────────────────────────

    _WIDE_THRESHOLD = 130  # slot widths >= this use the wide side-by-side layout

    def _draw_game_slot(
        self,
        img: Image.Image,
        game: dict[str, Any],
        x_offset: int,
        slot_width: int,
        n_cols: int,
    ) -> None:
        h = self.canvas.height

        away_color = _team_color(game.get("away_color", ""), game.get("away_alt_color", ""))
        home_color = _team_color(game.get("home_color", ""), game.get("home_alt_color", ""))

        away_rank = game.get("away_rank")
        away_prefix = f"#{away_rank} " if away_rank and away_rank <= 25 else ""
        home_rank = game.get("home_rank")
        home_suffix = f" #{home_rank}" if home_rank and home_rank <= 25 else ""

        away_abbr = f"{away_prefix}{game['away_abbr']}"
        home_abbr = f"{game['home_abbr']}{home_suffix}"
        away_score = str(game.get("away_score", "-"))
        home_score = str(game.get("home_score", "-"))
        status_text = game.get("series_summary") or str(game.get("status", ""))

        if slot_width >= self._WIDE_THRESHOLD:
            self._draw_wide(img, game, x_offset, slot_width, h, n_cols,
                            away_abbr, away_score, away_color,
                            home_abbr, home_score, home_color, status_text)
        else:
            self._draw_stacked(img, game, x_offset, slot_width, h,
                               away_abbr, away_score, away_color,
                               home_abbr, home_score, home_color, status_text)

    def _draw_wide(
        self,
        img: Image.Image,
        game: dict[str, Any],
        x_offset: int,
        slot_width: int,
        h: int,
        n_cols: int,
        away_abbr: str, away_score: str, away_color: tuple[int, int, int],
        home_abbr: str, home_score: str, home_color: tuple[int, int, int],
        status_text: str,
    ) -> None:
        """Logo fills height. Abbr above score in the text column beside each logo."""
        # All sizes derived from display height + n_cols — fixed per layout, never per game
        STATUS_H   = 12
        STATUS_FONT = 12

        # Logo: for a single score use nearly the full height; shrink for 2-up
        logo_size = (h - 4) if n_cols == 1 else max(28, h - 22)

        # Content area sits above the status strip
        content_h = h - STATUS_H
        logo_y    = max(0, (content_h - logo_size) // 2)

        # Font sizes fill content_h with a 2 px margin top and bottom.
        # Score gets ~65 % of the block, abbr the rest; gap absorbs whatever is left.
        _MARGIN       = 2
        block_avail   = content_h - 2 * _MARGIN
        score_font    = max(22, block_avail * 13 // 20)
        abbr_font     = max(12, block_avail * 6  // 20)

        # For multi-column layouts clamp score_font so a 3-digit score fits per-team.
        # Away text grows rightward from ax; home text grows leftward from rx = slot_width-ax.
        # Each team therefore has (rx - ax) // 2 horizontal pixels before they would overlap.
        if n_cols > 1:
            ax = 2 + logo_size + 3
            per_team_px = (slot_width - 2 * ax) // 2
            while score_font > 22:
                if render_text("000", (255, 255, 255), score_font, bold=True).width <= per_team_px:
                    break
                score_font -= 1

        probe_abbr_h  = render_text("A", (255, 255, 255), abbr_font).height
        probe_score_h = render_text("0", (255, 255, 255), score_font, bold=True).height
        text_gap      = 4
        block_h       = probe_abbr_h + text_gap + probe_score_h
        abbr_y        = (content_h - block_h) // 2
        score_y       = abbr_y + probe_abbr_h + text_gap

        # ── Away (left) ────────────────────────────────────────────────────
        ax = x_offset + 2
        a_logo = self._get_logo(game.get("away_logo_url"), logo_size)
        if a_logo:
            r, g, b, a = a_logo.split()
            img.paste(Image.merge("RGB", (r, g, b)), (ax, logo_y), a)
            ax += a_logo.size[0] + 3
        _paste(img, render_text(away_abbr,  away_color, abbr_font),             ax, abbr_y,  "lt")
        _paste(img, render_text(away_score, away_color, score_font, bold=True), ax, score_y, "lt")

        # ── Home (right) ───────────────────────────────────────────────────
        rx = x_offset + slot_width - 2
        h_logo = self._get_logo(game.get("home_logo_url"), logo_size)
        if h_logo:
            r, g, b, a = h_logo.split()
            img.paste(Image.merge("RGB", (r, g, b)), (rx - h_logo.size[0], logo_y), a)
            rx -= h_logo.size[0] + 3
        _paste(img, render_text(home_abbr,  home_color, abbr_font),             rx, abbr_y,  "rt")
        _paste(img, render_text(home_score, home_color, score_font, bold=True), rx, score_y, "rt")

        # ── Status ─────────────────────────────────────────────────────────
        _paste(img, render_text(status_text, (140, 140, 140), STATUS_FONT),
               x_offset + slot_width // 2, h - 2, "mb")

    def _draw_stacked(
        self,
        img: Image.Image,
        game: dict[str, Any],
        x_offset: int,
        slot_width: int,
        h: int,
        away_abbr: str, away_score: str, away_color: tuple[int, int, int],
        home_abbr: str, home_score: str, home_color: tuple[int, int, int],
        status_text: str,
    ) -> None:
        """Away top / home bottom. Logo left; abbr+score block centred on the logo."""
        STATUS_H    = 12
        STATUS_FONT = 12

        team_h    = (h - STATUS_H) // 2
        logo_size = max(6, team_h - 4)
        # Single font for inline name + score; snap to largest LoRes size that fits the row
        text_font = max(12, team_h)

        for i, (logo_key, abbr, score, color) in enumerate([
            ("away_logo_url", away_abbr, away_score, away_color),
            ("home_logo_url", home_abbr, home_score, home_color),
        ]):
            y_top  = i * team_h
            logo_y = y_top + (team_h - logo_size) // 2   # centred in row
            logo_cy = logo_y + logo_size // 2             # vertical centre of logo
            lx      = x_offset + 2

            logo = self._get_logo(game.get(logo_key), logo_size)
            if logo:
                r, g, b, a = logo.split()
                img.paste(Image.merge("RGB", (r, g, b)), (lx, logo_y), a)
                lx += logo.size[0] + 3

            # Render name and score inline, both centred on the logo's vertical midpoint
            abbr_img  = render_text(abbr,  color, text_font)
            score_img = render_text(score, color, text_font, bold=True)
            _paste(img, abbr_img,  lx,                        logo_cy, "lm")
            _paste(img, score_img, lx + abbr_img.width + 3,   logo_cy, "lm")

        _paste(img, render_text(status_text, (140, 140, 140), STATUS_FONT),
               x_offset + slot_width // 2, h - 2, "mb")
