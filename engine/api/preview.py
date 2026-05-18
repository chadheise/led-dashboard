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
from app_base import DisplayApp

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
_sizes_manager = _ConnectionManager()


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


@router.websocket("/ws/preview/sizes")
async def ws_preview_sizes(ws: WebSocket) -> None:
    await _sizes_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _sizes_manager.disconnect(ws)


# ── Preview renderer ───────────────────────────────────────────────────────────


class PreviewManager:
    """Renders one plugin config at a time to the /ws/preview/edit channel."""

    def __init__(self, width: int, height: int, fps: int) -> None:
        self._canvas = SimulatorCanvas(width, height, _manager.broadcast)
        self._fps = fps
        self._render_task: asyncio.Task[None] | None = None
        self._fetch_task: asyncio.Task[None] | None = None
        self._paused: bool = False

    @property
    def paused(self) -> bool:
        return self._paused

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        return self._paused

    async def start(
        self,
        app_id: str,
        config: dict[str, Any],
        registry: dict[str, type[DisplayApp]],
        *,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        await self.stop()
        self._paused = False  # always start playing
        cls = registry.get(app_id)
        if cls is None:
            raise ValueError(f"Unknown plugin id: {app_id!r}")
        plugin = cls(config, self._canvas, global_config, library_configs)
        # on_activate already calls fetch_data for apps that override it (e.g. SportsApp),
        # so this covers the initial data load synchronously before rendering starts.
        await plugin.on_activate()
        self._render_task = asyncio.create_task(self._render_loop(plugin))
        # Periodic re-fetch keeps preview data fresh while editing
        self._fetch_task = asyncio.create_task(self._fetch_periodic(plugin))

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

    async def _fetch_periodic(self, plugin: DisplayApp) -> None:
        while True:
            await asyncio.sleep(plugin.refresh_interval)
            try:
                await plugin.fetch_data()
            except Exception as exc:
                logger.debug("Preview fetch_data error: %s", exc)

    async def _render_loop(self, plugin: DisplayApp) -> None:
        interval = 1.0 / self._fps
        while True:
            if not self._paused:
                self._canvas.clear()
                try:
                    await plugin.render_frame()
                except Exception as exc:
                    logger.debug("Preview render_frame error: %s", exc)
                await self._canvas.render()
            await asyncio.sleep(interval)


# ── Multi-size preview renderer ────────────────────────────────────────────────

SIZES_PANEL_DIMS: list[tuple[int, int]] = [
    (64, 32), (128, 32), (196, 32), (256, 32),
    (64, 64), (128, 64), (196, 64), (256, 64),
]


class SizesPreviewManager:
    """Renders one plugin config simultaneously at all standard panel sizes.

    Two modes:
    - Edit: start(app_id, config, ...) — renders a specific app/config
    - Live: start_live(scene_manager, registry) — tracks and mirrors the active scene
    """

    def __init__(self, fps: int) -> None:
        self._fps = fps
        self._apps: list[DisplayApp] = []
        self._render_task: asyncio.Task[None] | None = None
        self._fetch_task: asyncio.Task[None] | None = None
        self._live_task: asyncio.Task[None] | None = None
        self._paused: bool = False
        self._scene_changed: asyncio.Event = asyncio.Event()

    @property
    def paused(self) -> bool:
        return self._paused

    def notify_scene_changed(self) -> None:
        """Wake the live-follow loop immediately (call after next/prev scene)."""
        self._scene_changed.set()

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        return self._paused

    # ── Public API ─────────────────────────────────────────────────────────

    async def start(
        self,
        app_id: str,
        config: dict[str, Any],
        registry: dict[str, type[DisplayApp]],
        *,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Edit mode: render a specific app/config at all sizes."""
        await self._cancel_live()
        await self._start_apps(app_id, config, registry, global_config=global_config, library_configs=library_configs)

    async def start_live(self, scene_manager: Any, registry: dict[str, type[DisplayApp]]) -> None:
        """Live mode: follow the scene manager, re-rendering when the scene changes."""
        await self._cancel_live()
        await self._stop_apps()
        self._live_task = asyncio.create_task(self._live_follow_loop(scene_manager, registry))

    async def stop(self) -> None:
        await self._cancel_live()
        await self._stop_apps()

    # ── Internal ───────────────────────────────────────────────────────────

    async def _start_apps(
        self,
        app_id: str,
        config: dict[str, Any],
        registry: dict[str, type[DisplayApp]],
        *,
        global_config: dict[str, Any] | None = None,
        library_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        await self._stop_apps()
        self._paused = False
        cls = registry.get(app_id)
        if cls is None:
            return
        self._apps = [
            cls(
                config,
                SimulatorCanvas(w, h, _sizes_manager.broadcast),
                global_config,
                library_configs,
            )
            for w, h in SIZES_PANEL_DIMS
        ]
        await asyncio.gather(
            *(app.on_activate() for app in self._apps),
            return_exceptions=True,
        )
        self._render_task = asyncio.create_task(self._render_loop())
        self._fetch_task = asyncio.create_task(self._fetch_periodic())

    async def _stop_apps(self) -> None:
        for task in (self._render_task, self._fetch_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._render_task = None
        self._fetch_task = None
        for app in self._apps:
            try:
                await app.on_deactivate()
            except Exception:
                pass
        self._apps = []

    async def _cancel_live(self) -> None:
        if self._live_task and not self._live_task.done():
            self._live_task.cancel()
            try:
                await self._live_task
            except (asyncio.CancelledError, Exception):
                pass
        self._live_task = None

    async def _live_follow_loop(self, scene_manager: Any, registry: dict[str, type[DisplayApp]]) -> None:
        last_entry_id: str | None = None
        while True:
            entry = scene_manager.current_entry
            if entry is not None and entry.entry_id != last_entry_id:
                logger.debug("Sizes live: scene changed to %s (%s)", entry.app_id, entry.entry_id)
                await self._start_apps(
                    entry.app_id,
                    entry.config,
                    registry,
                    global_config=entry.global_config,
                    library_configs=entry.library_configs,
                )
                last_entry_id = entry.entry_id
            # Wait up to 0.5 s or until explicitly woken by notify_scene_changed()
            self._scene_changed.clear()
            try:
                await asyncio.wait_for(self._scene_changed.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    async def _render_loop(self) -> None:
        interval = 1.0 / self._fps
        while True:
            if not self._paused:
                for app in self._apps:
                    app.canvas.clear()
                    try:
                        await app.render_frame()
                    except Exception as exc:
                        logger.debug("Sizes preview render error: %s", exc)
                    await app.canvas.render()
            await asyncio.sleep(interval)

    async def _fetch_periodic(self) -> None:
        while self._apps:
            await asyncio.sleep(self._apps[0].refresh_interval)
            await asyncio.gather(
                *(app.fetch_data() for app in self._apps),
                return_exceptions=True,
            )
