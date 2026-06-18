"""Build human-review contact sheets from a registered snapshot suite.

Renders every fixture at every suite width for one height, arranged as a grid
(rows = fixtures, columns = widths), upscaled with NEAREST so the pixel grid
stays visible. Output goes to ``tests/output/{app}_h{height}.png``.

Usage (from the engine/ directory):
    PYTHONPATH=. python -m tests.framework.contact_sheet --app sports --scale 3
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from libraries.text_renderer.library import render_text
from tests.framework import harness

OUTPUT_DIR = Path(__file__).parent.parent / "output"

_LABEL_COLOR = (200, 200, 200)
_BORDER_COLOR = (60, 60, 60)
_BG_COLOR = (15, 15, 15)
_LABEL_FONT = 12
_PAD = 6


def build_sheet(app_id: str, height: int, scale: int) -> Image.Image:
    suite = harness.get_suite(app_id)
    widths = sorted({w for (w, h) in suite.sizes if h == height})
    fixture_ids = list(suite.fixtures)

    label_imgs = {f: render_text(f, _LABEL_COLOR, _LABEL_FONT) for f in fixture_ids}
    label_w = max(img.width for img in label_imgs.values()) + 2 * _PAD
    header_h = render_text("0", _LABEL_COLOR, _LABEL_FONT).height + 2 * _PAD

    col_ws = [w * scale + 2 for w in widths]  # +2 for the 1px border
    row_h = height * scale + 2
    sheet_w = label_w + sum(col_ws) + _PAD * (len(widths) + 1)
    sheet_h = header_h + len(fixture_ids) * (row_h + _PAD) + _PAD

    sheet = Image.new("RGB", (sheet_w, sheet_h), _BG_COLOR)

    # Column headers
    x = label_w + _PAD
    for w, col_w in zip(widths, col_ws):
        hdr = render_text(f"{w}x{height}", _LABEL_COLOR, _LABEL_FONT)
        sheet.paste(hdr, (x + (col_w - hdr.width) // 2, _PAD))
        x += col_w + _PAD

    for row, fixture_id in enumerate(fixture_ids):
        y = header_h + row * (row_h + _PAD)
        label = label_imgs[fixture_id]
        sheet.paste(label, (_PAD, y + (row_h - label.height) // 2))

        x = label_w + _PAD
        for w, col_w in zip(widths, col_ws):
            card = harness.render_case(app_id, fixture_id, w, height).image
            card = card.resize((w * scale, height * scale), Image.NEAREST)
            # 1px border simulating the panel edge
            framed = Image.new("RGB", (card.width + 2, card.height + 2), _BORDER_COLOR)
            framed.paste(card, (1, 1))
            sheet.paste(framed, (x, y))
            x += col_w + _PAD

    return sheet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="sports")
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--heights", type=int, nargs="*", default=None,
                        help="Heights to render (default: every height in the suite)")
    args = parser.parse_args()

    harness.load_suites()
    suite = harness.get_suite(args.app)
    heights = args.heights or sorted({h for (_w, h) in suite.sizes})

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for height in heights:
        sheet = build_sheet(args.app, height, args.scale)
        out = OUTPUT_DIR / f"{args.app}_h{height}.png"
        sheet.save(out)
        print(f"wrote {out} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
