"""Unit tests for the world_clock config handling: per-city colors, the
any-city typeahead options, and backward compatibility with the legacy
bare-timezone city list."""

from __future__ import annotations

import asyncio
from typing import Any

from canvas.simulator import SimulatorCanvas
from libraries.timezones.library import list_timezone_options

from apps.world_clock.app import WorldClockApp, _parse_city_item


def _make_app(config: dict[str, Any]) -> WorldClockApp:
    async def _noop(_frame: bytes) -> None:
        pass

    return WorldClockApp({**config}, SimulatorCanvas(128, 64, _noop), {}, {})


# ── _parse_city_item ─────────────────────────────────────────────────────────


def test_parse_city_item_object_form():
    assert _parse_city_item({"timezone": "Europe/London", "color": "#FF0000"}) == (
        "Europe/London",
        "#FF0000",
    )


def test_parse_city_item_object_without_color():
    assert _parse_city_item({"timezone": "Asia/Tokyo"}) == ("Asia/Tokyo", None)


def test_parse_city_item_legacy_string():
    # Instances saved before per-city colors stored a bare timezone string.
    assert _parse_city_item("America/Chicago") == ("America/Chicago", None)


def test_parse_city_item_garbage():
    assert _parse_city_item(None) == (None, None)
    assert _parse_city_item({"color": "#FFFFFF"}) == (None, None)
    assert _parse_city_item("") == (None, None)


# ── fetch_data builds colored entries ────────────────────────────────────────


def test_fetch_data_carries_per_city_color():
    # No location configured -> no local row, so no network is touched.
    app = _make_app({
        "show_local": False,
        "cities": [
            {"timezone": "Europe/London", "color": "#FF0000"},
            {"timezone": "Asia/Tokyo"},
        ],
    })
    asyncio.run(app.fetch_data())

    assert app._entries == [
        ("Europe/London", "London", "#FF0000"),
        ("Asia/Tokyo", "Tokyo", None),
    ]


def test_fetch_data_accepts_legacy_string_cities():
    app = _make_app({"show_local": False, "cities": ["Europe/Paris", "Asia/Tokyo"]})
    asyncio.run(app.fetch_data())

    assert [(tz, color) for tz, _label, color in app._entries] == [
        ("Europe/Paris", None),
        ("Asia/Tokyo", None),
    ]


def test_per_city_color_renders_distinct_pixels():
    # A city with a bright red color should put red pixels on the canvas that a
    # default-gray render would not.
    red = _make_app({"show_local": False, "cities": [{"timezone": "Asia/Tokyo", "color": "#FF0000"}]})
    asyncio.run(red.fetch_data())
    asyncio.run(red.render_frame())
    red_px = list(red.canvas._pixels)

    gray = _make_app({"show_local": False, "cities": [{"timezone": "Asia/Tokyo"}]})
    asyncio.run(gray.fetch_data())
    asyncio.run(gray.render_frame())
    gray_px = list(gray.canvas._pixels)

    assert red_px != gray_px
    # At least one fully-red, no-green/blue pixel exists in the colored render.
    triples = list(zip(red_px[0::3], red_px[1::3], red_px[2::3]))
    assert any(r > 150 and g < 60 and b < 60 for r, g, b in triples)


# ── Typeahead options cover any world city ───────────────────────────────────


def test_timezone_options_include_non_curated_cities():
    options = list_timezone_options()
    by_tz = {o["timezone"]: o["label"] for o in options}

    # Curated city keeps its rich "City, Country" label...
    assert by_tz.get("America/New_York") == "New York, United States"
    # ...and a non-curated IANA zone is still selectable via a derived label.
    assert by_tz.get("America/Argentina/Ushuaia") == "Ushuaia"


def test_timezone_options_are_clean_place_zones():
    for o in list_timezone_options():
        assert "/" in o["timezone"]
        assert not o["timezone"].startswith("Etc/")
        assert o["label"]
