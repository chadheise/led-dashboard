"""Text app snapshot suite: static centred vs scrolling, font sizes, colors."""

from __future__ import annotations

from typing import Any

from tests.snaptest import harness


def _mid_scroll(app: Any) -> None:
    # Place the marquee mid-scroll so the frame shows readable text instead of
    # the first 2px entering from the right edge.
    app._marquee._offset = 12.0


def _fixtures() -> dict[str, dict[str, Any]]:
    return {
        "static_small": {
            "config": {"message": "HELLO", "scroll": False, "font_size": 12, "color": "#FFD700"},
            "seed": None,
        },
        "static_large": {
            "config": {"message": "42", "scroll": False, "font_size": 48, "color": "#FFFFFF"},
            "seed": None,
        },
        "static_overflow": {
            "config": {
                "message": "A MESSAGE FAR TOO LONG TO FIT", "scroll": False,
                "font_size": 15, "color": "#66CCFF",
            },
            "seed": None,
        },
        "scrolling": {
            "config": {"message": "BREAKING NEWS", "scroll": True, "font_size": 22, "color": "#FF6B6B"},
            "seed": _mid_scroll,
        },
    }


def _register() -> None:
    from apps.text.app import TextApp

    harness.register(
        harness.SnapshotSuite(
            app_id="text",
            fixtures=_fixtures(),
            sizes=harness.CORE_SIZES,
            render=harness.app_case_render(TextApp),
        )
    )


_register()
