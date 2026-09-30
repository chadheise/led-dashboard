"""National teams: composite leagues over every competition a side plays in.

A national team isn't in one ESPN league - the USWNT's year is friendlies,
the SheBelieves Cup, a Gold Cup, a World Cup, each its own scoreboard. The
``intl-men`` / ``intl-women`` entries fetch all of a composite's competitions
and label the games with the composite id, so one favorite
(``intl-women:USA``) follows the team everywhere it plays. Men's and women's
sides share abbreviations (both are ``USA``), so they are kept apart by being
separate composites.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from libraries.espn_sports.library import _LEAGUE_BY_ID, ESPNSportsLibrary, ScoresUnavailable


def _event(event_id: str, away: str, home: str) -> dict[str, Any]:
    start = datetime.now(timezone.utc) + timedelta(hours=3)
    return {
        "id": event_id,
        "status": {"type": {"state": "pre", "shortDetail": "Scheduled"}},
        "competitions": [
            {
                "date": start.strftime("%Y-%m-%dT%H:%MZ"),
                "competitors": [
                    {"homeAway": "away", "team": {"id": "1", "abbreviation": away,
                                                  "logo": "https://espn/logo.png"}},
                    {"homeAway": "home", "team": {"id": "2", "abbreviation": home,
                                                  "logo": "https://espn/logo.png"}},
                ],
            }
        ],
    }


def _library(by_competition: dict[str, list[dict[str, Any]] | Exception]) -> tuple[
    ESPNSportsLibrary, list[str]
]:
    """A library whose scoreboard requests are served per ESPN league path.

    Competitions not listed answer with no events, like an off-season
    tournament does; an ``Exception`` value makes that competition fail.
    """
    lib = ESPNSportsLibrary({})
    asked: list[str] = []

    async def _get_scoreboard(_client: Any, url: str, _params: dict[str, str]) -> dict[str, Any]:
        comp = url.rsplit("/", 2)[-2]
        asked.append(comp)
        served = by_competition.get(comp, [])
        if isinstance(served, Exception):
            raise served
        return {"events": served}

    lib._get_scoreboard = _get_scoreboard  # type: ignore[method-assign]
    lib._get_client = lambda: None  # type: ignore[method-assign]
    return lib, asked


def test_composites_are_listed_with_flags_and_competitions() -> None:
    for league_id in ("intl-men", "intl-women"):
        entry = _LEAGUE_BY_ID[league_id]
        assert entry["sport"] == "soccer"
        assert entry["use_flags"]
        assert entry["competitions"]
    assert "fifa.world" in _LEAGUE_BY_ID["intl-men"]["competitions"]
    assert "fifa.wwc" in _LEAGUE_BY_ID["intl-women"]["competitions"]
    # A men's tournament must never pull in women's games, and vice versa.
    assert not set(_LEAGUE_BY_ID["intl-men"]["competitions"]) & set(
        _LEAGUE_BY_ID["intl-women"]["competitions"]
    )


def test_composite_fetches_every_competition_and_labels_games() -> None:
    lib, asked = _library({
        "fifa.friendly.w": [_event("f1", "BRA", "USA")],
        "fifa.shebelieves": [_event("s1", "USA", "JPN")],
    })
    games = asyncio.run(lib._fetch_league(None, "intl-women", 30, 1))

    assert set(asked) == set(_LEAGUE_BY_ID["intl-women"]["competitions"])
    by_id = {g["id"]: g for g in games}
    assert set(by_id) == {"f1", "s1"}
    assert by_id["f1"]["league"] == "intl-women"
    assert by_id["f1"]["competition"] == "fifa.friendly.w"
    assert by_id["s1"]["competition"] == "fifa.shebelieves"
    assert by_id["f1"]["gender"] == "women"
    # National flags, not ESPN's crest.
    assert by_id["f1"]["home_logo_url"] == "https://flagcdn.com/w80/us.png"
    assert by_id["f1"]["away_logo_url"] == "https://flagcdn.com/w80/br.png"


def test_a_failing_competition_does_not_take_the_others_down() -> None:
    lib, _ = _library({
        "fifa.friendly": [_event("f1", "USA", "MEX")],
        "concacaf.gold": RuntimeError("HTTP 400"),
    })
    games = asyncio.run(lib._fetch_league(None, "intl-men", 30, 1))
    assert [g["id"] for g in games] == ["f1"]


def test_composite_is_unavailable_only_when_every_competition_fails() -> None:
    comps = _LEAGUE_BY_ID["intl-women"]["competitions"]
    lib, _ = _library({c: RuntimeError("down") for c in comps})
    with pytest.raises(ScoresUnavailable):
        asyncio.run(lib._fetch_league(None, "intl-women", 30, 1))


def test_same_match_in_two_competitions_is_listed_once() -> None:
    lib, _ = _library({
        "fifa.world": [_event("wc1", "USA", "ENG")],
        "fifa.worldq.concacaf": [_event("wc1", "USA", "ENG")],
    })
    games = asyncio.run(lib._fetch_league(None, "intl-men", 30, 1))
    assert [g["id"] for g in games] == ["wc1"]


def test_womens_favorite_shows_only_that_teams_games() -> None:
    """``intl-women:USA`` brings in the USWNT - not the USMNT, and not the
    rest of the women's international slate."""
    lib, asked = _library({
        "fifa.friendly.w": [_event("w_usa", "BRA", "USA"), _event("w_other", "ESP", "GER")],
        "fifa.friendly": [_event("m_usa", "USA", "MEX")],
    })
    games = asyncio.run(lib.fetch_scores([], favorite_teams=["intl-women:USA"], days_ahead=30))

    assert [g["id"] for g in games] == ["w_usa"]
    assert "fifa.friendly" not in asked


def test_mens_and_womens_favorites_together() -> None:
    lib, _ = _library({
        "fifa.friendly.w": [_event("w_usa", "BRA", "USA")],
        "fifa.friendly": [_event("m_usa", "USA", "MEX"), _event("m_other", "FRA", "ITA")],
    })
    games = asyncio.run(lib.fetch_scores(
        [], favorite_teams=["intl-men:USA", "intl-women:USA"], days_ahead=30,
    ))
    assert sorted(g["id"] for g in games) == ["m_usa", "w_usa"]


def test_national_favorite_matches_its_game_from_a_selected_member_competition() -> None:
    """With the World Cup selected on its own, a World Cup game comes back
    labelled ``fifa.world``; it is still the favorited men's team's game."""
    game = {"league": "fifa.world", "competition": "fifa.world",
            "home_abbr": "USA", "away_abbr": "ENG"}
    assert ESPNSportsLibrary._matches_favorites(game, ["intl-men:USA"])
    assert not ESPNSportsLibrary._matches_favorites(game, ["intl-women:USA"])
    assert not ESPNSportsLibrary._matches_favorites(game, ["intl-men:MEX"])


def test_national_teams_are_merged_across_competitions() -> None:
    lib = ESPNSportsLibrary({})
    rosters = {
        "fifa.friendly.w": [
            {"id": "660", "abbreviation": "USA", "display_name": "United States"},
            {"id": "205", "abbreviation": "BRA", "display_name": "Brazil"},
        ],
        "fifa.shebelieves": [
            {"id": "660", "abbreviation": "USA", "display_name": "United States"},
            {"id": "627", "abbreviation": "JPN", "display_name": "Japan"},
        ],
    }

    async def _fetch_espn_teams(_sport: str, league_path: str) -> list[dict[str, Any]]:
        if league_path == "fifa.wwc":
            raise RuntimeError("down")
        return [dict(t) for t in rosters.get(league_path, [])]

    lib._fetch_espn_teams = _fetch_espn_teams  # type: ignore[method-assign]
    teams = asyncio.run(lib._fetch_teams_fresh("intl-women"))

    assert [t["abbreviation"] for t in teams] == ["BRA", "JPN", "USA"]
    assert teams[2]["logo_url"] == "https://flagcdn.com/w80/us.png"
