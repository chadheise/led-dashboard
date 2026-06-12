"""Scoring-event detection by diffing successive scoreboard fetches.

The ESPN scoreboard is a snapshot, not an event stream, so celebrations are
inferred: the app keeps a :class:`GameSnapshot` per game and
:func:`detect_events` compares each new fetch against it. Everything here is
pure (no app state, no clock) so the rules are unit-testable in isolation.

Detection is deliberately conservative — a missed celebration is invisible,
a spurious one is not:

- Nothing fires for a game's first observation (startup/app activation).
- Score deltas are measured against the *maximum* score ever observed, so an
  ESPN score correction that dips and recovers doesn't re-celebrate.
- Football interceptions and baseball home runs never change the score (or
  not identifiably), so they require ``last_play`` — absent that field they
  are silently undetected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

CELEBRATION_KINDS = ("goal", "touchdown", "field_goal", "interception", "home_run")


@dataclass(frozen=True)
class GameSnapshot:
    state: str
    away_score: int | None
    home_score: int | None
    away_max_score: int
    home_max_score: int
    away_goal_count: int
    home_goal_count: int
    away_goal_max: int
    home_goal_max: int
    last_play_id: str


@dataclass(frozen=True)
class SportEvent:
    game_key: str
    kind: str           # one of CELEBRATION_KINDS
    side: str | None    # "away" | "home" | None (no score pulse target)


@dataclass
class Celebration:
    kind: str
    side: str | None
    started_at: float   # time.monotonic() at detection


def game_key(game: Mapping[str, Any]) -> str:
    """Stable per-game key: the ESPN event id, with a composite fallback."""
    event_id = str(game.get("id") or "")
    if event_id:
        return event_id
    return (
        f"{game.get('league', '')}:{game.get('away_abbr', '')}"
        f"@{game.get('home_abbr', '')}:{game.get('start_time', '')}"
    )


def _parse_score(raw: Any) -> int | None:
    try:
        return int(str(raw))
    except (ValueError, TypeError):
        return None


def make_snapshot(game: Mapping[str, Any], prev: GameSnapshot | None = None) -> GameSnapshot:
    away = _parse_score(game.get("away_score"))
    home = _parse_score(game.get("home_score"))
    away_goals = len(game.get("away_goals") or [])
    home_goals = len(game.get("home_goals") or [])
    last_play = game.get("last_play") or {}
    return GameSnapshot(
        state=str(game.get("state", "pre")),
        away_score=away,
        home_score=home,
        away_max_score=max(away or 0, prev.away_max_score if prev else 0),
        home_max_score=max(home or 0, prev.home_max_score if prev else 0),
        away_goal_count=away_goals,
        home_goal_count=home_goals,
        away_goal_max=max(away_goals, prev.away_goal_max if prev else 0),
        home_goal_max=max(home_goals, prev.home_goal_max if prev else 0),
        last_play_id=str(last_play.get("id") or ""),
    )


def _last_play_side(game: Mapping[str, Any]) -> str | None:
    team_id = str((game.get("last_play") or {}).get("team_id") or "")
    if team_id:
        for side in ("away", "home"):
            if str(game.get(f"{side}_id") or "") == team_id:
                return side
    return None


def _possession_side(game: Mapping[str, Any]) -> str | None:
    possession = (game.get("situation") or {}).get("possession")
    pos_ref = possession.get("$ref", "") if isinstance(possession, dict) else ""
    for side in ("away", "home"):
        team_id = game.get(f"{side}_id", "")
        if team_id and f"/teams/{team_id}" in pos_ref:
            return side
    return None


def _score_deltas(prev: GameSnapshot, snap: GameSnapshot) -> dict[str, int]:
    """Per-side score increase vs the max ever observed; 0 when unparseable."""
    deltas: dict[str, int] = {}
    for side in ("away", "home"):
        score = getattr(snap, f"{side}_score")
        prev_max = getattr(prev, f"{side}_max_score")
        deltas[side] = max(0, score - prev_max) if score is not None else 0
    return deltas


def _detect_soccer(
    key: str, game: Mapping[str, Any], prev: GameSnapshot, snap: GameSnapshot
) -> list[SportEvent]:
    # Fire as soon as *either* the score or the goal-minute list advances —
    # whichever ESPN exposes first. The goal-minute ``details[]`` array is
    # often updated a poll or two before the ``score`` field, so keying off it
    # too makes celebrations land closer to realtime. A single guard against
    # the max-ever of *both* counters (soccer scores move 1:1 with goals)
    # collapses the lead/lag into exactly one event per side.
    events: list[SportEvent] = []
    for side in ("away", "home"):
        prev_max = max(
            getattr(prev, f"{side}_max_score"), getattr(prev, f"{side}_goal_max")
        )
        score = getattr(snap, f"{side}_score")
        goal_count = getattr(snap, f"{side}_goal_count")
        if (score is not None and score > prev_max) or goal_count > prev_max:
            events.append(SportEvent(key, "goal", side))
    return events


def _detect_football(
    key: str, game: Mapping[str, Any], prev: GameSnapshot, snap: GameSnapshot
) -> list[SportEvent]:
    deltas = _score_deltas(prev, snap)
    scoring_side = next((s for s in ("away", "home") if deltas[s] > 0), None)

    # A new last play is the most precise signal: it distinguishes a pick-six
    # (touchdown) from a plain interception and confirms field goals.
    last_play = game.get("last_play") or {}
    if last_play and snap.last_play_id and snap.last_play_id != prev.last_play_id:
        text = f"{last_play.get('type_text', '')} {last_play.get('text', '')}".lower()
        if "touchdown" in text:
            return [SportEvent(key, "touchdown", scoring_side or _last_play_side(game))]
        if "field goal" in text and (scoring_side is None or deltas[scoring_side] == 3):
            return [SportEvent(key, "field_goal", scoring_side or _last_play_side(game))]
        if "intercept" in text:
            side = _last_play_side(game) or _possession_side(game)
            return [SportEvent(key, "interception", side)]

    # Score-delta heuristics cover games where the scoreboard has no lastPlay.
    # +1/+2 (extra point, safety, two-point conversion alone) stay silent.
    if scoring_side is not None:
        if deltas[scoring_side] in (6, 7, 8):
            return [SportEvent(key, "touchdown", scoring_side)]
        if deltas[scoring_side] == 3:
            return [SportEvent(key, "field_goal", scoring_side)]
    return []


def _detect_baseball(
    key: str, game: Mapping[str, Any], prev: GameSnapshot, snap: GameSnapshot
) -> list[SportEvent]:
    last_play = game.get("last_play") or {}
    if not last_play or not snap.last_play_id or snap.last_play_id == prev.last_play_id:
        return []
    text = f"{last_play.get('type_text', '')} {last_play.get('text', '')}".lower()
    if not any(t in text for t in ("home run", "homer", "grand slam")):
        return []
    deltas = _score_deltas(prev, snap)
    side = next((s for s in ("away", "home") if deltas[s] > 0), None)
    return [SportEvent(key, "home_run", side or _last_play_side(game))]


_DETECTORS = {
    "soccer": _detect_soccer,
    "football": _detect_football,
    "baseball": _detect_baseball,
}


def detect_events(
    prev_snaps: Mapping[str, GameSnapshot], games: list[dict[str, Any]]
) -> list[SportEvent]:
    """Compare a fresh fetch against the previous snapshots; emit new events."""
    events: list[SportEvent] = []
    for game in games:
        detector = _DETECTORS.get(str(game.get("sport", "")))
        if detector is None:
            continue
        key = game_key(game)
        prev = prev_snaps.get(key)
        if prev is None or prev.state != "in":
            continue  # first observation, or game wasn't live last time
        snap = make_snapshot(game, prev)
        if snap.state not in ("in", "post"):
            continue
        events.extend(detector(key, game, prev, snap))
    return events
