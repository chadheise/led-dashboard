from __future__ import annotations

from typing import Any, ClassVar

from PIL import Image

from canvas.base import Canvas
from app_base import DisplayApp
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import render_text


class TextApp(DisplayApp):
    id: ClassVar[str] = "text"
    name: ClassVar[str] = "Text Display"
    description: ClassVar[str] = "Show a static or scrolling message in any color and font size"
    icon: ClassVar[str] = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="10" x2="16" y2="10"/><line x1="3" y1="14" x2="21" y2="14"/><line x1="3" y1="18" x2="12" y2="18"/></svg>'
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Text Display",
        "properties": {
            "message": {"type": "string", "title": "Message"},
            "color": {"type": "string", "title": "Color", "x-input-type": "color", "default": "#FFFFFF"},
            "scroll": {"type": "boolean", "title": "Scroll text", "default": True},
            "font_size": {
                "type": "integer",
                "title": "Font size",
                "default": 16,
                "minimum": 6,
                "maximum": 64,
            },
        },
        "required": ["message"],
    }

    def __init__(self, config: dict[str, Any], canvas: Canvas, global_config: dict[str, Any] | None = None, library_configs: dict[str, dict[str, Any]] | None = None) -> None:
        super().__init__(config, canvas, global_config, library_configs)
        self._offset = 0
        self._rendered: Image.Image | None = None
        self._text_w = 0

    async def fetch_data(self) -> None:
        pass

    async def on_activate(self) -> None:
        self._build_image()
        self._offset = self.canvas.width

    def _build_image(self) -> None:
        msg = str(self.config.get("message", ""))
        size = int(self.config.get("font_size", 16))
        color = parse_color(str(self.config.get("color", "#FFFFFF")))
        aliasing = bool(self.config.get("aliasing", False))

        img = render_text(msg, color, size, aliasing=aliasing, fixed_h=self.canvas.height)
        self._rendered = img
        self._text_w = img.width

    async def render_frame(self) -> None:
        if self._rendered is None:
            self._build_image()

        scroll = bool(self.config.get("scroll", True))

        if scroll:
            blit(self.canvas, self._rendered, self._offset)
            self._offset -= 2
            if self._offset < -self._text_w:
                self._offset = self.canvas.width
        else:
            x_offset = (self.canvas.width - self._text_w) // 2
            blit(self.canvas, self._rendered, x_offset)
