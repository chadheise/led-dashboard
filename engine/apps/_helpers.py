from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from canvas.base import Canvas


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def parse_color(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) != 6:
        return (255, 255, 255)
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def measure_text(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> tuple[int, int]:
    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def blit(canvas: Canvas, img: Image.Image, x_offset: int = 0) -> None:
    """Copy img onto canvas with img's left edge at x_offset.

    Positive x_offset shifts the image right; negative scrolls it left.
    Only the pixels that fall within canvas bounds are drawn.
    """
    data = img.tobytes()
    w, h = img.size
    dst_start = max(0, x_offset)
    dst_end = min(canvas.width, x_offset + w)
    for dst_x in range(dst_start, dst_end):
        src_x = dst_x - x_offset
        for y in range(h):
            idx = (y * w + src_x) * 3
            canvas.set_pixel(dst_x, y, data[idx], data[idx + 1], data[idx + 2])


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
    x_offset = (canvas.width - text_w) // 2
    blit(canvas, img, x_offset)
