#!/usr/bin/env python3
"""
Ghost test harness - renders a static high-contrast pattern to make ghosting visible.

Run with: sudo python tools/ghost_test.py

Draws directly in physical (library) coordinates, bypassing the HardwareCanvas
logical-to-physical transform. This keeps the harness simple and independent of
any app code.

Physical canvas dimensions for this setup:
  chain_length x cols  =  10 x 64  =  640 px wide
  rows                 =  32           32 px tall

Panels are addressed in physical-chain order (chain position 0 = rightmost visible
panel = logical panel 10). The harness mirrors this so that logical panel numbers
match what you see on the wall:

  Logical  Physical-chain   Physical x range
  panel 1  pos 9            576-639
  panel 2  pos 8            512-575
  ...
  panel 8  pos 2            128-191
  panel 9  pos 1             64-127
  panel 10 pos 0              0-63

The test pattern:
  - Panels 1-7  : solid BLACK (the "clean" reference side)
  - Panels 8-10 : solid WHITE (the "problem" side - ghosting worst here)
  - Gray dividers at every panel boundary
  - Single white pixel rows at y=0 and y=31 across all panels (full-width reference lines)
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml
from rgbmatrix import RGBMatrix, RGBMatrixOptions  # type: ignore[import]

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_options(hw_cfg: dict) -> RGBMatrixOptions:
    options = RGBMatrixOptions()
    options.rows = hw_cfg.get("rows", 32)
    options.cols = hw_cfg.get("cols", 64)
    options.chain_length = hw_cfg.get("chain_length", 1)
    options.parallel = hw_cfg.get("parallel", 1)
    options.gpio_slowdown = hw_cfg.get("gpio_slowdown", 4)
    options.hardware_mapping = hw_cfg.get("hardware_mapping", "regular")
    options.brightness = 100
    options.drop_privileges = False
    options.show_refresh_rate = True  # always on for tuning runs

    if "pwm_lsb_nanoseconds" in hw_cfg:
        options.pwm_lsb_nanoseconds = hw_cfg["pwm_lsb_nanoseconds"]
    if "pwm_bits" in hw_cfg:
        options.pwm_bits = hw_cfg["pwm_bits"]
    if "pwm_dither_bits" in hw_cfg:
        options.pwm_dither_bits = hw_cfg["pwm_dither_bits"]
    if "panel_type" in hw_cfg:
        options.panel_type = hw_cfg["panel_type"]

    pixel_mapper = hw_cfg.get("pixel_mapper", "")
    if pixel_mapper:
        options.pixel_mapper_config = pixel_mapper

    return options


def fill_rect(canvas, x: int, y: int, w: int, h: int, r: int, g: int, b: int) -> None:
    for dy in range(h):
        for dx in range(w):
            canvas.SetPixel(x + dx, y + dy, r, g, b)


def main() -> None:
    cfg = load_config(CONFIG_PATH)
    hw_cfg = cfg.get("hardware", {})

    options = build_options(hw_cfg)

    chain = options.chain_length   # 10
    phys_w = chain * options.cols  # 640  (physical canvas width)
    phys_h = options.rows          # 32   (physical canvas height)
    panel_w = options.cols         # 64   (each panel's physical width)

    print("Options:")
    print(f"  rows={options.rows} cols={options.cols} chain={chain} parallel={options.parallel}")
    print(f"  gpio_slowdown={options.gpio_slowdown} hardware_mapping={options.hardware_mapping}")
    print(f"  pwm_lsb_nanoseconds={hw_cfg.get('pwm_lsb_nanoseconds', '<default>')}")
    print(f"  pwm_bits={hw_cfg.get('pwm_bits', '<default>')}")
    print(f"  pwm_dither_bits={hw_cfg.get('pwm_dither_bits', '<default>')}")
    print(f"  panel_type={hw_cfg.get('panel_type', '<default>')}")
    print(f"\nPhysical canvas: {phys_w}x{phys_h}")
    print()

    matrix = RGBMatrix(options=options)
    canvas = matrix.CreateFrameCanvas()

    # Physical-chain position for logical panel N (1-indexed):
    #   phys_pos = chain - N   (chain pos 0 = rightmost visible = logical panel 10)
    # Physical x start = phys_pos * panel_w

    for logical_panel in range(1, chain + 1):
        phys_pos = chain - logical_panel          # chain position (0 = rightmost)
        px_start = phys_pos * panel_w

        if logical_panel >= 8:
            # Solid white - the "problem" panels
            fill_rect(canvas, px_start, 0, panel_w, phys_h, 255, 255, 255)

        # Gray divider at the left edge of each panel
        for y in range(phys_h):
            canvas.SetPixel(px_start, y, 64, 64, 64)

    # Full-width white lines at top and bottom rows
    for x in range(phys_w):
        canvas.SetPixel(x, 0, 255, 255, 255)
        canvas.SetPixel(x, phys_h - 1, 255, 255, 255)

    canvas = matrix.SwapOnVSync(canvas)

    print("Ghost test pattern:")
    print("  Panels 1-7  : solid BLACK")
    print("  Panels 8-10 : solid WHITE")
    print("  Top/bottom rows : white (full width)")
    print("  Panel boundaries: gray dividers")
    print()
    print("Check the wall: any faint light on panels 1-7 is ghosting.")
    print("Press Ctrl-C to exit.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        canvas.Clear()
        matrix.SwapOnVSync(canvas)
        print("Done.")


if __name__ == "__main__":
    main()
