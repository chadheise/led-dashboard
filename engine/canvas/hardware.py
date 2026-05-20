import logging
import struct
from collections.abc import Awaitable, Callable

from .base import Canvas

logger = logging.getLogger(__name__)


class HardwareCanvas(Canvas):
    """Drives a physical HUB75 panel via rpi-rgb-led-matrix, with WebSocket broadcast for UI preview."""

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
        options.rows = hw_cfg.get("rows", height)
        options.cols = hw_cfg.get("cols", width)
        options.chain_length = hw_cfg.get("chain_length", 1)
        options.gpio_slowdown = hw_cfg.get("gpio_slowdown", 4)
        options.hardware_mapping = hw_cfg.get("hardware_mapping", "regular")
        options.drop_privileges = False

        self._matrix = RGBMatrix(options=options)
        self._canvas = self._matrix.CreateFrameCanvas()

        # Per-panel rotation is applied in set_pixel rather than via pixel_mapper_config.
        # pixel_mapper_config rotates the entire chained canvas as one surface, which maps
        # all panels into a single panel-width slice. Doing it per-panel in software lets
        # each panel render its own rotated slice of the logical display independently.
        self._hw_rows = options.rows
        self._hw_cols = options.cols
        self._rotation = hw_cfg.get("rotation", 0)

        logger.info(
            "HardwareCanvas: logical %dx%d from %d panels (%dx%d physical, rotation %d°)",
            width, height,
            options.chain_length,
            options.cols,
            options.rows,
            self._rotation,
        )
        self._pixels = bytearray(width * height * 3)
        self._broadcast = broadcast

    def _logical_to_physical(self, x: int, y: int) -> tuple[int, int]:
        if self._rotation == 90:
            # Portrait panel: hw_rows wide, hw_cols tall logically
            panel_idx = x // self._hw_rows
            px = x % self._hw_rows
            py = y
            return panel_idx * self._hw_cols + py, self._hw_rows - 1 - px
        if self._rotation == 270:
            panel_idx = x // self._hw_rows
            px = x % self._hw_rows
            py = y
            return panel_idx * self._hw_cols + (self._hw_cols - 1 - py), px
        return x, y

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
