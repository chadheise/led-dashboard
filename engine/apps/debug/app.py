from __future__ import annotations

from pathlib import Path
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


class DebugApp(DisplayApp):
    id: ClassVar[str] = "debug"
    name: ClassVar[str] = "Debug"
    description: ClassVar[str] = "Fill the display with a solid color, gradient, or stripe pattern for debugging"
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Debug",
        "properties": {
            "pattern": {
                "type": "string",
                "title": "Pattern",
                "enum": ["solid", "gradient", "stripes_vertical", "stripes_horizontal", "stripes_diagonal_45", "stripes_diagonal_neg45"],
                "enumNames": ["Solid", "Gradient (ROYGBV)", "Stripes — Vertical", "Stripes — Horizontal", "Stripes — Diagonal +45°", "Stripes — Diagonal −45°"],
                "default": "solid",
            },
            "color": {
                "type": "string",
                "title": "Color",
                "x-input-type": "color",
                "default": "#FF0000",
            },
            "stripe_width": {
                "type": "integer",
                "title": "Stripe Width (px)",
                "default": 4,
                "minimum": 1,
                "maximum": 32,
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
        pattern = str(self.config.get("pattern", "solid"))
        color = parse_color(str(self.config.get("color", "#FF0000")))
        sw = max(1, int(self.config.get("stripe_width", 4)))

        if pattern == "gradient":
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
        elif pattern in ("stripes_vertical", "stripes_horizontal", "stripes_diagonal_45", "stripes_diagonal_neg45"):
            img = Image.new("RGB", (w, h))
            for y in range(h):
                for x in range(w):
                    if pattern == "stripes_vertical":
                        idx = x
                    elif pattern == "stripes_horizontal":
                        idx = y
                    elif pattern == "stripes_diagonal_45":
                        idx = x + y
                    else:  # stripes_diagonal_neg45
                        idx = x - y
                    pixel = color if (idx // sw) % 2 == 0 else (0, 0, 0)
                    img.putpixel((x, y), pixel)
        else:
            img = Image.new("RGB", (w, h), color)

        self._image = img

    async def render_frame(self) -> None:
        if self._image is None:
            self._build_image()
        blit(self.canvas, self._image)
