"""The weekly view's hi/lo range: how it spaces, when it gives up, how it draws."""

from __future__ import annotations

from typing import Any

from PIL import Image

from apps.weather.app import WeatherApp, _dim, _temp_range_sep
from canvas.simulator import SimulatorCanvas
from libraries.text_renderer.library import render_text


async def _noop_broadcast(_frame: bytes) -> None:
    pass


def _app() -> WeatherApp:
    return WeatherApp({}, SimulatorCanvas(128, 64, _noop_broadcast), {}, {})


def _days(pairs: list[tuple[Any, Any]]) -> list[dict[str, Any]]:
    return [{"temp_min": lo, "temp_max": hi} for lo, hi in pairs]


def test_separator_tightens_then_gives_up_as_columns_narrow() -> None:
    days = _days([(55, 75), (56, 74)])

    assert _temp_range_sep(days, 8, 43) == " - "
    assert _temp_range_sep(days, 8, 25) == "-"
    # Too narrow even unspaced: the caller falls back to stacking hi over lo.
    assert _temp_range_sep(days, 8, 16) is None


def test_separator_is_chosen_for_the_whole_row() -> None:
    """One wide day tightens every column, so neighbours stay spaced alike."""
    assert _temp_range_sep(_days([(55, 75), (100, 100)]), 8, 34) == "-"
    assert _temp_range_sep(_days([(55, 75), (56, 74)]), 8, 34) == " - "


def test_a_day_missing_either_end_falls_back_to_the_stacked_layout() -> None:
    assert _temp_range_sep(_days([(55, 75), (None, 74)]), 8, 43) is None
    assert _temp_range_sep(_days([(55, 75), (56, None)]), 8, 43) is None


def _ink(img: Image.Image) -> set[tuple[int, int]]:
    px = img.load()
    return {
        (x, y)
        for x in range(img.width)
        for y in range(img.height)
        if px[x, y] != (0, 0, 0)
    }


def test_range_geometry_matches_a_single_string_render() -> None:
    """Drawn as one string: a separately pasted separator rides up to the top."""
    color = (200, 200, 200)
    expected = render_text("55 - 75", color, 8)
    img = Image.new("RGB", (expected.width + 20, expected.height + 4))

    _app()._draw_temp_range(img, 55, 75, " - ", 8, color, img.width // 2, 2)

    x0 = img.width // 2 - expected.width // 2
    drawn = img.crop((x0, 2, x0 + expected.width, 2 + expected.height))
    assert _ink(drawn) == _ink(expected)


def test_the_low_end_of_the_range_is_dimmed() -> None:
    color = (200, 200, 200)
    img = Image.new("RGB", (60, 10))

    _app()._draw_temp_range(img, 55, 75, " - ", 8, color, 30, 2)

    colors = {img.load()[x, y] for x, y in _ink(img)}
    assert colors == {_dim(color), color}
