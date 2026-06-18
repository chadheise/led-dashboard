"""Pre-game start time formatting respects the configured viewer timezone.

Regression coverage for a World Cup display bug: a 1:00 AM UTC kickoff
(6:00 PM the previous day in Los Angeles) was shown as "1:00 AM" — the raw
UTC time with no indication it wasn't the viewer's local time.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from apps.sports.model import _compose_status


def _pre_game(**extra):
    game = {
        "state": "pre",
        "sport": "soccer",
        "series_summary": None,
        "start_time": "2026-06-13T01:00Z",  # 6:00 PM PDT on 6/12
    }
    game.update(extra)
    return game


def test_pregame_time_converted_to_viewer_timezone():
    now = datetime.datetime(2026, 6, 12, 12, 0, tzinfo=datetime.timezone.utc)
    status = _compose_status(
        _pre_game(), tz=ZoneInfo("America/Los_Angeles"), time_format="12h", now=now
    )
    assert status == "6:00 PM"


def test_pregame_time_falls_back_to_labeled_utc_without_viewer_timezone():
    now = datetime.datetime(2026, 6, 12, 12, 0, tzinfo=datetime.timezone.utc)
    status = _compose_status(_pre_game(), tz=None, time_format="12h", now=now)
    assert status == "1:00 AM UTC"
