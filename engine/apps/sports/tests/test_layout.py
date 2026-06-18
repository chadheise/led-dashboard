"""Structural layout assertions for every sports card case.

These run on the PlacedBox audit trail from the layout engine — no image
analysis — and hold for any future fixture automatically:

- nothing overlaps, nothing is clipped, everything is in bounds
- required elements (scores, names, status) are present per tier
- the score is at least as prominent as the team name
"""

from __future__ import annotations

import pytest

from tests.framework import harness

harness.load_suites()

CASES = harness.all_cases("sports")
_IDS = [harness.case_id(*case) for case in CASES]


@pytest.fixture(scope="module")
def rendered():
    cache: dict[tuple[str, int, int], harness.RenderResult] = {}

    def get(fixture_id: str, w: int, h: int) -> harness.RenderResult:
        key = (fixture_id, w, h)
        if key not in cache:
            cache[key] = harness.render_case("sports", *key)
        return cache[key]

    return get


def _boxes(result: harness.RenderResult) -> list:
    assert result.boxes is not None, "render path must expose layout boxes"
    return result.boxes


@pytest.mark.parametrize("fixture_id,w,h", CASES, ids=_IDS)
def test_no_overlap(fixture_id, w, h, rendered):
    result = rendered(fixture_id, w, h)
    _boxes(result)
    from libraries.layout.library import Frame

    frame = Frame(w, h)
    frame.boxes = result.boxes
    pairs = frame.overlapping_pairs()
    assert pairs == [], [
        f"{a.name}({a.x},{a.y},{a.w}x{a.h}) <> {b.name}({b.x},{b.y},{b.w}x{b.h})"
        for a, b in pairs
    ]


@pytest.mark.parametrize("fixture_id,w,h", CASES, ids=_IDS)
def test_in_bounds_and_unclipped(fixture_id, w, h, rendered):
    for box in _boxes(rendered(fixture_id, w, h)):
        assert not box.clipped, f"{box.name} was clipped"
        assert box.x >= 0 and box.y >= 0 and box.right <= w and box.bottom <= h, (
            f"{box.name} at ({box.x},{box.y},{box.w}x{box.h}) exceeds {w}x{h}"
        )


@pytest.mark.parametrize("fixture_id,w,h", CASES, ids=_IDS)
def test_required_elements(fixture_id, w, h, rendered):
    suite = harness.get_suite("sports")
    game = suite.fixtures[fixture_id]
    names = {box.name for box in _boxes(rendered(fixture_id, w, h))}

    if game.get("state", "pre") != "pre":
        assert "away.score" in names and "home.score" in names, names
    if w >= 48:
        assert names & {"away.name", "away.abbr"}, names
        assert names & {"home.name", "home.abbr"}, names
        assert "footer.status" in names, names


# Digit-only scores have no descenders, so a name box ("City", "Bulldogs") can
# legitimately measure up to 2px taller than a visually larger score.
_DESCENDER_ALLOWANCE = 2


@pytest.mark.parametrize("fixture_id,w,h", CASES, ids=_IDS)
def test_score_most_prominent(fixture_id, w, h, rendered):
    boxes = {box.name: box for box in _boxes(rendered(fixture_id, w, h))}
    for side in ("away", "home"):
        score = boxes.get(f"{side}.score")
        name = boxes.get(f"{side}.name")
        if score and name:
            assert score.h >= name.h - _DESCENDER_ALLOWANCE, (
                f"{side}: score {score.h}px shorter than name {name.h}px"
            )
