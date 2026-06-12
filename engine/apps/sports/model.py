"""Normalization of raw ESPN game dicts into a render-ready view model.

Everything layout-independent happens here once per render: color palette
selection, logo contrast preparation, rank/possession decoration, and status
text composition. The card layouts in ``cards.py`` then only measure and
place. ``now`` is injectable so pre-game time formatting is testable.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from PIL import Image

from .colors import RGB, differentiate, prepare_logo, team_palette


@dataclass(frozen=True)
class TeamView:
    abbr: str                  # rank-decorated, e.g. "#3 UGA"
    plain_abbr: str            # bare abbreviation, e.g. "UGA"
    nickname: str              # "" when unavailable
    location: str
    rank: int | None           # top-25 rank, None otherwise
    score: str                 # "" for pre-game
    color: RGB                 # display-safe main color
    accent: RGB                # display-safe secondary color
    logo: Image.Image | None   # contrast-prepared RGBA, full cached size
    record: str | None         # win-loss record or soccer "N PTS"
    has_possession: bool


@dataclass(frozen=True)
class CelebrationView:
    """A live scoring celebration, resolved to this frame's pulse/anim phase."""

    kind: str            # "goal" | "touchdown" | "field_goal" | "interception" | "home_run"
    side: str | None     # "away" | "home" | None (no score pulse target)
    pulse_on: bool       # 1 Hz: text and scoring team's score visible this second
    anim_frame: int      # sprite animation frame index


@dataclass(frozen=True)
class GameView:
    away: TeamView
    home: TeamView
    sport: str
    state: str                 # "pre" | "in" | "post"
    status: str                # composed status, without soccer match note
    match_note: str            # soccer note ("Group C"), fitted by the footer
    situation: dict[str, Any]  # baseball outs/bases
    away_goals: list[str]
    home_goals: list[str]
    celebration: CelebrationView | None = None

    @property
    def is_baseball_live(self) -> bool:
        return self.sport == "baseball" and self.state == "in"

    @property
    def is_soccer(self) -> bool:
        return self.sport == "soccer"


def _rank_text(rank: Any) -> str:
    return f"#{rank}" if rank and rank <= 25 else ""


def _possession_side(game: dict[str, Any]) -> str | None:
    """Return "away"/"home" for the team with the ball, None otherwise."""
    situation = game.get("situation") or {}
    possession = situation.get("possession")
    pos_ref = possession.get("$ref", "") if isinstance(possession, dict) else ""
    for side in ("away", "home"):
        team_id = game.get(f"{side}_id", "")
        if team_id and f"/teams/{team_id}" in pos_ref:
            return side
    return None


def _format_start_time(
    start_raw: str,
    tz: datetime.tzinfo,
    time_format: str,
    now: datetime.datetime | None,
) -> str | None:
    try:
        start_utc = datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    local = start_utc.astimezone(tz)
    if time_format == "24h":
        text = f"{local.hour}:{local.minute:02d}"
    else:
        hour = local.hour % 12 or 12
        ampm = "AM" if local.hour < 12 else "PM"
        text = f"{hour}:{local.minute:02d} {ampm}"
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    if start_utc - now > datetime.timedelta(hours=20):
        text = f"{local.month}/{local.day} {text}"
    return text


def _compose_status(
    game: dict[str, Any],
    *,
    tz: datetime.tzinfo | None,
    time_format: str,
    now: datetime.datetime | None,
) -> str:
    status = game.get("series_summary") or str(game.get("status", ""))
    state = game.get("state", "pre")
    sport = game.get("sport", "")
    situation = game.get("situation") or {}

    if state == "in" and sport == "football":
        down = situation.get("down")
        distance = situation.get("distance")
        if down and distance is not None:
            down_str = ["1st", "2nd", "3rd", "4th"][min(int(down) - 1, 3)]
            status = f"{status} {down_str}&{distance}"

    elif state == "pre" and not game.get("series_summary"):
        start_raw = game.get("start_time")
        if start_raw:
            formatted = _format_start_time(start_raw, tz or datetime.timezone.utc, time_format, now)
            if formatted:
                # Without a resolved user timezone, the time above is UTC — label
                # it so it isn't mistaken for a (wrongly) converted local time.
                status = formatted if tz is not None else f"{formatted} UTC"

    return status


def _team_view(
    game: dict[str, Any],
    side: str,
    palette: tuple[RGB, RGB],
    logos: dict[str, Image.Image | None],
    possession: str | None,
) -> TeamView:
    rank_raw = game.get(f"{side}_rank")
    rank = int(rank_raw) if rank_raw and rank_raw <= 25 else None
    rank_text = _rank_text(rank_raw)
    plain_abbr = str(game[f"{side}_abbr"])
    abbr = plain_abbr
    if rank_text:
        abbr = f"{rank_text} {abbr}" if side == "away" else f"{abbr} {rank_text}"

    score = "" if game.get("state", "pre") == "pre" else str(game.get(f"{side}_score", "-"))

    logo_url = game.get(f"{side}_logo_url")
    logo = logos.get(logo_url) if logo_url else None
    if logo is not None:
        logo = prepare_logo(logo)

    if game.get("sport") == "soccer":
        points = game.get(f"{side}_points")
        record = f"{points} PTS" if points is not None else None
    else:
        record = game.get(f"{side}_record") or None

    return TeamView(
        abbr=abbr,
        plain_abbr=plain_abbr,
        nickname=game.get(f"{side}_nickname") or "",
        location=game.get(f"{side}_location") or "",
        rank=rank,
        score=score,
        color=palette[0],
        accent=palette[1],
        logo=logo,
        record=record,
        has_possession=possession == side,
    )


def build_game_view(
    game: dict[str, Any],
    logos: dict[str, Image.Image | None],
    *,
    tz: datetime.tzinfo | None = None,
    time_format: str = "12h",
    now: datetime.datetime | None = None,
    celebration: CelebrationView | None = None,
) -> GameView:
    state = game.get("state", "pre")
    sport = game.get("sport", "")

    away_palette = team_palette(game.get("away_color", ""), game.get("away_alt_color", ""))
    home_palette = team_palette(game.get("home_color", ""), game.get("home_alt_color", ""))
    away_palette, home_palette = differentiate(away_palette, home_palette)

    possession = _possession_side(game) if state == "in" and sport == "football" else None

    return GameView(
        away=_team_view(game, "away", away_palette, logos, possession),
        home=_team_view(game, "home", home_palette, logos, possession),
        sport=sport,
        state=state,
        status=_compose_status(game, tz=tz, time_format=time_format, now=now),
        match_note=str(game.get("match_note") or "") if sport == "soccer" else "",
        situation=dict(game.get("situation") or {}),
        away_goals=list(game.get("away_goals") or []),
        home_goals=list(game.get("home_goals") or []),
        celebration=celebration,
    )
