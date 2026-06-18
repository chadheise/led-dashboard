#!/usr/bin/env python3
"""Render animated GIF previews of the sports scoring celebrations.

For each celebration kind (soccer GOAL!, NFL TOUCHDOWN!/FIELD GOAL!/
INTERCEPTION!, MLB HOME RUN!) the matching test fixture is rendered over a few
seconds of simulated wall-clock time — driving the 1 Hz text/score pulse and
the 8 fps sprite animation exactly as SportsApp does — then upscaled with
nearest-neighbour (crisp LED pixels) and written as a looping GIF.

Run from the ``engine`` directory: ``python tools/render_celebration_gifs.py``.
Offline: uses the deterministic snapshot-test fixtures and placeholder logos.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))  # engine/ — run from anywhere

from apps.sports.app import _ANIM_FPS, _ANIM_FRAMES
from apps.sports.cards import render_card
from apps.sports.model import CelebrationView, build_game_view
from apps.sports.tests.fixtures import all_fixtures
from tests.framework.logos import fixture_logos

_CASES = [
    "soccer_goal_celebration",
    "nfl_td_celebration",
    "nfl_fg_celebration",
    "nfl_int_celebration",
    "mlb_hr_celebration",
]
# Full WIDE tier plus one narrow size that exercises the abbreviated text.
_SIZES = [(320, 64), (128, 32)]

_SECONDS = 4.0
_GIF_FPS = 10
_SCALE = 4


def render_gif(game: dict, w: int, h: int, out_path: Path) -> None:
    game = dict(game)
    celeb = dict(game.pop("_celebration"))
    logos = fixture_logos(game)

    frames: list[Image.Image] = []
    for i in range(int(_SECONDS * _GIF_FPS)):
        elapsed = i / _GIF_FPS
        view = build_game_view(
            game,
            logos,
            celebration=CelebrationView(
                kind=celeb["kind"],
                side=celeb["side"],
                pulse_on=int(elapsed) % 2 == 0,
                anim_frame=int(elapsed * _ANIM_FPS) % _ANIM_FRAMES,
            ),
        )
        img = render_card(view, w, h).image
        frames.append(img.resize((w * _SCALE, h * _SCALE), Image.NEAREST))

    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=round(1000 / _GIF_FPS),
        loop=0,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("/tmp/celebration_gifs"),
        help="output directory (default: /tmp/celebration_gifs)",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    fixtures = all_fixtures()
    for fixture_id in _CASES:
        for w, h in _SIZES:
            out_path = args.out / f"{fixture_id}_{w}x{h}.gif"
            render_gif(fixtures[fixture_id], w, h, out_path)
            print(out_path)


if __name__ == "__main__":
    main()
