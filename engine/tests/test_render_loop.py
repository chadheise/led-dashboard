"""The render loop paces itself to the configured fps.

On hardware an unpaced loop redraws continuously and keeps a core busy, which
starves the rgbmatrix refresh thread and flickers the panel, so the loop must
idle between frames -- including when render_frame() returns immediately
(paused, or simply a cheap frame).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from main import _render_loop


class _CountingSceneManager:
    """Stands in for SceneManager; records how often a frame was requested."""

    def __init__(self, frame_cost: float = 0.0) -> None:
        self.frames = 0
        self._frame_cost = frame_cost

    async def render_frame(self) -> None:
        self.frames += 1
        if self._frame_cost:
            await asyncio.sleep(self._frame_cost)


async def _run_for(scene_manager: _CountingSceneManager, fps: int, seconds: float) -> None:
    task = asyncio.create_task(_render_loop(scene_manager, fps))  # type: ignore[arg-type]
    await asyncio.sleep(seconds)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_instant_frames_are_paced_not_spun() -> None:
    scene_manager = _CountingSceneManager()
    await _run_for(scene_manager, fps=50, seconds=0.3)
    # ~15 frames at 50 fps. The old hardware path had no sleep at all and would
    # run thousands of iterations in the same window.
    assert 5 <= scene_manager.frames <= 40


@pytest.mark.asyncio
async def test_slow_frames_do_not_compound_with_the_sleep() -> None:
    """A frame that eats most of the interval still leaves the rate near fps."""
    scene_manager = _CountingSceneManager(frame_cost=0.015)
    await _run_for(scene_manager, fps=50, seconds=0.3)
    # 15ms of work inside a 20ms budget: deadline pacing keeps this near 15
    # frames. Sleeping a full interval *after* each frame would halve it.
    assert scene_manager.frames >= 8


@pytest.mark.asyncio
async def test_overrunning_frames_still_yield_to_the_event_loop() -> None:
    """Frames slower than the interval must not starve other tasks."""
    scene_manager = _CountingSceneManager(frame_cost=0.03)
    other_ran = 0

    async def _other() -> None:
        nonlocal other_ran
        while True:
            other_ran += 1
            await asyncio.sleep(0.01)

    other = asyncio.create_task(_other())
    await _run_for(scene_manager, fps=100, seconds=0.2)
    other.cancel()

    assert scene_manager.frames >= 3
    assert other_ran >= 3


@pytest.mark.asyncio
async def test_render_errors_do_not_stop_the_loop() -> None:
    class _Failing(_CountingSceneManager):
        async def render_frame(self) -> None:
            await super().render_frame()
            raise RuntimeError("boom")

    scene_manager = _Failing()
    await _run_for(scene_manager, fps=50, seconds=0.15)
    assert scene_manager.frames > 1


@pytest.mark.asyncio
async def test_loop_does_not_drift_behind_wall_clock() -> None:
    scene_manager = _CountingSceneManager()
    start = time.monotonic()
    await _run_for(scene_manager, fps=20, seconds=0.5)
    elapsed = time.monotonic() - start
    # At 20 fps we expect ~10 frames in half a second; allow wide slack for a
    # loaded machine but catch a loop that has stopped rendering entirely.
    assert scene_manager.frames >= 3
    assert elapsed < 1.0
