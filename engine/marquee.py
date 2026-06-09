from __future__ import annotations

from typing import Literal

from PIL import Image

from canvas.base import Canvas
from libraries.canvas_utils.library import blit


class Marquee:
    """Stateful directional scroller for a PIL image onto a Canvas.

    Two modes:
    - loop=True  (default): content scrolls continuously; seamless wrap using
                            tile-and-blit so any gap is filled automatically.
    - loop=False           : content enters from one edge, exits the other, then
                            re-enters from the same starting edge (ticker mode).

    Usage::

        marquee = Marquee(direction="left", speed=2.0, loop=False)
        # in on_activate:
        marquee.reset(canvas)
        # in render_frame:
        marquee.render(canvas, image)
    """

    def __init__(
        self,
        direction: Literal["left", "right", "up", "down"] = "left",
        speed: float = 2.0,
        loop: bool = True,
    ) -> None:
        self.direction = direction
        self.speed = speed
        self.loop = loop
        self._offset: float | None = None  # None = auto-initialise on first render

    # ── Public API ─────────────────────────────────────────────────────────────

    def reset(self, canvas: Canvas) -> None:
        """Reset scroll position to the start for the configured direction/mode.

        Call this in on_activate() or whenever the content image changes so the
        animation restarts cleanly.
        """
        if self.loop:
            self._offset = 0.0
        else:
            # Enter from the incoming edge (content starts just off-screen)
            if self.direction in ("left", "up"):
                dim = canvas.width if self.direction == "left" else canvas.height
                self._offset = float(dim)
            else:
                # right/down: starts off-screen to the left/top; img size unknown
                # here, so defer to first render() call.
                self._offset = None

    def render(self, canvas: Canvas, img: Image.Image) -> None:
        """Advance the scroll position and draw *img* onto *canvas*.

        For loop=True the image tiles seamlessly to cover the full canvas
        dimension. For loop=False a single copy scrolls in and out.
        """
        horiz = self.direction in ("left", "right")
        canvas_dim = canvas.width if horiz else canvas.height
        img_dim = img.width if horiz else img.height

        # Initialise offset on first call if reset() was not called yet
        if self._offset is None:
            if self.loop or self.direction in ("left", "up"):
                self._offset = float(canvas_dim) if not self.loop else 0.0
            else:
                self._offset = float(-img_dim)

        # Advance
        if self.direction in ("left", "up"):
            self._offset -= self.speed
        else:
            self._offset += self.speed

        off = int(self._offset)

        if self.loop:
            # Keep offset in [-img_dim, 0) for left/up, or (0, img_dim] for right/down
            if self.direction in ("left", "up"):
                if self._offset <= -img_dim:
                    self._offset += img_dim
            else:
                if self._offset >= img_dim:
                    self._offset -= img_dim

            # Tile: start one image-width before current position and draw until
            # the canvas dimension is covered.  Works for any ratio of img to canvas.
            pos = off - img_dim
            while pos < canvas_dim:
                if horiz:
                    blit(canvas, img, x_offset=pos)
                else:
                    blit(canvas, img, y_offset=pos)
                pos += img_dim
        else:
            # Single pass, re-enter from the same edge when fully off-screen
            if horiz:
                blit(canvas, img, x_offset=off)
            else:
                blit(canvas, img, y_offset=off)

            if self.direction in ("left", "up"):
                if self._offset < -img_dim:
                    self._offset = float(canvas_dim)
            else:
                if self._offset > canvas_dim:
                    self._offset = float(-img_dim)
