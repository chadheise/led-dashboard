from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from scene_manager import PlaylistEntry as SMEntry
from state import Playlist, PlaylistItem, Run

router = APIRouter(prefix="/api")


# ── Request bodies ─────────────────────────────────────────────────────────────


class RunBody(BaseModel):
    name: str
    plugin_id: str
    config: dict[str, Any] = {}


class PlaylistItemBody(BaseModel):
    run_id: str
    duration: float = 30.0


class PlaylistBody(BaseModel):
    name: str
    items: list[PlaylistItemBody] = []


# ── Plugin type catalog ────────────────────────────────────────────────────────


@router.get("/plugins")
def list_plugins() -> list[dict[str, Any]]:
    from plugins import REGISTRY

    return [
        {"id": cls.id, "name": cls.name, "schema": cls.config_schema}
        for cls in REGISTRY.values()
    ]


# ── Runs CRUD ──────────────────────────────────────────────────────────────────


@router.get("/runs")
def list_runs(request: Request) -> list[dict[str, Any]]:
    store = request.app.state.store
    return [r.model_dump() for r in store.state.runs.values()]


@router.post("/runs", status_code=201)
def create_run(request: Request, body: RunBody) -> dict[str, Any]:
    store = request.app.state.store
    _require_plugin(body.plugin_id)
    run = store.save_run(Run(name=body.name, plugin_id=body.plugin_id, config=body.config))
    return run.model_dump()


@router.put("/runs/{run_id}")
async def update_run(request: Request, run_id: str, body: RunBody) -> dict[str, Any]:
    store = request.app.state.store
    if run_id not in store.state.runs:
        raise HTTPException(404, "Run not found")
    _require_plugin(body.plugin_id)
    updated = Run(id=run_id, name=body.name, plugin_id=body.plugin_id, config=body.config)
    store.save_run(updated)
    # If this run is in the active playlist, reload the scene manager.
    await _maybe_reload(request)
    return updated.model_dump()


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(request: Request, run_id: str) -> None:
    store = request.app.state.store
    if run_id not in store.state.runs:
        raise HTTPException(404, "Run not found")
    store.delete_run(run_id)
    await _maybe_reload(request)


# ── Playlists CRUD ─────────────────────────────────────────────────────────────


def _playlist_view(store: Any, pl: Playlist) -> dict[str, Any]:
    """Serialise a playlist with run names resolved for display."""
    items = []
    for it in pl.items:
        run = store.state.runs.get(it.run_id)
        items.append(
            {
                "run_id": it.run_id,
                "run_name": run.name if run else "(deleted)",
                "plugin_id": run.plugin_id if run else None,
                "duration": it.duration,
            }
        )
    return {
        "id": pl.id,
        "name": pl.name,
        "items": items,
        "is_active": pl.id == store.state.active_playlist_id,
    }


@router.get("/playlists")
def list_playlists(request: Request) -> list[dict[str, Any]]:
    store = request.app.state.store
    return [_playlist_view(store, pl) for pl in store.state.playlists.values()]


@router.post("/playlists", status_code=201)
def create_playlist(request: Request, body: PlaylistBody) -> dict[str, Any]:
    store = request.app.state.store
    pl = store.save_playlist(
        Playlist(
            name=body.name,
            items=[PlaylistItem(run_id=it.run_id, duration=it.duration) for it in body.items],
        )
    )
    return _playlist_view(store, pl)


@router.put("/playlists/{playlist_id}")
async def update_playlist(
    request: Request, playlist_id: str, body: PlaylistBody
) -> dict[str, Any]:
    store = request.app.state.store
    if playlist_id not in store.state.playlists:
        raise HTTPException(404, "Playlist not found")
    updated = Playlist(
        id=playlist_id,
        name=body.name,
        items=[PlaylistItem(run_id=it.run_id, duration=it.duration) for it in body.items],
    )
    store.save_playlist(updated)
    await _maybe_reload(request)
    return _playlist_view(store, updated)


@router.delete("/playlists/{playlist_id}", status_code=204)
async def delete_playlist(request: Request, playlist_id: str) -> None:
    store = request.app.state.store
    if playlist_id not in store.state.playlists:
        raise HTTPException(404, "Playlist not found")
    store.delete_playlist(playlist_id)
    await _maybe_reload(request)


@router.post("/playlists/{playlist_id}/activate")
async def activate_playlist(request: Request, playlist_id: str) -> dict[str, Any]:
    store = request.app.state.store
    if playlist_id not in store.state.playlists:
        raise HTTPException(404, "Playlist not found")
    store.set_active(playlist_id)
    await _reload_scene_manager(request, playlist_id)
    return {"ok": True, "active_playlist_id": playlist_id}


# ── Session controls ───────────────────────────────────────────────────────────


@router.post("/playlist/next")
async def next_scene(request: Request) -> dict[str, Any]:
    sm = request.app.state.scene_manager
    await sm.next_scene()
    return {"current_idx": sm.current_idx}


@router.get("/status")
def get_status(request: Request) -> dict[str, Any]:
    store = request.app.state.store
    sm = request.app.state.scene_manager
    active_pid = store.state.active_playlist_id
    active_pl = store.state.playlists.get(active_pid) if active_pid else None
    return {
        **sm.get_status(),
        "active_playlist": {"id": active_pl.id, "name": active_pl.name}
        if active_pl
        else None,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────


def _require_plugin(plugin_id: str) -> None:
    from plugins import REGISTRY

    if plugin_id not in REGISTRY:
        raise HTTPException(422, f"Unknown plugin id: {plugin_id!r}")


async def _reload_scene_manager(request: Request, playlist_id: str | None = None) -> None:
    store = request.app.state.store
    sm = request.app.state.scene_manager
    resolved = store.resolve(playlist_id)
    entries = [
        SMEntry(plugin_id=e["plugin_id"], config=e["config"], duration=e["duration"])
        for e in resolved
    ]
    await sm.set_playlist(entries)


async def _maybe_reload(request: Request) -> None:
    """Reload scene manager only if the active playlist is affected."""
    store = request.app.state.store
    if store.state.active_playlist_id:
        await _reload_scene_manager(request)
