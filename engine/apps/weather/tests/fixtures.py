"""Weather snapshot suite: current / daily / weekly views, both unit systems,
with and without the opt-in air-quality readout.

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
# AQI values chosen to land in different EPA bands, so the air-quality fixtures
# exercise the whole color ramp (green -> yellow -> orange -> red -> purple).
_HOURLY_AQI = [18, 34, 47, 62, 88, 105, 133, 158, 184, 215, 268, 320]
_DAILY_AQI = [42, 78, 120, 165, 240, 310, 55]


def _weather_data(*, air_quality: bool = False) -> dict[str, Any]:
    start = FIXED_NOW.replace(tzinfo=None)
    hourly = [
        {
            "time": (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M"),
            "temperature": 58 + (i % 12),
            "weather_code": _HOURLY_CODES[i % len(_HOURLY_CODES)],
            **({"aqi": _HOURLY_AQI[i % len(_HOURLY_AQI)]} if air_quality else {}),
        }
        for i in range(48)
    ]
    daily = [
        {
            "date": (start.date() + timedelta(days=d)).isoformat(),
            "weather_code": _DAILY_CODES[d],
            "temp_max": 75 - d,
            "temp_min": 55 + d,
            **({"aqi": _DAILY_AQI[d]} if air_quality else {}),
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
            **({"aqi": 88} if air_quality else {}),
        },
        "hourly": hourly,
        "daily": daily,
    }


def _seed(app: Any) -> None:
    app._data = _weather_data()
    app._fetched_once = True


def _seed_aqi(app: Any) -> None:
    app._data = _weather_data(air_quality=True)
    app._fetched_once = True


def _fixtures() -> dict[str, dict[str, Any]]:
    aqi_on = {"show_air_quality": True}
    return {
        "current": {"config": {"display_mode": "current"}, "seed": _seed},
        "current_celsius": {
            "config": {"display_mode": "current", "units": "celsius"},
            "seed": _seed,
        },
        "daily_forecast": {"config": {"display_mode": "daily_forecast"}, "seed": _seed},
        "weekly_forecast": {"config": {"display_mode": "weekly_forecast"}, "seed": _seed},
        "current_aqi": {
            "config": {"display_mode": "current", **aqi_on},
            "seed": _seed_aqi,
        },
        "daily_forecast_aqi": {
            "config": {"display_mode": "daily_forecast", **aqi_on},
            "seed": _seed_aqi,
        },
        "weekly_forecast_aqi": {
            "config": {"display_mode": "weekly_forecast", **aqi_on},
            "seed": _seed_aqi,
        },
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
