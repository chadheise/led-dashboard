from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


class Canvas(ABC):
    def __init__(self, width: int, height: int, brightness: int = 100) -> None:
        self.width = width
        self.height = height
        self.brightness = brightness

    @abstractmethod
    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    async def render(self) -> None: ...

    def paste_image(self, img: "Image.Image", x_offset: int = 0, y_offset: int = 0) -> None:
        """Copy an RGB image onto the canvas with its top-left corner at
        (x_offset, y_offset), clipped to the canvas bounds.

        Generic per-pixel fallback. Buffer-backed canvases override this with a
        row-wise copy, which is what the render loop actually runs.
        """
        if img.mode != "RGB":
            img = img.convert("RGB")
        data = img.tobytes()
        w, h = img.size
        for dst_x in range(max(0, x_offset), min(self.width, x_offset + w)):
            src_x = dst_x - x_offset
            for dst_y in range(max(0, y_offset), min(self.height, y_offset + h)):
                idx = ((dst_y - y_offset) * w + src_x) * 3
                self.set_pixel(dst_x, dst_y, data[idx], data[idx + 1], data[idx + 2])

    def set_brightness(self, brightness: int) -> None:
        """Update display brightness (0-100). Subclasses extend this to apply
        the change to the underlying display."""
        self.brightness = brightness


class BufferedCanvas(Canvas):
    """Canvas backed by a contiguous RGB byte buffer, one frame of width x height.

    Both render targets keep the logical frame in this form: the simulator
    streams it to the browser, the hardware canvas remaps it onto the panel
    grid. Holding it here lets both copy whole rows in C rather than touching
    every pixel from Python -- on the Pi that is the difference between the
    render loop saturating a core and leaving it mostly idle, which is what
    the rgbmatrix refresh thread needs to avoid visible flicker.
    """

    def __init__(self, width: int, height: int, brightness: int = 100) -> None:
        super().__init__(width, height, brightness)
        self._pixels = bytearray(width * height * 3)
        # Reused by clear(): allocating a fresh buffer per frame churned
        # several MB/s of garbage, which showed up as periodic GC pauses.
        self._blank = bytes(width * height * 3)

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = (y * self.width + x) * 3
            self._pixels[idx] = r & 0xFF
            self._pixels[idx + 1] = g & 0xFF
            self._pixels[idx + 2] = b & 0xFF

    def clear(self) -> None:
        self._pixels[:] = self._blank

    def paste_image(self, img: "Image.Image", x_offset: int = 0, y_offset: int = 0) -> None:
        """Row-wise copy of an RGB image into the frame buffer.

        Same result as the per-pixel fallback, but one slice assignment per
        image row instead of one Python call per pixel.
        """
        w, h = img.size
        dst_x0 = max(0, x_offset)
        dst_x1 = min(self.width, x_offset + w)
        dst_y0 = max(0, y_offset)
        dst_y1 = min(self.height, y_offset + h)
        if dst_x0 >= dst_x1 or dst_y0 >= dst_y1:
            return
        if img.mode != "RGB":
            img = img.convert("RGB")
        data = img.tobytes()
        row_len = (dst_x1 - dst_x0) * 3
        src_x0 = dst_x0 - x_offset
        for dst_y in range(dst_y0, dst_y1):
            src = ((dst_y - y_offset) * w + src_x0) * 3
            dst = (dst_y * self.width + dst_x0) * 3
            self._pixels[dst:dst + row_len] = data[src:src + row_len]
