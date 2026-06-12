"""When `timezonefinder` can't resolve an IANA zone (e.g. its native
dependencies — numpy/h3/cffi — aren't available on the host), location-based
apps fall back to a fixed UTC offset derived from longitude, so pre-game
times are still converted toward the viewer's local time instead of UTC.
"""

from __future__ import annotations

import datetime

from libraries.location.library import LocationLibrary


def _library(lat: float, lon: float) -> LocationLibrary:
    return LocationLibrary({"location": {"latitude": lat, "longitude": lon, "name": ""}})


def test_fallback_offset_derived_from_longitude():
    # Los Angeles: ~-118 longitude -> roughly UTC-8.
    lib = _library(34.0522, -118.2437)
    offset = lib.get_fallback_offset()
    assert offset == datetime.timezone(datetime.timedelta(hours=-8))


def test_fallback_offset_none_without_configured_location():
    lib = _library(0.0, 0.0)
    assert lib.get_fallback_offset() is None


def test_get_timezone_falls_back_when_timezonefinder_unavailable(monkeypatch):
    lib = _library(34.0522, -118.2437)
    monkeypatch.setattr(lib, "_get_timezone_finder", lambda: None)
    assert lib.get_timezone() is None
    # Callers (e.g. SportsApp._get_user_tz) use get_fallback_offset() in this case.
    assert lib.get_fallback_offset() == datetime.timezone(datetime.timedelta(hours=-8))


def _sports_app(library_configs: dict[str, dict]):
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(64, 32, _noop_broadcast)
    return SportsApp({"leagues": []}, canvas, {}, library_configs)


def test_sports_app_uses_offset_fallback_when_timezonefinder_unavailable(monkeypatch):
    monkeypatch.setattr(LocationLibrary, "_get_timezone_finder", lambda self: None)
    library_configs = {
        "location": {
            "location": {"latitude": 34.0522, "longitude": -118.2437, "name": "Los Angeles, US"},
            "time_format": "12h",
            "date_format": "MM/DD/YYYY",
        }
    }
    app = _sports_app(library_configs)
    assert app._get_user_tz() == datetime.timezone(datetime.timedelta(hours=-8))


def test_sports_app_returns_none_tz_without_configured_location():
    app = _sports_app({})
    assert app._get_user_tz() is None
