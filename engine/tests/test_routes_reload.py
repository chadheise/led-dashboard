"""Regression tests for scene reloads after settings changes.

Changing a library/app/module setting must reload the display *in place* — it
must never switch the display to a different playlist or away from a single
module that is currently playing.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.routes import _maybe_reload, play_single_module
from scene_manager import PlaylistEntry as SMEntry
from state import Module, Playlist, PlaylistItem, StateStore


class FakeSceneManager:
    def __init__(self) -> None:
        self.calls: list[list[SMEntry]] = []

    async def set_playlist(self, entries: list[SMEntry]) -> None:
        self.calls.append(entries)

    @property
    def last(self) -> list[SMEntry]:
        return self.calls[-1]


def _store(tmp_path) -> StateStore:
    store = StateStore(path=tmp_path / "state.json")
    m_text = store.save_module(Module(name="Hello", app_id="text", config={"message": "hi"}))
    m_clock = store.save_module(Module(name="Clock", app_id="text", config={"message": "clock"}))
    pl = store.save_playlist(
        Playlist(
            name="Default",
            items=[
                PlaylistItem(module_id=m_text.id, duration=10.0),
                PlaylistItem(module_id=m_clock.id, duration=10.0),
            ],
        )
    )
    store.set_active(pl.id)
    return store


def _request(store: StateStore, sm: FakeSceneManager, single_id: str | None = None):
    state = SimpleNamespace(store=store, scene_manager=sm, active_single_module_id=single_id)
    return SimpleNamespace(app=SimpleNamespace(state=state))


@pytest.mark.asyncio
async def test_settings_change_keeps_single_module(tmp_path):
    store = _store(tmp_path)
    single_id = next(iter(store.state.modules))
    sm = FakeSceneManager()
    request = _request(store, sm, single_id=single_id)

    await _maybe_reload(request)

    # Reloaded the single module, not the active playlist.
    assert len(sm.last) == 1
    assert sm.last[0].config == store.state.modules[single_id].config


@pytest.mark.asyncio
async def test_settings_change_picks_up_updated_single_module_config(tmp_path):
    store = _store(tmp_path)
    single_id = next(iter(store.state.modules))
    mod = store.state.modules[single_id]
    store.save_module(Module(id=single_id, name=mod.name, app_id=mod.app_id, config={"message": "updated"}))
    sm = FakeSceneManager()
    request = _request(store, sm, single_id=single_id)

    await _maybe_reload(request)

    assert len(sm.last) == 1
    assert sm.last[0].config == {"message": "updated"}


@pytest.mark.asyncio
async def test_settings_change_reloads_active_playlist_when_no_single(tmp_path):
    store = _store(tmp_path)
    sm = FakeSceneManager()
    request = _request(store, sm, single_id=None)

    await _maybe_reload(request)

    # Both playlist entries reloaded.
    assert len(sm.last) == 2


@pytest.mark.asyncio
async def test_deleted_single_module_falls_back_to_playlist(tmp_path):
    store = _store(tmp_path)
    sm = FakeSceneManager()
    request = _request(store, sm, single_id="does-not-exist")

    await _maybe_reload(request)

    assert request.app.state.active_single_module_id is None
    assert len(sm.last) == 2


@pytest.mark.asyncio
async def test_play_single_module_sets_active_id(tmp_path):
    store = _store(tmp_path)
    module_id = next(iter(store.state.modules))
    sm = FakeSceneManager()
    request = _request(store, sm, single_id=None)

    result = await play_single_module(request, module_id)

    assert result["active_single_module_id"] == module_id
    assert request.app.state.active_single_module_id == module_id
    assert len(sm.last) == 1
