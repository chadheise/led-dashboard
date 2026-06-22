"""Unit tests for the world_clock config handling: per-city colors, the
any-city typeahead options, and backward compatibility with the legacy
bare-timezone city list."""

from __future__ import annotations

import asyncio
from typing import Any

from canvas.simulator import SimulatorCanvas

from apps.world_clock.app import WorldClockApp, _parse_city_item


def _make_app(config: dict[str, Any]) -> WorldClockApp:
    async def _noop(_frame: bytes) -> None:
        pass

    return WorldClockApp({**config}, SimulatorCanvas(128, 64, _noop), {}, {})


# ── _parse_city_item ─────────────────────────────────────────────────────────


def test_parse_city_item_object_with_name():
    # Any-city items carry the chosen city name (which can differ from the
    # timezone's representative city).
    assert _parse_city_item(
        {"name": "Boston, United States", "timezone": "America/New_York", "color": "#FF0000"}
    ) == ("America/New_York", "Boston, United States", "#FF0000")


def test_parse_city_item_object_without_name_or_color():
    assert _parse_city_item({"timezone": "Asia/Tokyo"}) == ("Asia/Tokyo", None, None)


def test_parse_city_item_legacy_string():
    # Instances saved before per-city colors stored a bare timezone string.
    assert _parse_city_item("America/Chicago") == ("America/Chicago", None, None)


def test_parse_city_item_garbage():
    assert _parse_city_item(None) == (None, None, None)
    assert _parse_city_item({"color": "#FFFFFF"}) == (None, None, None)
    assert _parse_city_item("") == (None, None, None)


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


def test_fetch_data_uses_stored_name_over_timezone_city():
    # "Boston" shares America/New_York with New York, but the configured name
    # must be shown on screen, not the timezone's representative city.
    app = _make_app({
        "show_local": False,
        "cities": [{"name": "Boston, United States", "timezone": "America/New_York"}],
    })
    asyncio.run(app.fetch_data())

    assert app._entries == [("America/New_York", "Boston, United States", None)]


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


# ── Local / default color ────────────────────────────────────────────────────


def _has_color(app: WorldClockApp, want: tuple[int, int, int]) -> bool:
    px = list(app.canvas._pixels)
    triples = zip(px[0::3], px[1::3], px[2::3])
    return any(
        abs(r - want[0]) < 40 and abs(g - want[1]) < 40 and abs(b - want[2]) < 40
        for r, g, b in triples
    )


def test_local_color_is_the_fallback_tint_for_uncolored_cities():
    # A city saved without its own color renders in the configured local color.
    app = _make_app({
        "show_local": False,
        "local_color": "#00FF00",
        "cities": [{"timezone": "Asia/Tokyo"}],
    })
    asyncio.run(app.fetch_data())
    asyncio.run(app.render_frame())
    assert _has_color(app, (0, 255, 0))


def test_local_color_takes_precedence_over_legacy_text_color():
    # Old instances stored the single color under `text_color`; a newer
    # `local_color` wins when both are present.
    app = _make_app({
        "show_local": False,
        "text_color": "#FF0000",
        "local_color": "#00FF00",
        "cities": [{"timezone": "Asia/Tokyo"}],
    })
    asyncio.run(app.fetch_data())
    asyncio.run(app.render_frame())
    assert _has_color(app, (0, 255, 0))
    assert not _has_color(app, (255, 0, 0))


def test_legacy_text_color_still_applies_when_no_local_color():
    app = _make_app({
        "show_local": False,
        "text_color": "#FF0000",
        "cities": [{"timezone": "Asia/Tokyo"}],
    })
    asyncio.run(app.fetch_data())
    asyncio.run(app.render_frame())
    assert _has_color(app, (255, 0, 0))
