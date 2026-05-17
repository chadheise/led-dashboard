from __future__ import annotations

from canvas.base import Canvas


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

    def clear(self) -> None:
        pass  # no-op: SceneManager clears the root canvas before each frame

    async def render(self) -> None:
        pass  # no-op: SceneManager renders the root canvas after each frame
