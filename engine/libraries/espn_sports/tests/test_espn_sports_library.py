"""ESPN scoreboard responses with null/missing fields must not crash a fetch.

ESPN returns ``"curatedRank": null`` (rather than omitting the key) for
international/World Cup teams, and can return ``"status": null`` for some
events. ``dict.get(key, default)`` only falls back to ``default`` when the
key is *absent*, not when its value is ``null`` — so naive
``.get("curatedRank", {}).get("current")`` chains raise ``AttributeError``
on these payloads. A single such event used to crash ``_fetch_league`` for
the *whole* league, which ``fetch_scores``'s ``return_exceptions=True`` +
``isinstance(result, list)`` filter then silently dropped, leaving zero
games for that league for the fetch cycle.
"""

from __future__ import annotations

import asyncio
from typing import Any


class _FakeResponse:
    status_code = 200

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._data


class _FakeClient:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    async def get(self, url: str, params: dict[str, str] | None = None) -> _FakeResponse:
        return _FakeResponse(self._data)


def _competitor(home_away: str, abbr: str, score: str = "0", curated_rank: Any = None, team_id: str = "") -> dict[str, Any]:
    return {
        "homeAway": home_away,
        "team": {"id": team_id, "abbreviation": abbr, "displayName": abbr},
        "score": score,
        "curatedRank": curated_rank,
    }


def test_fetch_league_handles_null_curated_rank_and_status() -> None:
    from libraries.espn_sports.library import ESPNSportsLibrary

    data = {
        "events": [
            {
                "id": "1",
                "status": None,
                "competitions": [
                    {
                        "competitors": [
                            _competitor("home", "FRA"),
                            _competitor("away", "GER"),
                        ],
                    }
                ],
            }
        ]
    }

    games = asyncio.run(ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world"))

    assert len(games) == 1
    game = games[0]
    assert game["home_rank"] is None
    assert game["away_rank"] is None
    assert game["status"] == "Scheduled"
    assert game["state"] == "pre"


def test_fetch_league_skips_malformed_event_but_returns_others() -> None:
    from libraries.espn_sports.library import ESPNSportsLibrary

    data = {
        "events": [
            # Malformed: competitors are not dicts, so `.get("homeAway")` blows up.
            {
                "id": "bad",
                "status": {"type": {"shortDetail": "Final", "state": "post"}},
                "competitions": [{"competitors": [1, 2]}],
            },
            # Well-formed event after the malformed one.
            {
                "id": "good",
                "status": {"type": {"shortDetail": "Final", "state": "post"}},
                "competitions": [
                    {
                        "competitors": [
                            _competitor("home", "BOS", score="3"),
                            _competitor("away", "NYY", score="1"),
                        ],
                    }
                ],
            },
        ]
    }

    games = asyncio.run(ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "mlb"))

    assert [g["id"] for g in games] == ["good"]


def _soccer_event(home_abbr: str, away_abbr: str, home_id: str, away_id: str,
                  home_score: str, away_score: str, details: list[dict[str, Any]]) -> dict[str, Any]:
    """Minimal ESPN event payload for a live soccer game with goal details."""
    return {
        "id": "99",
        "status": {"type": {"shortDetail": "90'", "state": "in"}},
        "competitions": [
            {
                "competitors": [
                    _competitor("home", home_abbr, score=home_score, team_id=home_id),
                    _competitor("away", away_abbr, score=away_score, team_id=away_id),
                ],
                "details": details,
            }
        ],
    }


def _goal_detail(team_id: str, clock: str, type_text: str = "Goal") -> dict[str, Any]:
    return {
        "type": {"text": type_text},
        "clock": {"displayValue": clock},
        "team": {"id": team_id},
    }


def test_own_goal_goes_to_benefiting_team() -> None:
    """ESPN's team.id in a goal detail always points to the benefiting team,
    even for own goals. An OG committed by AUS (home) benefits USA (away), so
    ESPN sets team.id = USA's away_id. The goal must land in away_goals.
    Bug: the OG assignment was previously inverted, inflating the committing
    team's displayed score via the max(score, goal_count) reconciliation."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    home_id, away_id = "10", "20"
    # AUS (home) commits own goal → USA (away) benefits → ESPN: team.id = away_id
    data = {"events": [_soccer_event(
        "AUS", "USA", home_id, away_id,
        home_score="0", away_score="2",
        details=[
            _goal_detail(away_id, "34'"),              # USA regular goal
            _goal_detail(away_id, "55'", "Own Goal"),  # AUS own goal; ESPN team.id = USA (benefiting)
            _goal_detail(away_id, "78'"),              # USA regular goal
        ],
    )]}

    games = asyncio.run(ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world"))

    assert len(games) == 1
    game = games[0]
    # All 3 goals (2 regular + 1 OG) benefit USA (away); AUS has no goals.
    assert game["away_goals"] == ["34'", "55'(OG)", "78'"]
    assert game["home_goals"] == []


def _shootout_event(
    short_detail: str, period: int = 0, state: str = "in", name: str = ""
) -> dict[str, Any]:
    """Soccer event whose status text alone should mark it a live shootout."""
    return {
        "id": "77",
        "status": {
            "period": period,
            "type": {"name": name, "shortDetail": short_detail, "state": state},
        },
        "competitions": [
            {
                "competitors": [
                    _competitor("home", "AUS", score="1", team_id="10"),
                    _competitor("away", "EGY", score="1", team_id="20"),
                ],
                "details": [],
            }
        ],
    }


def test_live_shootout_detected_from_aet_pens_status() -> None:
    """ESPN labels a live World Cup shootout "AET-pens" with period still 0.
    The substring match on "pen" must flip is_live_shootout so the circles
    render as soon as penalties are announced, before any kick lands."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    for detail in ("AET-pens", "AET-PKs", "Penalties", "PKs", "Pen."):
        data = {"events": [_shootout_event(detail)]}
        games = asyncio.run(
            ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world")
        )
        assert games[0]["is_live_shootout"] is True, detail
        assert games[0]["ended_in_shootout"] is False, detail


def test_live_shootout_detected_from_status_name() -> None:
    """The status ``name`` field is a second signal: any "pen" mention there
    (e.g. STATUS_PENALTIES) marks a live shootout even when shortDetail is a
    plain clock label."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    data = {"events": [_shootout_event("120'", name="STATUS_PENALTIES")]}
    games = asyncio.run(
        ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world")
    )
    assert games[0]["is_live_shootout"] is True


def test_regular_soccer_status_is_not_a_shootout() -> None:
    """Ordinary clock/half labels must never be mistaken for a shootout, and
    "Suspended" (sus-PEN-ded) must not false-positive the substring match."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    cases = [
        ("90'", ""), ("45'+2'", ""), ("HT", ""), ("AET", ""), ("FT", ""),
        ("Suspended", "STATUS_SUSPENDED"),
    ]
    for detail, name in cases:
        data = {"events": [_shootout_event(detail, name=name)]}
        games = asyncio.run(
            ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world")
        )
        assert games[0]["is_live_shootout"] is False, detail


def _shootout_kick_detail(team_id: str, type_text: str, period: int = 0) -> dict[str, Any]:
    return {
        "type": {"text": type_text},
        "clock": {"displayValue": ""},
        "team": {"id": team_id},
        "period": {"number": period},
    }


def test_live_shootout_auto_triggers_from_penalty_details() -> None:
    """Even when the status text doesn't announce penalties, shootout kicks in
    the details array (a save, or a period-5+ penalty) must flip the game into
    live-shootout mode so the circles render."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    home_id, away_id = "10", "20"
    for kick in (
        _shootout_kick_detail(home_id, "Penalty - Saved"),        # save signals shootout
        _shootout_kick_detail(away_id, "Penalty - Scored", period=5),  # period 5+ signals shootout
    ):
        # Status still reads "90'" (see _soccer_event) -- no "pen"/"pk" token.
        data = {"events": [_soccer_event(
            "AUS", "EGY", home_id, away_id,
            home_score="1", away_score="1", details=[kick],
        )]}
        games = asyncio.run(
            ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world")
        )
        assert games[0]["is_live_shootout"] is True
        # And the kick was captured into the reconstructed PK sequence.
        assert games[0]["home_pks"] or games[0]["away_pks"]


def test_regular_play_penalty_goal_is_not_a_shootout() -> None:
    """A normal in-run penalty goal (scored, early period) must NOT auto-trigger
    shootout mode -- it is just a goal."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    home_id, away_id = "10", "20"
    data = {"events": [_soccer_event(
        "AUS", "EGY", home_id, away_id,
        home_score="1", away_score="0",
        details=[_shootout_kick_detail(home_id, "Penalty - Scored", period=1)],
    )]}
    games = asyncio.run(
        ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world")
    )
    assert games[0]["is_live_shootout"] is False
    assert games[0]["home_goals"] == ["(PK)"]  # counted as a regular PK goal


def test_flag_league_maps_saudi_arabia_to_flag() -> None:
    """ESPN abbreviates Saudi Arabia as the FIFA code ``KSA`` (not ``SAU``);
    the flag lookup must recognize it so a flag is shown next to the team."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    data = {
        "events": [
            {
                "id": "1",
                "status": {"type": {"shortDetail": "Scheduled", "state": "pre"}},
                "competitions": [
                    {
                        "competitors": [
                            _competitor("home", "KSA"),
                            _competitor("away", "ARG"),
                        ],
                    }
                ],
            }
        ]
    }

    games = asyncio.run(ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world"))

    assert games[0]["home_logo_url"] == "https://flagcdn.com/w80/sa.png"
    assert games[0]["away_logo_url"] == "https://flagcdn.com/w80/ar.png"


# ── Summary-endpoint shootout data (authoritative, includes misses) ──────────
#
# The scoreboard's details array only ever lists *scored* shootout kicks, so
# misses there must be inferred from alternation gaps -- which silently
# misplaces them (a missed FIRST kick leaves no trace and shifts every
# inference after it). The per-event summary endpoint carries a top-level
# ``shootout`` array with every shot -- team id, shotNumber, didScore --
# including misses. These tests mirror the real Australia-Egypt 2026-07-03
# World Cup payload: AUS truly went [miss, score, score, miss] but the
# scoreboard-only reconstruction produced [score, score, miss, miss].


class _RoutingClient:
    """Serves different payloads for the scoreboard vs summary endpoints."""

    def __init__(self, scoreboard: dict[str, Any], summary: Any) -> None:
        self._scoreboard = scoreboard
        self._summary = summary
        self.summary_calls = 0

    async def get(self, url: str, params: dict[str, str] | None = None) -> _FakeResponse:
        if "summary" in url:
            self.summary_calls += 1
            if isinstance(self._summary, Exception):
                raise self._summary
            return _FakeResponse(self._summary)
        return _FakeResponse(self._scoreboard)


def _shootout_scoreboard(state: str, status_name: str, short_detail: str) -> dict[str, Any]:
    """AUS (home) vs EGY (away) with only the 6 *scored* kicks in details,
    exactly as the real scoreboard reports them (no misses, no period)."""
    details = []
    for team_id in ("20", "10", "20", "10", "20", "20"):  # EGY,AUS,EGY,AUS,EGY,EGY
        details.append({
            "type": {"text": "Penalty - Scored"},
            "clock": {"displayValue": "120'"},
            "team": {"id": team_id},
            "shootout": True,
        })
    home = _competitor("home", "AUS", score="1", team_id="10")
    away = _competitor("away", "EGY", score="1", team_id="20")
    home["shootoutScore"] = 2
    away["shootoutScore"] = 4
    return {
        "events": [
            {
                "id": "760499",
                "status": {
                    "period": 5,
                    "type": {"name": status_name, "shortDetail": short_detail, "state": state},
                },
                "competitions": [
                    {"competitors": [home, away], "details": details}
                ],
            }
        ]
    }


def _summary_payload() -> dict[str, Any]:
    """Summary endpoint shape: AUS missed shots 1 and 4, EGY made all four."""
    def shots(results: list[bool]) -> list[dict[str, Any]]:
        return [
            {"shotNumber": i + 1, "didScore": r} for i, r in enumerate(results)
        ]
    return {
        "shootout": [
            {"id": "10", "team": "Australia", "shots": shots([False, True, True, False])},
            {"id": "20", "team": "Egypt", "shots": shots([True, True, True, True])},
        ]
    }


def test_summary_shootout_overrides_reconstruction() -> None:
    """The summary's per-shot record must replace the alternation-inferred pks:
    it is the only source that places misses correctly (here AUS's missed
    opening kick, invisible to the scoreboard details)."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    for state, name, detail in (
        ("post", "STATUS_FINAL_PEN", "FT-Pens"),   # completed shootout
        ("in", "STATUS_SHOOTOUT", "Pens"),          # live shootout
    ):
        client = _RoutingClient(_shootout_scoreboard(state, name, detail), _summary_payload())
        games = asyncio.run(ESPNSportsLibrary({})._fetch_league(client, "fifa.world"))
        game = games[0]
        assert game["home_pks"] == [False, True, True, False], (state, game["home_pks"])
        assert game["away_pks"] == [True, True, True, True], (state, game["away_pks"])
        assert client.summary_calls == 1


def test_summary_failure_falls_back_to_reconstruction() -> None:
    """If the summary fetch fails, the scoreboard-based reconstruction still
    provides pks (misses inferred from alternation, possibly misplaced but
    with correct made/missed totals)."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    client = _RoutingClient(
        _shootout_scoreboard("post", "STATUS_FINAL_PEN", "FT-Pens"),
        RuntimeError("summary down"),
    )
    games = asyncio.run(ESPNSportsLibrary({})._fetch_league(client, "fifa.world"))
    game = games[0]
    # Totals still correct even though miss positions are inferred.
    assert sum(game["home_pks"]) == 2 and len(game["home_pks"]) == 4
    assert sum(game["away_pks"]) == 4


def test_summary_cached_for_ended_games_not_live() -> None:
    """Ended shootouts cache the summary result (it can't change), so finished
    games lingering on the scoreboard don't re-fetch every poll; live
    shootouts must re-fetch to pick up new kicks."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    lib = ESPNSportsLibrary({})
    ended = _RoutingClient(
        _shootout_scoreboard("post", "STATUS_FINAL_PEN", "FT-Pens"), _summary_payload()
    )
    asyncio.run(lib._fetch_league(ended, "fifa.world"))
    asyncio.run(lib._fetch_league(ended, "fifa.world"))
    assert ended.summary_calls == 1

    lib2 = ESPNSportsLibrary({})
    live = _RoutingClient(
        _shootout_scoreboard("in", "STATUS_SHOOTOUT", "Pens"), _summary_payload()
    )
    asyncio.run(lib2._fetch_league(live, "fifa.world"))
    asyncio.run(lib2._fetch_league(live, "fifa.world"))
    assert live.summary_calls == 2


def test_shootout_boolean_detail_auto_triggers_live_mode() -> None:
    """Real scoreboard details carry ``shootout: true`` (and no period object).
    That boolean alone must flip a live game into shootout mode even when the
    status text is still a plain clock label."""
    from libraries.espn_sports.library import ESPNSportsLibrary

    kick = {
        "type": {"text": "Penalty - Scored"},
        "clock": {"displayValue": "120'"},
        "team": {"id": "20"},
        "shootout": True,
    }
    data = {"events": [_soccer_event(
        "AUS", "EGY", "10", "20",
        home_score="1", away_score="1", details=[kick],
    )]}
    games = asyncio.run(
        ESPNSportsLibrary({})._fetch_league(_FakeClient(data), "fifa.world")
    )
    assert games[0]["is_live_shootout"] is True
    assert games[0]["away_pks"] == [True]
