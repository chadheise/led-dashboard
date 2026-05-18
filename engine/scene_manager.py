from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from canvas.base import Canvas
from app_base import DisplayApp

logger = logging.getLogger(__name__)


@dataclass
class RegionSpec:
    """One app within a SceneLayout."""
    app_id: str
    config: dict[str, Any] = field(default_factory=dict)
    global_config: dict[str, Any] = field(default_factory=dict)
    library_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    weight: int = 1  # proportional share of the split dimension


@dataclass
class SceneLayout:
    """Splits the canvas across multiple apps for one playlist entry."""
    direction: Literal["horizontal", "vertical"] = "horizontal"
    regions: list[RegionSpec] = field(default_factory=list)


@dataclass
class PlaylistEntry:
    app_id: str
    config: dict[str, Any]
    duration: float = 30.0
    global_config: dict[str, Any] = field(default_factory=dict)
    library_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    entry_id: str = field(default_factory=lambda: str(uuid4()))
    layout: SceneLayout | None = None  # None = single app filling the full canvas


class SceneManager:
    def __init__(self, canvas: Canvas, registry: dict[str, type[DisplayApp]]) -> None:
        self._canvas = canvas
        self._registry = registry
        self._entries: list[PlaylistEntry] = []
        # Each scene is a list of (app, canvas) pairs. Single-app scenes have one pair.
        self._scenes: list[list[tuple[DisplayApp, Canvas]]] = []
        self._current_idx = 0
        self._last_switch = time.monotonic()
        self._fetch_tasks: list[asyncio.Task[None]] = []
        self._running = False
        self._paused = False

    @property
    def current_entry(self) -> PlaylistEntry | None:
        if not self._entries:
            return None
        return self._entries[self._current_idx % len(self._entries)]

    # ── Playlist management ────────────────────────────────────────────────

    async def set_playlist(self, entries: list[PlaylistEntry]) -> None:
        was_running = self._running
        if was_running:
            await self._stop_tasks()

        self._entries = entries
        self._scenes = []
        for entry in entries:
            if entry.layout is None:
                cls = self._registry.get(entry.app_id)
                if cls is None:
                    raise ValueError(f"Unknown app id: {entry.app_id!r}")
                app = cls(entry.config, self._canvas, entry.global_config, entry.library_configs)
                self._scenes.append([(app, self._canvas)])
            else:
                self._scenes.append(self._build_layout_scene(entry))

        self._current_idx = 0
        self._last_switch = time.monotonic()

        if was_running and self._scenes:
            await self._start_tasks()

    def _build_layout_scene(self, entry: PlaylistEntry) -> list[tuple[DisplayApp, Canvas]]:
        from canvas.region import CanvasRegion
        layout = entry.layout
        assert layout is not None

        specs = layout.regions
        n = len(specs)
        if n == 0:
            return []

        total_weight = sum(max(1, s.weight) for s in specs)
        canvas_dim = self._canvas.width if layout.direction == "horizontal" else self._canvas.height
        pairs: list[tuple[DisplayApp, Canvas]] = []
        offset = 0

        for i, spec in enumerate(specs):
            if i < n - 1:
                size = round(canvas_dim * max(1, spec.weight) / total_weight)
            else:
                size = canvas_dim - offset

            if layout.direction == "horizontal":
                region: Canvas = CanvasRegion(self._canvas, offset, 0, size, self._canvas.height)
            else:
                region = CanvasRegion(self._canvas, 0, offset, self._canvas.width, size)

            cls = self._registry.get(spec.app_id)
            if cls is None:
                raise ValueError(f"Unknown app id: {spec.app_id!r}")
            if not cls.size_constraints.satisfied_by(region):
                logger.warning(
                    "App %r placed in %dx%d region which may be too small "
                    "(requires min %dx%d px)",
                    spec.app_id, region.width, region.height,
                    cls.size_constraints.min_width, cls.size_constraints.min_height,
                )
            app = cls(spec.config, region, spec.global_config, spec.library_configs)
            pairs.append((app, region))
            offset += size

        return pairs

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

    def _current_scene(self) -> list[tuple[DisplayApp, Canvas]]:
        if not self._scenes:
            return []
        return self._scenes[self._current_idx]

    @property
    def current(self) -> DisplayApp | None:
        """Return the primary app of the current scene (first app in a layout scene)."""
        scene = self._current_scene()
        return scene[0][0] if scene else None

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
        if not self._scenes:
            return
        for app, _ in self._current_scene():
            await app.on_deactivate()
        self._current_idx = (self._current_idx - 1) % len(self._scenes)
        for app, _ in self._current_scene():
            await app.on_activate()
        self._last_switch = time.monotonic()
        self._paused = False  # navigation always resumes so the new scene is visible

    async def next_scene(self) -> None:
        if not self._scenes:
            return
        for app, _ in self._current_scene():
            await app.on_deactivate()
        self._current_idx = (self._current_idx + 1) % len(self._scenes)
        for app, _ in self._current_scene():
            await app.on_activate()
        self._last_switch = time.monotonic()
        self._paused = False  # navigation always resumes so the new scene is visible

    async def _maybe_rotate(self) -> None:
        if self._paused or len(self._scenes) <= 1 or not self._entries:
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
        scene = self._current_scene()
        if scene:
            await asyncio.gather(*[self._render_one(app) for app, _ in scene])
        await self._canvas.render()

    async def _render_one(self, app: DisplayApp) -> None:
        try:
            await app.render_frame()
        except Exception as exc:
            logger.warning("render_frame error in %s: %s", app.id, exc)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        await self._start_tasks()

    async def stop(self) -> None:
        self._running = False
        await self._stop_tasks()

    def _all_apps(self) -> list[DisplayApp]:
        return [app for scene in self._scenes for app, _ in scene]

    async def _start_tasks(self) -> None:
        for app, _ in self._current_scene():
            await app.on_activate()
        for app in self._all_apps():
            task = asyncio.create_task(self._fetch_loop(app))
            self._fetch_tasks.append(task)

    async def _stop_tasks(self) -> None:
        for task in self._fetch_tasks:
            task.cancel()
        if self._fetch_tasks:
            await asyncio.gather(*self._fetch_tasks, return_exceptions=True)
        self._fetch_tasks.clear()
        for app, _ in self._current_scene():
            await app.on_deactivate()

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
            "scene_count": len(self._scenes),
            "paused": self._paused,
        }
