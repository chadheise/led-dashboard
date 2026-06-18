"""Measured layout primitives for composing pixel-exact LED screens.

The model is *measure-then-place*: every element is pre-rendered to a PIL
image (so its size is exact, never estimated), regions carve up the screen
with integer math, and :meth:`Frame.place` refuses to draw an element that
doesn't fit its region — overflow is an error, degradation is an explicit
decision the caller makes *before* placing. Each placement is recorded as a
:class:`PlacedBox`, giving tests an audit trail to assert "nothing overlaps,
nothing is cut off, the score is the biggest thing on screen".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image

from libraries.base import Library
from libraries.text_renderer.library import _ALL_PIXEL_SIZES, render_text


class LayoutOverflow(Exception):
    """An element was placed into a region too small to hold it."""


@dataclass(frozen=True)
class Region:
    """An axis-aligned rectangle in screen coordinates."""

    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def inset(self, dx: int, dy: int | None = None) -> Region:
        dy = dx if dy is None else dy
        return Region(self.x + dx, self.y + dy, max(0, self.w - 2 * dx), max(0, self.h - 2 * dy))

    def take_left(self, px: int) -> tuple[Region, Region]:
        px = max(0, min(px, self.w))
        return (
            Region(self.x, self.y, px, self.h),
            Region(self.x + px, self.y, self.w - px, self.h),
        )

    def take_right(self, px: int) -> tuple[Region, Region]:
        px = max(0, min(px, self.w))
        return (
            Region(self.right - px, self.y, px, self.h),
            Region(self.x, self.y, self.w - px, self.h),
        )

    def take_top(self, px: int) -> tuple[Region, Region]:
        px = max(0, min(px, self.h))
        return (
            Region(self.x, self.y, self.w, px),
            Region(self.x, self.y + px, self.w, self.h - px),
        )

    def take_bottom(self, px: int) -> tuple[Region, Region]:
        px = max(0, min(px, self.h))
        return (
            Region(self.x, self.bottom - px, self.w, px),
            Region(self.x, self.y, self.w, self.h - px),
        )

    def split_rows(self, n: int) -> list[Region]:
        """Split into n equal rows; the last row absorbs any remainder."""
        row_h = self.h // n
        rows = [Region(self.x, self.y + i * row_h, self.w, row_h) for i in range(n - 1)]
        last_y = self.y + (n - 1) * row_h
        rows.append(Region(self.x, last_y, self.w, self.bottom - last_y))
        return rows

    def split_cols(self, n: int) -> list[Region]:
        """Split into n equal columns; the last column absorbs any remainder."""
        col_w = self.w // n
        cols = [Region(self.x + i * col_w, self.y, col_w, self.h) for i in range(n - 1)]
        last_x = self.x + (n - 1) * col_w
        cols.append(Region(last_x, self.y, self.right - last_x, self.h))
        return cols


@dataclass(frozen=True)
class PlacedBox:
    """Record of one element placed on a Frame."""

    name: str        # e.g. "away.score", "home.logo", "footer.status"
    x: int
    y: int
    w: int
    h: int
    priority: int    # 0 = most important
    clipped: bool    # True if the image exceeded its region and was clipped

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def intersects(self, other: PlacedBox, min_gap: int = 0) -> bool:
        return (
            self.x - min_gap < other.right
            and other.x < self.right + min_gap
            and self.y - min_gap < other.bottom
            and other.y < self.bottom + min_gap
        )


_ANCHOR_X = {"l": 0.0, "m": 0.5, "r": 1.0}
_ANCHOR_Y = {"t": 0.0, "m": 0.5, "b": 1.0}


class Frame:
    """An RGB image plus a record of every placement made on it."""

    def __init__(self, w: int, h: int) -> None:
        self.image = Image.new("RGB", (w, h), (0, 0, 0))
        self.boxes: list[PlacedBox] = []

    @property
    def region(self) -> Region:
        return Region(0, 0, self.image.width, self.image.height)

    def place(
        self,
        name: str,
        img: Image.Image,
        region: Region,
        anchor: str = "lt",
        priority: int = 1,
        allow_clip: bool = False,
    ) -> PlacedBox:
        """Paste img into region at the given two-char anchor and record the box.

        anchor[0] ∈ {l, m, r} positions horizontally; anchor[1] ∈ {t, m, b}
        vertically. If the image exceeds the region (or the region itself is
        degenerate) a LayoutOverflow is raised unless allow_clip=True, in
        which case the visible portion is drawn and the box marked clipped.
        RGBA images composite through their alpha channel; RGB images paste
        opaque (their black background is the card background).
        """
        iw, ih = img.size
        clipped = iw > region.w or ih > region.h or region.w <= 0 or region.h <= 0
        if clipped and not allow_clip:
            raise LayoutOverflow(
                f"{name!r} is {iw}x{ih} but its region is {region.w}x{region.h} "
                f"at ({region.x},{region.y})"
            )

        x = region.x + round(_ANCHOR_X[anchor[0]] * (region.w - iw))
        y = region.y + round(_ANCHOR_Y[anchor[1]] * (region.h - ih))

        if clipped:
            crop = (
                max(0, region.x - x),
                max(0, region.y - y),
                min(iw, region.right - x),
                min(ih, region.bottom - y),
            )
            if crop[2] <= crop[0] or crop[3] <= crop[1]:
                box = PlacedBox(name, region.x, region.y, 0, 0, priority, True)
                self.boxes.append(box)
                return box
            img = img.crop(crop)
            x, y = max(x, region.x), max(y, region.y)
            iw, ih = img.size

        if img.mode == "RGBA":
            self.image.paste(img.convert("RGB"), (x, y), img.split()[3])
        else:
            self.image.paste(img, (x, y))

        box = PlacedBox(name, x, y, iw, ih, priority, clipped)
        self.boxes.append(box)
        return box

    def mark(
        self, name: str, region: Region, priority: int = 1
    ) -> PlacedBox:
        """Record a box for something drawn manually (e.g. a divider line)."""
        box = PlacedBox(name, region.x, region.y, region.w, region.h, priority, False)
        self.boxes.append(box)
        return box

    def overlapping_pairs(
        self, min_gap: int = 0, ignore: Iterable[tuple[str, str]] = ()
    ) -> list[tuple[PlacedBox, PlacedBox]]:
        """Return every pair of placed boxes that overlap (or sit closer than min_gap)."""
        ignored = {frozenset(pair) for pair in ignore}
        pairs: list[tuple[PlacedBox, PlacedBox]] = []
        for i, a in enumerate(self.boxes):
            for b in self.boxes[i + 1:]:
                if frozenset((a.name, b.name)) in ignored:
                    continue
                if a.intersects(b, min_gap):
                    pairs.append((a, b))
        return pairs


# ── Text measurement helpers ──────────────────────────────────────────────────


@dataclass(frozen=True)
class TextSpec:
    text: str
    size: int
    bold: bool = False


# Design sizes that render crisply (pixel fonts), largest first.
PIXEL_SIZES: list[int] = sorted(_ALL_PIXEL_SIZES, reverse=True)
_PIXEL_MAX = PIXEL_SIZES[0]


def text_img(spec: TextSpec, color: tuple[int, int, int]) -> Image.Image:
    return render_text(spec.text, color, spec.size, bold=spec.bold)


def measure(spec: TextSpec) -> tuple[int, int]:
    """Exact rendered pixel size of a TextSpec (render-based, never estimated)."""
    img = render_text(spec.text, (255, 255, 255), spec.size, bold=spec.bold)
    return img.size


def fit_font_size(
    text: str,
    max_h: int,
    max_w: int | None = None,
    *,
    bold: bool = False,
    allow_large: bool = False,
) -> int | None:
    """Largest font size whose actual render of `text` fits max_h (and max_w).

    Only crisp pixel-font design sizes are tried by default; allow_large=True
    additionally tries sizes above 28 (Roboto) for big elements like scores.
    Returns None when even the smallest pixel font doesn't fit.
    """
    candidates: list[int] = []
    if allow_large and max_h >= 22:
        # Above 21px the largest pixel font (LoRes28, 19px digits) wastes 3+px
        # of budget, so try Roboto sizes too. Rendered glyph height runs ~30%
        # below the nominal size; probing from 1.5x the height budget down to
        # 29 always brackets the best size.
        candidates.extend(range(min(96, max_h * 3 // 2), 28, -1))
    candidates.extend(PIXEL_SIZES)
    if bold:
        # LoRes28 ships no bold variant — "bold" 28 renders thin, which reads
        # wrong next to truly bold sizes. LoRes22 bold or Roboto cover it.
        candidates = [s for s in candidates if s != 28]

    for size in candidates:
        w, h = measure(TextSpec(text, size, bold))
        if h <= max_h and (max_w is None or w <= max_w):
            return size
    return None


def first_fitting(max_w: int, candidates: Sequence[TextSpec]) -> TextSpec | None:
    """First candidate whose actual render fits max_w; None if none fit."""
    for spec in candidates:
        if not spec.text:
            continue
        w, _h = measure(spec)
        if w <= max_w:
            return spec
    return None


# ── Library wrapper (engine convention) ────────────────────────────────────────


class LayoutLibrary(Library):
    id: ClassVar[str] = "layout"
    name: ClassVar[str] = "Layout"
    description: ClassVar[str] = (
        "Measured layout primitives — regions, anchored placement with overflow "
        "detection, and exact text fitting — for pixel-precise app screens"
    )
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    global_config_schema: ClassVar[dict[str, Any]] = {}

    Region = Region
    Frame = Frame
    PlacedBox = PlacedBox
    TextSpec = TextSpec
    LayoutOverflow = LayoutOverflow
    text_img = staticmethod(text_img)
    measure = staticmethod(measure)
    fit_font_size = staticmethod(fit_font_size)
    first_fitting = staticmethod(first_fitting)
