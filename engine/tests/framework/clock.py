"""Deterministic clock for snapshot tests.

Several apps call ``datetime.now()`` inside ``render_frame`` (weather hourly
filtering, world-clock times, countdown deltas). Freezing the ``datetime``
name *in the app's module* pins those reads to a fixed instant without
touching the app code.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from unittest import mock

# The fixed instant every time-dependent snapshot uses (UTC).
FIXED_NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _frozen_datetime_class(fixed: datetime) -> type[datetime]:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return fixed.replace(tzinfo=None)
            return fixed.astimezone(tz)

        @classmethod
        def utcnow(cls):  # type: ignore[override]
            return fixed.replace(tzinfo=None)

    return FrozenDateTime


@contextmanager
def frozen_time(module_datetime_path: str, fixed: datetime = FIXED_NOW) -> Iterator[None]:
    """Patch e.g. ``"apps.weather.app.datetime"`` so ``datetime.now()`` is fixed."""
    with mock.patch(module_datetime_path, _frozen_datetime_class(fixed)):
        yield
