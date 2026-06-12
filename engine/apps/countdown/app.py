from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from PIL import Image

from canvas.base import Canvas
from app_base import DisplayApp
from grid import SizeConstraints
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import render_text, can_fit_text
from libraries.location.library import LocationLibrary
from libraries.timezones.library import resolve_zone
from libraries.holidays.library import (
    holiday_icon_img,
    holiday_icons,
    holiday_name,
    list_holidays,
    next_occurrence,
)

logger = logging.getLogger(__name__)

_HOLIDAY_OPTIONS: list[dict[str, Any]] = list_holidays()
_HOLIDAY_ENUM: list[str] = ["none"] + [h["id"] for h in _HOLIDAY_OPTIONS]
_HOLIDAY_LABELS: dict[str, str] = {"none": "None (custom event)"}
_HOLIDAY_LABELS.update({h["id"]: h["name"] for h in _HOLIDAY_OPTIONS})
_ICON_HOLIDAYS: list[dict[str, Any]] = [h for h in _HOLIDAY_OPTIONS if h.get("icons")]

_UNIT_ORDER: list[str] = ["years", "days", "hours", "minutes", "seconds"]
_UNIT_SECONDS: dict[str, int] = {"days": 86400, "hours": 3600, "minutes": 60, "seconds": 1}
_UNIT_SUFFIX: dict[str, str] = {"years": "y", "days": "d", "hours": "h", "minutes": "m", "seconds": "s"}


def _icon_field_properties() -> dict[str, Any]:
    """One `<holiday_id>_icon` enum field per holiday that has selectable graphics.

    Each is shown only when that holiday is selected (`x-show-if`) — sidesteps
    the lack of cascading/dependent enums in AppForm with one small field per
    holiday, generated straight from the curated dataset.
    """
    fields: dict[str, Any] = {}
    for entry in _ICON_HOLIDAYS:
        icons = entry["icons"]
        fields[f"{entry['id']}_icon"] = {
            "type": "string",
            "title": f"{entry['name']} graphic",
            "enum": [ic["id"] for ic in icons],
            "x-enum-labels": {ic["id"]: ic["label"] for ic in icons},
            "x-show-if": {"field": "holiday", "equals": entry["id"]},
            "default": icons[0]["id"],
        }
    return fields


def _clip_text(text: str, size: int, max_w: int) -> str:
    while text:
        if render_text(text, (255, 255, 255), size).width <= max_w:
            return text
        text = text[:-1]
    return ""


def _fit_size(sample: str, max_size: int, max_width: int, min_size: int = 6) -> int:
    """Largest font size <= max_size at which `sample` fits within max_width."""
    size = max(min_size, max_size)
    while size > min_size and not can_fit_text(max_width, size, sample):
        size -= 1
    return size


def _dim(color: tuple[int, int, int], factor: float = 0.6) -> tuple[int, int, int]:
    return tuple(max(0, int(c * factor)) for c in color)  # type: ignore[return-value]


def _decompose(now: datetime, target: datetime, units: list[str]) -> list[tuple[str, int]]:
    """Break `target - now` into the selected units, coarsest first.

    The largest selected unit absorbs every coarser unit that *isn't*
    selected — e.g. `units=["hours","minutes"]` on a 3-day delta yields
    `[("hours", 74), ("minutes", 12)]`, not days+hours+minutes. "years" is
    handled calendar-aware (via repeated `replace(year=...)`, with a Feb-29
    fallback to Feb 28) so a delta of "exactly one year" reads as `1y 0d`
    rather than an off-by-one approximation from fixed-length arithmetic.
    """
    selected = [u for u in _UNIT_ORDER if u in units] or ["days"]

    parts: list[tuple[str, int]] = []
    cursor = now
    if "years" in selected:
        years = 0
        while True:
            try:
                candidate = cursor.replace(year=cursor.year + 1)
            except ValueError:
                candidate = cursor.replace(month=2, day=28, year=cursor.year + 1)
            if candidate > target:
                break
            cursor = candidate
            years += 1
        parts.append(("years", years))

    sub_units = [u for u in selected if u != "years"]
    remaining = max(0, int((target - cursor).total_seconds()))

    if sub_units:
        for unit in sub_units:
            unit_seconds = _UNIT_SECONDS[unit]
            value, remaining = divmod(remaining, unit_seconds) if unit != sub_units[-1] else (remaining // unit_seconds, 0)
            parts.append((unit, value))
    elif not parts:
        parts.append(("seconds", remaining))

    return parts


def _format_countdown(parts: list[tuple[str, int]]) -> str:
    """Render decomposed parts compactly, e.g. "1y 32d 04h 12m".

    Sub-day units are zero-padded; leading zero-valued units are dropped
    (but at least one — the smallest selected — is always kept).
    """
    trimmed = list(parts)
    while len(trimmed) > 1 and trimmed[0][1] == 0:
        trimmed = trimmed[1:]

    chunks = []
    for unit, value in trimmed:
        suffix = _UNIT_SUFFIX[unit]
        if unit in ("years", "days"):
            chunks.append(f"{value}{suffix}")
        else:
            chunks.append(f"{value:02d}{suffix}")
    return " ".join(chunks)


class CountdownApp(DisplayApp):
    id: ClassVar[str] = "countdown"
    name: ClassVar[str] = "Countdown"
    description: ClassVar[str] = (
        "A live countdown to a holiday or a custom event — pick from a curated "
        "world-holiday catalog (with selectable graphics for popular ones) or "
        "set your own name, date, and colors"
    )
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 2h12M6 22h12"/>'
        '<path d="M7 2c0 4 4 6 5 8 1-2 5-4 5-8M7 22c0-4 4-6 5-8 1 2 5 4 5 8"/></svg>'
    )
    libraries: ClassVar[list[str]] = ["holidays", "location"]
    size_constraints: ClassVar[SizeConstraints] = SizeConstraints(min_width=64, min_height=32)
    global_config_schema: ClassVar[dict[str, Any]] = {}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Countdown",
        "properties": {
            "holiday": {
                "type": "string",
                "title": "Holiday",
                "description": "Pick a curated holiday, or choose None to set up a custom event below",
                "enum": _HOLIDAY_ENUM,
                "x-enum-labels": _HOLIDAY_LABELS,
                "default": "none",
            },
            "event_name": {
                "type": "string",
                "title": "Event name",
                "default": "",
                "x-show-if": {"field": "holiday", "equals": "none"},
            },
            "target_datetime": {
                "type": "string",
                "title": "Event date & time",
                "x-input-type": "datetime",
                "default": "",
                "x-show-if": {"field": "holiday", "equals": "none"},
            },
            **_icon_field_properties(),
            "units": {
                "type": "array",
                "title": "Granularity",
                "description": "Which time units appear in the countdown breakdown",
                "items": {"type": "string", "enum": _UNIT_ORDER},
                "x-input-type": "multi-select",
                "x-enum-labels": {
                    "years": "Years", "days": "Days", "hours": "Hours",
                    "minutes": "Minutes", "seconds": "Seconds",
                },
                "default": ["days", "hours", "minutes"],
            },
            "text_color": {
                "type": "string",
                "title": "Text color",
                "x-input-type": "color",
                "default": "#C8C8C8",
            },
            "countdown_color": {
                "type": "string",
                "title": "Countdown color",
                "x-input-type": "color",
                "default": "#FF6B6B",
            },
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 3600,
                "minimum": 60,
            },
            "debug": {
                "type": "boolean",
                "title": "Debug mode (sample event)",
                "default": False,
            },
        },
    }

    def __init__(
        self,
        config: dict[str, Any],
        canvas: Canvas,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(config, canvas, global_config, library_configs)
        self._event_name: str = ""
        self._target_dt: datetime | None = None
        self._icon_id: str | None = None
        self._resolved: bool = False
        self._fetched_once: bool = False
        self._tz_key: tuple[float, float, str] | None = None
        self._tz: ZoneInfo | None = None

    # ── Timezone resolution ─────────────────────────────────────────────────────

    def _get_user_tz(self) -> ZoneInfo | None:
        """Return the user's timezone, re-resolving only when location changes.

        Mirrors `_get_user_tz` in `apps/sports/app.py` — needed so a custom
        event's naive "local wall-clock" datetime, and a holiday's "midnight
        on date X", are both interpreted in the *user's* zone rather than the
        server's or UTC.
        """
        loc_cfg = self.library_configs.get("location", {}).get("location", {})
        lat = float(loc_cfg.get("latitude", 0.0)) if isinstance(loc_cfg, dict) else 0.0
        lon = float(loc_cfg.get("longitude", 0.0)) if isinstance(loc_cfg, dict) else 0.0
        stored_tz = str(loc_cfg.get("timezone") or "") if isinstance(loc_cfg, dict) else ""

        # The stored timezone is part of the key so a config update that only
        # adds/changes the timezone (same pin) invalidates the cache too.
        key = (lat, lon, stored_tz)
        if key == self._tz_key:
            return self._tz

        self._tz_key = key
        if lat == 0.0 and lon == 0.0:
            self._tz = None
            return None

        location_lib = LocationLibrary(self.library_configs.get("location", {}))
        tz_name = location_lib.get_timezone()
        tz = resolve_zone(tz_name) if tz_name else None
        if tz is None:
            logger.warning(
                "No IANA timezone resolved for location (%.4f, %.4f) (got %r); "
                "falling back to UTC",
                lat, lon, tz_name,
            )
        self._tz = tz
        return self._tz

    # ── Data fetching ────────────────────────────────────────────────────────────

    async def fetch_data(self) -> None:
        """Resolve the (effectively static) event name/target/icon.

        Does *not* compute "now" for the live countdown — `render_frame`
        snapshots a fresh `datetime.now()` every frame for that, exactly like
        `world_clock` resolves its city list here while ticking the clock there.
        """
        self._fetched_once = True

        if self.config.get("debug", False):
            self._event_name = "Sample Event"
            self._target_dt = datetime.now(timezone.utc) + timedelta(days=3, hours=7, minutes=15)
            self._icon_id = None
            self._resolved = True
            return

        tz = self._get_user_tz() or timezone.utc
        holiday_id = str(self.config.get("holiday") or "none")

        if holiday_id != "none":
            self._event_name = holiday_name(holiday_id)
            self._target_dt = next_occurrence(holiday_id, datetime.now(tz))
            self._resolved = self._target_dt is not None

            icons = holiday_icons(holiday_id)
            if icons:
                valid_ids = [ic["id"] for ic in icons]
                chosen = str(self.config.get(f"{holiday_id}_icon") or "")
                self._icon_id = chosen if chosen in valid_ids else valid_ids[0]
            else:
                self._icon_id = None
            return

        self._event_name = str(self.config.get("event_name") or "").strip() or "Countdown"
        self._icon_id = None

        raw = str(self.config.get("target_datetime") or "").strip()
        try:
            self._target_dt = datetime.fromisoformat(raw).replace(tzinfo=tz)
            self._resolved = True
        except ValueError:
            self._target_dt = None
            self._resolved = False

    # ── Rendering ────────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        if not self._fetched_once:
            self._draw_message("Loading...")
            return
        if not self._resolved or self._target_dt is None:
            self._draw_message("Set event in Settings")
            return

        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))
        countdown_color = parse_color(str(self.config.get("countdown_color", "#FF6B6B")))

        tz = self._target_dt.tzinfo or timezone.utc
        now = datetime.now(tz)
        delta = self._target_dt - now

        if delta.total_seconds() <= 0:
            self._draw_arrived(text_color)
            return

        raw_units = self.config.get("units", ["days", "hours", "minutes"])
        units = [str(u) for u in raw_units] if isinstance(raw_units, list) and raw_units else ["days", "hours", "minutes"]
        parts = _decompose(now, self._target_dt, units)
        # Fallback ladder: full breakdown first, then progressively drop the
        # finest units ("3d 07h 15m" -> "3d 07h" -> "3d") for narrow panels.
        candidates = [_format_countdown(parts[:k]) for k in range(len(parts), 0, -1)]
        self._draw_countdown(text_color, countdown_color, candidates)

    def _draw_countdown(
        self,
        text_color: tuple[int, int, int],
        countdown_color: tuple[int, int, int],
        countdown_strs: list[str],
    ) -> None:
        w, h = self.canvas.width, self.canvas.height
        pad = 2
        img = Image.new("RGB", (w, h))

        icon_img: Image.Image | None = None
        icon_size = 0
        if self._icon_id:
            icon_size = max(14, min(h - 2 * pad, w // 3))
            icon_img = holiday_icon_img(self._icon_id, icon_size, countdown_color)

        text_x = pad + (icon_size + 4 if icon_img is not None else 0)
        avail_w = max(8, w - text_x - pad)

        name_size = _fit_size(self._event_name, max(8, min(h // 4, 14)), avail_w)
        name_img = render_text(_clip_text(self._event_name, name_size, avail_w), text_color, name_size)

        # First (most detailed) breakdown that actually fits; the coarsest one
        # may still need clipping on truly tiny panels.
        countdown_str = countdown_strs[-1]
        countdown_size = _fit_size(countdown_str, max(10, min(h // 2, 26)), avail_w)
        for cand in countdown_strs:
            size = _fit_size(cand, max(10, min(h // 2, 26)), avail_w)
            if can_fit_text(avail_w, size, cand):
                countdown_str, countdown_size = cand, size
                break
        countdown_img = render_text(_clip_text(countdown_str, countdown_size, avail_w), countdown_color, countdown_size)

        lines = [name_img, countdown_img]

        assert self._target_dt is not None
        target_str = f"{self._target_dt.strftime('%a %b')} {self._target_dt.day}"
        sub_size = max(6, name_size - 2)
        sub_img = render_text(_clip_text(target_str, sub_size, avail_w), _dim(text_color), sub_size)
        used_h = sum(li.height for li in lines) + 2 * len(lines)
        if used_h + sub_img.height <= h:
            lines.append(sub_img)

        total_h = sum(li.height for li in lines) + (len(lines) - 1) * 2
        y = max(0, (h - total_h) // 2)
        for li in lines:
            img.paste(li, (text_x + (avail_w - li.width) // 2, y))
            y += li.height + 2

        if icon_img is not None:
            img.paste(icon_img, (pad, (h - icon_size) // 2))

        blit(self.canvas, img)

    def _draw_arrived(self, text_color: tuple[int, int, int]) -> None:
        w, h = self.canvas.width, self.canvas.height
        max_w = max(6, w - 4)
        min_size = 8

        msg = f"{self._event_name} is here!"
        if not can_fit_text(max_w, min_size, msg):
            msg = "Today!"

        size = _fit_size(msg, min(16, h // 2), max_w, min_size=min_size)
        msg_img = render_text(_clip_text(msg, size, max_w), text_color, size)
        img = Image.new("RGB", (w, h))
        x = (w - msg_img.width) // 2
        y = (h - msg_img.height) // 2
        img.paste(msg_img, (max(0, x), max(0, y)))
        blit(self.canvas, img)

    def _draw_message(self, msg: str) -> None:
        w, h = self.canvas.width, self.canvas.height
        max_w = max(6, w - 4)
        size = _fit_size(msg, min(14, h), max_w)
        msg_img = render_text(_clip_text(msg, size, max_w), (80, 80, 80), size)
        img = Image.new("RGB", (w, h))
        x = (w - msg_img.width) // 2
        y = (h - msg_img.height) // 2
        img.paste(msg_img, (max(0, x), max(0, y)))
        blit(self.canvas, img)
