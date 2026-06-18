"""Weather snapshot suite: current / daily / weekly views, both unit systems.

``datetime.now()`` in the app module is frozen to ``clock.FIXED_NOW`` (June 10
2026, 12:00) and all fixture timestamps are fixed strings starting at that
hour, so hourly filtering is fully deterministic.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from tests.framework import harness
from tests.framework.clock import FIXED_NOW

_HOURLY_CODES = [0, 0, 1, 1, 2, 2, 3, 61, 61, 80, 2, 1, 0, 0, 1, 2, 3, 3, 95, 61, 71, 71, 2, 1]
_DAILY_CODES = [0, 2, 61, 71, 95, 3, 1]


def _weather_data() -> dict[str, Any]:
    start = FIXED_NOW.replace(tzinfo=None)
    hourly = [
        {
            "time": (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M"),
            "temperature": 58 + (i % 12),
            "weather_code": _HOURLY_CODES[i % len(_HOURLY_CODES)],
        }
        for i in range(48)
    ]
    daily = [
        {
            "date": (start.date() + timedelta(days=d)).isoformat(),
            "weather_code": _DAILY_CODES[d],
            "temp_max": 75 - d,
            "temp_min": 55 + d,
        }
        for d in range(len(_DAILY_CODES))
    ]
    return {
        "timezone": None,
        "current": {
            "temperature": 72.0,
            "feels_like": 70.0,
            "humidity": 48,
            "wind_speed": 6.0,
            "weather_code": 2,
            "is_day": True,
        },
        "hourly": hourly,
        "daily": daily,
    }


def _seed(app: Any) -> None:
    app._data = _weather_data()
    app._fetched_once = True


def _fixtures() -> dict[str, dict[str, Any]]:
    return {
        "current": {"config": {"display_mode": "current"}, "seed": _seed},
        "current_celsius": {
            "config": {"display_mode": "current", "units": "celsius"},
            "seed": _seed,
        },
        "daily_forecast": {"config": {"display_mode": "daily_forecast"}, "seed": _seed},
        "weekly_forecast": {"config": {"display_mode": "weekly_forecast"}, "seed": _seed},
        "unavailable": {
            "config": {"display_mode": "current"},
            "seed": lambda app: setattr(app, "_fetched_once", True),
        },
    }


def _register() -> None:
    from apps.weather.app import WeatherApp

    harness.register(
        harness.SnapshotSuite(
            app_id="weather",
            fixtures=_fixtures(),
            sizes=harness.CORE_SIZES,
            render=harness.app_case_render(
                WeatherApp, freeze_datetime="apps.weather.app.datetime"
            ),
        )
    )


_register()
