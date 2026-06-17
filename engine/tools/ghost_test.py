#!/usr/bin/env python3
"""
Ghost test harness - renders a static high-contrast pattern to make ghosting visible.

Run with: sudo python tools/ghost_test.py

Draws directly in physical (library) coordinates, bypassing the HardwareCanvas
logical-to-physical transform.

Physical canvas dimensions for this setup:
  chain_length x cols  =  10 x 64  =  640 px wide
  rows                 =  32           32 px tall

Panel physical x ranges (chain pos 0 = rightmost visible = logical panel 10):
  panel 1  : 576-639
  panel 2  : 512-575
  ...
  panel 8  : 128-191
  panel 9  :  64-127
  panel 10 :   0-63

The test pattern:
  - Full-display alternating 4px white/black horizontal stripes
  - Each white stripe is immediately above/below a black stripe - reveals row ghosting
  - Any black stripe that glows faintly is a ghost
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
    options.show_refresh_rate = True

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


def main() -> None:
    cfg = load_config(CONFIG_PATH)
    hw_cfg = cfg.get("hardware", {})

    options = build_options(hw_cfg)

    chain = options.chain_length
    phys_w = chain * options.cols  # 640
    phys_h = options.rows          # 32

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

    # Alternating 4px-wide horizontal stripes (white/black) across the full display.
    stripe_h = 4
    for y in range(phys_h):
        if (y // stripe_h) % 2 == 0:
            for x in range(phys_w):
                canvas.SetPixel(x, y, 255, 255, 255)
        # odd stripes stay black (canvas initialised to black)

    canvas = matrix.SwapOnVSync(canvas)

    print("Ghost test pattern: 4px alternating horizontal stripes (full display)")
    print("Any black stripe that glows faintly is a ghost.")
    print("Ghosting will be most visible toward panels 8-10 (right side of wall).")
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
