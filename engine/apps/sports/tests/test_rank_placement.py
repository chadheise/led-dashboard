"""Rank placement: stacked rows lead with the rank on both teams, while
side-by-side layouts mirror the home team's rank to the outer edge."""

from __future__ import annotations

import pytest

import apps.sports.cards as cards
from apps.sports.cards import Tier, select_tier
from apps.sports.tests.fixtures import _render_card, all_fixtures


def _rendered_names(monkeypatch, w: int, h: int) -> list[str]:
    seen: list[str] = []
    orig = cards._name_img

    def record(spec, color, max_w):
        # NameSpec (single-line names) carries the rank separately.
        seen.append(spec.joined if isinstance(spec, cards.NameSpec) else spec.text)
        return orig(spec, color, max_w)

    monkeypatch.setattr(cards, "_name_img", record)
    _render_card(all_fixtures()["ncaaf_ranked_long"], w, h)
    return seen


@pytest.mark.parametrize(
    "w,h,tier", [(80, 32, Tier.COMPACT), (112, 64, Tier.STACKED)]
)
def test_stacked_rows_lead_with_rank(monkeypatch, w, h, tier):
    assert select_tier(w, h) is tier
    names = _rendered_names(monkeypatch, w, h)
    assert "#3 UGA" in names
    assert "#14 TENN" in names
    assert "TENN #14" not in names


@pytest.mark.parametrize("w,h", [(192, 32), (256, 64)])
def test_side_by_side_mirrors_home_rank(monkeypatch, w, h):
    assert select_tier(w, h) in (Tier.INLINE, Tier.WIDE)
    names = _rendered_names(monkeypatch, w, h)
    assert "#3 UGA" in names
    assert "TENN #14" in names
