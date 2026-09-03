"""HardwareCanvas pushes each frame to the panel in one bulk SetImage call.

The bulk path has to land every pixel exactly where the original per-pixel
_logical_to_physical mapping put it -- a mistake here scrambles the wall and is
invisible in the simulator -- so these tests compare the two implementations
pixel for pixel across every supported panel layout.
"""
from __future__ import annotations

import sys
import types

import pytest
from PIL import Image


# ── fake rgbmatrix driver ─────────────────────────────────────────────────────

class _FakeFrameCanvas:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.brightness = 100
        self.pixels: dict[tuple[int, int], tuple[int, int, int]] = {}

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        self.pixels[(x, y)] = (r, g, b)

    def SetImage(self, image: Image.Image, offset_x: int = 0, offset_y: int = 0) -> None:
        # Mirrors the binding's reference implementation: copy every pixel of
        # the image onto the canvas at the given offset.
        assert image.mode == "RGB"
        px = image.load()
        for y in range(image.height):
            for x in range(image.width):
                self.SetPixel(x + offset_x, y + offset_y, *px[x, y])

    def Clear(self) -> None:
        self.pixels.clear()


class _FakeMatrix:
    def __init__(self, options: object) -> None:
        self.options = options
        self.brightness = 100
        self._width = options.cols * options.chain_length  # type: ignore[attr-defined]
        self._height = options.rows * options.parallel  # type: ignore[attr-defined]
        self.swaps = 0

    def CreateFrameCanvas(self) -> _FakeFrameCanvas:
        return _FakeFrameCanvas(self._width, self._height)

    def SwapOnVSync(self, canvas: _FakeFrameCanvas) -> _FakeFrameCanvas:
        self.swaps += 1
        self.displayed = canvas
        return _FakeFrameCanvas(self._width, self._height)


class _FakeOptions:
    def __init__(self) -> None:
        self.rows = 32
        self.cols = 32
        self.chain_length = 1
        self.parallel = 1


@pytest.fixture
def fake_rgbmatrix(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("rgbmatrix")
    module.RGBMatrix = _FakeMatrix  # type: ignore[attr-defined]
    module.RGBMatrixOptions = _FakeOptions  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rgbmatrix", module)


# ── helpers ───────────────────────────────────────────────────────────────────

async def _noop_broadcast(_: bytes) -> None:
    pass


def _make_canvas(hw_cfg: dict, width: int, height: int):
    from canvas.hardware import HardwareCanvas

    return HardwareCanvas(width, height, hw_cfg, _noop_broadcast)


def _fill_distinct(canvas) -> None:
    """Give every pixel a unique colour so any misplacement is detectable."""
    for y in range(canvas.height):
        for x in range(canvas.width):
            n = y * canvas.width + x
            canvas.set_pixel(x, y, (n % 251) + 1, (n // 251) % 256, (x * 7 + y * 13) % 256)


def _expected_physical(canvas) -> dict[tuple[int, int], tuple[int, int, int]]:
    """Reference mapping: _logical_to_physical applied to every logical pixel."""
    out: dict[tuple[int, int], tuple[int, int, int]] = {}
    for y in range(canvas.height):
        for x in range(canvas.width):
            idx = (y * canvas.width + x) * 3
            out[canvas._logical_to_physical(x, y)] = (
                canvas._pixels[idx],
                canvas._pixels[idx + 1],
                canvas._pixels[idx + 2],
            )
    return out


def _logical_size(hw_cfg: dict) -> tuple[int, int]:
    """Logical canvas size implied by a panel grid, per the config.yaml rules:
    landscape panels contribute cols x rows, portrait panels rows x cols.
    """
    rows, cols = hw_cfg["rows"], hw_cfg["cols"]
    tile_w, tile_h = (rows, cols) if hw_cfg["rotation"] in (90, 270) else (cols, rows)
    return hw_cfg["chain_length"] * tile_w, hw_cfg["parallel"] * tile_h


_LAYOUTS = [
    pytest.param({"rotation": 0, "chain_length": 3}, id="landscape"),
    pytest.param({"rotation": 180, "chain_length": 3}, id="landscape-180"),
    pytest.param({"rotation": 90, "chain_length": 4}, id="portrait-90"),
    pytest.param({"rotation": 270, "chain_length": 4}, id="portrait-270"),
    pytest.param(
        {"rotation": 270, "chain_length": 4, "alternate_rotation": True},
        id="portrait-zigzag",
    ),
    pytest.param({"rotation": 90, "chain_length": 10}, id="production-320x64"),
    pytest.param({"rotation": 0, "chain_length": 2, "parallel": 2}, id="two-chains"),
    pytest.param({"rotation": 90, "chain_length": 2, "parallel": 2}, id="two-chains-portrait"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", _LAYOUTS)
async def test_bulk_frame_matches_per_pixel_mapping(
    fake_rgbmatrix: None, overrides: dict
) -> None:
    hw_cfg = {"rows": 32, "cols": 64, "chain_length": 1, "parallel": 1, **overrides}
    canvas = _make_canvas(hw_cfg, *_logical_size(hw_cfg))
    _fill_distinct(canvas)

    await canvas.render()

    assert canvas._matrix.displayed.pixels == _expected_physical(canvas)


@pytest.mark.asyncio
async def test_every_physical_pixel_is_written(fake_rgbmatrix: None) -> None:
    """The whole panel is rewritten each frame, so no stale Clear() is needed."""
    hw_cfg = {"rows": 16, "cols": 32, "chain_length": 4, "parallel": 1, "rotation": 90}
    canvas = _make_canvas(hw_cfg, 64, 32)
    _fill_distinct(canvas)

    await canvas.render()

    displayed = canvas._matrix.displayed
    assert len(displayed.pixels) == displayed.width * displayed.height


@pytest.mark.asyncio
async def test_clear_then_render_blanks_the_panel(fake_rgbmatrix: None) -> None:
    hw_cfg = {"rows": 16, "cols": 32, "chain_length": 2, "parallel": 1, "rotation": 90}
    canvas = _make_canvas(hw_cfg, 32, 32)
    _fill_distinct(canvas)
    await canvas.render()

    canvas.clear()
    await canvas.render()

    assert set(canvas._matrix.displayed.pixels.values()) == {(0, 0, 0)}


@pytest.mark.asyncio
async def test_render_broadcasts_the_logical_frame(fake_rgbmatrix: None) -> None:
    """The browser preview keeps seeing the untransformed logical frame."""
    import struct

    frames: list[bytes] = []

    async def _capture(frame: bytes) -> None:
        frames.append(frame)

    from canvas.hardware import HardwareCanvas

    hw_cfg = {"rows": 16, "cols": 32, "chain_length": 2, "parallel": 1, "rotation": 90}
    canvas = HardwareCanvas(32, 32, hw_cfg, _capture)
    _fill_distinct(canvas)

    await canvas.render()

    assert frames == [struct.pack(">HH", 32, 32) + bytes(canvas._pixels)]


def test_limit_refresh_rate_is_passed_through(fake_rgbmatrix: None) -> None:
    hw_cfg = {"rows": 16, "cols": 32, "chain_length": 2, "rotation": 90,
              "limit_refresh_rate_hz": 90}
    canvas = _make_canvas(hw_cfg, 32, 32)
    assert canvas._matrix.options.limit_refresh_rate_hz == 90


def test_limit_refresh_rate_defaults_to_unset(fake_rgbmatrix: None) -> None:
    hw_cfg = {"rows": 16, "cols": 32, "chain_length": 2, "rotation": 90}
    canvas = _make_canvas(hw_cfg, 32, 32)
    assert not hasattr(canvas._matrix.options, "limit_refresh_rate_hz")
