"""What an empty sports module draws, and what it is allowed to claim.

``render_frame`` used to return without drawing when nothing qualified, which
looks identical to a crashed or misconfigured display. A playlist entry with
"skip if hidden" set never gets here (``should_display`` hides it first), so
anyone who does reach this asked to keep the module in rotation and is better
served by a reason than by an all-black panel.

The reason has to be the true one. "No games" is a claim about the world, and
a failed fetch produces exactly the same empty game list as a quiet day - so
saying "No games" during a full slate of fixtures told the viewer the display
was working when it wasn't. Only a fetch that came back may say that.
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


def test_a_failed_fetch_does_not_claim_there_are_no_games() -> None:
    from apps.sports.app import _UNAVAILABLE_TEXT

    app, _ = _make_app(320, 64)
    app._games = []
    app._fetch_failures = ["nfl"]
    assert app._empty_message() == _UNAVAILABLE_TEXT


def test_a_successful_but_idle_fetch_says_there_are_no_games() -> None:
    from apps.sports.app import _EMPTY_TEXT

    app, _ = _make_app(320, 64)
    app._games = []
    app._fetch_failures = []
    assert app._empty_message() == _EMPTY_TEXT


def test_the_two_empty_states_render_differently() -> None:
    """They must be distinguishable on the panel, not just in the code."""
    from apps.sports.app import _EMPTY_TEXT, _UNAVAILABLE_TEXT, _empty_message_image

    no_games = _empty_message_image(320, 64, _EMPTY_TEXT)
    unavailable = _empty_message_image(320, 64, _UNAVAILABLE_TEXT)
    assert no_games.tobytes() != unavailable.tobytes()


def test_each_message_is_cached_separately_per_size() -> None:
    from apps.sports.app import _EMPTY_TEXT, _UNAVAILABLE_TEXT, _empty_message_image

    assert _empty_message_image(320, 64, _EMPTY_TEXT) is _empty_message_image(
        320, 64, _EMPTY_TEXT
    )
    assert _empty_message_image(320, 64, _EMPTY_TEXT) is not _empty_message_image(
        320, 64, _UNAVAILABLE_TEXT
    )


def test_an_unreachable_espn_leaves_the_module_saying_scores_unavailable() -> None:
    """End to end through fetch_data, the shape of the real fault: ESPN cannot
    be reached, so there are no games and no honest way to say there are none.
    """
    from apps.sports.app import _UNAVAILABLE_TEXT

    app, canvas = _make_app(320, 64)

    class _Dead:
        async def get(self, _url: str, params: dict | None = None):
            raise RuntimeError("Network unreachable")

    app._espn._get_client = lambda: _Dead()  # type: ignore[method-assign]

    async def _no_logos(_games, _size):
        return {}

    app._espn.fetch_logos = _no_logos  # type: ignore[method-assign]

    asyncio.run(app.fetch_data())

    assert app._games == []
    assert app._fetch_failures == ["mlb"]
    assert app._empty_message() == _UNAVAILABLE_TEXT

    canvas.clear()
    asyncio.run(app.render_frame())
    assert _lit_pixels(canvas) > 0
