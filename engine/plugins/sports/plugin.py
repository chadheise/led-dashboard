from __future__ import annotations

from typing import Any, ClassVar

import httpx
from PIL import Image, ImageDraw

from canvas.base import Canvas
from plugin_base import DisplayApp
from plugins._helpers import blit, load_font


_SPORT_MAP: dict[str, str] = {
    "nfl": "football",
    "nba": "basketball",
    "mlb": "baseball",
    "nhl": "hockey",
}


class SportsApp(DisplayApp):
    id: ClassVar[str] = "sports"
    name: ClassVar[str] = "Sports Scores"
    description: ClassVar[str] = "Live scores from the ESPN API — NFL, NBA, MLB, and NHL, rotating through active games"
    icon: ClassVar[str] = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3v8a5 5 0 0010 0V3H7z"/><path d="M7 6H5a1.5 1.5 0 000 3h2"/><path d="M17 6h2a1.5 1.5 0 010 3h-2"/><line x1="12" y1="16" x2="12" y2="20"/><line x1="9" y1="20" x2="15" y2="20"/></svg>'
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Sports Scores",
        "properties": {
            "league": {
                "type": "string",
                "title": "League",
                "enum": ["nfl", "nba", "mlb", "nhl"],
                "default": "nfl",
            },
            "frames_per_game": {
                "type": "integer",
                "title": "Frames per score card",
                "default": 90,
                "minimum": 15,
            },
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 60,
                "minimum": 10,
            },
            "scene_duration": {
                "type": "number",
                "title": "Scene duration (s)",
                "default": 60,
            },
        },
        "required": ["league"],
    }

    def __init__(self, config: dict[str, Any], canvas: Canvas) -> None:
        super().__init__(config, canvas)
        self._games: list[dict[str, Any]] = []
        self._game_idx = 0
        self._frame_count = 0

    async def fetch_data(self) -> None:
        league = self.config.get("league", "nfl")
        sport = _SPORT_MAP.get(league, "football")
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
            data = resp.json()
        except Exception:
            return

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
            state: str = status_type.get("state", "pre")
            status_detail: str = status_type.get("shortDetail", "Scheduled")

            games.append(
                {
                    "home_abbr": home.get("team", {}).get("abbreviation", "???"),
                    "away_abbr": away.get("team", {}).get("abbreviation", "???"),
                    "home_score": home.get("score", "-"),
                    "away_score": away.get("score", "-"),
                    "status": status_detail,
                    "state": state,
                }
            )

        if games:
            self._games = games

    async def on_activate(self) -> None:
        self._game_idx = 0
        self._frame_count = 0

    async def render_frame(self) -> None:
        if not self._games:
            self._draw_no_games()
            return

        self._draw_game(self._games[self._game_idx])

        frames_per_game = int(self.config.get("frames_per_game", 90))
        self._frame_count += 1
        if self._frame_count >= frames_per_game:
            self._frame_count = 0
            self._game_idx = (self._game_idx + 1) % len(self._games)

    def _draw_game(self, game: dict[str, Any]) -> None:
        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        draw = ImageDraw.Draw(img)

        score_font = load_font(24)
        label_font = load_font(12)

        # Away team left, home team right, status bottom center
        away_text = f"{game['away_abbr']}  {game['away_score']}"
        home_text = f"{game['home_score']}  {game['home_abbr']}"
        vs_text = "—"
        status_text = str(game["status"])

        for font, text, xy, anchor in [
            (score_font, away_text, (8, 16), "lm"),
            (score_font, vs_text, (self.canvas.width // 2, 16), "mm"),
            (score_font, home_text, (self.canvas.width - 8, 16), "rm"),
            (label_font, status_text, (self.canvas.width // 2, self.canvas.height - 8), "mb"),
        ]:
            try:
                draw.text(xy, text, font=font, fill=(200, 200, 200), anchor=anchor)
            except TypeError:
                # anchor not supported by bitmap fonts — fall back to manual position
                bbox = draw.textbbox((0, 0), text, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                fx = {"l": xy[0], "m": xy[0] - tw // 2, "r": xy[0] - tw}[anchor[0]]
                fy = {"t": xy[1], "m": xy[1] - th // 2, "b": xy[1] - th}[anchor[1]]
                draw.text((fx, fy - bbox[1]), text, font=font, fill=(200, 200, 200))

        blit(self.canvas, img)

    def _draw_no_games(self) -> None:
        league = str(self.config.get("league", "nfl")).upper()
        font = load_font(14)
        msg = f"No {league} games"
        dummy = Image.new("RGB", (1, 1))
        bbox = ImageDraw.Draw(dummy).textbbox((0, 0), msg, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        draw = ImageDraw.Draw(img)
        x = (self.canvas.width - tw) // 2
        y = (self.canvas.height - th) // 2 - bbox[1]
        draw.text((x, y), msg, font=font, fill=(80, 80, 80))
        blit(self.canvas, img)
