"""Spotify snapshot suite: playing layouts (art/progress variants) + idle."""

from __future__ import annotations

from typing import Any

from PIL import Image

from tests.framework import harness

_TRACK = {
    "title": "Bohemian Rhapsody",
    "artist": "Queen",
    "album_art_url": "https://example.invalid/art.jpg",
    "is_playing": True,
    "duration_ms": 354000,
    "progress_ms": 120000,
}

_LONG_TRACK = {
    **_TRACK,
    "title": "The Continuing Story of a Song Title That Never Ends",
    "artist": "An Orchestra With an Extremely Long Name",
    "progress_ms": 300000,
}


def _album_art(size: int) -> Image.Image:
    """Deterministic stand-in album art: four colored quadrants + border."""
    img = Image.new("RGB", (size, size), (30, 30, 30))
    half = size // 2
    quads = [
        ((0, 0), (200, 60, 60)), ((half, 0), (60, 120, 200)),
        ((0, half), (60, 180, 90)), ((half, half), (220, 180, 60)),
    ]
    for (x, y), color in quads:
        img.paste(color, (x, y, min(size, x + half), min(size, y + half)))
    for i in range(size):
        for x, y in ((i, 0), (i, size - 1), (0, i), (size - 1, i)):
            img.putpixel((x, y), (15, 15, 15))
    return img


def _seed(track: dict[str, Any] | None, *, art: bool):
    def seed(app: Any) -> None:
        app._track = dict(track) if track else None
        if track and art:
            app._album_art = _album_art(app._art_size())
        # Mid-scroll so the frame shows readable text, not the entering edge.
        app._title_offset = 4.0
        app._artist_offset = 4.0

    return seed


def _fixtures() -> dict[str, dict[str, Any]]:
    return {
        "playing_art_progress": {
            "config": {"show_album_art": True, "show_progress": True},
            "seed": _seed(_TRACK, art=True),
        },
        "playing_no_art": {
            "config": {"show_album_art": False, "show_progress": True},
            "seed": _seed(_TRACK, art=False),
        },
        "playing_no_progress": {
            "config": {"show_album_art": True, "show_progress": False},
            "seed": _seed(_TRACK, art=True),
        },
        "playing_long_title": {
            "config": {"show_album_art": True, "show_progress": True},
            "seed": _seed(_LONG_TRACK, art=True),
        },
        "not_playing": {
            "config": {},
            "seed": _seed(None, art=False),
        },
    }


def _register() -> None:
    from apps.spotify.app import SpotifyApp

    harness.register(
        harness.SnapshotSuite(
            app_id="spotify",
            fixtures=_fixtures(),
            sizes=harness.CORE_SIZES,
            render=harness.app_case_render(SpotifyApp),
        )
    )


_register()
