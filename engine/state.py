"""Persistent application state: named run configurations and playlists.

Stored in data/state.json.  Writes are atomic (tmp + rename) so a crash
during a save cannot corrupt the file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

_DEFAULT_PATH = Path("data/state.json")


# ── Data models ────────────────────────────────────────────────────────────────


class Run(BaseModel):
    """A named, reusable plugin configuration."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    plugin_id: str
    config: dict[str, Any] = {}


class PlaylistItem(BaseModel):
    """One slot in a saved playlist — a run reference plus a display duration."""

    run_id: str
    duration: float = 30.0


class Playlist(BaseModel):
    """An ordered, named collection of run references."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    items: list[PlaylistItem] = []


class AppState(BaseModel):
    runs: dict[str, Run] = {}
    playlists: dict[str, Playlist] = {}
    active_playlist_id: str | None = None


# ── Store ──────────────────────────────────────────────────────────────────────


class StateStore:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path
        self._state = self._load()

    @property
    def state(self) -> AppState:
        return self._state

    # ── Persistence ────────────────────────────────────────────────────────

    def _load(self) -> AppState:
        if self._path.exists():
            return AppState.model_validate_json(self._path.read_text())
        return AppState()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(self._state.model_dump_json(indent=2))
        tmp.rename(self._path)

    # ── Runs ───────────────────────────────────────────────────────────────

    def save_run(self, run: Run) -> Run:
        self._state.runs[run.id] = run
        self._save()
        return run

    def delete_run(self, run_id: str) -> None:
        self._state.runs.pop(run_id, None)
        for pl in self._state.playlists.values():
            pl.items = [it for it in pl.items if it.run_id != run_id]
        self._save()

    # ── Playlists ──────────────────────────────────────────────────────────

    def save_playlist(self, playlist: Playlist) -> Playlist:
        self._state.playlists[playlist.id] = playlist
        self._save()
        return playlist

    def delete_playlist(self, playlist_id: str) -> None:
        self._state.playlists.pop(playlist_id, None)
        if self._state.active_playlist_id == playlist_id:
            remaining = list(self._state.playlists.keys())
            self._state.active_playlist_id = remaining[0] if remaining else None
        self._save()

    def set_active(self, playlist_id: str | None) -> None:
        self._state.active_playlist_id = playlist_id
        self._save()

    # ── Resolution ─────────────────────────────────────────────────────────

    def resolve(self, playlist_id: str | None = None) -> list[dict[str, Any]]:
        """Expand a playlist into concrete entries consumable by SceneManager.

        Returns [{plugin_id, config, duration, run_id, run_name}, ...].
        Dangling run references (deleted runs) are silently skipped.
        """
        pid = playlist_id or self._state.active_playlist_id
        if not pid or pid not in self._state.playlists:
            return []
        result = []
        for item in self._state.playlists[pid].items:
            run = self._state.runs.get(item.run_id)
            if run:
                result.append(
                    {
                        "plugin_id": run.plugin_id,
                        "config": run.config,
                        "duration": item.duration,
                        "run_id": run.id,
                        "run_name": run.name,
                    }
                )
        return result
