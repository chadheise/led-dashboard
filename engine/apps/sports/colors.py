"""Display-safe color handling for LED panels.

On an LED matrix black pixels are *off*, so dark team colors (navy, maroon,
forest) and black logo art disappear entirely. Everything here enforces a
relative-luminance floor instead of the old max-channel rule, which let
colors like pure navy through at ~7% luminance.
"""

from __future__ import annotations

from PIL import Image

from libraries.canvas_utils.library import parse_color

RGB = tuple[int, int, int]

# Minimum relative luminance for text/accent colors. Tuned on contact sheets:
# below this, saturated dark colors are illegible at LED viewing distance.
MIN_TEXT_LUM = 0.16
# Logos keep a bit more of their darkness — shapes read easier than glyphs.
MIN_LOGO_LUM = 0.10

_NEUTRAL: RGB = (170, 170, 170)
_GRAY_ACCENT: RGB = (150, 150, 150)

# Colors closer than this (squared RGB distance) are considered the same hue
# for accent fallback / home-away differentiation purposes.
_SIMILARITY_THRESHOLD_SQ = 90 * 90


def luminance(rgb: RGB) -> float:
    """Relative luminance (Rec. 709), 0.0–1.0."""
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255


def _raise_to_luminance(rgb: RGB, floor: float) -> RGB:
    """Brighten rgb until its luminance reaches floor, preserving hue.

    First scales the channels up; if a channel saturates before the floor is
    reached (e.g. pure blue), blends toward white for the remainder.
    """
    lum = luminance(rgb)
    if lum >= floor:
        return rgb
    if lum > 0:
        scale = min(floor / lum, 255 / max(c for c in rgb if c > 0))
        rgb = tuple(min(255, round(c * scale)) for c in rgb)  # type: ignore[assignment]
        lum = luminance(rgb)
        if lum >= floor:
            return rgb
    if lum <= 0:
        gray = round(floor * 255)
        return (gray, gray, gray)
    # Channels saturated: blend toward white. Luminance is linear in RGB, so
    # solve lum + t * (1 - lum) = floor.
    t = (floor - lum) / (1 - lum)
    return tuple(min(255, round(c + t * (255 - c))) for c in rgb)  # type: ignore[return-value]


def _dist_sq(a: RGB, b: RGB) -> int:
    return sum((ca - cb) ** 2 for ca, cb in zip(a, b))


def _is_near_black(rgb: RGB) -> bool:
    return max(rgb) < 30


def display_safe(color_hex: str, fallback_hex: str = "") -> RGB:
    """Parse a team color hex and make it legible on an LED panel.

    Near-black primaries carry no usable hue, so they fall back to the
    alternate color (e.g. Raiders black -> silver) before brightening.
    """
    color = parse_color(color_hex) if color_hex else None
    if color is None or _is_near_black(color):
        fallback = parse_color(fallback_hex) if fallback_hex else None
        color = fallback if fallback is not None and not _is_near_black(fallback) else None
    if color is None:
        return _NEUTRAL
    return _raise_to_luminance(color, MIN_TEXT_LUM)


def team_palette(primary_hex: str, alt_hex: str) -> tuple[RGB, RGB]:
    """Return (main, accent) display-safe colors for one team.

    The accent (used for the city/abbr line) falls back to gray when it is
    indistinguishable from the main color.
    """
    main = display_safe(primary_hex, alt_hex)
    accent = display_safe(alt_hex, primary_hex)
    if _dist_sq(main, accent) < _SIMILARITY_THRESHOLD_SQ:
        accent = _GRAY_ACCENT
    return main, accent


def differentiate(
    away: tuple[RGB, RGB], home: tuple[RGB, RGB]
) -> tuple[tuple[RGB, RGB], tuple[RGB, RGB]]:
    """Keep both teams visually distinct when their main colors collide.

    The home side switches to its own alternate color (still that team's
    palette), so home/away each remain in team colors.
    """
    away_main, _away_accent = away
    home_main, home_accent = home
    if _dist_sq(away_main, home_main) >= _SIMILARITY_THRESHOLD_SQ:
        return away, home
    if _dist_sq(away_main, home_accent) >= _SIMILARITY_THRESHOLD_SQ:
        return away, (home_accent, home_main)
    return away, (_NEUTRAL, home_accent)


def prepare_logo(logo: Image.Image) -> Image.Image:
    """Make a logo legible against off (black) LEDs.

    Dark opaque pixels are brightened to the logo luminance floor (hue kept);
    if most of the logo is dark (e.g. the Raiders shield) a 1px dim outline
    derived from the alpha channel is added so the silhouette reads.

    The result is memoized on the source image object — logos are long-lived
    in the app cache and this runs per frame.
    """
    cached = getattr(logo, "_led_prepared", None)
    if cached is not None:
        return cached

    rgba = logo.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    opaque = 0
    dark = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 128:
                continue
            opaque += 1
            if luminance((r, g, b)) < MIN_LOGO_LUM:
                dark += 1
                nr, ng, nb = _raise_to_luminance((r, g, b), MIN_LOGO_LUM)
                px[x, y] = (nr, ng, nb, a)

    if opaque and dark / opaque > 0.6:
        _add_silhouette_outline(rgba)

    prepared = rgba
    logo._led_prepared = prepared  # type: ignore[attr-defined]
    return prepared


def _add_silhouette_outline(rgba: Image.Image, color: RGB = (45, 45, 45)) -> None:
    """Draw a 1px outline just inside the alpha silhouette, in place."""
    alpha = rgba.split()[3]
    mask = alpha.point(lambda a: 255 if a >= 128 else 0)
    px = rgba.load()
    mpx = mask.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            if not mpx[x, y]:
                continue
            on_edge = (
                x == 0 or y == 0 or x == w - 1 or y == h - 1
                or not mpx[x - 1, y] or not mpx[x + 1, y]
                or not mpx[x, y - 1] or not mpx[x, y + 1]
            )
            if on_edge:
                a = px[x, y][3]
                px[x, y] = (*color, a)
