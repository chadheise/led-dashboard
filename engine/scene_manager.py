from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from canvas.base import Canvas
from plugin_base import DisplayApp

logger = logging.getLogger(__name__)


@dataclass
class PlaylistEntry:
    app_id: str
    config: dict[str, Any]
    duration: float = 30.0
    global_config: dict[str, Any] = field(default_factory=dict)
    entry_id: str = field(default_factory=lambda: str(uuid4()))


class SceneManager:
    def __init__(self, canvas: Canvas, registry: dict[str, type[DisplayApp]]) -> None:
        self._canvas = canvas
        self._registry = registry
        self._entries: list[PlaylistEntry] = []
        self._apps: list[DisplayApp] = []
        self._current_idx = 0
        self._last_switch = time.monotonic()
        self._fetch_tasks: list[asyncio.Task[None]] = []
        self._running = False
        self._paused = False

    # ── Playlist management ────────────────────────────────────────────────

    async def set_playlist(self, entries: list[PlaylistEntry]) -> None:
        was_running = self._running
        if was_running:
            await self._stop_tasks()

        self._entries = entries
        self._apps = []
        for entry in entries:
            cls = self._registry.get(entry.app_id)
            if cls is None:
                raise ValueError(f"Unknown app id: {entry.app_id!r}")
            self._apps.append(cls(entry.config, self._canvas, entry.global_config))

        self._current_idx = 0
        self._last_switch = time.monotonic()

        if was_running and self._apps:
            await self._start_tasks()

    def get_playlist(self) -> list[dict[str, Any]]:
        return [
            {
                "id": entry.entry_id,
                "app_id": entry.app_id,
                "config": entry.config,
                "duration": entry.duration,
            }
            for entry in self._entries
        ]

    # ── Scene rotation ─────────────────────────────────────────────────────

    @property
    def current(self) -> DisplayApp | None:
        if not self._apps:
            return None
        return self._apps[self._current_idx]

    @property
    def current_idx(self) -> int:
        return self._current_idx

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if not paused:
            self._last_switch = time.monotonic()  # reset timer on resume

    async def prev_scene(self) -> None:
        if not self._apps:
            return
        await self._apps[self._current_idx].on_deactivate()
        self._current_idx = (self._current_idx - 1) % len(self._apps)
        await self._apps[self._current_idx].on_activate()
        self._last_switch = time.monotonic()
        self._paused = False  # navigation always resumes so the new scene is visible

    async def next_scene(self) -> None:
        if not self._apps:
            return
        await self._apps[self._current_idx].on_deactivate()
        self._current_idx = (self._current_idx + 1) % len(self._apps)
        await self._apps[self._current_idx].on_activate()
        self._last_switch = time.monotonic()
        self._paused = False  # navigation always resumes so the new scene is visible

    async def _maybe_rotate(self) -> None:
        if self._paused or len(self._apps) <= 1 or not self._entries:
            return
        entry = self._entries[self._current_idx]
        if time.monotonic() - self._last_switch >= entry.duration:
            await self.next_scene()

    # ── Render ─────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        await self._maybe_rotate()
        if self._paused:
            return  # keep last broadcast frame frozen in the browser
        self._canvas.clear()
        app = self.current
        if app is not None:
            try:
                await app.render_frame()
            except Exception as exc:
                logger.warning("render_frame error in %s: %s", app.id, exc)
        await self._canvas.render()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        await self._start_tasks()

    async def stop(self) -> None:
        self._running = False
        await self._stop_tasks()

    async def _start_tasks(self) -> None:
        if self._apps:
            await self._apps[self._current_idx].on_activate()
        for app in self._apps:
            task = asyncio.create_task(self._fetch_loop(app))
            self._fetch_tasks.append(task)

    async def _stop_tasks(self) -> None:
        for task in self._fetch_tasks:
            task.cancel()
        if self._fetch_tasks:
            await asyncio.gather(*self._fetch_tasks, return_exceptions=True)
        self._fetch_tasks.clear()
        if self._apps:
            await self._apps[self._current_idx].on_deactivate()

    async def _fetch_loop(self, app: DisplayApp) -> None:
        while True:
            try:
                await app.fetch_data()
            except Exception as exc:
                logger.warning("fetch_data error in %s: %s", app.id, exc)
            await asyncio.sleep(app.refresh_interval)

    # ── Status ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        current = self.current
        return {
            "current_app": current.id if current else None,
            "current_idx": self._current_idx,
            "scene_count": len(self._apps),
            "paused": self._paused,
        }
