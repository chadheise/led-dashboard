from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from libraries.base import Library

logger = logging.getLogger(__name__)

_CITIES_FILE = Path(__file__).parent / "cities.json"
_CITIES: list[dict[str, str]] = json.loads(_CITIES_FILE.read_text(encoding="utf-8"))
_CITY_BY_TZ: dict[str, dict[str, str]] = {e["timezone"]: e for e in _CITIES}


def _entry_label(entry: dict[str, str]) -> str:
    return f"{entry['city']}, {entry['country']}"


def list_cities() -> list[dict[str, str]]:
    """Curated major-world-city dataset, each mapped to a unique IANA timezone.

    Returns dicts with "city", "country", "timezone", and a derived "label"
    ("City, Country") suitable for UI picker options.
    """
    return [{**entry, "label": _entry_label(entry)} for entry in _CITIES]


def _derive_city_name(tz_name: str) -> str:
    """Derive a short city-ish name from a raw IANA identifier.

    Used for timezones outside the curated dataset (e.g. a "local" zone
    resolved from the user's coordinates) — takes the last path segment and
    turns underscores into spaces, e.g. "America/Indiana/Indianapolis"
    becomes "Indianapolis".
    """
    return tz_name.rsplit("/", 1)[-1].replace("_", " ")


def city_name(tz_name: str) -> str:
    """A compact display name for a timezone — just the city, no country.

    Suited to space-constrained on-screen labels. Looks up the curated
    dataset first, falling back to a name derived from the IANA identifier.
    """
    entry = _CITY_BY_TZ.get(tz_name)
    if entry is not None:
        return entry["city"]
    return _derive_city_name(tz_name)


def city_label(tz_name: str) -> str:
    """A fuller "City, Country" display label for a timezone identifier.

    Looks up the curated city dataset first; falls back to the derived city
    name alone when the timezone (e.g. a resolved "local" zone) isn't in it.
    """
    entry = _CITY_BY_TZ.get(tz_name)
    if entry is not None:
        return _entry_label(entry)
    return _derive_city_name(tz_name)


def resolve_zone(tz_name: str) -> ZoneInfo | None:
    """Safely resolve an IANA timezone identifier to a `ZoneInfo`."""
    if not tz_name:
        return None
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        logger.warning("Unknown timezone %r: %s", tz_name, exc)
        return None


def current_time(tz_name: str, *, reference: datetime.datetime | None = None) -> dict[str, Any] | None:
    """"Fetch" the current date/time in `tz_name`.

    `reference` is the shared instant to convert (defaults to "now" in UTC) —
    callers displaying many zones at once should pass the same `reference` so
    every entry reflects a single, consistent snapshot. Returns a normalized
    dict {"datetime", "utc_offset_minutes", "tzname"}, or None if the
    timezone can't be resolved.
    """
    zone = resolve_zone(tz_name)
    if zone is None:
        return None
    if reference is None:
        reference = datetime.datetime.now(datetime.timezone.utc)
    local = reference.astimezone(zone)
    offset = local.utcoffset() or datetime.timedelta(0)
    return {
        "datetime": local,
        "utc_offset_minutes": int(offset.total_seconds() // 60),
        "tzname": local.tzname(),
    }


class TimezonesLibrary(Library):
    id: ClassVar[str] = "timezones"
    name: ClassVar[str] = "Timezones"
    description: ClassVar[str] = (
        "Current date and time lookups for cities and timezones around the "
        "world, built on Python's IANA timezone database — no API key required"
    )
    icon: ClassVar[str] = (Path(__file__).parent / "icon.svg").read_text()
    global_config_schema: ClassVar[dict[str, Any]] = {}

    list_cities = staticmethod(list_cities)
    city_name = staticmethod(city_name)
    city_label = staticmethod(city_label)
    resolve_zone = staticmethod(resolve_zone)
    current_time = staticmethod(current_time)
