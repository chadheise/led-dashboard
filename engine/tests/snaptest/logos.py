"""Deterministic team logos for offline snapshot tests.

Real logos cannot be fetched at test time (no network), so each fixture game's
``*_logo_url`` is mapped to an image from one of two sources:

1. A committed PNG at ``tests/fixtures/logos/{league}/{ABBR}.png`` (preferred —
   downloaded once with ``python -m tests.snaptest.fetch_fixture_logos`` and
   checked in so contact sheets look realistic).
2. A generated placeholder: a team-colored shield with the first letter of the
   abbreviation. Pure PIL, seeded only by its inputs, so output is stable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from libraries.canvas_utils.library import parse_color
from libraries.text_renderer.library import render_text

LOGO_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "logos"

# Matches the target size SportsApp.fetch_data stores logos at.
LOGO_SIZE = 64


def _letter_color(background: tuple[int, int, int]) -> tuple[int, int, int]:
    lum = 0.2126 * background[0] + 0.7152 * background[1] + 0.0722 * background[2]
    return (255, 255, 255) if lum < 140 else (0, 0, 0)


def _paste_text(img: Image.Image, text_img: Image.Image, x: int, y: int) -> None:
    # render_text returns RGB-on-black; use the lit pixels as a paste mask.
    mask = text_img.convert("L").point(lambda p: 255 if p > 0 else 0)
    img.paste(text_img, (x, y), mask)


def make_fixture_logo(abbr: str, color_hex: str, size: int = LOGO_SIZE) -> Image.Image:
    """Generate a deterministic RGBA placeholder logo: colored shield + monogram."""
    color = parse_color(color_hex or "888888")
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Shield: flat top, straight sides, tapering to a bottom point.
    top = size // 10
    side_bottom = size * 5 // 8
    pts = [
        (1, top),
        (size - 2, top),
        (size - 2, side_bottom),
        (size // 2, size - 2),
        (1, side_bottom),
    ]
    draw.polygon(pts, fill=(*color, 255))

    letters = render_text(abbr[:2].upper(), _letter_color(color), size * 2 // 5)
    _paste_text(
        img,
        letters,
        (size - letters.width) // 2,
        top + (side_bottom - top - letters.height) // 2 + 1,
    )
    return img


def make_fixture_flag(
    abbr: str, color_hex: str, alt_hex: str, height: int = LOGO_SIZE * 2 // 3
) -> Image.Image:
    """Generate a deterministic RGBA placeholder flag (3:2, two horizontal bands).

    Used for fifa.world fixtures, whose real assets are flagcdn rectangles —
    the wide aspect ratio matters to layout in a way a square crest wouldn't.
    """
    width = height * 3 // 2
    color = parse_color(color_hex or "888888")
    alt = parse_color(alt_hex or "cccccc")
    img = Image.new("RGBA", (width, height), (*color, 255))
    band = Image.new("RGBA", (width, height // 2), (*alt, 255))
    img.paste(band, (0, height - band.height))

    letters = render_text(abbr[:2].upper(), _letter_color(color), height // 2)
    _paste_text(img, letters, (width - letters.width) // 2, 1)
    return img


def fixture_logos(game: dict[str, Any]) -> dict[str, Image.Image]:
    """Build the url -> RGBA logo mapping SportsApp expects for one game."""
    out: dict[str, Image.Image] = {}
    league = str(game.get("league", ""))
    for side in ("away", "home"):
        url = game.get(f"{side}_logo_url")
        if not url:
            continue
        abbr = str(game.get(f"{side}_abbr", "?"))
        path = LOGO_FIXTURE_DIR / league / f"{abbr}.png"
        if path.exists():
            logo = Image.open(path).convert("RGBA")
        elif "flagcdn.com" in url or league == "fifa.world":
            logo = make_fixture_flag(
                abbr,
                str(game.get(f"{side}_color") or ""),
                str(game.get(f"{side}_alt_color") or ""),
            )
        else:
            logo = make_fixture_logo(abbr, str(game.get(f"{side}_color") or ""))
        out[url] = logo
    return out


def fixture_logos_for_games(games: list[dict[str, Any]]) -> dict[str, Image.Image]:
    out: dict[str, Image.Image] = {}
    for game in games:
        out.update(fixture_logos(game))
    return out
