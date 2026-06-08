from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image, ImageDraw

from libraries.base import Library

logger = logging.getLogger(__name__)

_HOLIDAYS_FILE = Path(__file__).parent / "holidays.json"
_HOLIDAYS: list[dict[str, Any]] = json.loads(_HOLIDAYS_FILE.read_text(encoding="utf-8"))
_HOLIDAY_BY_ID: dict[str, dict[str, Any]] = {e["id"]: e for e in _HOLIDAYS}


# ── Date math ───────────────────────────────────────────────────────────────
#
# Four rule kinds cover every holiday whose date follows a closed-form
# calendar rule (computable exactly for any year); a fifth ("lookup") covers
# lunar/lunisolar holidays whose dates are set by astronomical observation
# and have no such formula — those are backed by a precomputed table in
# holidays.json and gracefully resolve to None outside its covered range.


def _easter_date(year: int) -> date:
    """Easter Sunday for `year`, via the Anonymous Gregorian algorithm (Computus)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday_date(year: int, month: int, weekday: int, n: int) -> date:
    """The date of the n-th `weekday` (0=Mon..6=Sun) in `month`/`year`."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday_date(year: int, month: int, weekday: int) -> date:
    """The date of the last `weekday` (0=Mon..6=Sun) in `month`/`year`."""
    next_month_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = next_month_first - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _holiday_date_for_year(entry: dict[str, Any], year: int) -> date | None:
    """Resolve `entry`'s date in `year`, or None if its rule can't cover that year."""
    rule = entry.get("rule")
    if rule == "fixed":
        return date(year, int(entry["month"]), int(entry["day"]))
    if rule == "nth_weekday":
        return _nth_weekday_date(year, int(entry["month"]), int(entry["weekday"]), int(entry["n"]))
    if rule == "last_weekday":
        return _last_weekday_date(year, int(entry["month"]), int(entry["weekday"]))
    if rule == "easter_offset":
        return _easter_date(year) + timedelta(days=int(entry["offset_days"]))
    if rule == "lookup":
        raw = entry.get("dates", {}).get(str(year))
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def next_occurrence(holiday_id: str, after: datetime) -> datetime | None:
    """The next occurrence of `holiday_id` at/after `after`, at local midnight.

    `after` should be timezone-aware in the viewer's zone — the result is
    midnight on the holiday's date in that same zone. Returns None for
    unknown ids, or when neither this year's nor next year's date can be
    resolved (e.g. a `lookup` holiday outside its covered range).
    """
    entry = _HOLIDAY_BY_ID.get(holiday_id)
    if entry is None:
        return None

    today = after.date()
    candidate = _holiday_date_for_year(entry, today.year)
    if candidate is None or candidate < today:
        candidate = _holiday_date_for_year(entry, today.year + 1)
    if candidate is None:
        return None
    return datetime.combine(candidate, datetime.min.time(), tzinfo=after.tzinfo)


# ── Catalog accessors ───────────────────────────────────────────────────────


def list_holidays() -> list[dict[str, Any]]:
    """Curated world-holiday dataset, for building selection UIs."""
    return list(_HOLIDAYS)


def holiday_name(holiday_id: str) -> str:
    entry = _HOLIDAY_BY_ID.get(holiday_id)
    return entry["name"] if entry is not None else holiday_id


def holiday_icons(holiday_id: str) -> list[dict[str, str]]:
    """The selectable icon options for a holiday — empty for text-only ones."""
    entry = _HOLIDAY_BY_ID.get(holiday_id)
    return list(entry["icons"]) if entry is not None and "icons" in entry else []


# ── Procedural icon drawing ─────────────────────────────────────────────────
#
# Mirrors `weather_icon_img` in `open_meteo/library.py`: icons are drawn with
# simple PIL primitives, scaled to the requested pixel size, rather than
# loaded from bitmap assets — the project has no icon-asset pipeline, and a
# vector approach renders crisply at any resolution the LED panel needs.


def _heart(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple[int, int, int]) -> None:
    r = size * 0.27
    ly = cy - size * 0.12
    draw.ellipse([cx - 2 * r, ly - r, cx, ly + r], fill=color)
    draw.ellipse([cx, ly - r, cx + 2 * r, ly + r], fill=color)
    draw.polygon([(cx - 2 * r, ly), (cx + 2 * r, ly), (cx, cy + size * 0.42)], fill=color)


def _cupid_arrow(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple[int, int, int]) -> None:
    """A heart with a shallow arrow through it — shaft, head, and tail fletching."""
    _heart(draw, cx, cy, size * 0.66, color)
    half = size * 0.52
    width = max(1, round(size * 0.06))
    x0, y0 = cx - half, cy + half * 0.42
    x1, y1 = cx + half, cy - half * 0.42
    draw.line([(x0, y0), (x1, y1)], fill=color, width=width)
    ang = math.atan2(y1 - y0, x1 - x0)
    perp = ang + math.pi / 2
    head = size * 0.13
    head_base = (x1 - head * 1.4 * math.cos(ang), y1 - head * 1.4 * math.sin(ang))
    draw.polygon([
        (x1, y1),
        (head_base[0] + head * math.cos(perp), head_base[1] + head * math.sin(perp)),
        (head_base[0] - head * math.cos(perp), head_base[1] - head * math.sin(perp)),
    ], fill=color)
    fletch = size * 0.09
    tail_base = (x0 + fletch * 1.3 * math.cos(ang), y0 + fletch * 1.3 * math.sin(ang))
    draw.polygon([
        (x0, y0),
        (tail_base[0] + fletch * math.cos(perp), tail_base[1] + fletch * math.sin(perp)),
        (tail_base[0] - fletch * math.cos(perp), tail_base[1] - fletch * math.sin(perp)),
    ], fill=color)


def _firework_burst(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple[int, int, int]) -> None:
    width = max(1, round(r * 0.16))
    dot_r = max(1.0, r * 0.13)
    for deg in range(0, 360, 45):
        rad = math.radians(deg)
        length = r * (1.0 if deg % 90 == 0 else 0.7)
        x1, y1 = cx + length * math.cos(rad), cy + length * math.sin(rad)
        draw.line([(cx, cy), (x1, y1)], fill=color, width=width)
        draw.ellipse([x1 - dot_r, y1 - dot_r, x1 + dot_r, y1 + dot_r], fill=color)
    draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=color)


def _party_hat(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    apex = (cx, cy - h * 0.5)
    base_y = cy + h * 0.28
    draw.polygon([apex, (cx - w * 0.42, base_y), (cx + w * 0.42, base_y)], fill=color)
    draw.ellipse([cx - w * 0.5, base_y - h * 0.1, cx + w * 0.5, base_y + h * 0.12], fill=color)
    pom_r = max(1.0, h * 0.11)
    draw.ellipse([apex[0] - pom_r, apex[1] - pom_r, apex[0] + pom_r, apex[1] + pom_r], fill=color)


def _shamrock(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple[int, int, int]) -> None:
    """Three radially-arranged lobes (top, lower-left, lower-right) plus a stem."""
    lobe_r = r * 0.4
    center_y = cy - r * 0.18
    for deg in (270, 30, 150):
        rad = math.radians(deg)
        x = cx + lobe_r * 1.15 * math.cos(rad)
        y = center_y + lobe_r * 1.15 * math.sin(rad)
        draw.ellipse([x - lobe_r, y - lobe_r, x + lobe_r, y + lobe_r], fill=color)
    width = max(1, round(r * 0.16))
    draw.line([(cx, center_y + lobe_r * 0.6), (cx, cy + r * 1.05)], fill=color, width=width)


def _rainbow_arc(draw: ImageDraw.ImageDraw, cx: float, baseline: float, r: float, color: tuple[int, int, int]) -> None:
    bands = 3
    band = r / bands
    for i in range(bands):
        radius = r - i * band
        width = max(1, round(band * 0.85))
        bbox = [cx - radius, baseline - radius, cx + radius, baseline + radius]
        draw.arc(bbox, start=180, end=360, fill=color, width=width)


def _egg(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    """An egg silhouette — narrower top and wider bottom blended with heavy overlap."""
    draw.ellipse([cx - w * 0.4, cy - h * 0.5, cx + w * 0.4, cy + h * 0.16], fill=color)
    draw.ellipse([cx - w * 0.5, cy - h * 0.26, cx + w * 0.5, cy + h * 0.5], fill=color)


def _bunny(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    """A round bunny face with two long upright ears and dot eyes."""
    head_r = w * 0.3
    head_cy = cy + h * 0.22
    ear_w = w * 0.16
    ear_h = h * 0.46
    for dx in (-w * 0.16, w * 0.16):
        ex = cx + dx
        draw.rounded_rectangle(
            [ex - ear_w / 2, head_cy - head_r - ear_h * 0.92, ex + ear_w / 2, head_cy - head_r * 0.5],
            radius=ear_w * 0.5, fill=color,
        )
    draw.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=color)
    eye_r = max(1.0, head_r * 0.16)
    for dx in (-head_r * 0.4, head_r * 0.4):
        ex, ey = cx + dx, head_cy - head_r * 0.05
        draw.ellipse([ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r], fill=(0, 0, 0))


def _flag(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    pole_x = cx - w * 0.4
    width = max(1, round(w * 0.07))
    draw.line([(pole_x, cy - h * 0.6), (pole_x, cy + h * 0.6)], fill=color, width=width)
    draw.polygon([
        (pole_x, cy - h * 0.6),
        (pole_x + w * 0.8, cy - h * 0.32),
        (pole_x, cy - h * 0.04),
    ], fill=color)


def _star_burst(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple[int, int, int]) -> None:
    points = 8
    pts = []
    for i in range(points * 2):
        ang = math.pi * i / points - math.pi / 2
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    draw.polygon(pts, fill=color)


def _pumpkin(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    body_top = cy - h * 0.34
    draw.rounded_rectangle([cx - w * 0.5, body_top, cx + w * 0.5, cy + h * 0.5], radius=h * 0.32, fill=color)
    width = max(1, round(w * 0.05))
    for dx in (-w * 0.25, 0.0, w * 0.25):
        draw.line([(cx + dx, body_top + h * 0.06), (cx + dx, cy + h * 0.46)], fill=(0, 0, 0), width=width)
    draw.rectangle([cx - w * 0.06, cy - h * 0.62, cx + w * 0.06, body_top + h * 0.05], fill=color)


def _ghost(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    """A rounded body with a scalloped hem (alternating bumps/notches) and dot eyes."""
    r = w * 0.5
    top = cy - h * 0.5
    hem = cy + h * 0.22
    draw.rounded_rectangle([cx - r, top, cx + r, hem], radius=r, fill=color)
    n = 4
    seg = (2 * r) / n
    bump_r = seg * 0.42
    for i in range(n):
        x = cx - r + (i + 0.5) * seg
        fill = color if i % 2 == 0 else (0, 0, 0)
        draw.ellipse([x - bump_r, hem - bump_r, x + bump_r, hem + bump_r], fill=fill)
    eye_r = max(1.0, w * 0.08)
    for dx in (-w * 0.17, w * 0.17):
        ex, ey = cx + dx, top + r * 0.95
        draw.ellipse([ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r], fill=(0, 0, 0))


def _turkey(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    """A side-profile bird — scalloped fanned tail wedge behind an oval body with a beak."""
    body_cx, body_cy = cx - w * 0.06, cy + h * 0.16
    body_rx, body_ry = w * 0.24, h * 0.22
    tail_r = h * 0.62
    origin = (body_cx + body_rx * 0.2, body_cy - body_ry * 0.1)
    draw.pieslice(
        [origin[0] - tail_r, origin[1] - tail_r, origin[0] + tail_r, origin[1] + tail_r],
        start=-95, end=-5, fill=color,
    )
    bump_r = tail_r * 0.18
    for deg in (-90, -65, -40, -15):
        rad = math.radians(deg)
        x = origin[0] + tail_r * math.cos(rad)
        y = origin[1] + tail_r * math.sin(rad)
        draw.ellipse([x - bump_r, y - bump_r, x + bump_r, y + bump_r], fill=color)
    draw.ellipse([body_cx - body_rx, body_cy - body_ry, body_cx + body_rx, body_cy + body_ry], fill=color)
    head_r = h * 0.095
    head_cx, head_cy = body_cx - body_rx * 0.85, body_cy - body_ry * 0.75
    draw.ellipse([head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r], fill=color)
    draw.polygon([
        (head_cx - head_r * 0.5, head_cy + head_r * 0.1),
        (head_cx - head_r * 1.8, head_cy + head_r * 0.4),
        (head_cx - head_r * 0.5, head_cy + head_r * 0.7),
    ], fill=color)


def _pie(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple[int, int, int]) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    width = max(1, round(r * 0.14))
    for dx in (-r * 0.45, 0.0, r * 0.45):
        draw.line([(cx + dx, cy - r * 0.85), (cx + dx, cy + r * 0.85)], fill=(0, 0, 0), width=width)
    for dy in (-r * 0.45, 0.0, r * 0.45):
        draw.line([(cx - r * 0.85, cy + dy), (cx + r * 0.85, cy + dy)], fill=(0, 0, 0), width=width)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=max(1, round(r * 0.12)))


def _tree(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    trunk_w = w * 0.16
    trunk_h = h * 0.16
    base_y = cy + h * 0.5
    draw.rectangle([cx - trunk_w / 2, base_y - trunk_h, cx + trunk_w / 2, base_y], fill=color)
    tiers = 3
    tier_h = (h * 0.84) / tiers
    top = cy - h * 0.5
    for i in range(tiers):
        tier_top = top + i * tier_h * 0.72
        tier_bottom = tier_top + tier_h
        half_w = (w * 0.5) * ((i + 1) / tiers)
        draw.polygon([(cx, tier_top), (cx - half_w, tier_bottom), (cx + half_w, tier_bottom)], fill=color)


def _santa_hat(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    apex = (cx - w * 0.18, cy - h * 0.5)
    brim_y = cy + h * 0.22
    draw.polygon([apex, (cx - w * 0.45, brim_y), (cx + w * 0.48, brim_y)], fill=color)
    draw.rounded_rectangle([cx - w * 0.5, brim_y - h * 0.1, cx + w * 0.5, brim_y + h * 0.16], radius=h * 0.12, fill=color)
    pom_r = max(1.0, h * 0.13)
    draw.ellipse([apex[0] - pom_r, apex[1] - pom_r, apex[0] + pom_r, apex[1] + pom_r], fill=color)


def _lantern(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    """A round paper-lantern body with cord, end caps, and vertical rib lines."""
    width = max(1, round(w * 0.1))
    draw.line([(cx, cy - h * 0.5), (cx, cy - h * 0.32)], fill=color, width=width)
    cap_w = w * 0.4
    draw.ellipse([cx - cap_w / 2, cy - h * 0.34, cx + cap_w / 2, cy - h * 0.22], fill=color)
    draw.ellipse([cx - cap_w / 2, cy + h * 0.22, cx + cap_w / 2, cy + h * 0.34], fill=color)
    draw.ellipse([cx - w * 0.5, cy - h * 0.28, cx + w * 0.5, cy + h * 0.28], fill=color)
    rib_w = max(1, round(w * 0.045))
    for dx in (-w * 0.2, 0.0, w * 0.2):
        draw.line([(cx + dx, cy - h * 0.22), (cx + dx, cy + h * 0.22)], fill=(0, 0, 0), width=rib_w)


def _paper_fan(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple[int, int, int]) -> None:
    draw.pieslice([cx - r, cy - r, cx + r, cy + r], start=180, end=360, fill=color)
    width = max(1, round(r * 0.07))
    for deg in (200, 230, 270, 310, 340):
        rad = math.radians(deg)
        draw.line([(cx, cy), (cx + r * math.cos(rad), cy + r * math.sin(rad))], fill=(0, 0, 0), width=width)
    hub_r = max(1.0, r * 0.1)
    draw.ellipse([cx - hub_r, cy - hub_r, cx + hub_r, cy + hub_r], fill=color)


def _oil_lamp(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, color: tuple[int, int, int]) -> None:
    """A shallow diya saucer on a small stand, with a teardrop flame above it."""
    bowl_cy = cy + h * 0.22
    bowl_w = w * 0.74
    bowl_h = h * 0.16
    draw.ellipse([cx - bowl_w / 2, bowl_cy - bowl_h, cx + bowl_w / 2, bowl_cy + bowl_h], fill=color)
    base_w = bowl_w * 0.3
    draw.polygon([
        (cx - base_w / 2, bowl_cy + bowl_h * 0.5),
        (cx + base_w / 2, bowl_cy + bowl_h * 0.5),
        (cx, cy + h * 0.5),
    ], fill=color)
    flame_w = w * 0.1
    flame_top = cy - h * 0.4
    flame_bottom = bowl_cy - bowl_h * 1.8
    draw.ellipse([cx - flame_w, flame_top, cx + flame_w, flame_bottom], fill=color)


def _string_lights(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, color: tuple[int, int, int]) -> None:
    width = max(1, round(w * 0.045))
    n = 4
    seg = w / n
    sag = w * 0.12
    pts = []
    for i in range(n + 1):
        x = cx - w / 2 + i * seg
        y = cy - sag if i % 2 == 0 else cy + sag * 0.6
        pts.append((x, y))
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=color, width=width)
    bulb_r = max(1.0, w * 0.07)
    for x, y in pts[1:-1]:
        draw.ellipse([x - bulb_r, y - bulb_r, x + bulb_r, y + bulb_r], fill=color)


def holiday_icon_img(icon_id: str, size: int, color: tuple[int, int, int]) -> Image.Image:
    """Draw a small holiday icon, scaled to fill a size x size square."""
    size = max(8, int(size))
    img = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2.0

    if icon_id == "fireworks":
        _firework_burst(draw, cx, cy, size * 0.42, color)
    elif icon_id == "party_hat":
        _party_hat(draw, cx, cy, size * 0.6, size * 0.8, color)
    elif icon_id == "heart":
        _heart(draw, cx, cy * 0.96, size * 0.78, color)
    elif icon_id == "cupid_arrow":
        _cupid_arrow(draw, cx, cy, size * 0.8, color)
    elif icon_id == "shamrock":
        _shamrock(draw, cx, cy, size * 0.4, color)
    elif icon_id == "rainbow":
        _rainbow_arc(draw, cx, size * 0.66, size * 0.42, color)
    elif icon_id == "egg":
        _egg(draw, cx, cy, size * 0.56, size * 0.78, color)
    elif icon_id == "bunny":
        _bunny(draw, cx, cy, size * 0.66, size * 0.8, color)
    elif icon_id == "flag":
        _flag(draw, cx, cy, size * 0.6, size * 0.46, color)
    elif icon_id == "star_burst":
        _star_burst(draw, cx, cy, size * 0.44, color)
    elif icon_id == "pumpkin":
        _pumpkin(draw, cx, cy, size * 0.7, size * 0.6, color)
    elif icon_id == "ghost":
        _ghost(draw, cx, cy, size * 0.6, size * 0.74, color)
    elif icon_id == "turkey":
        _turkey(draw, cx, cy, size * 0.78, size * 0.66, color)
    elif icon_id == "pie":
        _pie(draw, cx, cy, size * 0.42, color)
    elif icon_id == "tree":
        _tree(draw, cx, cy, size * 0.66, size * 0.84, color)
    elif icon_id == "santa_hat":
        _santa_hat(draw, cx, cy, size * 0.7, size * 0.66, color)
    elif icon_id == "lantern":
        _lantern(draw, cx, cy, size * 0.58, size * 0.82, color)
    elif icon_id == "paper_fan":
        _paper_fan(draw, cx, cy, size * 0.42, color)
    elif icon_id == "oil_lamp":
        _oil_lamp(draw, cx, cy, size * 0.7, size * 0.7, color)
    elif icon_id == "string_lights":
        _string_lights(draw, cx, cy, size * 0.78, color)

    return img


# ── Library class ───────────────────────────────────────────────────────────


class HolidaysLibrary(Library):
    id: ClassVar[str] = "holidays"
    name: ClassVar[str] = "Holidays"
    description: ClassVar[str] = (
        "A curated catalog of common world holidays — closed-form date rules "
        "for fixed and floating observances, a precomputed table for "
        "lunar/lunisolar ones, and small procedural icons for popular days"
    )
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7"/>'
        '<path d="M7.5 8a2.5 2.5 0 0 1 0-5C11 3 12 8 12 8s1-5 4.5-5a2.5 2.5 0 0 1 0 5"/></svg>'
    )
    global_config_schema: ClassVar[dict[str, Any]] = {}

    list_holidays = staticmethod(list_holidays)
    holiday_name = staticmethod(holiday_name)
    holiday_icons = staticmethod(holiday_icons)
    next_occurrence = staticmethod(next_occurrence)
    holiday_icon_img = staticmethod(holiday_icon_img)
