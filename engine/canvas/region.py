from __future__ import annotations

from typing import TYPE_CHECKING

from canvas.base import Canvas

if TYPE_CHECKING:
    from PIL import Image


class CanvasRegion(Canvas):
    """A Canvas that renders into a rectangular sub-region of a parent Canvas.

    Coordinates are relative to (0, 0) of this region; set_pixel calls are
    translated and silently clipped at the region boundary. clear() and
    render() are no-ops — the SceneManager owns those calls on the root canvas.
    """

    def __init__(
        self,
        parent: Canvas,
        x_offset: int,
        y_offset: int,
        width: int,
        height: int,
    ) -> None:
        super().__init__(width, height)
        self._parent = parent
        self._x_offset = x_offset
        self._y_offset = y_offset

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self._parent.set_pixel(
                x + self._x_offset,
                y + self._y_offset,
                r, g, b,
            )

    def paste_image(self, img: "Image.Image", x_offset: int = 0, y_offset: int = 0) -> None:
        # Clip to this region first -- the parent only clips at its own bounds,
        # so an oversized image would otherwise bleed into neighbouring regions.
        w, h = img.size
        x0 = max(0, -x_offset)
        y0 = max(0, -y_offset)
        x1 = min(w, self.width - x_offset)
        y1 = min(h, self.height - y_offset)
        if x0 >= x1 or y0 >= y1:
            return
        if (x0, y0, x1, y1) != (0, 0, w, h):
            img = img.crop((x0, y0, x1, y1))
        self._parent.paste_image(
            img,
            x_offset + x0 + self._x_offset,
            y_offset + y0 + self._y_offset,
        )

    def clear(self) -> None:
        pass  # no-op: SceneManager clears the root canvas before each frame

    async def render(self) -> None:
        pass  # no-op: SceneManager renders the root canvas after each frame
