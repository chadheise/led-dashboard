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
        rotation = hw_cfg.get("rotation", 0)
        if rotation:
            options.pixel_mapper_config = f"Rotate:{rotation}"

        self._matrix = RGBMatrix(options=options)
        self._canvas = self._matrix.CreateFrameCanvas()
        logger.info(
            "HardwareCanvas: %dx%d (panel %dx%d, chain %d, rotation %d°)",
            options.cols * options.chain_length,
            options.rows,
            options.cols,
            options.rows,
            options.chain_length,
            rotation,
        )
        self._pixels = bytearray(width * height * 3)
        self._broadcast = broadcast

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self._canvas.SetPixel(x, y, r & 0xFF, g & 0xFF, b & 0xFF)
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
