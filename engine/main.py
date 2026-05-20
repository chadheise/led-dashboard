import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import FastAPI

from api.preview import PreviewManager, SizesPreviewManager
from api.server import create_app
from api.websocket import manager
from canvas.hardware import HardwareCanvas
from canvas.simulator import SimulatorCanvas
from apps import APP_REGISTRY
from scene_manager import PlaylistEntry, SceneManager
from state import Module, Playlist, PlaylistItem, StateStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def _seed_from_config(store: StateStore, playlist_cfg: list[dict[str, Any]]) -> None:
    """Bootstrap state.json from config.yaml playlist on first run."""
    items: list[PlaylistItem] = []
    for i, entry in enumerate(playlist_cfg):
        app_id = entry.get("app_id", "text")
        config: dict[str, Any] = entry.get("config", {})
        duration = float(entry.get("duration", 30.0))
        name = str(config.get("message") or f"{app_id.title()} {i + 1}")
        module = store.save_module(Module(name=name, app_id=app_id, config=config))
        items.append(PlaylistItem(module_id=module.id, duration=duration))
    if items:
        pl = store.save_playlist(Playlist(name="Default", items=items))
        store.set_active(pl.id)


def _seed_default(store: StateStore) -> None:
    """Create a minimal default state when nothing else is available."""
    module = store.save_module(
        Module(
            name="Welcome",
            app_id="text",
            config={"message": "LED Wall Display", "scroll": True, "font_size": 16, "color": "#00FFAA"},
        )
    )
    pl = store.save_playlist(
        Playlist(name="Default", items=[PlaylistItem(module_id=module.id, duration=30.0)])
    )
    store.set_active(pl.id)


def _sm_entries(store: StateStore) -> list[PlaylistEntry]:
    return [
        PlaylistEntry(
            app_id=e["app_id"],
            config=e["config"],
            duration=e["duration"],
            global_config=e.get("global_config", {}),
        )
        for e in store.resolve()
    ]


async def _render_loop(scene_manager: SceneManager, fps: int) -> None:
    interval = 1.0 / fps
    while True:
        try:
            await scene_manager.render_frame()
        except Exception as exc:
            logger.warning("Render loop error: %s", exc)
        await asyncio.sleep(interval)


def main() -> None:
    cfg = _load_config()
    display_cfg = cfg["display"]
    server_cfg = cfg["server"]

    if os.environ.get("CANVAS", "").lower() == "hardware":
        preview_enabled = os.environ.get("PREVIEW_ENABLED", "true").lower() != "false"

        async def _noop(_: bytes) -> None:
            pass

        broadcast = manager.broadcast if preview_enabled else _noop
        canvas = HardwareCanvas(
            display_cfg["width"], display_cfg["height"], cfg.get("hardware", {}), broadcast
        )
    else:
        canvas = SimulatorCanvas(
            display_cfg["width"], display_cfg["height"], manager.broadcast
        )
    store = StateStore()
    scene_manager = SceneManager(canvas, APP_REGISTRY)
    preview_manager = PreviewManager(
        display_cfg["width"], display_cfg["height"], display_cfg["fps"]
    )
    sizes_preview_manager = SizesPreviewManager(display_cfg["fps"])

    # Seed persisted state on first run
    if not store.state.modules:
        playlist_cfg: list[dict[str, Any]] = cfg.get("playlist", [])
        if playlist_cfg:
            _seed_from_config(store, playlist_cfg)
        else:
            _seed_default(store)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await scene_manager.set_playlist(_sm_entries(store))
        await scene_manager.start()
        render_task = asyncio.create_task(_render_loop(scene_manager, display_cfg["fps"]))
        hot_reload_task: asyncio.Task | None = None
        if os.environ.get("HOT_RELOAD", "").lower() == "true":
            from hot_reload import start_hot_reload_watcher
            from libraries import LIBRARY_REGISTRY
            hot_reload_task = asyncio.create_task(
                start_hot_reload_watcher(
                    store, scene_manager, APP_REGISTRY, LIBRARY_REGISTRY, Path(__file__).parent
                )
            )
            logger.info("Hot-reload enabled")
        try:
            yield
        finally:
            render_task.cancel()
            if hot_reload_task is not None:
                hot_reload_task.cancel()
                try:
                    await hot_reload_task
                except (asyncio.CancelledError, Exception):
                    pass
            await scene_manager.stop()

    app = create_app(
        lifespan=lifespan,
        store=store,
        scene_manager=scene_manager,
        preview_manager=preview_manager,
        sizes_preview_manager=sizes_preview_manager,
    )
    uvicorn.run(app, host=server_cfg["host"], port=server_cfg["port"])


if __name__ == "__main__":
    main()
