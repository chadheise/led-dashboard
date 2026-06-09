"""Persistent application state: named module configurations and playlists.

Stored in data/state.json.  Writes are atomic (tmp + rename) so a crash
during a save cannot corrupt the file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, Field

_DEFAULT_PATH = Path("data/state.json")


# ── Data models ────────────────────────────────────────────────────────────────


class Module(BaseModel):
    """A named, reusable app configuration."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    app_id: str = Field(validation_alias=AliasChoices("app_id", "plugin_id"))
    config: dict[str, Any] = {}


class PlaylistItem(BaseModel):
    """One slot in a saved playlist — a module reference plus a display duration."""

    module_id: str = Field(validation_alias=AliasChoices("module_id", "run_id"))
    duration: float = 30.0
    skip_if_hidden: bool = False


class Playlist(BaseModel):
    """An ordered, named collection of module references."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    items: list[PlaylistItem] = []


class AppState(BaseModel):
    modules: dict[str, Module] = Field(
        default={}, validation_alias=AliasChoices("modules", "runs")
    )
    playlists: dict[str, Playlist] = {}
    active_playlist_id: str | None = None
    app_configs: dict[str, dict[str, Any]] = {}  # keyed by app_id
    library_configs: dict[str, dict[str, Any]] = {}  # keyed by library_id


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

    # ── Modules ────────────────────────────────────────────────────────────

    def save_module(self, module: Module) -> Module:
        self._state.modules[module.id] = module
        self._save()
        return module

    def delete_module(self, module_id: str) -> None:
        self._state.modules.pop(module_id, None)
        for pl in self._state.playlists.values():
            pl.items = [it for it in pl.items if it.module_id != module_id]
        self._save()

    # ── App configs ────────────────────────────────────────────────────────

    def get_app_config(self, app_id: str) -> dict[str, Any]:
        return self._state.app_configs.get(app_id, {})

    def save_app_config(self, app_id: str, config: dict[str, Any]) -> None:
        self._state.app_configs[app_id] = config
        self._save()

    # ── Library configs ────────────────────────────────────────────────────

    def get_library_config(self, lib_id: str) -> dict[str, Any]:
        return self._state.library_configs.get(lib_id, {})

    def save_library_config(self, lib_id: str, config: dict[str, Any]) -> None:
        self._state.library_configs[lib_id] = config
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

        Returns [{app_id, config, duration, module_id, module_name}, ...].
        Dangling module references (deleted modules) are silently skipped.
        """
        pid = playlist_id or self._state.active_playlist_id
        if not pid or pid not in self._state.playlists:
            return []
        all_library_configs = dict(self._state.library_configs)
        result = []
        for item in self._state.playlists[pid].items:
            module = self._state.modules.get(item.module_id)
            if module:
                result.append(
                    {
                        "app_id": module.app_id,
                        "config": module.config,
                        "duration": item.duration,
                        "module_id": module.id,
                        "module_name": module.name,
                        "global_config": self._state.app_configs.get(module.app_id, {}),
                        "library_configs": all_library_configs,
                        "skip_if_hidden": item.skip_if_hidden,
                    }
                )
        return result
