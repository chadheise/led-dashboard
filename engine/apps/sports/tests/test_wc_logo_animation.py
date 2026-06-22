"""World Cup logo slide animation.

The WC logo crowds the game content, so rather than sitting on the left
permanently it slides in from the left, holds for 10s, then slides back out,
repeating every 2 minutes. While hidden the content reclaims the full width.

These tests cover the reveal timeline and that the card renderer honours it:
``reveal == 1`` keeps the historical fixed-strip layout (an audited
``league.logo`` box), ``reveal == 0`` drops the panel entirely (content runs
full width), and a mid-slide reveal composites the logo without a layout box.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.framework import harness
from tests.framework.logos import fixture_logos

from apps.sports.cards import (
    _WC_CYCLE_SECONDS,
    _WC_HOLD_SECONDS,
    _WC_SLIDE_SECONDS,
    render_card,
    wc_logo_reveal,
)
from apps.sports.model import build_game_view

harness.load_suites()

# A wide WIDE-tier size where the WC panel is active (w >= 192, h >= 48).
_W, _H = 320, 64


def _wc_view():
    game = dict(harness.get_suite("sports").fixtures["soccer_long_note"])
    game.pop("_celebration", None)
    assert game["league"] == "fifa.world"
    return build_game_view(game, fixture_logos(game))


def _box_names(reveal: float) -> set[str]:
    result = render_card(_wc_view(), _W, _H, wc_reveal=reveal)
    return {b.name for b in result.boxes}


def _min_content_x(reveal: float) -> int:
    """Leftmost x of any placed game-content box (the logo box excluded)."""
    result = render_card(_wc_view(), _W, _H, wc_reveal=reveal)
    return min(b.x for b in result.boxes if b.name != "league.logo")


# ── Reveal timeline ──────────────────────────────────────────────────────────


def test_reveal_slides_in_holds_and_slides_out():
    slide, hold = _WC_SLIDE_SECONDS, _WC_HOLD_SECONDS
    # Slide in: 0 -> 1 across the first slide window.
    assert wc_logo_reveal(0.0) == 0.0
    assert wc_logo_reveal(slide / 2) == pytest.approx(0.5)
    assert wc_logo_reveal(slide) == 1.0
    # Hold fully shown.
    assert wc_logo_reveal(slide + hold / 2) == 1.0
    assert wc_logo_reveal(slide + hold - 0.01) == 1.0
    # Slide out: 1 -> 0 across the second slide window.
    assert wc_logo_reveal(slide + hold) == 1.0
    assert wc_logo_reveal(slide + hold + slide / 2) == pytest.approx(0.5)
    assert wc_logo_reveal(slide + hold + slide) == 0.0
    # Hidden for the rest of the cycle.
    assert wc_logo_reveal(_WC_CYCLE_SECONDS - 1.0) == 0.0


def test_reveal_repeats_every_cycle():
    for base in (0.0, _WC_CYCLE_SECONDS, 5 * _WC_CYCLE_SECONDS):
        assert wc_logo_reveal(base) == 0.0
        assert wc_logo_reveal(base + _WC_SLIDE_SECONDS) == 1.0


# ── Card rendering honours the reveal ────────────────────────────────────────


def test_logo_box_present_only_when_fully_shown():
    # Fully shown: an audited league.logo box, exactly as before the animation.
    assert "league.logo" in _box_names(1.0)
    # Hidden: no logo box at all.
    assert "league.logo" not in _box_names(0.0)
    # Mid-slide: composited as an overlay, deliberately left out of the audit.
    assert "league.logo" not in _box_names(0.5)


def test_hidden_logo_reclaims_left_space():
    # With the logo gone the content starts further left than when it is shown.
    assert _min_content_x(0.0) < _min_content_x(1.0)


def test_partial_slide_differs_from_hidden_and_shown():
    hidden = render_card(_wc_view(), _W, _H, wc_reveal=0.0).image.tobytes()
    partial = render_card(_wc_view(), _W, _H, wc_reveal=0.5).image.tobytes()
    shown = render_card(_wc_view(), _W, _H, wc_reveal=1.0).image.tobytes()
    assert partial != hidden  # the sliding logo is visible
    assert partial != shown


# ── App threads its animation clock into the render ──────────────────────────


def test_app_reveal_tracks_cycle_clock():
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop(_frame: bytes) -> None:
        pass

    app = SportsApp({"leagues": []}, SimulatorCanvas(_W, _H, _noop), {}, {})

    now = 1000.0
    app._now = lambda: now  # type: ignore[method-assign]

    app._wc_cycle_start = now  # start of cycle -> hidden
    assert app._wc_reveal() == 0.0

    app._wc_cycle_start = now - _WC_SLIDE_SECONDS  # into the hold -> shown
    assert app._wc_reveal() == 1.0
