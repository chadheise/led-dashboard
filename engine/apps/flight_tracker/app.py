from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image

logger = logging.getLogger(__name__)

from canvas.base import Canvas
from app_base import DisplayApp
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import render_text, draw_status_message
from libraries.opensky.library import OpenSkyLibrary
from libraries.flightaware.library import FlightAwareLibrary, iata_from_callsign
from libraries.location.library import LocationLibrary
from libraries.timezones.library import resolve_zone
from apps.flights_overhead.icons import render_category_icon

_UNIT_CYCLE_S: float = 4.0
_GATED_PHASES = ("unknown", "not_found", "approaching", "active", "recently_landed")

# How far ahead a configured flight date can be before FlightAware has schedule
# data for it. Flights dated beyond this are neither polled nor displayed (they
# would otherwise sit on a "not available" card), until they enter the window.
_LOOKUP_WINDOW_DAYS: int = 2

# Status-indicator colors: on time / ahead of schedule, delayed, cancelled.
_STATUS_GREEN: tuple[int, int, int] = (72, 200, 76)
_STATUS_YELLOW: tuple[int, int, int] = (230, 196, 0)
_STATUS_RED: tuple[int, int, int] = (224, 52, 44)

# Status-indicator colors: on time / ahead of schedule, delayed, cancelled.
_STATUS_GREEN: tuple[int, int, int] = (72, 200, 76)
_STATUS_YELLOW: tuple[int, int, int] = (230, 196, 0)
_STATUS_RED: tuple[int, int, int] = (224, 52, 44)

# Auto-hide window: a flight counts as "active" from 2h before its (estimated)
# departure, while airborne, and until 2h after it lands.
_ACTIVE_WINDOW = timedelta(hours=2)


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


def _fmt_time(value: str | None, tz: tzinfo | None = None, time_format: str = "24h") -> str:
    """Format a UTC ISO timestamp as a local time-of-day string.

    Converts to ``tz`` (the user's configured timezone) when available, and
    honours the location/time ``time_format`` setting ("12h" -> "2:30 PM",
    "24h" -> "14:30"). Falls back to UTC when no timezone is configured.
    """
    dt = _parse_dt(value)
    if dt is None:
        return "--:--"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if tz is not None:
        dt = dt.astimezone(tz)
    if time_format == "12h":
        hour = dt.hour % 12 or 12
        suffix = "AM" if dt.hour < 12 else "PM"
        return f"{hour}:{dt.minute:02d} {suffix}"
    return f"{dt.hour:02d}:{dt.minute:02d}"


def _within_lookup_window(date_str: str | None, today: date) -> bool:
    """Whether a flight's configured date is near enough to track/display.

    FlightAware only has schedule data a couple of days out, so a flight dated
    further ahead can't be resolved and should stay hidden (rather than showing
    "not available") until it enters the window. Flights with no configured date
    are always in-window since their next instance can't be known in advance.
    """
    if not date_str:
        return True
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return True
    return d <= today + timedelta(days=_LOOKUP_WINDOW_DAYS)


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


def _poll_interval_seconds(
    phase: str,
    tracked: dict[str, Any],
    tier: str,
    interval_approaching_far: float = 600.0,
    interval_approaching_near: float = 150.0,
    interval_active: float = 150.0,
    interval_recently_landed: float = 300.0,
) -> float:
    if phase == "approaching":
        scheduled_off = _parse_dt(tracked.get("scheduled_off"))
        near = (
            scheduled_off is not None
            and scheduled_off - datetime.now(timezone.utc) <= timedelta(minutes=15)
        )
        base = interval_approaching_near if near else interval_approaching_far
    elif phase == "active":
        base = interval_active
    elif phase == "recently_landed":
        base = interval_recently_landed
    else:
        base = interval_approaching_far
    if tier in ("conservative", "minimal"):
        base *= 2
    return base


def _is_active_flight(tracked: dict[str, Any] | None, now: datetime) -> bool:
    """Whether a tracked flight is "active" for the auto-hide gate.

    Active means any of: departing within the next 2 hours, currently airborne,
    or landed within the last 2 hours. Operates purely on the cached schedule
    timestamps so the gate keeps working as the clock advances even when the
    module isn't being polled.
    """
    if not tracked or not tracked.get("found"):
        return False
    # Landed within the last 2 hours.
    actual_on = _parse_dt(tracked.get("actual_on"))
    if actual_on is not None:
        return timedelta(0) <= now - actual_on <= _ACTIVE_WINDOW
    # Airborne (departed, not yet landed) — relevant for the whole flight.
    if _parse_dt(tracked.get("actual_off")) is not None:
        return True
    # Departing within the next 2 hours (estimated, falling back to scheduled).
    departure = _parse_dt(tracked.get("estimated_off")) or _parse_dt(tracked.get("scheduled_off"))
    if departure is not None:
        return timedelta(0) <= departure - now <= _ACTIVE_WINDOW
    return False


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
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    libraries: ClassVar[list[str]] = ["flightaware", "opensky", "location"]
    global_config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Flight Tracker",
        "properties": {
            "refresh_interval": {
                "type": "number",
                "title": "Refresh interval (s)",
                "default": 60,
                "minimum": 30,
            },
            "poll_interval_approaching_far": {
                "type": "number",
                "title": "Poll interval — approaching >15 min (s)",
                "default": 600,
                "minimum": 60,
            },
            "poll_interval_approaching_near": {
                "type": "number",
                "title": "Poll interval — approaching ≤15 min (s)",
                "default": 150,
                "minimum": 30,
            },
            "poll_interval_active": {
                "type": "number",
                "title": "Poll interval — active/airborne (s)",
                "default": 150,
                "minimum": 30,
            },
            "poll_interval_recently_landed": {
                "type": "number",
                "title": "Poll interval — recently landed (s)",
                "default": 300,
                "minimum": 30,
            },
        },
    }
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
        self._logos: dict[str, Image.Image | None] = {}
        self._logos_fetched: set[str] = set()
        self._next_poll_due: dict[str, float] = {}
        self._last_flight_dates: dict[str, str | None] = {}
        self._fetched_once: bool = False
        self._card_idx: int = 0
        self._card_last_ts: float = 0.0
        self._show_imperial: bool = False
        self._unit_ts: float = time.monotonic()
        self._is_active: bool = False

    @property
    def refresh_interval(self) -> float:
        return float(self.global_config.get("refresh_interval", 60.0))

    def _flights_in_range(self) -> list[str]:
        """Flight numbers currently within FlightAware's schedule window.

        Single source of truth for "which flights can be shown right now",
        shared by ``render_frame`` (its "No flights in range" fallback) and
        ``should_display`` (the playlist auto-hide gate), so the two never
        disagree. Flights dated beyond the lookup window are excluded.
        """
        today = datetime.now(timezone.utc).date()
        return [
            f["number"] for f in self._flights()
            if _within_lookup_window(f["date"] or None, today)
        ]

    async def should_display(self) -> bool:
        """Auto-hide gate: skip the module when nothing is worth showing.

        Hidden unless at least one in-range flight (see ``_flights_in_range``)
        is also active -- departing within the next 2 hours, airborne, or landed
        within the last 2 hours. So a module whose only flights are out of range
        (the "No flights in range" state) is not displayed at all in a playlist
        that has the hide setting on. Stays hidden until the first (background)
        fetch resolves so a flight with no info never flashes before we know to
        skip it.
        """
        if not self._fetched_once:
            return False
        now = datetime.now(timezone.utc)
        return any(
            _is_active_flight(self._tracked.get(fn), now)
            for fn in self._flights_in_range()
        )

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
        the legacy global ``date`` field is migrated as a fallback for
        per-flight dates not yet set.
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
        return flights

    def _flight_numbers(self) -> list[str]:
        return [f["number"] for f in self._flights()]

    def _labels(self) -> dict[str, str]:
        """Map of flight number → its label (last one wins on duplicates)."""
        return {f["number"]: f["label"] for f in self._flights()}

    # ── Data fetching ──────────────────────────────────────────────────────────

    def _all_flights_resolved(self) -> bool:
        """Whether every configured flight has a resolved tracking result.

        A flight is "resolved" once a lookup has returned something (found or
        not-found) and stored it in ``_tracked``. Flights that never resolved
        (e.g. the budget was exhausted or the network was down when they were
        first polled) stay unresolved so the background fetch keeps retrying
        them instead of leaving newly added flights permanently blank. Flights
        dated beyond the lookup window count as resolved -- there is nothing to
        fetch for them yet -- so they don't hold background polling open.
        """
        today = datetime.now(timezone.utc).date()
        return all(
            self._tracked.get(f["number"]) is not None
            or not _within_lookup_window(f["date"] or None, today)
            for f in self._flights()
        )

    async def fetch_data(self) -> None:
        if self.config.get("debug", False):
            self._seed_debug()
            return

        flights = self._flights()
        flight_numbers = [f["number"] for f in flights]
        flight_date_map = {f["number"]: f["date"] or None for f in flights}

        # Drop tracked/scheduling state for flights that are no longer
        # configured so a removed flight number can't linger in _tracked (and
        # so should_display never keeps the module visible for a flight the user
        # deleted). Done before the polling gate below so it applies even when
        # the gate short-circuits.
        configured = set(flight_numbers)
        for fn in list(self._tracked):
            if fn not in configured:
                self._tracked.pop(fn, None)
                self._next_poll_due.pop(fn, None)

        # Poll in the background until every configured flight has resolved, so
        # the auto-hide gate (should_display) can evaluate real schedule data
        # before the module is ever shown -- and so a flight added or changed
        # later still loads even while the module is off-screen. Once all
        # flights are resolved, restrict polling to when the module is active to
        # conserve AeroAPI budget; the auto-hide gate then works off the cached
        # timestamps and reactivates the module (resuming live polling) when a
        # flight enters its active window.
        if not self._is_active and self._fetched_once and self._all_flights_resolved():
            return

        if not self._flightaware.has_api_key:
            self._fetched_once = True
            return

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
        today = datetime.now(timezone.utc).date()
        pi_far    = float(self.global_config.get("poll_interval_approaching_far", 600.0))
        pi_near   = float(self.global_config.get("poll_interval_approaching_near", 150.0))
        pi_active = float(self.global_config.get("poll_interval_active", 150.0))
        pi_landed = float(self.global_config.get("poll_interval_recently_landed", 300.0))

        # Don't spend budget on flights dated beyond FlightAware's schedule
        # horizon -- they'd only come back "not found" and get cached as such.
        to_poll = [
            fn for fn in flight_numbers
            if tier != "disabled"
            and _within_lookup_window(flight_date_map.get(fn), today)
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
                interval = _poll_interval_seconds(
                    new_phase, self._tracked.get(fn) or {}, tier,
                    pi_far, pi_near, pi_active, pi_landed,
                )
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

        await self._fetch_logos()

        min_card_s = float(self.config.get("min_card_seconds", 5.0))
        elapsed = now_mono - self._card_last_ts
        if elapsed >= min_card_s or not flight_numbers:
            self._card_idx = 0
            self._card_last_ts = now_mono
        else:
            self._card_idx = min(self._card_idx, max(0, len(flight_numbers) - 1))

    def _operator_iata(self, fn: str, tracked: dict[str, Any] | None) -> str:
        """Airline IATA code for a tracked flight, for logo lookup.

        Prefers the operator code from FlightAware, falling back to the airline
        prefix parsed from the flight number itself (e.g. ``DL699`` -> ``DL``).
        """
        if tracked and tracked.get("operator_iata"):
            return str(tracked["operator_iata"]).upper()
        return iata_from_callsign(fn) or ""

    async def _fetch_logos(self) -> None:
        needed = {
            iata
            for fn in self._flight_numbers()
            if (t := self._tracked.get(fn)) and t.get("found")
            and (iata := self._operator_iata(fn, t))
        } - self._logos_fetched
        if not needed:
            return
        results = await asyncio.gather(
            *[self._flightaware.fetch_logo(code) for code in needed],
            return_exceptions=True,
        )
        for iata, result in zip(needed, results):
            self._logos_fetched.add(iata)
            self._logos[iata] = result if isinstance(result, Image.Image) else None

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

    def _tz_and_time_format(self) -> tuple[tzinfo | None, str]:
        """Resolved user timezone + time-format ("12h"/"24h") from settings."""
        tz_str = self._location.get_timezone()
        tz = resolve_zone(tz_str) if tz_str else None
        return tz, self._location.get_time_format()

    async def render_frame(self) -> None:
        if not self._flight_numbers():
            msg = "Loading..." if not self._fetched_once else "No flights configured"
            draw_status_message(self.canvas, msg)
            return

        # Show only flights within FlightAware's schedule horizon. Flights dated
        # further out can't be resolved yet, so rather than parking them on a
        # "not available" card we drop them until they enter the lookup window.
        # This is the same set the auto-hide gate keys off (see should_display),
        # so a hidden module and this "No flights in range" state stay in sync.
        visible = self._flights_in_range()
        if not visible:
            msg = "Loading..." if not self._fetched_once else "No flights in range"
            draw_status_message(self.canvas, msg)
            return

        if self.config.get("display_mode", "cards") == "table":
            self._draw_table(visible)
        else:
            self._draw_card(visible)

    def _status_rows(
        self,
        tracked: dict[str, Any],
        kind: str,
        text_color: tuple[int, int, int],
    ) -> list[tuple[str, tuple[int, int, int]]]:
        """The two bottom card rows as (text, color) pairs.

        Row 1 (schedule/progress) uses the card's base text color. Row 2 is the
        on-time/delay/cancelled indicator, colored green when on time or ahead
        of schedule, yellow when delayed, and red when cancelled.
        """
        tz, time_format = self._tz_and_time_format()

        def delay_cell(delay_seconds: int | None) -> tuple[str, tuple[int, int, int]]:
            text = _fmt_delay(delay_seconds)
            return (text, _STATUS_YELLOW) if text else ("On time", _STATUS_GREEN)

        if kind == "scheduled":
            schedule = f"Dep {_fmt_time(tracked.get('scheduled_off'), tz, time_format)}"
            delay_key = "departure_delay"
        elif kind == "airborne":
            pct = tracked.get("progress_percent")
            schedule = f"En route {pct}%" if pct is not None else "En route"
            delay_key = "arrival_delay"
        elif kind == "landed":
            schedule = f"Landed {_fmt_time(tracked.get('actual_on'), tz, time_format)}"
            delay_key = "arrival_delay"
        else:
            return []

        if tracked.get("cancelled"):
            return [(schedule, text_color), ("Cancelled", _STATUS_RED)]
        return [(schedule, text_color), delay_cell(tracked.get(delay_key))]

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
        self._render_flight_card(fn, tracked, kind, label, text_color)

    def _render_flight_card(
        self,
        fn: str,
        tracked: dict[str, Any],
        kind: str,
        label: str,
        text_color: tuple[int, int, int],
    ) -> None:
        """Render one flight card: airline logo, flight info, and live stats.

        Mirrors the Flights Overhead card layout -- a square airline logo on the
        left, a middle text column (airline/label, flight number, route), a
        colon-aligned stats column on the right for airborne flights, and two
        bottom rows for schedule/status -- so the two flight apps look consistent.
        """
        w, h = self.canvas.width, self.canvas.height
        img = Image.new("RGB", (w, h))

        pad = 2
        inner_h = h - 2 * pad
        inner_w = w - 2 * pad
        logo_gap = 2
        stats_gap = 2

        # Largest font whose measured glyph height fits five rows; fall back to
        # fewer rows on short panels rather than overlapping text.
        n_rows = 5
        font_size = 7
        size_cap = max(7, inner_h // 5 - 2)
        for size in (15, 12, 9, 8, 7):
            if size > size_cap:
                continue
            if 5 * (render_text("Ag", text_color, size).height + 1) - 1 <= inner_h:
                font_size = size
                break
        else:
            glyph_h = render_text("Ag", text_color, 7).height
            n_rows = max(2, (inner_h + 1) // (glyph_h + 1))
        slot_h = inner_h // n_rows

        def row_y(row: int, img_h: int) -> int:
            return pad + row * slot_h + (slot_h - img_h) // 2

        # Stats column (airborne only): colon-aligned alt/spd/track.
        stat_strs = (
            self._stat_lines(tracked, self._show_imperial)[:n_rows]
            if kind == "airborne" else []
        )
        stat_parts: list[tuple[str, str]] = []
        for s in stat_strs:
            if ": " in s:
                idx = s.index(": ")
                stat_parts.append((s[: idx + 1], s[idx + 1:]))
            else:
                stat_parts.append((s, ""))

        _worst_vals = [
            " 45000 ft", " 700 mph", " 13700 m", " 1100 kph", " 359 deg", " ---",
        ]
        label_imgs = [render_text(lbl, text_color, font_size) for lbl, _ in stat_parts]
        value_imgs = [render_text(val, text_color, font_size) if val else None
                      for _, val in stat_parts]
        label_col_w = max((li.width for li in label_imgs), default=0)
        value_col_w = (
            max(
                max((render_text(v, text_color, font_size).width for v in _worst_vals), default=0),
                max((vi.width for vi in value_imgs if vi is not None), default=0),
            )
            if stat_parts else 0
        )
        stats_w = label_col_w + value_col_w
        if stats_w > inner_w // 2:
            stat_parts, label_imgs, value_imgs = [], [], []
            label_col_w = value_col_w = stats_w = 0

        # Logo: square spanning the top rows, capped so text keeps room.
        logo_dim = min(min(3, n_rows) * slot_h, w // 4)
        operator_iata = self._operator_iata(fn, tracked)
        raw_logo = self._logos.get(operator_iata) if operator_iata else None
        if logo_dim >= 8:
            if raw_logo is not None:
                resized = raw_logo.resize((logo_dim, logo_dim), Image.LANCZOS)
                bg = Image.new("RGB", resized.size, (0, 0, 0))
                if resized.mode == "RGBA":
                    bg.paste(resized.convert("RGB"), mask=resized.split()[3])
                else:
                    bg.paste(resized.convert("RGB"))
                img.paste(bg, (pad, pad))
            else:
                fallback = render_category_icon(None, logo_dim)
                bg = Image.new("RGB", (logo_dim, logo_dim), (0, 0, 0))
                bg.paste(fallback.convert("RGB"), mask=fallback.split()[3])
                img.paste(bg, (pad, pad))
            mid_x = pad + logo_dim + logo_gap
        else:
            mid_x = pad

        # Middle text: airline (or user label), flight number, route.
        mid_w = max(0, (w - pad - stats_w - (stats_gap if stats_w else 0)) - mid_x)
        airline = label or tracked.get("airline", "") or fn
        origin = tracked.get("origin", "") or ""
        dest = tracked.get("dest", "") or ""
        route = f"{origin}->{dest}" if origin and dest else ""

        for i, line in enumerate([airline, fn, route][: min(3, n_rows)]):
            if line and mid_w > 0:
                clipped = _clip_text(line, font_size, mid_w)
                line_img = render_text(clipped, text_color, font_size)
                img.paste(line_img, (mid_x, row_y(i, line_img.height)))

        # Bottom rows (full-height cards only): schedule/status + delay, with
        # the status indicator colored by on-time/delayed/cancelled state.
        if n_rows == 5:
            bottom_w = inner_w - stats_w - (stats_gap if stats_w else 0)
            for i, (line, color) in enumerate(self._status_rows(tracked, kind, text_color)[:2]):
                if line and bottom_w > 0:
                    clipped = _clip_text(line, font_size, bottom_w)
                    line_img = render_text(clipped, color, font_size)
                    img.paste(line_img, (pad, row_y(3 + i, line_img.height)))

        # Stats: labels right-aligned to the colon column, values to the edge.
        if stat_parts:
            colon_x = w - pad - value_col_w
            for i, (li, vi) in enumerate(zip(label_imgs, value_imgs)):
                img.paste(li, (colon_x - li.width, row_y(i, li.height)))
                if vi is not None:
                    img.paste(vi, (w - pad - vi.width, row_y(i, vi.height)))

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
