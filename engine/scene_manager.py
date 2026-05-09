from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from canvas.base import Canvas
from plugin_base import DisplayPlugin

logger = logging.getLogger(__name__)


@dataclass
class PlaylistEntry:
    plugin_id: str
    config: dict[str, Any]
    duration: float = 30.0
    entry_id: str = field(default_factory=lambda: str(uuid4()))


class SceneManager:
    def __init__(self, canvas: Canvas, registry: dict[str, type[DisplayPlugin]]) -> None:
        self._canvas = canvas
        self._registry = registry
        self._entries: list[PlaylistEntry] = []
        self._plugins: list[DisplayPlugin] = []
        self._current_idx = 0
        self._last_switch = time.monotonic()
        self._fetch_tasks: list[asyncio.Task[None]] = []
        self._running = False

    # ── Playlist management ────────────────────────────────────────────────

    async def set_playlist(self, entries: list[PlaylistEntry]) -> None:
        was_running = self._running
        if was_running:
            await self._stop_tasks()

        self._entries = entries
        self._plugins = []
        for entry in entries:
            cls = self._registry.get(entry.plugin_id)
            if cls is None:
                raise ValueError(f"Unknown plugin id: {entry.plugin_id!r}")
            self._plugins.append(cls(entry.config, self._canvas))

        self._current_idx = 0
        self._last_switch = time.monotonic()

        if was_running and self._plugins:
            await self._start_tasks()

    def get_playlist(self) -> list[dict[str, Any]]:
        return [
            {
                "id": entry.entry_id,
                "plugin_id": entry.plugin_id,
                "config": entry.config,
                "duration": entry.duration,
            }
            for entry in self._entries
        ]

    # ── Scene rotation ─────────────────────────────────────────────────────

    @property
    def current(self) -> DisplayPlugin | None:
        if not self._plugins:
            return None
        return self._plugins[self._current_idx]

    @property
    def current_idx(self) -> int:
        return self._current_idx

    async def next_scene(self) -> None:
        if not self._plugins:
            return
        await self._plugins[self._current_idx].on_deactivate()
        self._current_idx = (self._current_idx + 1) % len(self._plugins)
        await self._plugins[self._current_idx].on_activate()
        self._last_switch = time.monotonic()

    async def _maybe_rotate(self) -> None:
        if len(self._plugins) <= 1 or not self._entries:
            return
        entry = self._entries[self._current_idx]
        if time.monotonic() - self._last_switch >= entry.duration:
            await self.next_scene()

    # ── Render ─────────────────────────────────────────────────────────────

    async def render_frame(self) -> None:
        await self._maybe_rotate()
        self._canvas.clear()
        plugin = self.current
        if plugin is not None:
            try:
                await plugin.render_frame()
            except Exception as exc:
                logger.warning("render_frame error in %s: %s", plugin.id, exc)
        await self._canvas.render()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        await self._start_tasks()

    async def stop(self) -> None:
        self._running = False
        await self._stop_tasks()

    async def _start_tasks(self) -> None:
        if self._plugins:
            await self._plugins[self._current_idx].on_activate()
        for plugin in self._plugins:
            task = asyncio.create_task(self._fetch_loop(plugin))
            self._fetch_tasks.append(task)

    async def _stop_tasks(self) -> None:
        for task in self._fetch_tasks:
            task.cancel()
        if self._fetch_tasks:
            await asyncio.gather(*self._fetch_tasks, return_exceptions=True)
        self._fetch_tasks.clear()
        if self._plugins:
            await self._plugins[self._current_idx].on_deactivate()

    async def _fetch_loop(self, plugin: DisplayPlugin) -> None:
        while True:
            try:
                await plugin.fetch_data()
            except Exception as exc:
                logger.warning("fetch_data error in %s: %s", plugin.id, exc)
            await asyncio.sleep(plugin.refresh_interval)

    # ── Status ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        current = self.current
        return {
            "current_plugin": current.id if current else None,
            "current_idx": self._current_idx,
            "scene_count": len(self._plugins),
        }
