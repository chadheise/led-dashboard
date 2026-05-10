from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from scene_manager import PlaylistEntry as SMEntry
from state import Module, Playlist, PlaylistItem

router = APIRouter(prefix="/api")


# ── Request bodies ─────────────────────────────────────────────────────────────


class PreviewBody(BaseModel):
    app_id: str
    config: dict[str, Any] = {}


class ModuleBody(BaseModel):
    name: str
    app_id: str
    config: dict[str, Any] = {}


class PlaylistItemBody(BaseModel):
    module_id: str
    duration: float = 30.0


class PlaylistBody(BaseModel):
    name: str
    items: list[PlaylistItemBody] = []


# ── Edit preview ──────────────────────────────────────────────────────────────


@router.post("/preview")
async def start_preview(request: Request, body: PreviewBody) -> dict[str, Any]:
    from apps import APP_REGISTRY

    _require_app(body.app_id)
    await request.app.state.preview_manager.start(body.app_id, body.config, APP_REGISTRY)
    return {"ok": True}


@router.delete("/preview", status_code=204)
async def stop_preview(request: Request) -> None:
    await request.app.state.preview_manager.stop()


@router.post("/preview/playpause")
async def toggle_preview_pause(request: Request) -> dict[str, Any]:
    pm = request.app.state.preview_manager
    paused = pm.toggle_pause()
    return {"paused": paused}


# ── App type catalog ───────────────────────────────────────────────────────────


@router.get("/apps")
def list_apps() -> list[dict[str, Any]]:
    from apps import APP_REGISTRY

    return [
        {
            "id": cls.id,
            "name": cls.name,
            "description": cls.description,
            "icon": cls.icon,
            "schema": cls.config_schema,
        }
        for cls in APP_REGISTRY.values()
    ]


# ── Modules CRUD ───────────────────────────────────────────────────────────────


@router.get("/modules")
def list_modules(request: Request) -> list[dict[str, Any]]:
    store = request.app.state.store
    return [m.model_dump() for m in store.state.modules.values()]


@router.post("/modules", status_code=201)
def create_module(request: Request, body: ModuleBody) -> dict[str, Any]:
    store = request.app.state.store
    _require_app(body.app_id)
    module = store.save_module(
        Module(name=body.name, app_id=body.app_id, config=body.config)
    )
    return module.model_dump()


@router.put("/modules/{module_id}")
async def update_module(
    request: Request, module_id: str, body: ModuleBody
) -> dict[str, Any]:
    store = request.app.state.store
    if module_id not in store.state.modules:
        raise HTTPException(404, "Module not found")
    _require_app(body.app_id)
    updated = Module(id=module_id, name=body.name, app_id=body.app_id, config=body.config)
    store.save_module(updated)
    await _maybe_reload(request)
    return updated.model_dump()


@router.delete("/modules/{module_id}", status_code=204)
async def delete_module(request: Request, module_id: str) -> None:
    store = request.app.state.store
    if module_id not in store.state.modules:
        raise HTTPException(404, "Module not found")
    store.delete_module(module_id)
    await _maybe_reload(request)


# ── Playlists CRUD ─────────────────────────────────────────────────────────────


def _playlist_view(store: Any, pl: Playlist) -> dict[str, Any]:
    """Serialise a playlist with module names resolved for display."""
    items = []
    for it in pl.items:
        module = store.state.modules.get(it.module_id)
        items.append(
            {
                "module_id": it.module_id,
                "module_name": module.name if module else "(deleted)",
                "app_id": module.app_id if module else None,
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
            items=[
                PlaylistItem(module_id=it.module_id, duration=it.duration)
                for it in body.items
            ],
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
        items=[
            PlaylistItem(module_id=it.module_id, duration=it.duration)
            for it in body.items
        ],
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


@router.post("/playlist/prev")
async def prev_scene(request: Request) -> dict[str, Any]:
    sm = request.app.state.scene_manager
    await sm.prev_scene()
    return {"current_idx": sm.current_idx}


@router.post("/playlist/next")
async def next_scene(request: Request) -> dict[str, Any]:
    sm = request.app.state.scene_manager
    await sm.next_scene()
    return {"current_idx": sm.current_idx}


@router.post("/playlist/playpause")
async def toggle_playpause(request: Request) -> dict[str, Any]:
    sm = request.app.state.scene_manager
    sm.set_paused(not sm.paused)
    return {"paused": sm.paused}


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


def _require_app(app_id: str) -> None:
    from apps import APP_REGISTRY

    if app_id not in APP_REGISTRY:
        raise HTTPException(422, f"Unknown app id: {app_id!r}")


async def _reload_scene_manager(
    request: Request, playlist_id: str | None = None
) -> None:
    store = request.app.state.store
    sm = request.app.state.scene_manager
    resolved = store.resolve(playlist_id)
    entries = [
        SMEntry(app_id=e["app_id"], config=e["config"], duration=e["duration"])
        for e in resolved
    ]
    await sm.set_playlist(entries)


async def _maybe_reload(request: Request) -> None:
    store = request.app.state.store
    if store.state.active_playlist_id:
        await _reload_scene_manager(request)
