"""Staggered display: independent per-slot rotation must never show the same
game in two sections at once.

Each slot in staggered mode advances on its own timer by ``+n`` (the slot
count), so its raw index mod ``n_games`` can collide with another slot's —
e.g. 3 games with 2 slots/screen: slot indices 0 and 1 both land on game 0
after one tick. ``_resolve_stagger_indices`` is the pure mapping from raw
slot indices to displayed game indices that avoids this.
"""

from __future__ import annotations

from typing import Any


def _make_app(config: dict[str, Any] | None = None, w: int = 320, h: int = 64):
    from apps.sports.app import SportsApp
    from canvas.simulator import SimulatorCanvas

    async def _noop_broadcast(_frame: bytes) -> None:
        pass

    canvas = SimulatorCanvas(w, h, _noop_broadcast)
    return SportsApp({"leagues": [], **(config or {})}, canvas, {}, {})


def test_resolve_stagger_indices_no_collision_when_enough_games():
    app = _make_app({"scores_per_screen": 2})
    # The exact collision case: 2 slots, 3 games, both raw indices land on 0.
    app._stagger_slot_idx = [0, 0]

    indices = app._resolve_stagger_indices(2, 3)

    assert len(set(indices)) == 2
    assert indices[0] == 0
    assert indices[1] == 1  # nudged forward off the collision


def test_resolve_stagger_indices_wraps_to_find_free_slot():
    app = _make_app({"scores_per_screen": 3})
    # All three raw indices collide on the same game, with 4 games available.
    app._stagger_slot_idx = [2, 2, 2]

    indices = app._resolve_stagger_indices(3, 4)

    assert len(set(indices)) == 3
    assert indices == [2, 3, 0]


def test_resolve_stagger_indices_allows_repeats_when_too_few_games():
    app = _make_app({"scores_per_screen": 3})
    app._stagger_slot_idx = [0, 1, 2]

    # Only 2 games for 3 slots — a repeat is unavoidable.
    indices = app._resolve_stagger_indices(3, 2)

    assert indices == [0, 1, 0]


def test_render_staggered_frame_never_repeats_a_game_on_screen():
    """Drive the staggered renderer through a tick that would otherwise put
    the same game in both slots (3 games, 2 slots/screen)."""
    from PIL import Image

    from apps.sports.tests.fixtures import _game

    games = [
        _game("nba", "basketball", ("LAL", "Los Angeles", "Lakers"), ("BOS", "Boston", "Celtics"),
              away_score="50", home_score="48", status="Q3", state="in", id="1"),
        _game("nba", "basketball", ("GSW", "Golden State", "Warriors"), ("MIA", "Miami", "Heat"),
              away_score="60", home_score="55", status="Q3", state="in", id="2"),
        _game("nba", "basketball", ("DEN", "Denver", "Nuggets"), ("PHX", "Phoenix", "Suns"),
              away_score="70", home_score="65", status="Q3", state="in", id="3"),
    ]

    app = _make_app({
        "display_mode": "staggered",
        "scores_per_screen": 2,
        "seconds_per_score": 5,
        "stagger_delay": 2,
    })
    app._games = games
    app._logos = {}

    rendered_ids: list[str] = []

    def fake_render_slot_image(game: Any, w: int, h: int) -> Image.Image:
        rendered_ids.append(game["id"])
        return Image.new("RGB", (max(1, w), max(1, h)))

    app._render_slot_image = fake_render_slot_image

    now = 1000.0
    app._now = lambda: now
    app._init_stagger_state()
    assert app._stagger_slot_idx == [0, 1]

    # First frame: no tick yet, slots show distinct games 0 and 1.
    app._render_staggered_frame()
    assert rendered_ids == ["1", "2"]

    # Advance so slot 1 (started "2s earlier") ticks: raw idx 1 -> (1+1) % 3 = 2.
    # With step +1 the slots stay one apart so there is no collision.
    now = 1003.0
    rendered_ids.clear()
    app._render_staggered_frame()

    assert app._stagger_slot_idx == [0, 2]  # no raw collision — slots stay distinct
    assert len(rendered_ids) == 2
    assert len(set(rendered_ids)) == 2  # displayed games are distinct


def test_active_slot_count_capped_by_game_count():
    app = _make_app({"scores_per_screen": 4})

    app._games = [object()]
    assert app._active_slot_count() == 1

    app._games = [object(), object(), object()]
    assert app._active_slot_count() == 3

    app._games = [object()] * 5
    assert app._active_slot_count() == 4  # capped at scores_per_screen


def test_render_staggered_frame_single_game_uses_one_full_width_slot():
    """A single game with scores_per_screen=4 should render once, full
    width — not the same game repeated across all 4 slots."""
    from PIL import Image

    from apps.sports.tests.fixtures import _game

    games = [
        _game("nba", "basketball", ("LAL", "Los Angeles", "Lakers"), ("BOS", "Boston", "Celtics"),
              away_score="50", home_score="48", status="Q3", state="in", id="1"),
    ]

    app = _make_app({
        "display_mode": "staggered",
        "scores_per_screen": 4,
        "seconds_per_score": 5,
        "stagger_delay": 2,
    }, w=320, h=64)
    app._games = games
    app._logos = {}

    rendered: list[tuple[str, int]] = []

    def fake_render_slot_image(game: Any, w: int, h: int) -> Image.Image:
        rendered.append((game["id"], w))
        return Image.new("RGB", (max(1, w), max(1, h)))

    app._render_slot_image = fake_render_slot_image

    now = 1000.0
    app._now = lambda: now
    app._init_stagger_state()
    assert app._stagger_slot_idx == [0]

    app._render_staggered_frame()

    assert rendered == [("1", 320)]


def test_draw_games_single_game_uses_full_width():
    """Paginate mode: a lone game on a 4-up page should fill the screen
    instead of being squeezed into one quarter-width slot."""
    from PIL import Image

    from apps.sports.tests.fixtures import _game

    games = [
        _game("nba", "basketball", ("LAL", "Los Angeles", "Lakers"), ("BOS", "Boston", "Celtics"),
              away_score="50", home_score="48", status="Q3", state="in", id="1"),
    ]

    app = _make_app({"scores_per_screen": 4}, w=320, h=64)
    app._games = games
    app._logos = {}

    rendered: list[tuple[str, int]] = []

    def fake_render_slot_image(game: Any, w: int, h: int) -> Image.Image:
        rendered.append((game["id"], w))
        return Image.new("RGB", (max(1, w), max(1, h)))

    app._render_slot_image = fake_render_slot_image

    app._draw_games(games, 4)

    assert rendered == [("1", 320)]


def test_build_marquee_strip_single_game_full_width():
    from apps.sports.tests.fixtures import _game

    games = [
        _game("nba", "basketball", ("LAL", "Los Angeles", "Lakers"), ("BOS", "Boston", "Celtics"),
              away_score="50", home_score="48", status="Q3", state="in", id="1"),
    ]

    app = _make_app({"scores_per_screen": 4}, w=320, h=64)
    app._games = games
    app._logos = {}

    strip = app._build_marquee_strip()

    assert strip is not None
    assert strip.width == 320
