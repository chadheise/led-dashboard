from __future__ import annotations

from typing import Any, ClassVar

from PIL import Image

from canvas.base import Canvas
from app_base import DisplayApp
from libraries.canvas_utils.library import blit, parse_color

_ROYGBV: list[tuple[int, int, int]] = [
    (255, 0, 0),
    (255, 127, 0),
    (255, 255, 0),
    (0, 255, 0),
    (0, 0, 255),
    (148, 0, 211),
]


class ColorApp(DisplayApp):
    id: ClassVar[str] = "color"
    name: ClassVar[str] = "Color"
    description: ClassVar[str] = "Fill the display with a solid color or a ROYGBV rainbow gradient"
    icon: ClassVar[str] = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 0 20"/></svg>'
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Color",
        "properties": {
            "mode": {
                "type": "string",
                "title": "Display Mode",
                "enum": ["solid", "gradient"],
                "default": "solid",
            },
            "color": {
                "type": "string",
                "title": "Color",
                "x-input-type": "color",
                "default": "#FF0000",
            },
        },
    }

    def __init__(
        self,
        config: dict[str, Any],
        canvas: Canvas,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(config, canvas, global_config, library_configs)
        self._image: Image.Image | None = None

    async def fetch_data(self) -> None:
        pass

    async def on_activate(self) -> None:
        self._build_image()

    def _build_image(self) -> None:
        w, h = self.canvas.width, self.canvas.height
        mode = str(self.config.get("mode", "solid"))

        if mode == "gradient":
            img = Image.new("RGB", (w, h))
            stops = _ROYGBV
            n = len(stops) - 1
            for x in range(w):
                t = x / max(w - 1, 1) * n
                i = min(int(t), n - 1)
                f = t - i
                r1, g1, b1 = stops[i]
                r2, g2, b2 = stops[i + 1]
                pixel = (
                    int(r1 + (r2 - r1) * f),
                    int(g1 + (g2 - g1) * f),
                    int(b1 + (b2 - b1) * f),
                )
                for y in range(h):
                    img.putpixel((x, y), pixel)
        else:
            color = parse_color(str(self.config.get("color", "#FF0000")))
            img = Image.new("RGB", (w, h), color)

        self._image = img

    async def render_frame(self) -> None:
        if self._image is None:
            self._build_image()
        blit(self.canvas, self._image)
