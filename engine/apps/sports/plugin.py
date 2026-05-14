from __future__ import annotations

import datetime
import math
from typing import Any, ClassVar

from PIL import Image, ImageDraw

from canvas.base import Canvas
from plugin_base import DisplayApp
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import load_font
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


def _brighten(color: tuple[int, int, int], minimum: int = 100) -> tuple[int, int, int]:
    """Ensure a team color is bright enough to read on a black LED background."""
    r, g, b = color
    peak = max(r, g, b)
    if peak < minimum:
        scale = minimum / max(peak, 1)
        return (min(255, int(r * scale)), min(255, int(g * scale)), min(255, int(b * scale)))
    return (r, g, b)




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
                "default": {"hours": 24},
            },
            "completed_game_window": {
                "type": "object",
                "title": "Keep completed games for",
                "x-input-type": "duration",
                "x-duration-units": ["days", "hours", "minutes"],
                "default": {"hours": 3},
            },
            "seconds_per_score": {
                "type": "integer",
                "title": "Seconds per score card",
                "default": 5,
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
        self._page_idx = 0
        self._frame_count = 0
        self._logos: dict[str, Image.Image | None] = {}

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

    @staticmethod
    def _logo_size_for_columns(cols: int) -> tuple[int, int]:
        return {1: (20, 20), 2: (16, 16)}.get(cols, (12, 12))

    async def fetch_data(self) -> None:
        favorite_teams = list(self.config.get("favorite_teams") or [])

        games = await self._espn.fetch_scores(
            self._get_leagues(),
            favorite_teams=favorite_teams if favorite_teams else None,
        )

        self._games = self._filter_by_time_window(games)

        n = self._scores_per_screen()
        logo_size = self._logo_size_for_columns(n)
        new_logos = await self._espn.fetch_logos(self._games, logo_size)
        self._logos.update(new_logos)

    def _filter_by_time_window(
        self, games: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        now = datetime.datetime.now(datetime.timezone.utc)
        show_upcoming = bool(self.config.get("show_upcoming_games", True))
        upcoming_secs = _duration_to_seconds(
            self.config.get("upcoming_game_window", {"hours": 24})
        )
        completed_secs = _duration_to_seconds(
            self.config.get("completed_game_window", {"hours": 3})
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

    async def on_activate(self) -> None:
        self._page_idx = 0
        self._frame_count = 0
        await self.fetch_data()

    async def render_frame(self) -> None:
        if not self._games:
            return  # blank canvas — scene manager has already cleared it

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
            self._draw_game_slot(img, game, x_off, actual_w)

        blit(self.canvas, img)

    def _draw_game_slot(
        self,
        img: Image.Image,
        game: dict[str, Any],
        x_offset: int,
        slot_width: int,
    ) -> None:
        draw = ImageDraw.Draw(img)
        h = self.canvas.height
        n = self._scores_per_screen()
        logo_size = self._logo_size_for_columns(n)
        lw = logo_size[0]

        font_size = 18 if slot_width < 100 else 24
        score_font = load_font(font_size)
        label_font = load_font(10 if slot_width < 100 else 12)

        score_y = h // 2

        # Team colors — ensure visible on black background
        away_color = _brighten(parse_color(game.get("away_color") or "aaaaaa"))
        home_color = _brighten(parse_color(game.get("home_color") or "aaaaaa"))

        # ── Away side (left) ────────────────────────────────────────────────
        ax = x_offset + 2
        away_logo = self._logos.get(game.get("away_logo_url") or "")
        if away_logo:
            paste_y = score_y - lw // 2
            # Extract alpha as explicit mask to avoid any RGBA→RGB mode confusion
            r, g, b, a = away_logo.split()
            img.paste(Image.merge("RGB", (r, g, b)), (ax, paste_y), a)
            ax += lw + 2

        away_rank = game.get("away_rank")
        away_prefix = f"#{away_rank} " if away_rank else ""
        away_text = f"{away_prefix}{game['away_abbr']} {game['away_score']}"
        self._draw_text(draw, (ax, score_y), away_text, score_font, away_color, "lm")

        # ── Home side (right) ───────────────────────────────────────────────
        rx = x_offset + slot_width - 2
        home_logo = self._logos.get(game.get("home_logo_url") or "")
        if home_logo:
            paste_y = score_y - lw // 2
            paste_x = rx - lw
            r, g, b, a = home_logo.split()
            img.paste(Image.merge("RGB", (r, g, b)), (paste_x, paste_y), a)
            rx -= lw + 2

        home_rank = game.get("home_rank")
        home_suffix = f" #{home_rank}" if home_rank else ""
        home_text = f"{game['home_score']} {game['home_abbr']}{home_suffix}"
        self._draw_text(draw, (rx, score_y), home_text, score_font, home_color, "rm")

        # ── Status / playoff info (bottom center) ───────────────────────────
        status_text = game.get("series_summary") or str(game.get("status", ""))
        self._draw_text(
            draw, (x_offset + slot_width // 2, h - 3),
            status_text, label_font, (140, 140, 140), "mb",
        )

    @staticmethod
    def _draw_text(
        draw: ImageDraw.ImageDraw,
        xy: tuple[int, int],
        text: str,
        font: Any,
        fill: tuple[int, int, int],
        anchor: str,
    ) -> None:
        try:
            draw.text(xy, text, font=font, fill=fill, anchor=anchor)
        except TypeError:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            fx = {"l": xy[0], "m": xy[0] - tw // 2, "r": xy[0] - tw}[anchor[0]]
            fy = {"t": xy[1], "m": xy[1] - th // 2, "b": xy[1] - th}[anchor[1]]
            draw.text((fx, fy - bbox[1]), text, font=font, fill=fill)
