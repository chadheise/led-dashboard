from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image, ImageDraw, ImageFont

from canvas.base import Canvas
from libraries.base import Library
from libraries.canvas_utils.library import blit


FONTS_DIR = Path(__file__).parent / "fonts"
_LORES_DIR: Path = FONTS_DIR / "LoRes"
_DANIEL_DIR: Path = FONTS_DIR / "DanielLinssen"

# Explicit LoRes font table keyed by design size.
# Each entry is (regular_filename, bold_filename).
# Size 28 has no bold variant, so regular is used for both.
_LORES_FONTS: dict[int, tuple[str, str]] = {
    9:  ("LoRes9OTNarrow-Regular.ttf",  "LoRes9OTNarrow-Bold.ttf"),
    12: ("LoRes12OT-Regular.ttf",       "LoRes12OT-Bold.ttf"),
    15: ("LoRes15OTNarrow-Regular.ttf", "LoRes15OT-Bold.ttf"),
    22: ("LoRes22OTNarrow-Regular.ttf", "LoRes22OTOakland-Bold.ttf"),
    28: ("LoRes28OT-Regular.ttf",       "LoRes28OT-Regular.ttf"),
}

# Daniel Linssen pixel fonts keyed by their actual crisp rendered height.
# Each entry: (regular_filename, bold_filename, native_load_size).
# native_load_size is the PIL truetype() size that produces pixel-perfect output —
# it differs from the font's name-size because the internal em-squares don't align
# with the label dimensions (e.g. "m5x7" renders cleanly only when loaded at 16).
# No bold variants exist; m6x11plus is the extended-charset edition of m6x11.
# Size 9 is present for documentation but LoRes9 takes priority when snapped to 9.
_DANIEL_FONTS: dict[int, tuple[str, str, int]] = {
    7: ("m6x11plus.ttf", "m6x11plus.ttf",  9),  # load_size= 9 → crisp 7px output
    8: ("m3x6.ttf",      "m3x6.ttf",      16),  # load_size=16 → crisp 8px output
    9: ("m5x7.ttf",      "m5x7.ttf",      16),  # load_size=16 → crisp 9px output
}

_LORES_SIZES: list[int] = sorted(_LORES_FONTS)
_LORES_MAX: int = max(_LORES_SIZES)  # 28

# Unified pixel-font design sizes across both families (DanielLinssen + LoRes)
_ALL_PIXEL_SIZES: list[int] = sorted(set(_DANIEL_FONTS) | set(_LORES_FONTS))
_PIXEL_MAX: int = max(_ALL_PIXEL_SIZES)  # 28
_PIXEL_MIN: int = min(_ALL_PIXEL_SIZES)  # 7

# Roboto variable font (OFL licensed) for sizes > _LORES_MAX.
# Supports named instances "Regular" and "Bold" via set_variation_by_name.
_ROBOTO_PATH: Path = FONTS_DIR / "Roboto" / "Roboto[wdth,wght].ttf"

# Legacy auto-selection support (used by select_font / render_lores).
_DEFAULT_SIZE_THRESHOLD: int = 24  # px; below this switches to low-res font
_LORES_SIZE_RE = re.compile(r"LoRes(\d+)(Minus|Plus)?OT")

_BASE_FONT: ImageFont.ImageFont = ImageFont.load_default()
_BASE_FONT_H: int = 10
_BITMAP_THRESHOLD: int = 80  # grayscale cutoff for pixel-on/off in bitmap_text_img


# ── Module-level utility functions ─────────────────────────────────────────────


def _snap_pixel_size(size: int) -> int:
    """Return the nearest supported design size across all pixel-font families."""
    return min(_ALL_PIXEL_SIZES, key=lambda s: abs(s - size))


def _resolve_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Select the best font for size and bold.

    Sizes ≤ _PIXEL_MAX: snap to the nearest supported design size across both
    DanielLinssen (7, 8, 9) and LoRes (9, 12, 15, 22, 28) pixel-font families.
    LoRes takes priority when both families share a design size (currently 9).
    Daniel Linssen fonts are loaded at their native_load_size for crisp output.
    Sizes > _PIXEL_MAX: use Roboto, falling back to PIL's built-in default.
    """
    if size <= _PIXEL_MAX:
        snapped = _snap_pixel_size(size)
        if snapped in _LORES_FONTS:
            filename = _LORES_FONTS[snapped][1 if bold else 0]
            return load_font_file(_LORES_DIR / filename, snapped)
        regular, bold_f, load_size = _DANIEL_FONTS[snapped]
        return load_font_file(_DANIEL_DIR / (bold_f if bold else regular), load_size)
    if _ROBOTO_PATH.exists():
        try:
            font = ImageFont.truetype(str(_ROBOTO_PATH), size=size)
            if bold:
                font.set_variation_by_name("Bold")
            return font
        except Exception:
            pass
    return load_font(size)


def _parse_lores_design_size(filename: str) -> float | None:
    m = _LORES_SIZE_RE.match(filename)
    if not m:
        return None
    base = int(m.group(1))
    modifier = m.group(2)
    if modifier == "Minus":
        return base - 1.0
    if modifier == "Plus":
        return base + 1.0
    return float(base)


def _lores_font_priority(path: Path) -> tuple[int, int]:
    """Lower tuple = higher priority. Prefers base Regular over styled/Bold variants."""
    after_ot = path.stem.split("OT", 1)[1] if "OT" in path.stem else path.stem
    has_style = bool(re.search(r"(Narrow|Wide|Serif|Oakland|Alt)", after_ot))
    is_bold = "Bold" in after_ot
    return (int(has_style), int(is_bold))


def _find_lores_font(size: int) -> Path | None:
    """Return the LoRes font file whose design size is closest to size."""
    candidates: list[tuple[float, Path]] = []
    for path in _LORES_DIR.glob("*.ttf"):
        design_size = _parse_lores_design_size(path.name)
        if design_size is not None:
            candidates.append((design_size, path))
    if not candidates:
        return None
    closest = min(candidates, key=lambda x: abs(x[0] - size))[0]
    at_closest = [p for ds, p in candidates if ds == closest]
    return min(at_closest, key=_lores_font_priority)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def load_font_file(
    path: Path | str,
    size: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a TrueType/OpenType font file at the given pixel size, falling back to the PIL default."""
    try:
        return ImageFont.truetype(str(path), size=size)
    except (OSError, IOError):
        return load_font(size)


def select_font(
    size: int,
    *,
    high_res_font: Path | str | None = None,
    low_res_font: Path | str | None = None,
    threshold: int = _DEFAULT_SIZE_THRESHOLD,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return the appropriate font for the given pixel size.

    Picks high_res_font when size >= threshold, otherwise low_res_font.
    Falls back to PIL's default font if the file cannot be loaded.
    """
    if size >= threshold:
        if high_res_font:
            return load_font_file(high_res_font, size)
        return load_font(size)
    if low_res_font:
        return load_font_file(low_res_font, size)
    path = _find_lores_font(size)
    return load_font_file(path, size) if path else load_font(size)


def measure_text(
    text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont
) -> tuple[int, int]:
    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def can_fit_text(max_width: int, size: int, text: str, bold: bool = False) -> bool:
    """Return True if text renders within max_width pixels at the given font size."""
    font  = _resolve_font(size, bold)
    dummy = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox  = dummy.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0] <= max_width


def fit_text(max_width: int, size: int, *candidates: str, bold: bool = False) -> str:
    """Return the first candidate whose rendered pixel width fits within max_width.

    Try candidates in order (longest/preferred first). Return the last candidate
    if none fit. Return "" if no candidates are given.
    """
    if not candidates:
        return ""
    for text in candidates:
        if can_fit_text(max_width, size, text, bold=bold):
            return text
    return candidates[-1]


def draw_text_centered(
    canvas: Canvas,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    color: tuple[int, int, int],
) -> None:
    text_w, text_h = measure_text(text, font)
    img = Image.new("RGB", (max(text_w, 1), canvas.height))
    draw = ImageDraw.Draw(img)
    dummy = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy)
    bbox = dummy_draw.textbbox((0, 0), text, font=font)
    y = (canvas.height - text_h) // 2 - bbox[1]
    draw.text((0, y), text, font=font, fill=color)
    blit(canvas, img, (canvas.width - text_w) // 2)


def _apply_aliasing(
    gray: Image.Image,
    color: tuple[int, int, int],
    aliasing: bool,
) -> Image.Image:
    """Convert a grayscale glyph render to RGB using the chosen aliasing mode.

    aliasing=True  — composite smoothly; partial-gray pixels become blended color.
    aliasing=False — snap every pixel to either full color or black (no partials).
    """
    rgb = Image.new("RGB", gray.size, (0, 0, 0))
    if aliasing:
        # Use the gray channel as an alpha mask so the glyph blends against black.
        rgba = Image.new("RGBA", gray.size, (*color, 0))
        rgba.putalpha(gray)
        rgb.paste(rgba, mask=rgba.split()[3])
    else:
        rgb.putdata(
            [(color if p >= 128 else (0, 0, 0)) for p in gray.getdata()]
        )
    return rgb


def render_text(
    text: str,
    color: tuple[int, int, int],
    size: int,
    *,
    bold: bool = False,
    aliasing: bool = False,
    fixed_h: int | None = None,
    # Legacy override params — if either is provided the old select_font path is used.
    high_res_font: Path | str | None = None,
    low_res_font: Path | str | None = None,
    threshold: int = _DEFAULT_SIZE_THRESHOLD,
) -> Image.Image:
    """Render text with automatic font selection and configurable aliasing.

    Font selection (default path):
        size ≤ 28 → nearest pixel-font design size: DanielLinssen (6, 7, 11) or
                    LoRes (9, 12, 15, 22, 28), bold variant if bold=True.
        size > 28 → Roboto (falls back to PIL built-in if not found on the system).

    aliasing=True  → smooth anti-aliased render.
    aliasing=False → pixel-perfect: every pixel is either full color or black.

    fixed_h forces the output image to a specific height; shorter glyphs are
    centred, taller ones are scaled down with NEAREST resampling.
    """
    if not text:
        h = fixed_h if fixed_h is not None else max(1, size)
        return Image.new("RGB", (1, h))

    if high_res_font is not None or low_res_font is not None:
        font = select_font(
            size,
            high_res_font=high_res_font,
            low_res_font=low_res_font,
            threshold=threshold,
        )
    else:
        font = _resolve_font(size, bold)

    bbox = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
    gw = max(1, bbox[2] - bbox[0])
    gh = max(1, bbox[3] - bbox[1])

    gray = Image.new("L", (gw, gh), 0)
    ImageDraw.Draw(gray).text((-bbox[0], -bbox[1]), text, font=font, fill=255)

    rgb = _apply_aliasing(gray, color, aliasing)

    if fixed_h is not None and rgb.height != fixed_h:
        if rgb.height > fixed_h:
            new_w = max(1, round(rgb.width * fixed_h / rgb.height))
            rgb = rgb.resize((new_w, fixed_h), Image.NEAREST)
        else:
            canvas = Image.new("RGB", (rgb.width, fixed_h), (0, 0, 0))
            canvas.paste(rgb, (0, (fixed_h - rgb.height) // 2))
            rgb = canvas

    return rgb


def render_lores(
    text: str,
    color: tuple[int, int, int],
    size: int,
    *,
    font_path: Path | str | None = None,
    aliasing: bool = False,
    fixed_h: int | None = None,
) -> Image.Image:
    """Render text using a LoRes pixel font, with no high-res fallback.

    font_path overrides auto-selection; when omitted the closest LoRes design
    size is chosen automatically via _find_lores_font.
    """
    if not text:
        h = fixed_h if fixed_h is not None else max(1, size)
        return Image.new("RGB", (1, h))

    path = Path(font_path) if font_path else _find_lores_font(size)
    font = load_font_file(path, size) if path else load_font(size)

    bbox = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
    gw = max(1, bbox[2] - bbox[0])
    gh = max(1, bbox[3] - bbox[1])

    gray = Image.new("L", (gw, gh), 0)
    ImageDraw.Draw(gray).text((-bbox[0], -bbox[1]), text, font=font, fill=255)

    rgb = _apply_aliasing(gray, color, aliasing)

    if fixed_h is not None and rgb.height != fixed_h:
        if rgb.height > fixed_h:
            new_w = max(1, round(rgb.width * fixed_h / rgb.height))
            rgb = rgb.resize((new_w, fixed_h), Image.NEAREST)
        else:
            canvas = Image.new("RGB", (rgb.width, fixed_h), (0, 0, 0))
            canvas.paste(rgb, (0, (fixed_h - rgb.height) // 2))
            rgb = canvas

    return rgb


def bitmap_text_img(
    text: str,
    color: tuple[int, int, int],
    target_h: int,
    fixed_h: int | None = None,
) -> Image.Image:
    """Render text at target_h pixels tall with every pixel fully on or off.

    If fixed_h is given the output image is forced to exactly that height:
    shorter glyphs are embedded centred in a black canvas, taller ones are
    scaled down. Pass the cap-height of a representative "A" as fixed_h so
    that symbols like "$" align with letters and every element shares an
    identical image height.
    """
    if not text:
        h = fixed_h if fixed_h else max(1, target_h)
        return Image.new("RGB", (1, h))

    if target_h <= _BASE_FONT_H:
        bbox = ImageDraw.Draw(Image.new("1", (1, 1))).textbbox(
            (0, 0), text, font=_BASE_FONT
        )
        gw = max(1, bbox[2] - bbox[0])
        gh = max(1, bbox[3] - bbox[1])
        mono = Image.new("1", (gw, gh), 0)
        ImageDraw.Draw(mono).text((-bbox[0], -bbox[1]), text, font=_BASE_FONT, fill=1)
        rgb = Image.new("RGB", (gw, gh), (0, 0, 0))
        rgb.putdata([(color if p else (0, 0, 0)) for p in mono.getdata()])
    else:
        try:
            font = ImageFont.load_default(size=target_h)
        except TypeError:
            scale = max(1, round(target_h / _BASE_FONT_H))
            bbox = ImageDraw.Draw(Image.new("1", (1, 1))).textbbox(
                (0, 0), text, font=_BASE_FONT
            )
            gw = max(1, bbox[2] - bbox[0])
            gh = max(1, bbox[3] - bbox[1])
            mono = Image.new("1", (gw, gh), 0)
            ImageDraw.Draw(mono).text((-bbox[0], -bbox[1]), text, font=_BASE_FONT, fill=1)
            rgb = Image.new("RGB", (gw, gh), (0, 0, 0))
            rgb.putdata([(color if p else (0, 0, 0)) for p in mono.getdata()])
            rgb = rgb.resize((gw * scale, gh * scale), Image.NEAREST)
        else:
            bbox = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox(
                (0, 0), text, font=font
            )
            gw = max(1, bbox[2] - bbox[0])
            gh = max(1, bbox[3] - bbox[1])
            gray = Image.new("L", (gw, gh), 0)
            ImageDraw.Draw(gray).text((-bbox[0], -bbox[1]), text, font=font, fill=255)
            rgb = Image.new("RGB", (gw, gh), (0, 0, 0))
            rgb.putdata(
                [(color if p >= _BITMAP_THRESHOLD else (0, 0, 0)) for p in gray.getdata()]
            )

    if fixed_h is not None and rgb.height != fixed_h:
        if rgb.height > fixed_h:
            new_w = max(1, round(rgb.width * fixed_h / rgb.height))
            rgb = rgb.resize((new_w, fixed_h), Image.NEAREST)
        else:
            canvas = Image.new("RGB", (rgb.width, fixed_h), (0, 0, 0))
            canvas.paste(rgb, (0, (fixed_h - rgb.height) // 2))
            rgb = canvas

    return rgb


_STATUS_COLOR: tuple[int, int, int] = (80, 80, 80)
_STATUS_MAX_SIZE: int = 14


def draw_status_message(canvas: Canvas, msg: str) -> None:
    """Render a dim, centered status message (e.g. "Loading...") onto canvas.

    Always renders at _STATUS_MAX_SIZE px, clipping trailing characters if the
    text would overflow the canvas width.
    """
    w, h = canvas.width, canvas.height
    max_w = max(6, w - 4)
    clipped = msg
    while clipped and not can_fit_text(max_w, _STATUS_MAX_SIZE, clipped):
        clipped = clipped[:-1]
    msg_img = render_text(clipped, _STATUS_COLOR, _STATUS_MAX_SIZE)
    img = Image.new("RGB", (w, h))
    x = (w - msg_img.width) // 2
    y = (h - msg_img.height) // 2
    img.paste(msg_img, (max(0, x), max(0, y)))
    blit(canvas, img)


def arrow_img(
    up: bool,
    size: int,
    color: tuple[int, int, int],
) -> Image.Image:
    """Draw a solid pixel-perfect triangle arrow. up=True → ▲, up=False → ▼."""
    size = max(3, size)
    img = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = size // 2
    if up:
        pts = [(cx, 0), (0, size - 1), (size - 1, size - 1)]
    else:
        pts = [(0, 0), (size - 1, 0), (cx, size - 1)]
    draw.polygon(pts, fill=color)
    return img


# ── Library class ──────────────────────────────────────────────────────────────


class TextRendererLibrary(Library):
    id: ClassVar[str] = "text_renderer"
    name: ClassVar[str] = "Text Renderer"
    description: ClassVar[str] = "Pixel-perfect bitmap text rendering utilities for LED displays"
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    global_config_schema: ClassVar[dict[str, Any]] = {}

    load_font = staticmethod(load_font)
    load_font_file = staticmethod(load_font_file)
    select_font = staticmethod(select_font)
    measure_text = staticmethod(measure_text)
    can_fit_text = staticmethod(can_fit_text)
    fit_text = staticmethod(fit_text)
    draw_text_centered = staticmethod(draw_text_centered)
    render_text = staticmethod(render_text)
    render_lores = staticmethod(render_lores)
    bitmap_text_img = staticmethod(bitmap_text_img)
    draw_status_message = staticmethod(draw_status_message)
    arrow_img = staticmethod(arrow_img)

    @property
    def base_font_h(self) -> int:
        return _BASE_FONT_H

    @property
    def min_pixel_font_size(self) -> int:
        return _PIXEL_MIN

    @property
    def default_size_threshold(self) -> int:
        return _DEFAULT_SIZE_THRESHOLD

    @property
    def fonts_dir(self) -> Path:
        return FONTS_DIR
