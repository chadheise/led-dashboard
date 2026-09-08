"""``favorite_teams`` narrows the league it names, not the whole fetch.

A favorite is stored as ``"<league id>:<abbr>"`` and the team picker only
offers base leagues, so favoriting a college team yields
``college-football:UGA``. ``fetch_scores`` used to apply favorites as a
filter over the *merged* result of every league, which silently emptied
every other selected league: a module set to "NCAAF Top 25 + a few favorite
teams" showed only the favorites' games, with the whole top-25 selection
(past and upcoming) dropped.
"""

from __future__ import annotations

import asyncio
from typing import Any


def _game(game_id: str, league: str, away: str, home: str) -> dict[str, Any]:
    return {"id": game_id, "league": league, "away_abbr": away, "home_abbr": home}


def _stub_leagues(lib: Any, by_league: dict[str, list[dict[str, Any]]]) -> None:
    """Replace the network fetch with canned per-league games."""

    async def _fetch_league(
        _client: Any, league: str, days_ahead: int = 1, days_behind: int = 1
    ) -> list[dict[str, Any]]:
        return [dict(g) for g in by_league.get(league, [])]

    lib._fetch_league = _fetch_league
    lib._get_client = lambda: None


def _fetch(by_league: dict[str, list[dict[str, Any]]], leagues: list[str],
           favorites: list[str] | None) -> list[str]:
    from libraries.espn_sports.library import ESPNSportsLibrary

    lib = ESPNSportsLibrary({})
    _stub_leagues(lib, by_league)
    games = asyncio.run(lib.fetch_scores(leagues, favorite_teams=favorites))
    return [g["id"] for g in games]


def test_favorites_do_not_empty_other_selected_leagues() -> None:
    by_league = {
        "ncaaf-top25": [
            _game("top25_a", "ncaaf-top25", "OSU", "MICH"),
            _game("top25_b", "ncaaf-top25", "BAMA", "LSU"),
        ],
        # Implicitly fetched because a favorite lives in this league.
        "college-football": [
            _game("uga_game", "college-football", "UGA", "VAN"),
            _game("other_cfb", "college-football", "DUKE", "WAKE"),
        ],
    }
    ids = _fetch(
        by_league,
        ["ncaaf-top25", "college-football"],
        ["college-football:UGA"],
    )
    # Top-25 games survive in full; the favorite's league is trimmed to UGA.
    assert ids == ["top25_a", "top25_b", "uga_game"]


def test_favorites_still_filter_their_own_league() -> None:
    by_league = {
        "nfl": [
            _game("kc_game", "nfl", "KC", "LV"),
            _game("no_fav", "nfl", "DEN", "MIA"),
        ]
    }
    assert _fetch(by_league, ["nfl"], ["nfl:KC"]) == ["kc_game"]


def test_favorites_in_one_league_leave_another_league_untouched() -> None:
    by_league = {
        "nfl": [
            _game("kc_game", "nfl", "KC", "LV"),
            _game("no_fav", "nfl", "DEN", "MIA"),
        ],
        "mlb": [_game("mlb_game", "mlb", "BOS", "NYY")],
    }
    ids = _fetch(by_league, ["nfl", "mlb"], ["nfl:KC"])
    assert ids == ["kc_game", "mlb_game"]


def test_no_favorites_returns_every_league_in_full() -> None:
    by_league = {
        "nfl": [_game("a", "nfl", "KC", "LV")],
        "mlb": [_game("b", "mlb", "BOS", "NYY")],
    }
    assert _fetch(by_league, ["nfl", "mlb"], None) == ["a", "b"]


def test_failed_league_does_not_shift_favorite_filtering() -> None:
    """One league raising must not misalign the per-league favorite filter."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    async def _fetch_league(
        _client: Any, league: str, days_ahead: int = 1, days_behind: int = 1
    ) -> list[dict[str, Any]]:
        if league == "ncaaf-top25":
            raise RuntimeError("ESPN down")
        return [
            _game("uga_game", "college-football", "UGA", "VAN"),
            _game("other_cfb", "college-football", "DUKE", "WAKE"),
        ]

    lib = ESPNSportsLibrary({})
    lib._fetch_league = _fetch_league
    lib._get_client = lambda: None
    games = asyncio.run(
        lib.fetch_scores(
            ["ncaaf-top25", "college-football"],
            favorite_teams=["college-football:UGA"],
        )
    )
    assert [g["id"] for g in games] == ["uga_game"]


def test_matches_favorites_spans_league_variants() -> None:
    """A favorite stored against the base league still matches its own game
    when that game arrived via a variant of the same league (so the live-game
    spotlight doesn't skip a ranked favorite)."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    top25_uga = _game("uga_ranked", "ncaaf-top25", "UGA", "BAMA")
    assert ESPNSportsLibrary._matches_favorites(top25_uga, ["college-football:UGA"])
    assert not ESPNSportsLibrary._matches_favorites(top25_uga, ["college-football:OSU"])
    assert not ESPNSportsLibrary._matches_favorites(top25_uga, ["nfl:UGA"])
