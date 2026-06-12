"""Home timezone resolution for location-based apps (sports pre-game times,
countdown).

The map picker resolves an IANA timezone client-side (pure JS lat/lon
lookup, no native deps) and stores it alongside the coordinates as
`location.timezone`. The backend reads that directly; `timezonefinder` is
only a server-side fallback for configs saved before that field existed.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from libraries.location.library import LocationLibrary


def _library(lat: float, lon: float, timezone: str = "") -> LocationLibrary:
    return LocationLibrary(
        {"location": {"latitude": lat, "longitude": lon, "name": "", "timezone": timezone}}
    )


def test_get_timezone_prefers_client_resolved_value():
    # No timezonefinder call needed when the timezone is already stored.
    lib = _library(34.0522, -118.2437, timezone="America/Los_Angeles")
    assert lib.get_timezone() == "America/Los_Angeles"


def test_get_timezone_falls_back_to_timezonefinder_without_stored_value():
    lib = _library(34.0522, -118.2437)
    assert lib.get_timezone() == "America/Los_Angeles"


def test_get_timezone_none_when_timezonefinder_unavailable(monkeypatch):
    lib = _library(34.0522, -118.2437)
    monkeypatch.setattr(lib, "_get_timezone_finder", lambda: None)
    assert lib.get_timezone() is None


def _sports_app(library_configs: dict[str, dict]):
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(64, 32, _noop_broadcast)
    return SportsApp({"leagues": []}, canvas, {}, library_configs)


def test_sports_app_returns_none_tz_without_configured_location():
    app = _sports_app({})
    assert app._get_user_tz() is None


def test_sports_app_uses_client_resolved_timezone():
    library_configs = {
        "location": {
            "location": {
                "latitude": 34.0522,
                "longitude": -118.2437,
                "name": "Los Angeles, US",
                "timezone": "America/Los_Angeles",
            },
            "time_format": "12h",
            "date_format": "MM/DD/YYYY",
        }
    }
    app = _sports_app(library_configs)
    assert app._get_user_tz() == ZoneInfo("America/Los_Angeles")
