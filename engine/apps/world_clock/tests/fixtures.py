"""World clock snapshot suite: cell layouts at 2 and 5 cities, empty state.

The app's ``datetime.now()`` is frozen to ``clock.FIXED_NOW`` so every zone's
displayed time (including day-offset markers) is fixed.
"""

from __future__ import annotations

from typing import Any

from tests.framework import harness

# Entries are (timezone, label, color); None color renders in the default
# text color so these golden snapshots are unaffected by per-city colors.
_FIVE = [
    ("America/Chicago", "Chicago", None),
    ("Europe/London", "London", None),
    ("Asia/Tokyo", "Tokyo", None),
    ("Australia/Sydney", "Sydney", None),
    ("Pacific/Honolulu", "Honolulu", None),
]


def _seed(entries: list[tuple[str, str, str | None]]):
    def seed(app: Any) -> None:
        app._entries = list(entries)
        app._home_tz = entries[0][0] if entries else None
        app._fetched_once = True

    return seed


def _fixtures() -> dict[str, dict[str, Any]]:
    return {
        "five_cities": {"config": {}, "seed": _seed(_FIVE)},
        "two_cities": {"config": {}, "seed": _seed(_FIVE[:1] + _FIVE[2:3])},
        "single_city": {"config": {}, "seed": _seed(_FIVE[2:3])},
        "empty": {"config": {}, "seed": _seed([])},
    }


def _register() -> None:
    from apps.world_clock.app import WorldClockApp

    harness.register(
        harness.SnapshotSuite(
            app_id="world_clock",
            fixtures=_fixtures(),
            sizes=harness.CORE_SIZES,
            render=harness.app_case_render(
                WorldClockApp, freeze_datetime="apps.world_clock.app.datetime"
            ),
        )
    )


_register()
