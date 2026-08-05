"""US EPA AQI banding and the air-quality merge into a parsed weather payload.

The air-quality endpoint is a *second* request with its own hourly series and
no daily aggregate, so the merge has to line hours up by timestamp and roll its
own daily summary. These tests pin both, plus the color/label band edges the
display depends on.
"""

from __future__ import annotations

from typing import Any

import pytest

from libraries.open_meteo.library import (
    OpenMeteoLibrary,
    _AQI_UNKNOWN_COLOR,
    aqi_color,
    aqi_label,
)


@pytest.mark.parametrize(
    "aqi,label",
    [
        (0, "Good"),
        (50, "Good"),
        (51, "Moderate"),
        (100, "Moderate"),
        (101, "Poor"),
        (150, "Poor"),
        (151, "Unhealthy"),
        (200, "Unhealthy"),
        (201, "Very Bad"),
        (300, "Very Bad"),
        (301, "Hazardous"),
        (999, "Hazardous"),
    ],
)
def test_aqi_label_band_edges(aqi: int, label: str) -> None:
    assert aqi_label(aqi) == label


def test_aqi_color_is_distinct_per_band() -> None:
    colors = [aqi_color(v) for v in (25, 75, 125, 175, 250, 400)]
    assert len(set(colors)) == len(colors)
    # Good is green-dominant, Unhealthy is red-dominant — the ramp's endpoints
    # are what makes the readout scannable at a glance.
    good_r, good_g, _ = aqi_color(25)
    bad_r, bad_g, _ = aqi_color(175)
    assert good_g > good_r
    assert bad_r > bad_g


def test_aqi_missing_or_garbage_falls_back() -> None:
    assert aqi_label(None) == "Unknown"
    assert aqi_color(None) == _AQI_UNKNOWN_COLOR
    assert aqi_color("n/a") == _AQI_UNKNOWN_COLOR  # type: ignore[arg-type]


def _parsed() -> dict[str, Any]:
    return {
        "timezone": "America/Denver",
        "current": {"temperature": 72.0, "weather_code": 2},
        "hourly": [
            {"time": "2026-06-10T12:00", "temperature": 72, "weather_code": 2},
            {"time": "2026-06-10T13:00", "temperature": 74, "weather_code": 2},
            {"time": "2026-06-11T09:00", "temperature": 60, "weather_code": 3},
        ],
        "daily": [
            {"date": "2026-06-10", "weather_code": 2, "temp_max": 75, "temp_min": 55},
            {"date": "2026-06-11", "weather_code": 3, "temp_max": 74, "temp_min": 56},
            {"date": "2026-06-12", "weather_code": 0, "temp_max": 73, "temp_min": 57},
        ],
    }


def test_merge_air_quality_populates_current_hourly_and_daily() -> None:
    parsed = _parsed()
    OpenMeteoLibrary._merge_air_quality(
        parsed,
        {
            "current": {"us_aqi": 42},
            "hourly": {
                "time": ["2026-06-10T12:00", "2026-06-10T13:00", "2026-06-11T09:00"],
                "us_aqi": [38, 91, 160],
            },
        },
    )

    assert parsed["current"]["aqi"] == 42
    assert [e["aqi"] for e in parsed["hourly"]] == [38, 91, 160]
    # Daily is the worst hour of that date; 06-12 has no readings at all.
    assert parsed["daily"][0]["aqi"] == 91
    assert parsed["daily"][1]["aqi"] == 160
    assert "aqi" not in parsed["daily"][2]


def test_merge_air_quality_skips_unmatched_hours_and_nulls() -> None:
    parsed = _parsed()
    OpenMeteoLibrary._merge_air_quality(
        parsed,
        {
            "current": {},
            "hourly": {
                "time": ["2026-06-10T12:00", "2026-06-10T13:00", "2026-06-30T00:00"],
                "us_aqi": [38, None, 200],
            },
        },
    )

    assert "aqi" not in parsed["current"]
    assert parsed["hourly"][0]["aqi"] == 38
    assert "aqi" not in parsed["hourly"][1]  # null reading
    assert "aqi" not in parsed["hourly"][2]  # no matching hour in the response
    assert parsed["daily"][0]["aqi"] == 38
    assert "aqi" not in parsed["daily"][1]


def test_merge_air_quality_no_op_on_empty_response() -> None:
    parsed = _parsed()
    assert OpenMeteoLibrary._merge_air_quality(parsed, {}) == _parsed()
