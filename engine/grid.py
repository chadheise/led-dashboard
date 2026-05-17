from __future__ import annotations

from dataclasses import dataclass

from canvas.base import Canvas
from canvas.region import CanvasRegion


def split_horizontal(canvas: Canvas, n: int) -> list[CanvasRegion]:
    """Split canvas into n equal-width CanvasRegion columns.

    The last column absorbs any pixel remainder. If n <= 0, returns a single
    region covering the full canvas.
    """
    if n <= 0:
        n = 1
    slot_w = canvas.width // n
    regions: list[CanvasRegion] = []
    for i in range(n):
        x_off = i * slot_w
        w = slot_w if i < n - 1 else canvas.width - x_off
        regions.append(CanvasRegion(canvas, x_off, 0, w, canvas.height))
    return regions


def split_vertical(canvas: Canvas, n: int) -> list[CanvasRegion]:
    """Split canvas into n equal-height CanvasRegion rows.

    The last row absorbs any pixel remainder. If n <= 0, returns a single
    region covering the full canvas.
    """
    if n <= 0:
        n = 1
    slot_h = canvas.height // n
    regions: list[CanvasRegion] = []
    for i in range(n):
        y_off = i * slot_h
        h = slot_h if i < n - 1 else canvas.height - y_off
        regions.append(CanvasRegion(canvas, 0, y_off, canvas.width, h))
    return regions


@dataclass(frozen=True)
class SizeConstraints:
    """Minimum pixel dimensions an app needs to render sensibly.

    Used by the SceneManager to warn when an app is placed into a region that
    is likely too small. Not enforced — the app still runs.
    """
    min_width: int = 1
    min_height: int = 1

    def satisfied_by(self, canvas: Canvas) -> bool:
        return canvas.width >= self.min_width and canvas.height >= self.min_height
