from .base import Canvas


class HardwareCanvas(Canvas):
    """Drives a physical HUB75 panel via rpi-rgb-led-matrix."""

    def __init__(self, width: int, height: int, hw_cfg: dict) -> None:
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

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self._canvas.SetPixel(x, y, r & 0xFF, g & 0xFF, b & 0xFF)

    def clear(self) -> None:
        self._canvas.Clear()

    async def render(self) -> None:
        self._canvas = self._matrix.SwapOnVSync(self._canvas)
