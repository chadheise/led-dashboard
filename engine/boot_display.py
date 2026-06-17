#!/usr/bin/env python3
"""Display a boot status message on the LED matrix and hold it until killed.

Intended to be launched in the background by start.sh before each slow startup
step, then killed when the step completes (or when the engine takes over).

Usage:
    CANVAS=hardware PYTHONPATH=/path/to/engine python3 boot_display.py "Git pull..."
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path


# ── coordinate transform (mirrors HardwareCanvas._logical_to_physical) ────────

def _logical_to_physical(
    x: int, y: int,
    hw_rows: int, hw_cols: int,
    chain_length: int, rotation: int,
    alternate_rotation: bool,
) -> tuple[int, int]:
    def _panel_rot(logical_col: int) -> int:
        if alternate_rotation and logical_col % 2 == 1:
            return (rotation + 180) % 360
        return rotation

    def _phys_col(logical_col: int) -> int:
        return logical_col if alternate_rotation else chain_length - 1 - logical_col

    if rotation in (90, 270):
        logical_col = x // hw_rows
        panel_row   = y // hw_cols
        px = x % hw_rows
        py = y % hw_cols
        rot = _panel_rot(logical_col)
        pc  = _phys_col(logical_col)
        if rot == 90:
            return pc * hw_cols + py, panel_row * hw_rows + (hw_rows - 1 - px)
        else:  # 270
            return pc * hw_cols + (hw_cols - 1 - py), panel_row * hw_rows + px

    logical_col = x // hw_cols
    panel_row   = y // hw_rows
    px = x % hw_cols
    py = y % hw_rows
    rot = _panel_rot(logical_col)
    pc  = _phys_col(logical_col)
    if rot == 180:
        return pc * hw_cols + (hw_cols - 1 - px), panel_row * hw_rows + (hw_rows - 1 - py)
    return pc * hw_cols + px, panel_row * hw_rows + py


# ── config ────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    cfg_path = Path(__file__).parent / "config.yaml"
    try:
        import yaml
        with open(cfg_path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# ── rendering ─────────────────────────────────────────────────────────────────

_STATUS_COLOR = (80, 80, 80)
_STATUS_SIZE  = 14


def _render_message(msg: str, width: int, height: int):
    from PIL import Image
    from libraries.text_renderer.library import render_text, can_fit_text

    max_w   = max(6, width - 4)
    clipped = msg
    while clipped and not can_fit_text(max_w, _STATUS_SIZE, clipped):
        clipped = clipped[:-1]

    text_img = render_text(clipped, _STATUS_COLOR, _STATUS_SIZE)
    img = Image.new("RGB", (width, height))
    x = (width  - text_img.width)  // 2
    y = (height - text_img.height) // 2
    img.paste(text_img, (max(0, x), max(0, y)))
    return img


def _push_to_hardware(img, hw_cfg: dict, width: int, height: int) -> None:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions  # type: ignore[import]

    options = RGBMatrixOptions()
    options.rows             = hw_cfg.get("rows", 32)
    options.cols             = hw_cfg.get("cols", 32)
    options.chain_length     = hw_cfg.get("chain_length", 1)
    options.parallel         = hw_cfg.get("parallel", 1)
    options.gpio_slowdown    = hw_cfg.get("gpio_slowdown", 4)
    options.hardware_mapping = hw_cfg.get("hardware_mapping", "regular")
    options.drop_privileges  = False
    if "pwm_lsb_nanoseconds" in hw_cfg:
        options.pwm_lsb_nanoseconds = hw_cfg["pwm_lsb_nanoseconds"]
    if "pwm_bits" in hw_cfg:
        options.pwm_bits = hw_cfg["pwm_bits"]
    if "panel_type" in hw_cfg:
        options.panel_type = hw_cfg["panel_type"]
    pixel_mapper = hw_cfg.get("pixel_mapper", "")
    if pixel_mapper:
        options.pixel_mapper_config = pixel_mapper

    hw_rows           = options.rows
    hw_cols           = options.cols
    chain_length      = options.chain_length
    rotation          = hw_cfg.get("rotation", 0)
    alternate_rotation = hw_cfg.get("alternate_rotation", False)

    matrix = RGBMatrix(options=options)
    frame  = matrix.CreateFrameCanvas()

    pixels = img.load()
    for ly in range(height):
        for lx in range(width):
            r, g, b = pixels[lx, ly]
            px, py = _logical_to_physical(
                lx, ly, hw_rows, hw_cols, chain_length, rotation, alternate_rotation
            )
            frame.SetPixel(px, py, r, g, b)

    matrix.SwapOnVSync(frame)

    # Hold a reference so the matrix refresh thread keeps running until we exit.
    signal.pause()


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        return

    msg      = sys.argv[1]
    hardware = os.environ.get("CANVAS", "").lower() == "hardware"

    cfg          = _load_config()
    display_cfg  = cfg.get("display", {})
    width        = display_cfg.get("width",  320)
    height       = display_cfg.get("height",  64)

    try:
        img = _render_message(msg, width, height)
    except ImportError:
        return

    if not hardware:
        return

    try:
        _push_to_hardware(img, cfg.get("hardware", {}), width, height)
    except (ImportError, Exception):
        return


if __name__ == "__main__":
    main()
