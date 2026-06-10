"""One-off dev utility: download real team logos for the snapshot fixtures.

Fetches every ``*_logo_url`` referenced by a suite's fixtures, scales each to
the same target size the app caches at (fits within 64x64), and writes it to
``tests/fixtures/logos/{league}/{ABBR}.png`` for committing. Tests never hit
the network: any logo missing here falls back to a generated placeholder.

Usage (from the engine/ directory):
    PYTHONPATH=. python -m tests.snaptest.fetch_fixture_logos --app sports
"""

from __future__ import annotations

import argparse
import io

import httpx
from PIL import Image

from tests.snaptest import harness
from tests.snaptest.logos import LOGO_FIXTURE_DIR, LOGO_SIZE


def _scale_down(img: Image.Image, max_size: int) -> Image.Image:
    w, h = img.size
    if w <= max_size and h <= max_size:
        return img
    scale = min(max_size / w, max_size / h)
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="sports")
    parser.add_argument("--force", action="store_true", help="Re-download existing logos")
    args = parser.parse_args()

    harness.load_suites()
    suite = harness.get_suite(args.app)

    targets: dict[tuple[str, str], str] = {}  # (league, abbr) -> url
    for game in suite.fixtures.values():
        for side in ("away", "home"):
            url = game.get(f"{side}_logo_url")
            if url:
                targets[(str(game.get("league", "")), str(game[f"{side}_abbr"]))] = url

    ok = failed = skipped = 0
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for (league, abbr), url in sorted(targets.items()):
            path = LOGO_FIXTURE_DIR / league / f"{abbr}.png"
            if path.exists() and not args.force:
                skipped += 1
                continue
            try:
                resp = client.get(url)
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            except Exception as exc:  # noqa: BLE001 — report and continue
                print(f"FAIL {league}/{abbr}: {exc}")
                failed += 1
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            _scale_down(img, LOGO_SIZE).save(path)
            print(f"ok   {league}/{abbr} <- {url}")
            ok += 1

    print(f"\n{ok} downloaded, {skipped} already present, {failed} failed")


if __name__ == "__main__":
    main()
