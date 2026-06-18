from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image

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


# ── Icon loading ────────────────────────────────────────────────────────────
#
# Full-color holiday icons from the Twemoji set, pre-rasterized to PNG by
# `tools/bake_icons.py` and bundled under `icons/`. Resized lazily and cached
# per (icon, size) so the render loop just reuses the composited image.

_ICONS_DIR = Path(__file__).parent / "icons"
_icon_cache: dict[tuple[str, int], Image.Image] = {}


def holiday_icon_img(icon_id: str, size: int, color: tuple[int, int, int] | None = None) -> Image.Image:
    """The holiday icon composited onto black, scaled to a size x size square.

    `color` is accepted for call-site compatibility but ignored — the artwork
    is full-color. Unknown icon ids yield a blank tile.
    """
    size = max(8, int(size))
    cached = _icon_cache.get((icon_id, size))
    if cached is not None:
        return cached

    img = Image.new("RGB", (size, size), (0, 0, 0))
    path = _ICONS_DIR / f"{icon_id}.png"
    if path.is_file():
        icon = Image.open(path).convert("RGBA")
        if icon.width != size:
            icon = icon.resize((size, size), Image.LANCZOS)
        img.paste(icon, (0, 0), icon)
    else:
        logger.warning("No icon asset for holiday icon id %r", icon_id)
    _icon_cache[(icon_id, size)] = img
    return img


# ── Library class ───────────────────────────────────────────────────────────


class HolidaysLibrary(Library):
    id: ClassVar[str] = "holidays"
    name: ClassVar[str] = "Holidays"
    description: ClassVar[str] = (
        "A curated catalog of common world holidays — closed-form date rules "
        "for fixed and floating observances, a precomputed table for "
        "lunar/lunisolar ones, and colorful Twemoji icons for popular days"
    )
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    global_config_schema: ClassVar[dict[str, Any]] = {}

    list_holidays = staticmethod(list_holidays)
    holiday_name = staticmethod(holiday_name)
    holiday_icons = staticmethod(holiday_icons)
    next_occurrence = staticmethod(next_occurrence)
    holiday_icon_img = staticmethod(holiday_icon_img)
