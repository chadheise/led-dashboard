import asyncio
import logging
import struct
from collections.abc import Awaitable, Callable

from PIL import Image

from .base import BufferedCanvas

logger = logging.getLogger(__name__)

# Per-panel rotation as a whole-image transpose. Each maps exactly onto the
# per-pixel arithmetic in _logical_to_physical (see test_hardware_canvas.py).
_PANEL_TRANSPOSE = {
    90: Image.Transpose.ROTATE_90,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_270,
}


class HardwareCanvas(BufferedCanvas):
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
        brightness: int = 100,
    ) -> None:
        super().__init__(width, height, brightness)
        from rgbmatrix import RGBMatrix, RGBMatrixOptions  # type: ignore[import]

        options = RGBMatrixOptions()
        options.rows = hw_cfg.get("rows", 32)
        options.cols = hw_cfg.get("cols", 32)
        options.chain_length = hw_cfg.get("chain_length", 1)
        options.parallel = hw_cfg.get("parallel", 1)
        options.gpio_slowdown = hw_cfg.get("gpio_slowdown", 4)
        options.hardware_mapping = hw_cfg.get("hardware_mapping", "regular")
        options.brightness = brightness
        options.drop_privileges = False
        options.show_refresh_rate = hw_cfg.get("show_refresh_rate", False)

        if "pwm_lsb_nanoseconds" in hw_cfg:
            options.pwm_lsb_nanoseconds = hw_cfg["pwm_lsb_nanoseconds"]
        if "pwm_bits" in hw_cfg:
            options.pwm_bits = hw_cfg["pwm_bits"]
        if "pwm_dither_bits" in hw_cfg:
            options.pwm_dither_bits = hw_cfg["pwm_dither_bits"]
        if "panel_type" in hw_cfg:
            options.panel_type = hw_cfg["panel_type"]
        # Pinning the refresh rate keeps the panel from visibly changing
        # brightness when the refresh rate drifts under load (network traffic,
        # other IO). Costs a little brightness; set it just under the lowest
        # rate reported with show_refresh_rate: true.
        if "limit_refresh_rate_hz" in hw_cfg:
            options.limit_refresh_rate_hz = hw_cfg["limit_refresh_rate_hz"]

        pixel_mapper = hw_cfg.get("pixel_mapper", "")
        if pixel_mapper:
            options.pixel_mapper_config = pixel_mapper

        logger.info(
            "HardwareCanvas options: rows=%d cols=%d chain=%d parallel=%d gpio_slowdown=%d "
            "hardware_mapping=%s pwm_lsb_ns=%s pwm_bits=%s pwm_dither_bits=%s panel_type=%s "
            "limit_refresh_rate_hz=%s",
            options.rows, options.cols, options.chain_length, options.parallel,
            options.gpio_slowdown, options.hardware_mapping,
            hw_cfg.get("pwm_lsb_nanoseconds", "<default>"),
            hw_cfg.get("pwm_bits", "<default>"),
            hw_cfg.get("pwm_dither_bits", "<default>"),
            hw_cfg.get("panel_type", "<default>"),
            hw_cfg.get("limit_refresh_rate_hz", "<unlimited>"),
        )

        self._matrix = RGBMatrix(options=options)
        self._canvas = self._matrix.CreateFrameCanvas()

        self._hw_rows = options.rows
        self._hw_cols = options.cols
        self._chain_length = options.chain_length
        self._parallel = options.parallel
        self._rotation = hw_cfg.get("rotation", 0)
        self._alternate_rotation = hw_cfg.get("alternate_rotation", False)

        # Size of one panel's slice of the logical canvas. Portrait panels are
        # rows wide x cols tall; landscape panels keep the physical dimensions.
        if self._rotation in (90, 270):
            self._tile_w, self._tile_h = self._hw_rows, self._hw_cols
        else:
            self._tile_w, self._tile_h = self._hw_cols, self._hw_rows
        self._panel_cols = min(self._chain_length, width // self._tile_w)
        self._panel_rows = min(self._parallel, height // self._tile_h)

        # Panel-space frame reused every render. Any physical pixel not covered
        # by a panel tile stays black for the life of the process.
        self._phys_frame = Image.new(
            "RGB", (self._chain_length * self._hw_cols, self._parallel * self._hw_rows)
        )

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

    def _physical_frame(self) -> Image.Image:
        """Remap the logical frame onto the physical panel grid.

        Produces exactly what calling _logical_to_physical for every pixel
        would, but as one crop/rotate/paste per panel: a full 320x64 frame
        costs ~10 C-level image operations instead of ~20k Python calls. The
        whole physical canvas is rewritten each frame, so no separate Clear()
        is needed.
        """
        logical = Image.frombytes("RGB", (self.width, self.height), bytes(self._pixels))
        for panel_row in range(self._panel_rows):
            top = panel_row * self._tile_h
            for logical_col in range(self._panel_cols):
                left = logical_col * self._tile_w
                tile = logical.crop((left, top, left + self._tile_w, top + self._tile_h))
                transpose = _PANEL_TRANSPOSE.get(self._panel_rotation(logical_col))
                if transpose is not None:
                    tile = tile.transpose(transpose)
                self._phys_frame.paste(
                    tile,
                    (
                        self._phys_panel_col(logical_col) * self._hw_cols,
                        panel_row * self._hw_rows,
                    ),
                )
        return self._phys_frame

    def set_brightness(self, brightness: int) -> None:
        super().set_brightness(brightness)
        self._matrix.brightness = brightness
        self._canvas.brightness = brightness

    async def render(self) -> None:
        # Push the whole frame in one call; SetImage loops over the pixels in C.
        self._canvas.SetImage(self._physical_frame())
        # SwapOnVSync blocks until the next hardware vsync (~22ms at 45 Hz).
        # Running it in a thread executor lets the asyncio event loop continue
        # handling API requests and WebSocket traffic during that wait, reducing
        # CPU contention with the rgbmatrix internal thread.
        loop = asyncio.get_running_loop()
        self._canvas = await loop.run_in_executor(
            None, self._matrix.SwapOnVSync, self._canvas
        )
        self._canvas.brightness = self.brightness
        frame = struct.pack(">HH", self.width, self.height) + bytes(self._pixels)
        await self._broadcast(frame)
