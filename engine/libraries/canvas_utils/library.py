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
    """
    data = img.tobytes()
    w, h = img.size
    dst_x_start = max(0, x_offset)
    dst_x_end = min(canvas.width, x_offset + w)
    dst_y_start = max(0, y_offset)
    dst_y_end = min(canvas.height, y_offset + h)
    for dst_x in range(dst_x_start, dst_x_end):
        src_x = dst_x - x_offset
        for dst_y in range(dst_y_start, dst_y_end):
            src_y = dst_y - y_offset
            idx = (src_y * w + src_x) * 3
            canvas.set_pixel(dst_x, dst_y, data[idx], data[idx + 1], data[idx + 2])


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
