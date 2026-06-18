from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from PIL import Image

logger = logging.getLogger(__name__)

from canvas.base import Canvas
from app_base import DisplayApp
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import render_text, draw_status_message
from libraries.opensky.library import OpenSkyLibrary
from libraries.flightaware.library import FlightAwareLibrary
from libraries.location.library import LocationLibrary

_UNIT_CYCLE_S: float = 4.0
_GATED_PHASES = ("unknown", "not_found", "approaching", "active", "recently_landed")


def _clip_text(text: str, size: int, max_w: int) -> str:
    while text:
        if render_text(text, (255, 255, 255), size).width <= max_w:
            return text
        text = text[:-1]
    return ""


def _normalize_ident(value: str) -> str:
    """Normalize a flight number into an AeroAPI-friendly ident.

    Strips *all* whitespace (so "DL 1070" and "DL1070" are equivalent) and
    uppercases. Both IATA ("DL1070") and ICAO ("DAL1070") airline prefixes are
    accepted by AeroAPI's /flights/{ident} endpoint, so removing the spaces is
    the actual fix — no airline-code mapping is required.
    """
    return re.sub(r"\s+", "", value or "").upper()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_time(value: str | None) -> str:
    if not value or "T" not in value:
        return "--:--"
    return value.split("T")[1][:5]


def _fmt_delay(seconds: int | None) -> str:
    if seconds is None:
        return ""
    minutes = round(seconds / 60)
    if minutes <= 0:
        return ""
    return f"Delayed +{minutes}m"


def _phase(tracked: dict[str, Any] | None) -> str:
    """Classify a tracked flight's lifecycle phase for AeroAPI polling gates.

    Only "unknown" (never checked), "approaching" (<=1h to departure),
    "active" (airborne), and "recently_landed" (<=1h since landing) are
    worth polling — everything else means waiting quietly on cached data.
    """
    if tracked is None:
        return "unknown"
    if not tracked.get("found"):
        return "not_found"

    now = datetime.now(timezone.utc)
    actual_on = _parse_dt(tracked.get("actual_on"))
    estimated_on = _parse_dt(tracked.get("estimated_on"))
    landed_at = actual_on or estimated_on
    if landed_at is not None:
        if now - landed_at <= timedelta(hours=1):
            return "recently_landed"
        return "far_past"

    actual_off = _parse_dt(tracked.get("actual_off"))
    if actual_off is not None:
        return "active"

    scheduled_off = _parse_dt(tracked.get("scheduled_off"))
    if scheduled_off is None:
        return "unknown"
    if scheduled_off - now <= timedelta(hours=1):
        return "approaching"
    return "far_future"


def _poll_interval_seconds(phase: str, tracked: dict[str, Any], tier: str) -> float:
    if phase == "approaching":
        scheduled_off = _parse_dt(tracked.get("scheduled_off"))
        near = (
            scheduled_off is not None
            and scheduled_off - datetime.now(timezone.utc) <= timedelta(minutes=15)
        )
        base = 150.0 if near else 600.0
    elif phase == "active":
        base = 150.0
    elif phase == "recently_landed":
        base = 300.0
    else:
        base = 600.0
    if tier in ("conservative", "minimal"):
        base *= 2
    return base


def _card_kind(tracked: dict[str, Any] | None) -> str:
    if tracked is None or not tracked.get("found"):
        return "not_found"
    if tracked.get("actual_on"):
        return "landed"
    if tracked.get("actual_off"):
        return "airborne"
    return "scheduled"


def _build_stat_lines_opensky(d: dict[str, Any], imperial: bool) -> list[str]:
    track = d.get("track")
    trk_str = f"Trk: {track} deg" if track is not None else "Trk: ---"
    if imperial:
        alt, spd = d.get("alt_ft"), d.get("spd_mph")
        alt_str = f"Alt: {alt} ft" if alt is not None else "Alt: ---"
        spd_str = f"Spd: {spd} mph" if spd is not None else "Spd: ---"
    else:
        alt, spd = d.get("alt_m"), d.get("spd_kph")
        alt_str = f"Alt: {alt} m" if alt is not None else "Alt: ---"
        spd_str = f"Spd: {spd} kph" if spd is not None else "Spd: ---"
    return [alt_str, spd_str, trk_str]


def _build_stat_lines_aero(live: dict[str, Any], imperial: bool) -> list[str]:
    alt_ft = live.get("alt_ft")
    gs_kt = live.get("gs_kt")
    heading = live.get("heading")
    trk_str = f"Trk: {heading} deg" if heading is not None else "Trk: ---"
    if imperial:
        alt_str = f"Alt: {alt_ft} ft" if alt_ft is not None else "Alt: ---"
        spd_mph = round(gs_kt * 1.151) if gs_kt is not None else None
        spd_str = f"Spd: {spd_mph} mph" if spd_mph is not None else "Spd: ---"
    else:
        alt_m = round(alt_ft * 0.3048) if alt_ft is not None else None
        alt_str = f"Alt: {alt_m} m" if alt_m is not None else "Alt: ---"
        spd_kph = round(gs_kt * 1.852) if gs_kt is not None else None
        spd_str = f"Spd: {spd_kph} kph" if spd_kph is not None else "Spd: ---"
    return [alt_str, spd_str, trk_str]


_DEBUG_TRACKED_FOUND: dict[str, Any] = {
    "found": True,
    "ident": "DL699",
    "origin": "JFK", "dest": "SEA",
    "origin_name": "JFK Intl", "dest_name": "Seattle-Tacoma Intl",
    "airline": "Delta Air Lines", "operator_iata": "DL", "aircraft_type": "Boeing 737-700",
    "status": "En Route",
    "scheduled_off": "2026-06-18T14:00:00Z", "estimated_off": "2026-06-18T14:05:00Z",
    "actual_off": "2026-06-18T14:07:00Z",
    "scheduled_on": "2026-06-18T22:30:00Z", "estimated_on": "2026-06-18T22:42:00Z",
    "actual_on": None,
    "departure_delay": 420, "arrival_delay": 720, "progress_percent": 45,
    "live": {
        "lat": 40.0, "lon": -100.0, "alt_ft": 35000, "gs_kt": 480,
        "heading": 270, "updated_at": "2026-06-18T18:00:00Z",
    },
    "icao24": "a1b2c3",
}

_DEBUG_TRACKED_NOT_FOUND: dict[str, Any] = {"found": False, "ident": "ZZ000"}


class FlightTrackerApp(DisplayApp):
    id: ClassVar[str] = "flight_tracker"
    name: ClassVar[str] = "Flight Tracker"
    description: ClassVar[str] = (
        "Track specific flight(s) by number and date — schedule, on-time/delay "
        "status, and live position via FlightAware AeroAPI + OpenSky Network"
    )
    icon: ClassVar[str] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M2 16l20-8-7 7 2 7-4-3-4 3 1-7-8-2z"/></svg>'
    )
    libraries: ClassVar[list[str]] = ["flightaware", "opensky", "location"]
    global_config_schema: ClassVar[dict[str, Any]] = {}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Flight Tracker",
        "properties": {
            "flights": {
                "type": "array",
                "title": "Flights",
                "x-input-type": "flight-list",
                "items": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "string", "default": ""},
                        "label": {"type": "string", "default": ""},
                        "date": {"type": "string", "default": "", "x-input-type": "date"},
                    },
                },
                "maxItems": 5,
                "default": [{"number": "", "label": "", "date": ""}],
            },
            "display_mode": {
                "type": "string",
                "title": "Display mode",
                "enum": ["cards", "table"],
                "default": "cards",
            },
            "min_card_seconds": {
                "type": "number",
                "title": "Minimum seconds per card",
                "default": 5.0,
                "minimum": 1.0,
            },
            "max_card_seconds": {
                "type": "number",
                "title": "Maximum seconds per card",
                "default": 15.0,
                "minimum": 1.0,
            },
            "text_color": {
                "type": "string",
                "title": "Text color",
                "x-input-type": "color",
                "default": "#C8C8C8",
            },
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 60,
                "minimum": 30,
            },
            "units": {
                "type": "string",
                "title": "Units",
                "enum": ["metric", "imperial", "metric+imperial"],
                "default": "metric+imperial",
            },
            "debug": {
                "type": "boolean",
                "title": "Debug mode (static data)",
                "default": False,
            },
        },
        "required": ["flights"],
    }

    def __init__(
        self,
        config: dict[str, Any],
        canvas: Canvas,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(config, canvas, global_config, library_configs)
        self._flightaware = FlightAwareLibrary(self.library_configs.get("flightaware", {}))
        self._opensky = OpenSkyLibrary(self.library_configs.get("opensky", {}))
        self._location = LocationLibrary(self.library_configs.get("location", {}))
        self._tracked: dict[str, dict[str, Any]] = {}
        self._live_overrides: dict[str, dict[str, Any]] = {}
        self._next_poll_due: dict[str, float] = {}
        self._last_flight_dates: dict[str, str | None] = {}
        self._fetched_once: bool = False
        self._card_idx: int = 0
        self._card_last_ts: float = 0.0
        self._show_imperial: bool = False
        self._unit_ts: float = time.monotonic()
        self._is_active: bool = False

    async def on_activate(self) -> None:
        self._is_active = True

    async def on_deactivate(self) -> None:
        self._is_active = False

    # ── Config helpers ─────────────────────────────────────────────────────────

    def _flights(self) -> list[dict[str, str]]:
        """Ordered, normalized list of {number, label, date} for each configured flight.

        Reads the current ``flights`` array-of-objects, falling back to the
        legacy ``flight_numbers`` (list[str]) + ``label`` (str) config so module
        instances saved before per-flight labels keep working. Flight numbers
        are normalized (whitespace-stripped, uppercased); blanks are dropped and
        the list is capped at 5. Migrates the legacy global ``date`` field as a
        fallback for per-flight dates not yet set.
        """
        raw = self.config.get("flights")
        if not isinstance(raw, list) or not raw:
            # Legacy fallback: flight_numbers[] + single shared label.
            numbers = self.config.get("flight_numbers") or []
            legacy_label = str(self.config.get("label", "") or "")
            raw = [
                {"number": n, "label": legacy_label if i == 0 else "", "date": ""}
                for i, n in enumerate(numbers)
            ]

        # Migrate old global date as fallback for flights without a per-flight date.
        global_date = str(self.config.get("date", "") or "").strip()
        if global_date and "T" in global_date:
            global_date = global_date.split("T")[0]

        flights: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            number = _normalize_ident(str(item.get("number", "") or ""))
            if not number:
                continue
            date = str(item.get("date", "") or "").strip()
            if not date and global_date:
                date = global_date
            if date and "T" in date:
                date = date.split("T")[0]
            flights.append({
                "number": number,
                "label": str(item.get("label", "") or ""),
                "date": date,
            })
        return flights[:5]

    def _flight_numbers(self) -> list[str]:
        return [f["number"] for f in self._flights()]

    def _labels(self) -> dict[str, str]:
        """Map of flight number → its label (last one wins on duplicates)."""
        return {f["number"]: f["label"] for f in self._flights()}

    # ── Data fetching ──────────────────────────────────────────────────────────

    async def fetch_data(self) -> None:
        if self.config.get("debug", False):
            self._seed_debug()
            return

        if not self._is_active:
            return

        if not self._flightaware.has_api_key:
            self._fetched_once = True
            return

        flights = self._flights()
        flight_numbers = [f["number"] for f in flights]
        flight_date_map = {f["number"]: f["date"] or None for f in flights}

        # Clear stale tracked state when a flight's date config changes so the
        # old phase (e.g. "far_past" from a previous day's instance) doesn't
        # block re-polling for the new date.
        for fn, new_date in flight_date_map.items():
            if fn in self._last_flight_dates and self._last_flight_dates[fn] != new_date:
                self._tracked.pop(fn, None)
                self._next_poll_due.pop(fn, None)
        self._last_flight_dates = dict(flight_date_map)

        tz = self._location.get_timezone()
        tier = self._flightaware.budget_tier
        now_mono = time.monotonic()

        to_poll = [
            fn for fn in flight_numbers
            if tier != "disabled"
            and _phase(self._tracked.get(fn)) in _GATED_PHASES
            and now_mono >= self._next_poll_due.get(fn, 0.0)
        ]

        if to_poll:
            results = await asyncio.gather(
                *[self._flightaware.track_flight(fn, flight_date_map.get(fn), tz) for fn in to_poll],
                return_exceptions=True,
            )
            for fn, result in zip(to_poll, results):
                if isinstance(result, dict):
                    self._tracked[fn] = result
                new_phase = _phase(self._tracked.get(fn))
                interval = _poll_interval_seconds(new_phase, self._tracked.get(fn) or {}, tier)
                self._next_poll_due[fn] = now_mono + interval

        self._fetched_once = True

        icao24s = [
            t["icao24"]
            for fn in flight_numbers
            if (t := self._tracked.get(fn))
            and t.get("found")
            and _phase(t) == "active"
            and t.get("icao24")
        ]
        if icao24s:
            live = await self._opensky.fetch_by_icao24(icao24s)
            if live is not None:
                self._live_overrides.update(live)

        min_card_s = float(self.config.get("min_card_seconds", 5.0))
        elapsed = now_mono - self._card_last_ts
        if elapsed >= min_card_s or not flight_numbers:
            self._card_idx = 0
            self._card_last_ts = now_mono
        else:
            self._card_idx = min(self._card_idx, max(0, len(flight_numbers) - 1))

    def _seed_debug(self) -> None:
        flight_numbers = self._flight_numbers() or ["DL699"]
        self._tracked = {
            fn: dict(_DEBUG_TRACKED_FOUND if i == 0 else _DEBUG_TRACKED_NOT_FOUND)
            for i, fn in enumerate(flight_numbers)
        }
        if flight_numbers:
            self._tracked[flight_numbers[0]] = dict(_DEBUG_TRACKED_FOUND)
            self._tracked[flight_numbers[0]]["ident"] = flight_numbers[0]
        self._fetched_once = True
        self._card_idx = 0
        self._card_last_ts = time.monotonic()
        self._unit_ts = time.monotonic()

    def _stat_lines(self, tracked: dict[str, Any], imperial: bool) -> list[str]:
        icao24 = tracked.get("icao24") or ""
        osky = self._live_overrides.get(icao24) if icao24 else None
        if osky:
            return _build_stat_lines_opensky(osky, imperial)
        aero_live = tracked.get("live")
        if aero_live:
            return _build_stat_lines_aero(aero_live, imperial)
        return ["Alt: ---", "Spd: ---", "Trk: ---"]

    # ── Rendering ──────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        flight_numbers = self._flight_numbers()
        if not flight_numbers:
            msg = "Loading..." if not self._fetched_once else "No flights configured"
            draw_status_message(self.canvas, msg)
            return
        if self.config.get("display_mode", "cards") == "table":
            self._draw_table(flight_numbers)
        else:
            self._draw_card(flight_numbers)

    def _draw_card(self, flight_numbers: list[str]) -> None:
        now = time.monotonic()
        max_card_s = float(self.config.get("max_card_seconds", 15.0))
        if now - self._card_last_ts >= max_card_s and len(flight_numbers) > 1:
            self._card_idx = (self._card_idx + 1) % len(flight_numbers)
            self._card_last_ts = now
        self._card_idx = min(self._card_idx, len(flight_numbers) - 1)

        units = self.config.get("units", "metric+imperial")
        if units == "metric+imperial":
            if now - self._unit_ts >= _UNIT_CYCLE_S:
                self._show_imperial = not self._show_imperial
                self._unit_ts = now
        else:
            self._show_imperial = units == "imperial"

        fn = flight_numbers[self._card_idx]
        tracked = self._tracked.get(fn)
        kind = _card_kind(tracked)
        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))
        label = self._labels().get(fn, "")

        if kind == "not_found":
            if tracked is None and not self._flightaware.has_api_key:
                draw_status_message(self.canvas, "Add FlightAware API key in settings")
            else:
                draw_status_message(self.canvas, f"{fn}: not available")
            return

        assert tracked is not None
        lines: list[str] = [label] if label else []
        lines.append(fn)
        if tracked.get("origin") and tracked.get("dest"):
            lines.append(f"{tracked['origin']}->{tracked['dest']}")

        if kind == "scheduled":
            lines.append(f"Dep: {_fmt_time(tracked.get('scheduled_off'))}")
            delay = _fmt_delay(tracked.get("departure_delay"))
            lines.append(delay or "On time")
        elif kind == "airborne":
            pct = tracked.get("progress_percent")
            if pct is not None:
                lines.append(f"En route {pct}%")
            lines.extend(self._stat_lines(tracked, self._show_imperial))
        elif kind == "landed":
            lines.append(f"Landed {_fmt_time(tracked.get('actual_on'))}")
            delay = _fmt_delay(tracked.get("arrival_delay"))
            lines.append(delay or "On time")

        w, h = self.canvas.width, self.canvas.height
        img = Image.new("RGB", (w, h))

        n_rows = max(1, len(lines))
        size_cap = max(7, (h - 4) // n_rows - 2)
        font_size = 7
        for size in (15, 12, 9, 8, 7):
            if size > size_cap:
                continue
            if n_rows * (render_text("Ag", text_color, size).height + 1) - 1 <= h - 4:
                font_size = size
                break

        y = 2
        for line in lines:
            if not line:
                continue
            line_img = render_text(_clip_text(line, font_size, w - 4), text_color, font_size)
            if y + line_img.height <= h:
                img.paste(line_img, (2, y))
            y += line_img.height + 1

        blit(self.canvas, img)

    def _draw_table(self, flight_numbers: list[str]) -> None:
        text_color = parse_color(str(self.config.get("text_color", "#C8C8C8")))
        max_w = self.canvas.width - 4

        labels = self._labels()

        def _rows() -> list[str]:
            rows = []
            for fn in flight_numbers:
                tracked = self._tracked.get(fn)
                kind = _card_kind(tracked)
                if kind == "not_found":
                    status, delay = "not avail", ""
                elif kind == "scheduled":
                    status = "Scheduled"
                    delay = _fmt_delay(tracked.get("departure_delay")) or "On time"
                elif kind == "airborne":
                    status = "En route"
                    delay = _fmt_delay(tracked.get("departure_delay")) or "On time"
                else:
                    status = "Landed"
                    delay = _fmt_delay(tracked.get("arrival_delay")) or "On time"
                # Lead each row with the user's label when set, else the number.
                ident = labels.get(fn) or fn
                rows.append(f"{ident:<8}{status:<10}{delay}")
            return rows

        rows = _rows()
        font_size = None
        for size in (12, 9, 8, 7):
            widest = max((render_text(r, text_color, size).width for r in rows), default=0)
            if widest <= max_w:
                font_size = size
                break
        if font_size is None:
            font_size = 7

        glyph_h = render_text("A", text_color, font_size).height
        row_h = glyph_h + 2

        img = Image.new("RGB", (self.canvas.width, self.canvas.height))
        for i, row in enumerate(rows):
            row_img = render_text(row, text_color, font_size)
            y = i * row_h + 1
            if y + row_img.height <= img.height:
                img.paste(row_img, (2, y))

        blit(self.canvas, img)
