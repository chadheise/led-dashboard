"""blit() takes a row-wise fast path; it must match the per-pixel reference.

Canvas.paste_image is the generic per-pixel implementation (what blit used to
do inline). BufferedCanvas and CanvasRegion override it for speed, so these
tests check the overrides against that reference across the offset cases the
apps actually produce -- notably marquee's negative scroll offsets and images
larger than the target.
"""
from __future__ import annotations

import pytest
from PIL import Image

from canvas.base import Canvas
from canvas.region import CanvasRegion
from canvas.simulator import SimulatorCanvas


async def _noop_broadcast(_: bytes) -> None:
    pass


def _gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 5 + 1) % 256, (y * 11 + 3) % 256, (x * y + 7) % 256)
    return img


_OFFSETS = [
    (0, 0),
    (5, 3),
    (-7, -2),      # marquee scrolling off the left/top edge
    (-400, 0),     # entirely off-canvas
    (300, 60),     # straddling the right/bottom edge
    (320, 0),      # exactly past the right edge
]


@pytest.mark.parametrize("size", [(320, 64), (40, 12), (500, 100)])
@pytest.mark.parametrize("offset", _OFFSETS)
def test_buffered_paste_matches_per_pixel_reference(
    size: tuple[int, int], offset: tuple[int, int]
) -> None:
    img = _gradient(*size)

    fast = SimulatorCanvas(320, 64, _noop_broadcast)
    fast.paste_image(img, *offset)

    reference = SimulatorCanvas(320, 64, _noop_broadcast)
    Canvas.paste_image(reference, img, *offset)

    assert fast._pixels == reference._pixels


@pytest.mark.parametrize("offset", _OFFSETS)
def test_region_paste_matches_per_pixel_reference(offset: tuple[int, int]) -> None:
    img = _gradient(200, 40)

    fast_parent = SimulatorCanvas(320, 64, _noop_broadcast)
    CanvasRegion(fast_parent, 100, 16, 160, 32).paste_image(img, *offset)

    ref_parent = SimulatorCanvas(320, 64, _noop_broadcast)
    Canvas.paste_image(CanvasRegion(ref_parent, 100, 16, 160, 32), img, *offset)

    assert fast_parent._pixels == ref_parent._pixels


def test_region_paste_stays_inside_its_bounds() -> None:
    """An oversized image must not bleed into a neighbouring region."""
    parent = SimulatorCanvas(320, 64, _noop_broadcast)
    CanvasRegion(parent, 0, 0, 160, 64).paste_image(_gradient(320, 64))

    for y in range(64):
        for x in range(160, 320):
            idx = (y * 320 + x) * 3
            assert parent._pixels[idx:idx + 3] == bytearray(3)


def test_paste_converts_non_rgb_images() -> None:
    canvas = SimulatorCanvas(8, 8, _noop_broadcast)
    canvas.paste_image(Image.new("L", (8, 8), 128))
    assert set(canvas._pixels) == {128}


def test_clear_reuses_the_frame_buffer() -> None:
    """clear() zeroes in place -- reallocating per frame churned GC on the Pi."""
    canvas = SimulatorCanvas(32, 16, _noop_broadcast)
    buffer = canvas._pixels
    canvas.paste_image(_gradient(32, 16))
    canvas.clear()
    assert canvas._pixels is buffer
    assert not any(buffer)
