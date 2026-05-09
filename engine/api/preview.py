"""Secondary WebSocket channel + render loop for edit-time previews.

Completely independent of the main SceneManager — the active playlist
continues running unchanged while this renders a single plugin config
for the UI edit form.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from canvas.simulator import SimulatorCanvas
from plugin_base import DisplayPlugin

logger = logging.getLogger(__name__)

router = APIRouter()


# ── WebSocket connection manager (mirrors the main one) ────────────────────────


class _ConnectionManager:
    def __init__(self) -> None:
        self._active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def broadcast(self, data: bytes) -> None:
        dead: set[WebSocket] = set()
        for ws in self._active:
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.add(ws)
        self._active -= dead


_manager = _ConnectionManager()


@router.websocket("/ws/preview/edit")
async def ws_preview_edit(ws: WebSocket) -> None:
    await _manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _manager.disconnect(ws)


# ── Preview renderer ───────────────────────────────────────────────────────────


class PreviewManager:
    """Renders one plugin config at a time to the /ws/preview/edit channel."""

    def __init__(self, width: int, height: int, fps: int) -> None:
        self._canvas = SimulatorCanvas(width, height, _manager.broadcast)
        self._fps = fps
        self._render_task: asyncio.Task[None] | None = None
        self._fetch_task: asyncio.Task[None] | None = None

    async def start(
        self,
        plugin_id: str,
        config: dict[str, Any],
        registry: dict[str, type[DisplayPlugin]],
    ) -> None:
        await self.stop()
        cls = registry.get(plugin_id)
        if cls is None:
            raise ValueError(f"Unknown plugin id: {plugin_id!r}")
        plugin = cls(config, self._canvas)
        await plugin.on_activate()
        # Kick off a single fetch in the background so data arrives quickly
        self._fetch_task = asyncio.create_task(self._fetch_once(plugin))
        self._render_task = asyncio.create_task(self._render_loop(plugin))

    async def stop(self) -> None:
        for task in (self._render_task, self._fetch_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._render_task = None
        self._fetch_task = None

    async def _fetch_once(self, plugin: DisplayPlugin) -> None:
        try:
            await plugin.fetch_data()
        except Exception as exc:
            logger.debug("Preview fetch_data error: %s", exc)

    async def _render_loop(self, plugin: DisplayPlugin) -> None:
        interval = 1.0 / self._fps
        while True:
            self._canvas.clear()
            try:
                await plugin.render_frame()
            except Exception as exc:
                logger.debug("Preview render_frame error: %s", exc)
            await self._canvas.render()
            await asyncio.sleep(interval)
