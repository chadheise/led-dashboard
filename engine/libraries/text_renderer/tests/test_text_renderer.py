"""Pin the rendered pixel heights of every pixel-font design size.

Layout math relies on these exact heights (requested sizes silently snap to
the nearest design size, a historic source of overlap bugs). If a font or
Pillow upgrade shifts any of these, this fails before the snapshots do —
with a much clearer message.
"""

from __future__ import annotations

import pytest

from libraries.text_renderer.library import _ALL_PIXEL_SIZES, render_text

# Rendered height of "0123456789" (digit cap height) per design size.
_EXPECTED_DIGIT_HEIGHTS = {7: 6, 8: 6, 9: 6, 12: 8, 15: 10, 22: 15, 28: 19}


@pytest.mark.parametrize("size", _ALL_PIXEL_SIZES)
def test_digit_height_per_design_size(size: int) -> None:
    img = render_text("0123456789", (255, 255, 255), size)
    assert img.height == _EXPECTED_DIGIT_HEIGHTS[size], (
        f"design size {size} now renders digits {img.height}px tall — "
        f"layout assumptions and snapshots must be re-validated"
    )


def test_bold_variant_same_height(size: int = 12) -> None:
    regular = render_text("0123456789", (255, 255, 255), size)
    bold = render_text("0123456789", (255, 255, 255), size, bold=True)
    assert regular.height == bold.height


def test_empty_text_has_requested_height() -> None:
    assert render_text("", (255, 255, 255), 12, fixed_h=10).height == 10
