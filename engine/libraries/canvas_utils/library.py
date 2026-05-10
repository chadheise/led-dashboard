from __future__ import annotations

from typing import Any, ClassVar

from PIL import Image

from canvas.base import Canvas
from libraries.base import Library


def blit(canvas: Canvas, img: Image.Image, x_offset: int = 0) -> None:
    """Copy img onto canvas with img's left edge at x_offset.

    Positive x_offset shifts the image right; negative scrolls it left.
    Only pixels that fall within canvas bounds are drawn.
    """
    data = img.tobytes()
    w, h = img.size
    dst_start = max(0, x_offset)
    dst_end = min(canvas.width, x_offset + w)
    for dst_x in range(dst_start, dst_end):
        src_x = dst_x - x_offset
        for y in range(h):
            idx = (y * w + src_x) * 3
            canvas.set_pixel(dst_x, y, data[idx], data[idx + 1], data[idx + 2])


def parse_color(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) != 6:
        return (255, 255, 255)
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)

class CanvasUtilsLibrary(Library):
    id: ClassVar[str] = "canvas_utils"
    name: ClassVar[str] = "Canvas Utils"
    description: ClassVar[str] = "Low-level utilities for compositing PIL images onto the LED canvas"
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="3" y="3" width="18" height="18" rx="2"/>'
        '<path d="M3 9h18M9 21V9"/></svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {}

    blit = staticmethod(blit)
