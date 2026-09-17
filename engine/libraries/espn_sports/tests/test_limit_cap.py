"""``limit`` must stay inside the value ESPN honours.

The endpoint accepts `limit` up to 500. Above that it neither clamps nor
rejects: it ignores the parameter and serves its small default, so a league
comes back looking like it has a couple dozen games on when it has hundreds.
Measured against the live endpoint - one day of college football returns 80
events at limit=500 and 25 at limit=510.

This is a plain bound on the constant: there is no runtime probe to test,
because an over-cap value doesn't fail in a way the fetch could detect.
"""

from __future__ import annotations

import asyncio
from typing import Any

from libraries.espn_sports.library import _SCOREBOARD_EVENT_LIMIT, ESPNSportsLibrary

# The largest value the endpoint honours.
_MAX_ACCEPTED_LIMIT = 500


def test_limit_constant_is_within_the_endpoint_cap() -> None:
    assert 100 <= _SCOREBOARD_EVENT_LIMIT <= _MAX_ACCEPTED_LIMIT


def test_limit_is_sent_on_every_scoreboard_request() -> None:
    """Without it the response is truncated to a couple dozen events."""
    lib = ESPNSportsLibrary({})
    calls: list[dict[str, str]] = []

    async def record(_client: Any, _url: str, params: dict[str, str]) -> dict[str, Any]:
        calls.append(dict(params))
        return {"events": []}

    lib._get_scoreboard = record  # type: ignore[method-assign]
    asyncio.run(lib._fetch_league(object(), "nfl", 30, 1))

    assert calls, "expected at least one scoreboard request"
    assert all(
        int(c["limit"]) == _SCOREBOARD_EVENT_LIMIT <= _MAX_ACCEPTED_LIMIT for c in calls
    )
