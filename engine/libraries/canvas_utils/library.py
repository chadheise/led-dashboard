from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from PIL import Image

from canvas.base import Canvas
from libraries.base import Library


def blit(canvas: Canvas, img: Image.Image, x_offset: int = 0, y_offset: int = 0) -> None:
    """Copy img onto canvas with img's top-left corner at (x_offset, y_offset).

    Positive offsets shift the image right/down; negative values scroll it
    left/up. Only pixels within canvas bounds are drawn.

    Delegates to Canvas.paste_image so buffer-backed canvases copy whole rows
    in C. Compositing a 320x64 frame one pixel at a time from Python cost
    ~20k calls per blit, which kept the Pi pegged and starved the rgbmatrix
    refresh thread.
    """
    canvas.paste_image(img, x_offset, y_offset)


def parse_color(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) != 6:
        return (255, 255, 255)
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)

class CanvasUtilsLibrary(Library):
    id: ClassVar[str] = "canvas_utils"
    name: ClassVar[str] = "Canvas Utils"
    description: ClassVar[str] = "Low-level utilities for compositing PIL images onto the LED canvas"
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    global_config_schema: ClassVar[dict[str, Any]] = {}

    blit = staticmethod(blit)
