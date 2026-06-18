"""Sports snapshot suite: fixture games, size matrix, and render entry point.

Fixtures are the union of the dev-UI debug games (``apps/sports/debug_games.json``,
left untouched) and extra test-only games that each target a known rendering
failure mode (overflow, near-black colors, missing logos, ...). All times are
fixed ISO strings and no timezone is configured, so output is deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.snaptest import harness
from tests.snaptest.logos import fixture_logos

_DEBUG_GAMES_PATH = (
    Path(__file__).parent.parent.parent / "apps" / "sports" / "debug_games.json"
)

# Sizes every fixture is rendered at: the realistic panel widths × both heights.
CORE_SIZES = harness.CORE_SIZES

# Layout tier edges (minimal tier, multi-card slot widths) only need coverage
# from one representative in-progress fixture per sport.
EDGE_SIZES: list[tuple[int, int]] = [
    (w, h) for h in (32, 64) for w in (40, 48, 80, 96, 160)
]
EDGE_FIXTURES: list[str] = [
    "mlb_in_progress",
    "nfl_in_progress",
    "nba_in_progress",
    "nhl_in_progress",
    "epl_in_progress",
]


def _game(
    league: str,
    sport: str,
    away: tuple[str, str, str],   # (abbr, location, nickname)
    home: tuple[str, str, str],
    *,
    away_score: str = "",
    home_score: str = "",
    away_color: str = "888888",
    home_color: str = "888888",
    away_alt_color: str = "aaaaaa",
    home_alt_color: str = "aaaaaa",
    status: str = "Scheduled",
    state: str = "pre",
    logo_slug: tuple[str | None, str | None] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a full ESPN-shaped game dict with sensible defaults."""
    espn_league = {"college-football": "ncaa", "mens-college-basketball": "ncaa"}.get(
        league, league
    )

    def _logo(slug: str | None) -> str | None:
        if slug is None:
            return None
        return f"https://a.espncdn.com/i/teamlogos/{espn_league}/500/{slug}.png"

    slugs = logo_slug or (away[0].lower(), home[0].lower())
    game: dict[str, Any] = {
        "league": league,
        "sport": sport,
        "away_abbr": away[0], "home_abbr": home[0],
        "away_name": f"{away[1]} {away[2]}", "home_name": f"{home[1]} {home[2]}",
        "away_location": away[1], "home_location": home[1],
        "away_nickname": away[2], "home_nickname": home[2],
        "away_score": away_score, "home_score": home_score,
        "away_color": away_color, "home_color": home_color,
        "away_alt_color": away_alt_color, "home_alt_color": home_alt_color,
        "away_logo_url": _logo(slugs[0]), "home_logo_url": _logo(slugs[1]),
        "status": status, "state": state,
        "series_summary": None,
        "start_time": "2026-07-10T23:00:00Z" if state == "pre" else None,
        "away_rank": None, "home_rank": None,
        "away_conf": None, "home_conf": None,
        "situation": {},
        "away_id": "", "home_id": "",
        "away_record": None, "home_record": None,
        "match_note": "",
    }
    game.update(extra)
    return game


def _extra_fixtures() -> dict[str, dict[str, Any]]:
    """Test-only games, each exercising a specific rendering failure mode."""
    return {
        # Black primary color AND a near-black logo — contrast handling.
        "nfl_black_team": _game(
            "nfl", "football",
            ("LV", "Las Vegas", "Raiders"), ("KC", "Kansas City", "Chiefs"),
            away_score="13", home_score="21",
            away_color="000000", home_color="e31837",
            away_alt_color="a5acaf", home_alt_color="ffb612",
            status="Q3 4:18", state="in",
            away_record="6-5", home_record="8-3",
            away_id="13", home_id="12",
            situation={
                "possession": {"$ref": "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/teams/13"},
                "down": 3, "distance": 4,
            },
        ),
        # Rank prefixes + long school names + records.
        "ncaaf_ranked_long": _game(
            "college-football", "football",
            ("UGA", "Georgia", "Bulldogs"), ("TENN", "Tennessee", "Volunteers"),
            away_score="24", home_score="20",
            away_color="ba0c2f", home_color="ff8200",
            away_alt_color="000000", home_alt_color="58595b",
            status="Q2 6:11", state="in",
            away_rank=3, home_rank=14,
            away_conf="SEC", home_conf="SEC",
            away_record="9-1", home_record="8-2",
            logo_slug=("61", "2633"),
        ),
        # 3-digit scores in overtime — score width stress.
        "nba_high_score_ot": _game(
            "nba", "basketball",
            ("LAL", "Los Angeles", "Lakers"), ("BOS", "Boston", "Celtics"),
            away_score="145", home_score="142",
            away_color="552583", home_color="007a33",
            away_alt_color="fdb927", home_alt_color="ba9653",
            status="OT 2:30", state="in",
            away_record="28-15", home_record="33-10",
            logo_slug=("lal", "bos"),
        ),
        # Bases loaded, 2 outs, extra innings — diamond + long inning text.
        "mlb_bases_loaded": _game(
            "mlb", "baseball",
            ("NYY", "New York", "Yankees"), ("BOS", "Boston", "Red Sox"),
            away_score="7", home_score="7",
            away_color="003087", home_color="bd3039",
            away_alt_color="c4ced4", home_alt_color="0d2b56",
            status="Top 12th", state="in",
            away_record="55-30", home_record="48-37",
            situation={"outs": 2, "onFirst": True, "onSecond": True, "onThird": True},
        ),
        # Extra-innings final.
        "mlb_walkoff_final": _game(
            "mlb", "baseball",
            ("NYY", "New York", "Yankees"), ("BOS", "Boston", "Red Sox"),
            away_score="7", home_score="8",
            away_color="003087", home_color="bd3039",
            away_alt_color="c4ced4", home_alt_color="0d2b56",
            status="Final/11", state="post",
            away_record="55-31", home_record="49-37",
        ),
        # Home possession arrow + 4th and short late.
        "nfl_redzone_home_poss": _game(
            "nfl", "football",
            ("KC", "Kansas City", "Chiefs"), ("NE", "New England", "Patriots"),
            away_score="20", home_score="17",
            away_color="e31837", home_color="002244",
            away_alt_color="ffb612", home_alt_color="c60c30",
            status="Q4 0:38", state="in",
            away_record="8-3", home_record="4-7",
            away_id="12", home_id="17",
            situation={
                "possession": {"$ref": "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/teams/17"},
                "down": 4, "distance": 1,
            },
        ),
        # Shootout final.
        "nhl_shootout_final": _game(
            "nhl", "hockey",
            ("TOR", "Toronto", "Maple Leafs"), ("MTL", "Montréal", "Canadiens"),
            away_score="4", home_score="3",
            away_color="003e7e", home_color="af1e2d",
            away_alt_color="ffffff", home_alt_color="003da5",
            status="Final/SO", state="post",
            away_record="25-18-5", home_record="20-23-4",
        ),
        # Many goals — goal-list overflow/truncation.
        "soccer_many_goals": _game(
            "eng.1", "soccer",
            ("MCI", "Manchester", "City"), ("ARS", "London", "Arsenal"),
            away_score="4", home_score="3",
            away_color="6cabdd", home_color="ef0107",
            away_alt_color="1c2c5b", home_alt_color="023474",
            status="88'", state="in",
            match_note="Matchday 14",
            away_goals=["3'", "27'", "55'", "81'"],
            home_goals=["12'", "45+2'", "78'(og)"],
            away_points=None, home_points=None,
            logo_slug=("382", "359"),
        ),
        # Long knockout note + stoppage-time status.
        "soccer_long_note": _game(
            "fifa.world", "soccer",
            ("FRA", "France", "France"), ("GER", "Germany", "Germany"),
            away_score="1", home_score="1",
            away_color="003189", home_color="1c2d4f",
            away_alt_color="ed2939", home_alt_color="dd0000",
            status="45+2'", state="in",
            match_note="Quarter-Final",
            away_goals=["19'"], home_goals=["44'"],
            away_points=None, home_points=None,
            away_id="fra", home_id="ger",
        ),
        # Both teams red-ish — color differentiation.
        "similar_colors": _game(
            "nfl", "football",
            ("ATL", "Atlanta", "Falcons"), ("KC", "Kansas City", "Chiefs"),
            away_score="14", home_score="17",
            away_color="a71930", home_color="e31837",
            away_alt_color="000000", home_alt_color="ffb612",
            status="Q2 1:55", state="in",
            away_record="5-6", home_record="8-3",
            away_id="1", home_id="12",
        ),
        # Missing logos — layout must reflow, not leave holes.
        "missing_logos": _game(
            "nhl", "hockey",
            ("TOR", "Toronto", "Maple Leafs"), ("MTL", "Montréal", "Canadiens"),
            away_score="2", home_score="1",
            away_color="003e7e", home_color="af1e2d",
            away_alt_color="ffffff", home_alt_color="003da5",
            status="P2 14:22", state="in",
            away_record="24-18-5", home_record="20-22-4",
            logo_slug=(None, None),
        ),
        # Celebration overlays: pulsing big text + sprite replace the centre
        # widget (goal list / diamond) and the scoring team's score blinks.
        # anim_frame is fixed so sprite output is deterministic.
        "soccer_goal_celebration": _game(
            "eng.1", "soccer",
            ("MCI", "Manchester", "City"), ("ARS", "London", "Arsenal"),
            away_score="1", home_score="2",
            away_color="6cabdd", home_color="ef0107",
            away_alt_color="1c2c5b", home_alt_color="023474",
            status="67'", state="in",
            away_goals=["23'"], home_goals=["12'", "66'"],
            away_points=None, home_points=None,
            logo_slug=("382", "359"),
            _celebration={"kind": "goal", "side": "home", "pulse_on": True, "anim_frame": 2},
        ),
        # Off pulse phase: text and home score blanked, geometry unchanged.
        "soccer_goal_celebration_off": _game(
            "eng.1", "soccer",
            ("MCI", "Manchester", "City"), ("ARS", "London", "Arsenal"),
            away_score="1", home_score="2",
            away_color="6cabdd", home_color="ef0107",
            away_alt_color="1c2c5b", home_alt_color="023474",
            status="67'", state="in",
            away_goals=["23'"], home_goals=["12'", "66'"],
            away_points=None, home_points=None,
            logo_slug=("382", "359"),
            _celebration={"kind": "goal", "side": "home", "pulse_on": False, "anim_frame": 3},
        ),
        "nfl_td_celebration": _game(
            "nfl", "football",
            ("KC", "Kansas City", "Chiefs"), ("NE", "New England", "Patriots"),
            away_score="27", home_score="17",
            away_color="e31837", home_color="002244",
            away_alt_color="ffb612", home_alt_color="c60c30",
            status="Q4 8:11", state="in",
            away_record="8-3", home_record="4-7",
            _celebration={"kind": "touchdown", "side": "away", "pulse_on": True, "anim_frame": 1},
        ),
        "nfl_fg_celebration": _game(
            "nfl", "football",
            ("KC", "Kansas City", "Chiefs"), ("NE", "New England", "Patriots"),
            away_score="20", home_score="20",
            away_color="e31837", home_color="002244",
            away_alt_color="ffb612", home_alt_color="c60c30",
            status="Q4 0:04", state="in",
            away_record="8-3", home_record="4-7",
            _celebration={"kind": "field_goal", "side": "home", "pulse_on": True, "anim_frame": 5},
        ),
        # Longest text — exercises the "INT!" abbreviation at narrow widths.
        "nfl_int_celebration": _game(
            "nfl", "football",
            ("KC", "Kansas City", "Chiefs"), ("NE", "New England", "Patriots"),
            away_score="14", home_score="10",
            away_color="e31837", home_color="002244",
            away_alt_color="ffb612", home_alt_color="c60c30",
            status="Q3 5:02", state="in",
            away_record="8-3", home_record="4-7",
            _celebration={"kind": "interception", "side": "home", "pulse_on": True, "anim_frame": 0},
        ),
        "mlb_hr_celebration": _game(
            "mlb", "baseball",
            ("NYY", "New York", "Yankees"), ("BOS", "Boston", "Red Sox"),
            away_score="5", home_score="3",
            away_color="003087", home_color="bd3039",
            away_alt_color="c4ced4", home_alt_color="0d2b56",
            status="Top 7th", state="in",
            away_record="55-30", home_record="48-37",
            situation={"outs": 1, "onFirst": True},
            _celebration={"kind": "home_run", "side": "away", "pulse_on": True, "anim_frame": 4},
        ),
        # Worst case: long city + long nickname + ranks + 3-digit scores.
        "long_everything": _game(
            "mens-college-basketball", "basketball",
            ("NW", "Northwestern", "Wildcats"), ("MSST", "Mississippi State", "Bulldogs"),
            away_score="108", home_score="109",
            away_color="4e2a84", home_color="660000",
            away_alt_color="d9d9d9", home_alt_color="cccccc",
            status="2OT 0:42", state="in",
            away_rank=23, home_rank=14,
            away_record="19-4", home_record="21-2",
            logo_slug=("77", "344"),
        ),
    }


def all_fixtures() -> dict[str, dict[str, Any]]:
    debug_games = json.loads(_DEBUG_GAMES_PATH.read_text())
    fixtures = {entry["id"]: entry["game"] for entry in debug_games}
    fixtures.update(_extra_fixtures())
    return fixtures


def _render_card(game: dict[str, Any], w: int, h: int) -> harness.RenderResult:
    """Render one game card through the real model + card pipeline.

    Calls build_game_view/render_card directly (what SportsApp._render_slot_image
    delegates to) so the layout boxes are available for assertion tests.
    """
    from apps.sports.cards import render_card
    from apps.sports.model import CelebrationView, build_game_view

    game = dict(game)
    celeb_raw = game.pop("_celebration", None)
    celebration = CelebrationView(**celeb_raw) if celeb_raw else None
    view = build_game_view(game, fixture_logos(game), celebration=celebration)
    result = render_card(view, w, h)
    return harness.RenderResult(image=result.image, boxes=result.boxes)


harness.register(
    harness.SnapshotSuite(
        app_id="sports",
        fixtures=all_fixtures(),
        sizes=CORE_SIZES,
        render=_render_card,
        extra_cases=[
            (fixture_id, w, h)
            for fixture_id in EDGE_FIXTURES
            for (w, h) in EDGE_SIZES
        ],
    )
)
