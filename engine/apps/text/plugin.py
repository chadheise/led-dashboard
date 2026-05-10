from __future__ import annotations

from typing import Any, ClassVar

from PIL import Image, ImageDraw

from canvas.base import Canvas
from plugin_base import DisplayApp
from apps._helpers import blit, load_font, parse_color


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
                "minimum": 8,
                "maximum": 64,
            },
            "scene_duration": {
                "type": "number",
                "title": "Scene duration (s)",
                "default": 30,
            },
        },
        "required": ["message"],
    }

    def __init__(self, config: dict[str, Any], canvas: Canvas, global_config: dict[str, Any] | None = None) -> None:
        super().__init__(config, canvas, global_config)
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
        font = load_font(size)

        dummy = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(dummy)
        bbox = draw.textbbox((0, 0), msg, font=font)
        text_w = max(bbox[2] - bbox[0], 1)
        text_h = bbox[3] - bbox[1]

        img = Image.new("RGB", (text_w, self.canvas.height))
        draw = ImageDraw.Draw(img)
        y = (self.canvas.height - text_h) // 2 - bbox[1]
        draw.text((0, y), msg, font=font, fill=color)

        self._rendered = img
        self._text_w = text_w

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
