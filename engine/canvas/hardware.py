import logging
import struct
from collections.abc import Awaitable, Callable

from .base import Canvas

logger = logging.getLogger(__name__)


class HardwareCanvas(Canvas):
    """
    Drives HUB75 panels via rpi-rgb-led-matrix.

    Supports arbitrary panel grid layouts (chain_length x parallel), per-panel rotation
    (0 / 90 / 180 / 270), and pass-through pixel_mapper strings for special wiring
    arrangements such as U-mapper zigzag chains.

    Layout reference
    ----------------
    rotation 0 / 180  -- panels are in landscape orientation.
        rotation 180 flips each panel individually.

    rotation 90 / 270 -- panels are in portrait orientation (rotated from landscape).
        Each panel occupies hw_rows logical pixels wide x hw_cols logical pixels tall.
        _logical_to_physical transforms coordinates per-panel before calling SetPixel,
        so every panel in the chain gets its own correctly-rotated slice of the display.
        This is necessary because pixel_mapper_config applies to the whole chained canvas
        as a single surface, which collapses all panels into one panel-width of content.

    alternate_rotation -- zigzag cable workaround.
        When cables are too short to wire panels in the same direction, set
        alternate_rotation: true. Even-indexed logical panels use `rotation`; odd-indexed
        panels use rotation + 180 deg. The pattern repeats: 270, 90, 270, 90, ...
        Because zigzag wiring also reverses the physical panel order, it cancels out
        the chain mirroring applied in the non-zigzag case, so logical col 0 maps
        directly to physical chain position 0.

    panel chain order
    ------------------
    Panels are connected left-to-right, but the chain's addressing renders chain
    position 0 on the rightmost panel. _phys_panel_col mirrors the logical column
    index so that logical col 0 (the leftmost visible panel) maps to the last
    physical chain position.

    display dimensions vs hardware config
    --------------------------------------
    rotation 0 / 180:  display.width = chain_length x cols,  display.height = parallel x rows
    rotation 90 / 270: display.width = chain_length x rows,  display.height = parallel x cols
    """

    def __init__(
        self,
        width: int,
        height: int,
        hw_cfg: dict,
        broadcast: Callable[[bytes], Awaitable[None]],
    ) -> None:
        super().__init__(width, height)
        from rgbmatrix import RGBMatrix, RGBMatrixOptions  # type: ignore[import]

        options = RGBMatrixOptions()
        options.rows = hw_cfg.get("rows", 32)
        options.cols = hw_cfg.get("cols", 32)
        options.chain_length = hw_cfg.get("chain_length", 1)
        options.parallel = hw_cfg.get("parallel", 1)
        options.gpio_slowdown = hw_cfg.get("gpio_slowdown", 4)
        options.hardware_mapping = hw_cfg.get("hardware_mapping", "regular")
        options.drop_privileges = False

        pixel_mapper = hw_cfg.get("pixel_mapper", "")
        if pixel_mapper:
            options.pixel_mapper_config = pixel_mapper

        self._matrix = RGBMatrix(options=options)
        self._canvas = self._matrix.CreateFrameCanvas()

        self._hw_rows = options.rows
        self._hw_cols = options.cols
        self._chain_length = options.chain_length
        self._rotation = hw_cfg.get("rotation", 0)
        self._alternate_rotation = hw_cfg.get("alternate_rotation", False)

        alt_note = (
            f", alternating {self._rotation}/{(self._rotation + 180) % 360} deg"
            if self._alternate_rotation else ""
        )
        logger.info(
            "HardwareCanvas: logical %dx%d, grid %dx%d panels (%dx%d physical each, rotation %d deg%s%s)",
            width, height,
            options.chain_length, options.parallel,
            options.cols, options.rows,
            self._rotation,
            alt_note,
            f", mapper: {pixel_mapper}" if pixel_mapper else "",
        )

        self._pixels = bytearray(width * height * 3)
        self._broadcast = broadcast

    def _panel_rotation(self, logical_col: int) -> int:
        if self._alternate_rotation and logical_col % 2 == 1:
            return (self._rotation + 180) % 360
        return self._rotation

    def _phys_panel_col(self, logical_col: int) -> int:
        # Although panels are connected left-to-right, chain position 0 renders on
        # the rightmost panel, so mirror the column index to keep logical col 0 as
        # the leftmost visible panel. Zigzag wiring reverses the physical order
        # again, cancelling out the mirroring.
        if self._alternate_rotation:
            return logical_col
        return self._chain_length - 1 - logical_col

    def _logical_to_physical(self, x: int, y: int) -> tuple[int, int]:
        hw_rows = self._hw_rows
        hw_cols = self._hw_cols

        if self._rotation in (90, 270):
            # Portrait panels: hw_rows logical px wide x hw_cols logical px tall each
            logical_col = x // hw_rows
            panel_row = y // hw_cols
            px = x % hw_rows  # 0 ... hw_rows-1
            py = y % hw_cols  # 0 ... hw_cols-1
            rotation = self._panel_rotation(logical_col)
            phys_col = self._phys_panel_col(logical_col)
            if rotation == 90:
                return phys_col * hw_cols + py, panel_row * hw_rows + (hw_rows - 1 - px)
            else:  # 270
                return phys_col * hw_cols + (hw_cols - 1 - py), panel_row * hw_rows + px

        # Landscape panels (rotation 0 or 180)
        logical_col = x // hw_cols
        panel_row = y // hw_rows
        px = x % hw_cols
        py = y % hw_rows
        rotation = self._panel_rotation(logical_col)
        phys_col = self._phys_panel_col(logical_col)
        if rotation == 180:
            return phys_col * hw_cols + (hw_cols - 1 - px), panel_row * hw_rows + (hw_rows - 1 - py)
        return phys_col * hw_cols + px, panel_row * hw_rows + py

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            phys_x, phys_y = self._logical_to_physical(x, y)
            self._canvas.SetPixel(phys_x, phys_y, r & 0xFF, g & 0xFF, b & 0xFF)
            idx = (y * self.width + x) * 3
            self._pixels[idx] = r & 0xFF
            self._pixels[idx + 1] = g & 0xFF
            self._pixels[idx + 2] = b & 0xFF

    def clear(self) -> None:
        self._canvas.Clear()
        self._pixels = bytearray(self.width * self.height * 3)

    async def render(self) -> None:
        self._canvas = self._matrix.SwapOnVSync(self._canvas)
        frame = struct.pack(">HH", self.width, self.height) + bytes(self._pixels)
        await self._broadcast(frame)
