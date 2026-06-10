"""Stocks snapshot suite: every display mode at every size.

Covers marquee (1 and 2 streams/rows), paginate (1-up rows, N-up splits),
chart mode (single and split, both directions), and the loading state.
Quotes, logos, and chart series are deterministic fixtures — no Yahoo calls.
"""

from __future__ import annotations

from typing import Any

from tests.snaptest import harness
from tests.snaptest.logos import make_fixture_logo

_QUOTES = [
    {"symbol": "AAPL", "price": 150.23, "change_pct": 2.5, "dollar_change": 3.75},
    {"symbol": "MSFT", "price": 380.45, "change_pct": -1.2, "dollar_change": -4.60},
    {"symbol": "GOOGL", "price": 2801.10, "change_pct": 0.8, "dollar_change": 22.15},
    {"symbol": "TSLA", "price": 99.50, "change_pct": -3.4, "dollar_change": -3.50},
]

_INDEX_QUOTES = [
    {"symbol": "^GSPC", "price": 6123.45, "change_pct": 0.4, "dollar_change": 24.31},
    {"symbol": "^IXIC", "price": 20987.65, "change_pct": -0.6, "dollar_change": -126.70},
]

_LOGO_COLORS = {"AAPL": "a2aaad", "MSFT": "00a4ef", "GOOGL": "4285f4", "TSLA": "cc0000"}


def _closes(base: float, pct: float) -> list[float]:
    # A deterministic wiggly series ending at the current price.
    deltas = [0, 3, -2, 5, 1, -4, 2, 6, -1, 3, -3, 4, 0, 2, -2, 5]
    start = base / (1 + pct / 100)
    step = (base - start) / len(deltas)
    return [round(start + i * step + d * base / 400, 2) for i, d in enumerate(deltas)] + [base]


def _seed(streams: list[list[dict[str, Any]]], *, charts: bool = False):
    def seed(app: Any) -> None:
        app._stream_quotes = [[dict(q) for q in s] for s in streams]
        app._logos = {
            q["symbol"]: make_fixture_logo(q["symbol"], _LOGO_COLORS.get(q["symbol"], "888888"))
            for s in streams
            for q in s
        }
        if charts:
            app._chart_data = {
                q["symbol"]: {
                    "symbol": q["symbol"],
                    "current_price": q["price"],
                    "change_pct": q["change_pct"],
                    "dollar_change": q["dollar_change"],
                    "closes": _closes(q["price"], q["change_pct"]),
                }
                for s in streams
                for q in s
            }

    return seed


def _streams_config(streams: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Config "streams" entries matching the seeded quote rows — layout (row
    count, text sizing) is derived from the config, not the seeded data."""
    return [
        {"source": "custom", "symbols": [q["symbol"] for q in s]} for s in streams
    ]


def _fixtures() -> dict[str, dict[str, Any]]:
    one_stream = [_QUOTES]
    two_streams = [_QUOTES[:2], _INDEX_QUOTES]
    one_cfg = _streams_config(one_stream)
    two_cfg = _streams_config(two_streams)
    return {
        "marquee_1row": {
            "config": {"display_mode": "marquee", "show_icons": True, "streams": one_cfg},
            "seed": _seed(one_stream),
        },
        "marquee_2row": {
            "config": {"display_mode": "marquee", "show_icons": True, "streams": two_cfg},
            "seed": _seed(two_streams),
        },
        "marquee_no_icons": {
            "config": {"display_mode": "marquee", "show_icons": False, "streams": one_cfg},
            "seed": _seed(one_stream),
        },
        "paginate_1up": {
            "config": {
                "display_mode": "paginate", "stocks_per_screen": 1,
                "show_icons": True, "streams": one_cfg,
            },
            "seed": _seed(one_stream),
        },
        "paginate_1up_2rows": {
            "config": {
                "display_mode": "paginate", "stocks_per_screen": 1,
                "show_icons": True, "streams": two_cfg,
            },
            "seed": _seed(two_streams),
        },
        "paginate_2up_horizontal": {
            "config": {
                "display_mode": "paginate", "stocks_per_screen": 2,
                "chart_split_direction": "horizontal", "show_icons": True, "streams": one_cfg,
            },
            "seed": _seed(one_stream),
        },
        "paginate_4up_vertical": {
            "config": {
                "display_mode": "paginate", "stocks_per_screen": 4,
                "chart_split_direction": "vertical", "show_icons": True, "streams": one_cfg,
            },
            "seed": _seed(one_stream),
        },
        "chart_1up": {
            "config": {
                "display_mode": "chart", "stocks_per_screen": 1,
                "show_icons": True, "streams": one_cfg,
            },
            "seed": _seed(one_stream, charts=True),
        },
        "chart_2up_horizontal": {
            "config": {
                "display_mode": "chart", "stocks_per_screen": 2,
                "chart_split_direction": "horizontal", "show_icons": True, "streams": one_cfg,
            },
            "seed": _seed(one_stream, charts=True),
        },
        "chart_2up_vertical": {
            "config": {
                "display_mode": "chart", "stocks_per_screen": 2,
                "chart_split_direction": "vertical", "show_icons": True, "streams": one_cfg,
            },
            "seed": _seed(one_stream, charts=True),
        },
        "loading": {"config": {"display_mode": "marquee"}, "seed": None},
    }


def _register() -> None:
    from apps.stocks.app import StocksApp

    harness.register(
        harness.SnapshotSuite(
            app_id="stocks",
            fixtures=_fixtures(),
            sizes=harness.CORE_SIZES,
            render=harness.app_case_render(StocksApp),
        )
    )


_register()
