"""The air-quality setting gates both the fetch and every view's rendering."""

from __future__ import annotations

import asyncio
from typing import Any

from apps.weather.app import WeatherApp
from apps.weather.tests.fixtures import _weather_data
from canvas.simulator import SimulatorCanvas
from tests.framework.clock import frozen_time
from tests.framework.harness import render_app_frame


async def _noop_broadcast(_frame: bytes) -> None:
    pass


def _app(config: dict[str, Any], w: int = 128, h: int = 64) -> WeatherApp:
    return WeatherApp(config, SimulatorCanvas(w, h, _noop_broadcast), {}, {})


class _RecordingLibrary:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    async def fetch_weather(self, lat: float, lon: float, unit: str, **kwargs: Any) -> dict[str, Any]:
        self.kwargs = kwargs
        return _weather_data()


def _fetch_with(show_air_quality: bool) -> dict[str, Any]:
    app = _app(
        {
            "location": {"latitude": 39.7, "longitude": -104.9},
            "show_air_quality": show_air_quality,
        }
    )
    library = _RecordingLibrary()
    app._open_meteo = library  # type: ignore[assignment]
    asyncio.run(app.fetch_data())
    return library.kwargs


def test_fetch_requests_air_quality_only_when_enabled() -> None:
    assert _fetch_with(True) == {"include_air_quality": True}
    assert _fetch_with(False) == {"include_air_quality": False}


def test_footer_plan_off_by_default() -> None:
    app = _app({})
    entries = _weather_data(air_quality=True)["daily"]
    assert app._aqi_footer_plan(entries, 64, 20)[0] == "none"


def test_footer_plan_needs_data() -> None:
    app = _app({"show_air_quality": True})
    entries = _weather_data()["daily"]  # no AQI in the payload
    assert app._aqi_footer_plan(entries, 64, 20)[0] == "none"


def test_footer_plan_prints_the_number_only_on_tall_panels() -> None:
    app = _app({"show_air_quality": True})
    entries = _weather_data(air_quality=True)["daily"]

    short_mode, short_h, _ = app._aqi_footer_plan(entries, 32, 20)
    tall_mode, tall_h, tall_size = app._aqi_footer_plan(entries, 64, 20)

    assert short_mode == "bar"
    assert tall_mode == "text"
    assert tall_size >= 6
    # Either way the footer has to be cheap enough to leave the icon room.
    assert 0 < short_h < tall_h <= 12


def _render(config: dict[str, Any], *, air_quality_data: bool, w: int, h: int) -> bytes:
    def seed(app: WeatherApp) -> None:
        app._data = _weather_data(air_quality=air_quality_data)
        app._fetched_once = True

    with frozen_time("apps.weather.app.datetime"):
        return render_app_frame(WeatherApp, config, w, h, seed=seed).tobytes()


def test_views_are_unchanged_when_the_setting_is_off() -> None:
    """AQI in the payload must not leak into the frame unless it was asked for."""
    for mode in ("current", "daily_forecast", "weekly_forecast"):
        for w, h in ((128, 32), (256, 64)):
            config = {"display_mode": mode}
            assert _render(config, air_quality_data=True, w=w, h=h) == _render(
                config, air_quality_data=False, w=w, h=h
            ), f"{mode} at {w}x{h} changed with the setting off"


def test_views_change_when_the_setting_is_on() -> None:
    for mode in ("current", "daily_forecast", "weekly_forecast"):
        for w, h in ((128, 32), (256, 64)):
            off = _render({"display_mode": mode}, air_quality_data=True, w=w, h=h)
            on = _render(
                {"display_mode": mode, "show_air_quality": True},
                air_quality_data=True,
                w=w,
                h=h,
            )
            assert off != on, f"{mode} at {w}x{h} did not render its AQI"
