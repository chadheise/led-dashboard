"""An empty sports module says "No games" instead of rendering black.

``render_frame`` used to return without drawing when nothing qualified, which
looks identical to a crashed or misconfigured display. A playlist entry with
"skip if hidden" set never gets here (``should_display`` hides it first), so
anyone who does reach this asked to keep the module in rotation and is better
served by a reason than by an all-black panel.
"""

from __future__ import annotations

import asyncio
from typing import Any


def _make_app(w: int, h: int) -> Any:
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(w, h, _noop_broadcast)
    return SportsApp({"leagues": ["mlb"]}, canvas, {}, {}), canvas


def _lit_pixels(canvas: Any) -> int:
    return sum(1 for byte in canvas._pixels if byte)


def test_empty_module_draws_a_message_not_a_black_frame() -> None:
    app, canvas = _make_app(320, 64)
    app._games = []
    canvas.clear()
    asyncio.run(app.render_frame())
    assert _lit_pixels(canvas) > 0


def test_empty_module_message_fits_every_supported_size() -> None:
    from tests.framework import harness

    for w, h in harness.CORE_SIZES:
        app, canvas = _make_app(w, h)
        app._games = []
        canvas.clear()
        asyncio.run(app.render_frame())
        assert _lit_pixels(canvas) > 0, f"nothing drawn at {w}x{h}"


def test_empty_module_stays_hidden_from_the_auto_hide_gate() -> None:
    """The placeholder is a last resort, not a reason to keep the module in
    rotation: ``should_display`` must still report it as having nothing."""
    app, _ = _make_app(320, 64)
    app._games = []
    assert asyncio.run(app.should_display()) is False


def test_message_image_is_cached_per_canvas_size() -> None:
    """It is composed on every frame the module is on screen, so it has to be
    built once per size (same reasoning as connectivity.py's offline message)."""
    from apps.sports.app import _empty_message_image

    assert _empty_message_image(320, 64) is _empty_message_image(320, 64)
    assert _empty_message_image(320, 64) is not _empty_message_image(320, 32)
