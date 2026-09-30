"""``/teams`` paging must terminate even when ESPN ignores ``page``.

The US league endpoints honour ``page`` and answer an empty page past the
end. The soccer competition endpoints don't: they serve the whole roster on
every page, at any ``limit`` (``fifa.friendly`` returns ~190 sides). A loop
that only stops on a short page therefore never stops there - which is what
hung the international-football team pickers in the sports settings UI, since
those composites fetch a dozen-plus competitions before returning anything.

So the loop stops on a page that adds no team it hasn't already seen, and a
hard page cap backstops that.
"""

from __future__ import annotations

import asyncio
from typing import Any

from libraries.espn_sports.library import (
    _MAX_TEAM_PAGES,
    _TEAM_PAGE_SIZE,
    ESPNSportsLibrary,
)


def _roster(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [
        {
            "team": {
                "id": str(start + i),
                "abbreviation": f"T{start + i}",
                "displayName": f"Team {start + i:04d}",
                "logos": [{"href": "https://espn/logo.png"}],
                "color": "000000",
            }
        }
        for i in range(count)
    ]


def _serve(pages, monkeypatch) -> list[int]:
    """Install a fake httpx client answering ``/teams`` from ``pages``.

    ``pages`` is called with the requested page number. Returns the list of
    page numbers actually asked for.
    """
    asked: list[int] = []

    class _Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def json(self) -> dict[str, Any]:
            return self._payload

    class _Client:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def get(self, _url: str, params: dict[str, Any]) -> _Response:
            page = int(params["page"])
            asked.append(page)
            teams = pages(page)
            return _Response({"sports": [{"leagues": [{"teams": teams}]}]})

    import libraries.espn_sports.library as lib_mod

    monkeypatch.setattr(lib_mod.httpx, "AsyncClient", _Client)
    return asked


def test_endpoint_that_ignores_page_is_read_once(monkeypatch) -> None:
    """The soccer case: the same full roster on every page."""
    full = _roster(193)
    asked = _serve(lambda _page: full, monkeypatch)

    lib = ESPNSportsLibrary({})
    teams = asyncio.run(lib._fetch_espn_teams("soccer", "fifa.friendly"))

    assert len(teams) == 193
    # Page 2 proves nothing new is coming; page 3 is never asked for.
    assert asked == [1, 2]
    assert len({t["abbreviation"] for t in teams}) == 193


def test_paginated_endpoint_still_reads_every_page(monkeypatch) -> None:
    """The US-league case: ``page`` is honoured, so all pages are collected."""
    pages = {
        1: _roster(_TEAM_PAGE_SIZE, start=0),
        2: _roster(_TEAM_PAGE_SIZE, start=_TEAM_PAGE_SIZE),
        3: _roster(7, start=2 * _TEAM_PAGE_SIZE),
    }
    asked = _serve(lambda page: pages.get(page, []), monkeypatch)

    lib = ESPNSportsLibrary({})
    teams = asyncio.run(lib._fetch_espn_teams("football", "nfl"))

    assert asked == [1, 2, 3]
    assert len(teams) == 2 * _TEAM_PAGE_SIZE + 7


def test_page_count_is_capped(monkeypatch) -> None:
    """Backstop: a page that keeps yielding new teams still can't run away."""
    asked = _serve(lambda page: _roster(_TEAM_PAGE_SIZE, start=page * _TEAM_PAGE_SIZE), monkeypatch)

    lib = ESPNSportsLibrary({})
    teams = asyncio.run(lib._fetch_espn_teams("soccer", "endless"))

    assert asked == list(range(1, _MAX_TEAM_PAGES + 1))
    assert len(teams) == _MAX_TEAM_PAGES * _TEAM_PAGE_SIZE


def test_composite_league_team_list_terminates(monkeypatch) -> None:
    """End to end: an ``intl-*`` picker resolves instead of hanging."""
    full = _roster(193)
    _serve(lambda _page: full, monkeypatch)

    lib = ESPNSportsLibrary({})
    teams = asyncio.run(
        asyncio.wait_for(lib._fetch_teams_fresh("intl-men"), timeout=10)
    )

    assert len(teams) == 193
