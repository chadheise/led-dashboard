from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from PIL import Image

from app_base import DisplayApp
from canvas.base import Canvas
from grid import SizeConstraints
from libraries.canvas_utils.library import blit, parse_color
from libraries.spotify.library import SpotifyLibrary
from libraries.text_renderer.library import TextRendererLibrary


class SpotifyApp(DisplayApp):
    id: ClassVar[str] = "spotify"
    name: ClassVar[str] = "Spotify Now Playing"
    description: ClassVar[str] = (
        "Displays the track currently playing on Spotify — "
        "scrolling title, artist, album art thumbnail, and progress bar"
    )
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    libraries: ClassVar[list[str]] = ["spotify", "text_renderer"]
    size_constraints: ClassVar[SizeConstraints] = SizeConstraints(min_width=64, min_height=16)
    global_config_schema: ClassVar[dict[str, Any]] = {}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Spotify Now Playing",
        "properties": {
            "show_album_art": {
                "type": "boolean",
                "title": "Show album art",
                "default": True,
            },
            "show_progress": {
                "type": "boolean",
                "title": "Show progress bar",
                "default": True,
            },
            "scroll_speed": {
                "type": "integer",
                "title": "Scroll speed (px/frame)",
                "default": 2,
                "minimum": 1,
                "maximum": 8,
            },
            "accent_color": {
                "type": "string",
                "title": "Accent color",
                "x-input-type": "color",
                "default": "#1DB954",
            },
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 10,
                "minimum": 5,
            },
        },
        "required": [],
    }

    def __init__(
        self,
        config: dict[str, Any],
        canvas: Canvas,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(config, canvas, global_config, library_configs)
        self._spotify = SpotifyLibrary(self.library_configs.get("spotify", {}))
        self._renderer = TextRendererLibrary(self.library_configs.get("text_renderer", {}))

        self._track: dict[str, Any] | None = None
        self._album_art: Image.Image | None = None
        self._last_art_url: str | None = None

        self._title_img: Image.Image | None = None
        self._artist_img: Image.Image | None = None
        self._title_offset: float = 0.0
        self._artist_offset: float = 0.0

    async def should_display(self) -> bool:
        return bool(self._track and self._track.get("is_playing"))

    async def on_activate(self) -> None:
        self._title_offset = float(self.canvas.width)
        self._artist_offset = float(self.canvas.width)
        await self.fetch_data()

    async def fetch_data(self) -> None:
        try:
            track = await self._spotify.get_currently_playing()
        except Exception:
            return

        if track is None:
            self._track = None
            return

        prev = self._track
        track_changed = (
            prev is None
            or prev.get("title") != track.get("title")
            or prev.get("artist") != track.get("artist")
        )
        art_changed = track.get("album_art_url") != self._last_art_url

        self._track = track

        if track_changed:
            self._build_text_images()
            self._title_offset = float(self.canvas.width)
            self._artist_offset = float(self.canvas.width)

        if art_changed and track.get("album_art_url"):
            show_art = bool(self.config.get("show_album_art", True))
            if show_art:
                art_size = self._art_size()
                self._album_art = await self._spotify.fetch_album_art(
                    track["album_art_url"], art_size
                )
            self._last_art_url = track.get("album_art_url")

    def _art_size(self) -> int:
        show_progress = bool(self.config.get("show_progress", True))
        h = self.canvas.height
        bar_h = 3 if show_progress else 0
        return min(h - bar_h, 32)

    def _text_area_x(self) -> int:
        show_art = bool(self.config.get("show_album_art", True))
        if show_art and self._album_art is not None:
            return self._art_size() + 2
        return 0

    def _build_text_images(self) -> None:
        if not self._track:
            return
        accent = parse_color(str(self.config.get("accent_color", "#1DB954")))
        white = (255, 255, 255)
        h = self.canvas.height
        show_progress = bool(self.config.get("show_progress", True))
        bar_h = 3 if show_progress else 0
        text_area_h = h - bar_h
        line_h = max(self._renderer.min_pixel_font_size, text_area_h // 2)

        self._title_img = self._renderer.render_text(
            self._track["title"], white, line_h, bold=True
        )
        self._artist_img = self._renderer.render_text(
            self._track["artist"],
            tuple(max(0, c - 60) for c in accent),  # type: ignore[arg-type]
            line_h,
            bold=False,
        )

    async def render_frame(self) -> None:
        if not self._track or not self._track.get("is_playing"):
            self._draw_not_playing()
            return
        self._draw_playing()

    def _draw_playing(self) -> None:
        if self._title_img is None:
            self._build_text_images()
        if self._title_img is None:
            return

        w, h = self.canvas.width, self.canvas.height
        show_progress = bool(self.config.get("show_progress", True))
        bar_h = 3 if show_progress else 0
        text_area_h = h - bar_h
        speed = int(self.config.get("scroll_speed", 2))

        img = Image.new("RGB", (w, h), (0, 0, 0))

        # Album art
        if bool(self.config.get("show_album_art", True)) and self._album_art is not None:
            art_size = self._album_art.height
            y_off = (text_area_h - art_size) // 2
            img.paste(self._album_art, (0, max(0, y_off)))

        text_x = self._text_area_x()
        text_w = w - text_x
        line_h = max(self._renderer.min_pixel_font_size, text_area_h // 2)

        # Title scroll
        title_img = self._title_img
        if title_img is not None:
            self._title_offset -= speed
            if self._title_offset <= -title_img.width:
                self._title_offset = float(text_w)
            tx = int(self._title_offset)
            title_y = max(0, (text_area_h // 2 - line_h) // 2)
            while tx < text_w:
                img.paste(title_img, (text_x + tx, title_y))
                tx += title_img.width + text_w // 4

        # Artist scroll
        artist_img = self._artist_img
        if artist_img is not None:
            self._artist_offset -= speed
            if self._artist_offset <= -artist_img.width:
                self._artist_offset = float(text_w)
            ax = int(self._artist_offset)
            artist_y = text_area_h // 2 + max(0, (text_area_h // 2 - line_h) // 2)
            while ax < text_w:
                img.paste(artist_img, (text_x + ax, artist_y))
                ax += artist_img.width + text_w // 4

        # Progress bar
        if show_progress and self._track:
            duration = self._track.get("duration_ms", 0)
            progress = self._track.get("progress_ms", 0)
            if duration > 0:
                accent = parse_color(str(self.config.get("accent_color", "#1DB954")))
                filled_w = int(w * progress / duration)
                bar_y = h - bar_h
                for py in range(bar_y, h):
                    for px in range(filled_w):
                        img.putpixel((px, py), accent)
                    dim = tuple(max(0, c - 140) for c in accent)
                    for px in range(filled_w, w):
                        img.putpixel((px, py), dim)

        blit(self.canvas, img)

    def _draw_not_playing(self) -> None:
        accent = parse_color(str(self.config.get("accent_color", "#1DB954")))
        w, h = self.canvas.width, self.canvas.height
        text_img = self._renderer.render_text("Not Playing", accent, h // 2, bold=False)
        img = Image.new("RGB", (w, h), (0, 0, 0))
        x = (w - text_img.width) // 2
        y = (h - text_img.height) // 2
        img.paste(text_img, (max(0, x), max(0, y)))
        blit(self.canvas, img)
