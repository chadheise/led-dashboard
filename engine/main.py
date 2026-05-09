import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
import yaml
from fastapi import FastAPI

from api.server import create_app
from api.websocket import manager
from canvas.simulator import SimulatorCanvas
from plugins import REGISTRY
from scene_manager import PlaylistEntry, SceneManager
from state import Playlist, PlaylistItem, Run, StateStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def _seed_from_config(store: StateStore, playlist_cfg: list[dict[str, Any]]) -> None:
    """Bootstrap state.json from config.yaml playlist on first run."""
    items: list[PlaylistItem] = []
    for i, entry in enumerate(playlist_cfg):
        plugin_id = entry.get("plugin_id", "text")
        config: dict[str, Any] = entry.get("config", {})
        duration = float(entry.get("duration", 30.0))
        name = str(config.get("message") or f"{plugin_id.title()} {i + 1}")
        run = store.save_run(Run(name=name, plugin_id=plugin_id, config=config))
        items.append(PlaylistItem(run_id=run.id, duration=duration))
    if items:
        pl = store.save_playlist(Playlist(name="Default", items=items))
        store.set_active(pl.id)


def _seed_default(store: StateStore) -> None:
    """Create a minimal default state when nothing else is available."""
    run = store.save_run(
        Run(
            name="Welcome",
            plugin_id="text",
            config={"message": "LED Wall Display", "scroll": True, "font_size": 16, "color": "#00FFAA"},
        )
    )
    pl = store.save_playlist(Playlist(name="Default", items=[PlaylistItem(run_id=run.id, duration=30.0)]))
    store.set_active(pl.id)


def _sm_entries(store: StateStore) -> list[PlaylistEntry]:
    return [
        PlaylistEntry(plugin_id=e["plugin_id"], config=e["config"], duration=e["duration"])
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

    canvas = SimulatorCanvas(
        display_cfg["width"], display_cfg["height"], manager.broadcast
    )
    store = StateStore()
    scene_manager = SceneManager(canvas, REGISTRY)

    # Seed persisted state on first run
    if not store.state.runs:
        playlist_cfg: list[dict[str, Any]] = cfg.get("playlist", [])
        if playlist_cfg:
            _seed_from_config(store, playlist_cfg)
        else:
            _seed_default(store)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await scene_manager.set_playlist(_sm_entries(store))
        await scene_manager.start()
        task = asyncio.create_task(_render_loop(scene_manager, display_cfg["fps"]))
        try:
            yield
        finally:
            task.cancel()
            await scene_manager.stop()

    app = create_app(lifespan=lifespan, store=store, scene_manager=scene_manager)
    uvicorn.run(app, host=server_cfg["host"], port=server_cfg["port"])


if __name__ == "__main__":
    main()
