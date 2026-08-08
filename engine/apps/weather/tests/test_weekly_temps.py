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
    assert _temp_range_sep(days, 8, 34) == "-"
    # Too narrow even unspaced: the caller falls back to stacking hi over lo.
    assert _temp_range_sep(days, 8, 25) is None


def test_separator_is_chosen_for_the_whole_row() -> None:
    """One wide day tightens every column, so neighbours stay spaced alike."""
    assert _temp_range_sep(_days([(55, 75), (100, 100)]), 8, 40) == "-"
    assert _temp_range_sep(_days([(55, 75), (56, 74)]), 8, 40) == " - "


def test_a_lopsided_range_is_measured_from_its_wider_end() -> None:
    """The dash holds the centre, so the wider end has to fit twice over."""
    wide_end = render_text("100°", (255, 255, 255), 8).width
    sep_w = render_text("-", (255, 255, 255), 8).width

    assert _temp_range_sep(_days([(9, 100)]), 8, 2 * wide_end + sep_w) == "-"
    assert _temp_range_sep(_days([(9, 100)]), 8, 2 * wide_end + sep_w - 1) is None


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


def _draw(lo: float, hi: float, sep: str, cx: int, color: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (2 * cx, 12))
    _app()._draw_temp_range(img, lo, hi, sep, 8, color, cx, 2)
    return img


def test_range_geometry_matches_a_single_string_render() -> None:
    """Drawn as one string: a separately pasted separator rides up to the top."""
    color = (200, 200, 200)
    expected = render_text("55° - 75°", color, 8)
    drawn = _ink(_draw(55, 75, " - ", 40, color))

    # Same shape, wherever it was placed.
    dx, dy = min(x for x, _ in drawn), min(y for _, y in drawn)
    ink = _ink(expected)
    ex, ey = min(x for x, _ in ink), min(y for _, y in ink)
    assert {(x - dx, y - dy) for x, y in drawn} == {(x - ex, y - ey) for x, y in ink}


def test_the_separator_sits_on_the_column_centre() -> None:
    """Centring the whole string instead leaves the dash a pixel off, and drifts
    further as the two ends diverge in width."""
    color = (200, 200, 200)
    for lo, hi, sep in ((55, 75, " - "), (9, 100, " - "), (9, 100, "-")):
        text = f"{round(lo)}°{sep}{round(hi)}°"
        # Where the separator's ink falls inside a plain render of the range...
        whole = render_text(text, color, 8)
        low_w = render_text(f"{round(lo)}°", color, 8).width
        sep_box = render_text(sep, color, 8).getbbox()
        assert sep_box is not None

        cx = 40
        drawn = _ink(_draw(lo, hi, sep, cx, color))
        # ...pinned against where the drawn copy actually landed.
        paste_x = min(x for x, _ in drawn) - min(x for x, _ in _ink(whole))
        dash = (paste_x + low_w + sep_box[0], paste_x + low_w + sep_box[2] - 1)
        assert (dash[0] + dash[1]) / 2 == cx, f"{lo}{sep}{hi} dash at {dash}, centre {cx}"


def test_the_low_end_of_the_range_is_dimmed() -> None:
    color = (200, 200, 200)
    img = _draw(55, 75, " - ", 30, color)

    colors = {img.load()[x, y] for x, y in _ink(img)}
    assert colors == {_dim(color), color}
