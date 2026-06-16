"""Reboot-resume tests.

On startup the engine must resume whatever was on the display before the last
shutdown: the active playlist, or a single module if one was being played.
"""
from __future__ import annotations

from main import _startup_entries
from state import Module, Playlist, PlaylistItem, StateStore


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


def test_startup_resumes_active_playlist(tmp_path):
    store = _store(tmp_path)

    entries = _startup_entries(store)

    assert len(entries) == 2


def test_startup_resumes_single_module(tmp_path):
    store = _store(tmp_path)
    single_id = next(iter(store.state.modules))
    store.set_active_single_module(single_id)

    entries = _startup_entries(store)

    assert len(entries) == 1
    assert entries[0].config == store.state.modules[single_id].config


def test_single_module_survives_store_reload(tmp_path):
    """The single module choice is persisted, so a fresh store (reboot) keeps it."""
    store = _store(tmp_path)
    single_id = next(iter(store.state.modules))
    store.set_active_single_module(single_id)

    reloaded = StateStore(path=tmp_path / "state.json")
    entries = _startup_entries(reloaded)

    assert len(entries) == 1
    assert reloaded.state.active_single_module_id == single_id


def test_startup_clears_stale_single_module(tmp_path):
    store = _store(tmp_path)
    store.set_active_single_module("does-not-exist")

    entries = _startup_entries(store)

    # Falls back to the active playlist and clears the dangling reference.
    assert store.state.active_single_module_id is None
    assert len(entries) == 2
