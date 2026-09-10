"""Every view colors its temperatures by value, and the setting can turn it off."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from PIL import Image

from apps.weather.app import WeatherApp, _dim
from canvas.simulator import SimulatorCanvas
from libraries.open_meteo.library import temp_color
from tests.framework.clock import FIXED_NOW, frozen_time
from tests.framework.harness import render_app_frame

# The app's default "text_color", i.e. what an uncolored reading renders as.
_TEXT = (200, 200, 200)
_W, _H = 192, 64
# Left of this the current view draws its condition icon, whose full-color
# pixels would swamp any assertion about text.
_ICON_RIGHT = 2 + max(14, min(_H - 4, _W // 3))
# The forecast views anchor their temperatures to the bottom of the panel, with
# the icon band ending at least 2px above them.
_TEMP_BAND_H = 12


async def _noop_broadcast(_frame: bytes) -> None:
    pass


def _app(config: dict[str, Any]) -> WeatherApp:
    return WeatherApp(config, SimulatorCanvas(_W, _H, _noop_broadcast), {}, {})


def _data(*, current: float, feels: float, hourly: float, hi: float, lo: float) -> dict[str, Any]:
    """A payload with one temperature per view, so a crop has a single answer."""
    start = FIXED_NOW.replace(tzinfo=None)
    return {
        "timezone": None,
        "current": {
            "temperature": current,
            "feels_like": feels,
            "humidity": 48,
            "weather_code": 2,
            "is_day": True,
        },
        "hourly": [
            {
                "time": (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M"),
                "temperature": hourly,
                "weather_code": 2,
            }
            for i in range(24)
        ],
        "daily": [
            {
                "date": (start.date() + timedelta(days=d)).isoformat(),
                "weather_code": 2,
                "temp_max": hi,
                "temp_min": lo,
            }
            for d in range(7)
        ],
    }


def _render(mode: str, data: dict[str, Any], **config: Any) -> Image.Image:
    def seed(app: WeatherApp) -> None:
        app._data = data
        app._fetched_once = True

    with frozen_time("apps.weather.app.datetime"):
        return render_app_frame(
            WeatherApp, {"display_mode": mode, **config}, _W, _H, seed=seed
        )


def _colors(img: Image.Image, box: tuple[int, int, int, int]) -> set[tuple[int, int, int]]:
    counted = img.crop(box).getcolors(maxcolors=1 << 16) or []
    return {color for _, color in counted if color != (0, 0, 0)}


def _text_box(img: Image.Image) -> tuple[int, int, int, int]:
    return (_ICON_RIGHT, 0, img.width, img.height)


def _temp_band(img: Image.Image) -> tuple[int, int, int, int]:
    return (0, img.height - _TEMP_BAND_H, img.width, img.height)


_HOT_AND_COLD = _data(current=95, feels=105, hourly=38, hi=101, lo=45)


def test_the_current_view_colors_the_reading_and_the_feels_like_number() -> None:
    """Both are temperatures, so both carry their own spot on the ramp; the
    condition label beside them stays in the configured text color."""
    img = _render("current", _HOT_AND_COLD)

    assert _colors(img, _text_box(img)) == {temp_color(95), temp_color(105), _TEXT}


def test_the_daily_forecast_colors_its_hourly_temperatures() -> None:
    img = _render("daily_forecast", _HOT_AND_COLD)

    assert _colors(img, _temp_band(img)) == {temp_color(38)}


def test_the_weekly_forecast_colors_each_end_of_the_range() -> None:
    """The low keeps its dimmed treatment, now off its own color."""
    img = _render("weekly_forecast", _HOT_AND_COLD)

    assert _colors(img, _temp_band(img)) == {temp_color(101), _dim(temp_color(45))}


def test_the_setting_turns_the_spectrum_off() -> None:
    for mode, box in (("current", _text_box), ("daily_forecast", _temp_band)):
        img = _render(mode, _HOT_AND_COLD, color_temps=False)
        assert _colors(img, box(img)) == {_TEXT}, mode


def test_the_setting_off_dims_the_weekly_low_off_the_text_color() -> None:
    img = _render("weekly_forecast", _HOT_AND_COLD, color_temps=False)

    assert _colors(img, _temp_band(img)) == {_TEXT, _dim(_TEXT)}


def test_a_celsius_reading_lands_where_its_fahrenheit_equal_does() -> None:
    """The payload is already in the configured unit, so the ramp is told which."""
    celsius = _app({"units": "celsius"})
    fahrenheit = _app({"units": "fahrenheit"})

    assert celsius._temp_color(35, _TEXT) == fahrenheit._temp_color(95, _TEXT)
    assert celsius._temp_color(35, _TEXT) != fahrenheit._temp_color(35, _TEXT)


def test_a_missing_reading_keeps_the_text_color() -> None:
    """"--°" has no value to encode; a grey among coloured neighbours would
    read as a failed lookup instead of a missing number."""
    assert _app({})._temp_color(None, _TEXT) == _TEXT
