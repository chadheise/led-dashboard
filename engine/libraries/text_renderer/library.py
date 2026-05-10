from __future__ import annotations

from typing import Any, ClassVar

from PIL import Image, ImageDraw, ImageFont

from canvas.base import Canvas
from libraries.base import Library
from libraries.canvas_utils.library import blit


_BASE_FONT: ImageFont.ImageFont = ImageFont.load_default()
_BASE_FONT_H: int = 10
_THRESHOLD: int = 80


# ── Module-level utility functions ─────────────────────────────────────────────


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


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
                [(color if p >= _THRESHOLD else (0, 0, 0)) for p in gray.getdata()]
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
    measure_text = staticmethod(measure_text)
    draw_text_centered = staticmethod(draw_text_centered)
    bitmap_text_img = staticmethod(bitmap_text_img)
    arrow_img = staticmethod(arrow_img)

    @property
    def base_font_h(self) -> int:
        return _BASE_FONT_H
