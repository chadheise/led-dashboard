import struct
from collections.abc import Awaitable, Callable

from .base import Canvas


class SimulatorCanvas(Canvas):
    def __init__(
        self,
        width: int,
        height: int,
        broadcast: Callable[[bytes], Awaitable[None]],
    ) -> None:
        super().__init__(width, height)
        self._pixels = bytearray(width * height * 3)
        self._broadcast = broadcast

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = (y * self.width + x) * 3
            self._pixels[idx] = r & 0xFF
            self._pixels[idx + 1] = g & 0xFF
            self._pixels[idx + 2] = b & 0xFF

    def clear(self) -> None:
        self._pixels = bytearray(self.width * self.height * 3)

    async def render(self) -> None:
        # 4-byte header: width and height as big-endian uint16
        frame = struct.pack(">HH", self.width, self.height) + bytes(self._pixels)
        await self._broadcast(frame)
