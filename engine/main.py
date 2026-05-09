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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def _entries_from_config(playlist_cfg: list[dict[str, Any]]) -> list[PlaylistEntry]:
    return [
        PlaylistEntry(
            plugin_id=e["plugin_id"],
            config=e.get("config", {}),
            duration=float(e.get("duration", 30.0)),
        )
        for e in playlist_cfg
    ]


def _default_entries() -> list[PlaylistEntry]:
    return [
        PlaylistEntry(
            plugin_id="text",
            config={"message": "LED Wall Display", "scroll": True, "font_size": 16},
            duration=30.0,
        )
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
    scene_manager = SceneManager(canvas, REGISTRY)

    playlist_cfg: list[dict[str, Any]] = cfg.get("playlist", [])
    entries = _entries_from_config(playlist_cfg) if playlist_cfg else _default_entries()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await scene_manager.set_playlist(entries)
        await scene_manager.start()
        task = asyncio.create_task(_render_loop(scene_manager, display_cfg["fps"]))
        try:
            yield
        finally:
            task.cancel()
            await scene_manager.stop()

    app = create_app(lifespan=lifespan)
    app.state.scene_manager = scene_manager
    uvicorn.run(app, host=server_cfg["host"], port=server_cfg["port"])


if __name__ == "__main__":
    main()
