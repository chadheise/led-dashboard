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

# High-res uses PIL's built-in default (clean, smooth).
# Low-res auto-selects from _LORES_DIR by closest design size.
_DEFAULT_SIZE_THRESHOLD: int = 24  # px; below this switches to low-res font

_LORES_SIZE_RE = re.compile(r"LoRes(\d+)(Minus|Plus)?OT")

_BASE_FONT: ImageFont.ImageFont = ImageFont.load_default()
_BASE_FONT_H: int = 10
_BITMAP_THRESHOLD: int = 80  # grayscale cutoff for pixel-on/off in bitmap_text_img


# ── Module-level utility functions ─────────────────────────────────────────────


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
    high_res_font: Path | str | None = None,
    low_res_font: Path | str | None = None,
    threshold: int = _DEFAULT_SIZE_THRESHOLD,
    aliasing: bool = False,
    fixed_h: int | None = None,
) -> Image.Image:
    """Render text with automatic font selection and configurable aliasing.

    Font selection:
        size >= threshold → high_res_font (default: CoFo Sans Pixel)
        size <  threshold → low_res_font  (default: Lo-Res OT)

    aliasing=True  → smooth anti-aliased render.
    aliasing=False → pixel-perfect: every pixel is either full color or black.

    fixed_h forces the output image to a specific height; shorter glyphs are
    centred, taller ones are scaled down with NEAREST resampling.
    """
    if not text:
        h = fixed_h if fixed_h is not None else max(1, size)
        return Image.new("RGB", (1, h))

    font = select_font(
        size,
        high_res_font=high_res_font,
        low_res_font=low_res_font,
        threshold=threshold,
    )

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
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/>'
        '<line x1="12" y1="4" x2="12" y2="20"/></svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {}

    load_font = staticmethod(load_font)
    load_font_file = staticmethod(load_font_file)
    select_font = staticmethod(select_font)
    measure_text = staticmethod(measure_text)
    draw_text_centered = staticmethod(draw_text_centered)
    render_text = staticmethod(render_text)
    render_lores = staticmethod(render_lores)
    bitmap_text_img = staticmethod(bitmap_text_img)
    arrow_img = staticmethod(arrow_img)

    @property
    def base_font_h(self) -> int:
        return _BASE_FONT_H

    @property
    def default_size_threshold(self) -> int:
        return _DEFAULT_SIZE_THRESHOLD

    @property
    def fonts_dir(self) -> Path:
        return FONTS_DIR
