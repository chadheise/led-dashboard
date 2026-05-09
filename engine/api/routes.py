from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")


class PlaylistEntryRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    plugin_id: str
    config: dict[str, Any] = {}
    duration: float = 30.0


@router.get("/plugins")
def list_plugins() -> list[dict[str, Any]]:
    from plugins import REGISTRY

    return [
        {"id": cls.id, "name": cls.name, "schema": cls.config_schema}
        for cls in REGISTRY.values()
    ]


@router.get("/playlist")
def get_playlist(request: Request) -> list[dict[str, Any]]:
    return request.app.state.scene_manager.get_playlist()


@router.post("/playlist")
async def set_playlist(
    request: Request, entries: list[PlaylistEntryRequest]
) -> dict[str, Any]:
    from plugins import REGISTRY
    from scene_manager import PlaylistEntry

    sm = request.app.state.scene_manager
    try:
        await sm.set_playlist(
            [
                PlaylistEntry(
                    plugin_id=e.plugin_id,
                    config=e.config,
                    duration=e.duration,
                    entry_id=e.id,
                )
                for e in entries
            ]
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "count": len(entries)}


@router.post("/playlist/next")
async def next_scene(request: Request) -> dict[str, Any]:
    sm = request.app.state.scene_manager
    await sm.next_scene()
    return {"current_idx": sm.current_idx}


@router.get("/status")
def get_status(request: Request) -> dict[str, Any]:
    return request.app.state.scene_manager.get_status()
