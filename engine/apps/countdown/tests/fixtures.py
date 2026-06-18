"""Countdown snapshot suite: custom event, holiday icon, granularities, arrived.

The app's ``datetime.now()`` is frozen to ``clock.FIXED_NOW`` and the seeded
targets are fixed instants, so the rendered deltas never change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tests.framework import harness
from tests.framework.clock import FIXED_NOW

_JULY4 = datetime(2026, 7, 4, 0, 0, tzinfo=timezone.utc)
_HALLOWEEN = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
_PAST = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)

assert _PAST < FIXED_NOW < _JULY4  # fixture sanity


def _seed(name: str, target: datetime, icon_id: str | None = None):
    def seed(app: Any) -> None:
        app._event_name = name
        app._target_dt = target
        app._icon_id = icon_id
        app._resolved = True
        app._fetched_once = True

    return seed


def _fixtures() -> dict[str, dict[str, Any]]:
    return {
        "custom_event": {
            "config": {"units": ["days", "hours", "minutes"]},
            "seed": _seed("Lake Trip", _JULY4),
        },
        "holiday_icon": {
            "config": {"units": ["days", "hours", "minutes"]},
            "seed": _seed("Halloween", _HALLOWEEN, icon_id="pumpkin"),
        },
        "hours_minutes_seconds": {
            "config": {"units": ["hours", "minutes", "seconds"]},
            "seed": _seed("Launch", _JULY4),
        },
        "arrived": {
            "config": {},
            "seed": _seed("Graduation", _PAST),
        },
        "unconfigured": {
            "config": {},
            "seed": lambda app: setattr(app, "_fetched_once", True),
        },
    }


def _register() -> None:
    from apps.countdown.app import CountdownApp

    harness.register(
        harness.SnapshotSuite(
            app_id="countdown",
            fixtures=_fixtures(),
            sizes=harness.CORE_SIZES,
            render=harness.app_case_render(
                CountdownApp, freeze_datetime="apps.countdown.app.datetime"
            ),
        )
    )


_register()
