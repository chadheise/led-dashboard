"""The temperature ramp: band character, continuity, units, and fallbacks.

The display reads the ramp for every temperature it prints, so what matters is
that each band is recognisable at a glance (cold reads blue, hot reads red),
that neighbouring readings differ by a shade rather than a jump, and that a
Celsius payload lands on the same color as the Fahrenheit reading it equals.
"""

from __future__ import annotations

import pytest

from libraries.open_meteo.library import _TEMP_STOPS, _TEMP_UNKNOWN_COLOR, temp_color


def _dominant_is(color: tuple[int, int, int], channel: int) -> bool:
    return all(color[channel] > c for i, c in enumerate(color) if i != channel)


def test_sub_freezing_reads_white_through_pink_and_violet() -> None:
    assert temp_color(-20) == (255, 255, 255)
    r, g, b = temp_color(10)
    assert r > 200 and b > 200 and g < r  # pink
    r, g, b = temp_color(26)
    assert b > r > g  # violet


def test_the_freezing_band_reads_blue() -> None:
    for f in (32, 35, 39):
        assert _dominant_is(temp_color(f), 2), f


def test_the_cool_band_reads_cyan_then_green() -> None:
    r, g, b = temp_color(46)
    assert b > r and g > r  # cyan/teal
    assert _dominant_is(temp_color(57), 1)  # green


def test_the_mild_band_reads_green_through_yellow() -> None:
    r, g, b = temp_color(65)
    assert g > r > b  # light green
    r, g, b = temp_color(79)
    assert r >= 250 and g > 200 and b < 40  # yellow


def test_the_hot_bands_read_orange_then_red_then_purple() -> None:
    r, g, b = temp_color(86)
    assert r > g > b  # orange
    r, g, b = temp_color(99)
    assert r > 200 and g < 80 and b < 80  # bright red
    r, g, b = temp_color(112)
    assert r > 200 and b > 150 and g < 60  # magenta
    assert _dominant_is(temp_color(125), 2)  # purple


def test_the_named_bands_are_visibly_distinct() -> None:
    """One reading per band of the spectrum the display advertises."""
    colors = [temp_color(f) for f in (20, 35, 50, 70, 90, 110)]
    assert len(set(colors)) == len(colors)


def test_the_ramp_is_continuous() -> None:
    """No band edges: a degree either way must not restyle the whole readout."""
    for f in range(-30, 140):
        before, after = temp_color(f), temp_color(f + 1)
        assert max(abs(a - b) for a, b in zip(before, after)) <= 20, f


def test_every_stop_stays_bright_enough_for_the_panel() -> None:
    """Dark red and dark blue read as near-black on LEDs, so the ramp avoids
    them: it reaches those bands by hue, not by dimming."""
    for degrees, color in _TEMP_STOPS:
        assert max(color) >= 200, f"{degrees}F is {color}"


def test_the_ends_of_the_ramp_clamp() -> None:
    assert temp_color(-40) == temp_color(-100) == _TEMP_STOPS[0][1]
    assert temp_color(130) == temp_color(200) == _TEMP_STOPS[-1][1]


@pytest.mark.parametrize("celsius,fahrenheit", [(-20, -4), (0, 32), (10, 50), (21, 69.8), (35, 95)])
def test_celsius_readings_land_on_the_same_color(celsius: float, fahrenheit: float) -> None:
    assert temp_color(celsius, "celsius") == temp_color(fahrenheit)


def test_an_unknown_unit_is_read_as_fahrenheit() -> None:
    assert temp_color(72, "kelvin") == temp_color(72)


def test_missing_or_garbage_readings_fall_back() -> None:
    assert temp_color(None) == _TEMP_UNKNOWN_COLOR
    assert temp_color("n/a") == _TEMP_UNKNOWN_COLOR  # type: ignore[arg-type]
