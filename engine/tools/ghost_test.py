#!/usr/bin/env python3
"""
Ghost test harness — renders a static high-contrast pattern to make ghosting visible.

Run with: sudo python tools/ghost_test.py

Displays bright white elements on black, focused on panels 8-10 (the right-most
panels in a 10-panel chain where ghosting is worst). Press Ctrl-C to exit.
"""

import os
import sys
import time

# Allow running from the engine/ directory or the tools/ subdirectory.
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


def draw_rect(canvas, x: int, y: int, w: int, h: int, r: int, g: int, b: int) -> None:
    for dy in range(h):
        for dx in range(w):
            canvas.SetPixel(x + dx, y + dy, r, g, b)


def main() -> None:
    cfg = load_config(CONFIG_PATH)
    hw_cfg = cfg.get("hardware", {})

    options = build_options(hw_cfg)

    print("Options:")
    print(f"  rows={options.rows} cols={options.cols} chain={options.chain_length} parallel={options.parallel}")
    print(f"  gpio_slowdown={options.gpio_slowdown} hardware_mapping={options.hardware_mapping}")
    print(f"  pwm_lsb_nanoseconds={hw_cfg.get('pwm_lsb_nanoseconds', '<default>')}")
    print(f"  pwm_bits={hw_cfg.get('pwm_bits', '<default>')}")
    print(f"  pwm_dither_bits={hw_cfg.get('pwm_dither_bits', '<default>')}")
    print(f"  panel_type={hw_cfg.get('panel_type', '<default>')}")
    print()

    matrix = RGBMatrix(options=options)
    canvas = matrix.CreateFrameCanvas()

    # Display dimensions (rotation 90: width = chain * rows, height = parallel * cols)
    display_w = cfg["display"]["width"]   # 320
    display_h = cfg["display"]["height"]  # 64

    # Hardware panel size in the rotated (logical) space
    hw_rows = options.rows  # 32 — this is the logical WIDTH of each panel after 90° rotation
    # hw_cols = options.cols  # 64 — logical HEIGHT

    # Paint the canvas: white rectangles over panels 8, 9, 10 (0-indexed: 7, 8, 9)
    # and a white text-like stripe across the full top.

    # Full-width top stripe (panels 1-10)
    draw_rect(canvas, 0, 0, display_w, 4, 255, 255, 255)

    # Label stripe: "GHOST TEST" in simple block letters — just solid rectangles per panel
    # Solid white block covering right half of panels 8, 9, 10
    panel8_start = 7 * hw_rows  # logical x-start of panel 8
    draw_rect(canvas, panel8_start, 8, 3 * hw_rows, display_h - 16, 255, 255, 255)

    # Thin white border around the entire display
    draw_rect(canvas, 0, 0, display_w, 1, 255, 255, 255)
    draw_rect(canvas, 0, display_h - 1, display_w, 1, 255, 255, 255)
    draw_rect(canvas, 0, 0, 1, display_h, 255, 255, 255)
    draw_rect(canvas, display_w - 1, 0, 1, display_h, 255, 255, 255)

    # Panel boundary markers (thin white lines between each panel)
    for p in range(1, options.chain_length):
        x = p * hw_rows
        draw_rect(canvas, x, 0, 1, display_h, 128, 128, 128)

    canvas = matrix.SwapOnVSync(canvas)

    print("Displaying ghost test pattern. Check panels 8-10 for ghosting.")
    print("Press Ctrl-C to exit.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        canvas.Clear()
        matrix.SwapOnVSync(canvas)
        print("\nDone.")


if __name__ == "__main__":
    main()
