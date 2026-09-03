import struct
from collections.abc import Awaitable, Callable

from .base import BufferedCanvas


class SimulatorCanvas(BufferedCanvas):
    def __init__(
        self,
        width: int,
        height: int,
        broadcast: Callable[[bytes], Awaitable[None]],
        brightness: int = 100,
    ) -> None:
        super().__init__(width, height, brightness)
        self._broadcast = broadcast

    async def render(self) -> None:
        # 4-byte header: width and height as big-endian uint16
        if self.brightness >= 100:
            pixels = bytes(self._pixels)
        else:
            scale = self.brightness / 100
            pixels = bytes(round(b * scale) for b in self._pixels)
        frame = struct.pack(">HH", self.width, self.height) + pixels
        await self._broadcast(frame)
