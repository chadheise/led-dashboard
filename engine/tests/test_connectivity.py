"""Tests for the "No wifi connection" overlay and its connectivity check."""
from __future__ import annotations

import asyncio
import socket

import pytest

import connectivity as connectivity_module
from canvas.simulator import SimulatorCanvas
from connectivity import ConnectivityMonitor, check_internet, draw_offline_message
from scene_manager import PlaylistEntry, SceneManager
from app_base import DisplayApp


async def _noop_broadcast(_: bytes) -> None:
    pass


class _RecordingApp(DisplayApp):
    id = "recording"
    name = "Recording"
    config_schema: dict = {}
    render_calls = 0

    async def fetch_data(self) -> None:
        pass

    async def render_frame(self) -> None:
        _RecordingApp.render_calls += 1


class _FakeConnectivity:
    def __init__(self, online: bool) -> None:
        self.is_online = online


def test_check_internet_true_when_connection_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _FakeSocketCM())

    assert check_internet(timeout=0.1) is True


def test_check_internet_false_when_all_probes_fail(monkeypatch) -> None:
    def _raise(*_a, **_k):
        raise OSError("network unreachable")

    monkeypatch.setattr(socket, "create_connection", _raise)

    assert check_internet(timeout=0.1) is False


class _FakeSocketCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_connectivity_monitor_starts_optimistic_and_updates() -> None:
    monitor = ConnectivityMonitor(check_interval=0.01, timeout=0.01)
    assert monitor.is_online is True

    calls = iter([False, False, False])

    def _fake_check(_timeout: float) -> bool:
        return next(calls, False)

    orig = connectivity_module.check_internet
    connectivity_module.check_internet = _fake_check
    try:
        await monitor.start()
        for _ in range(50):
            if monitor.is_online is False:
                break
            await asyncio.sleep(0.01)
        assert monitor.is_online is False
    finally:
        await monitor.stop()
        connectivity_module.check_internet = orig


def test_draw_offline_message_renders_non_blank_pixels() -> None:
    canvas = SimulatorCanvas(320, 64, _noop_broadcast)
    canvas.clear()

    draw_offline_message(canvas)

    assert any(b != 0 for b in canvas._pixels)


@pytest.mark.asyncio
async def test_scene_manager_shows_offline_message_instead_of_apps() -> None:
    _RecordingApp.render_calls = 0
    canvas = SimulatorCanvas(320, 64, _noop_broadcast)
    sm = SceneManager(canvas, {"recording": _RecordingApp}, connectivity=_FakeConnectivity(online=False))
    await sm.set_playlist([PlaylistEntry(app_id="recording", config={}, duration=30.0)])
    await sm.start()
    try:
        canvas.clear()
        await sm.render_frame()
        assert _RecordingApp.render_calls == 0
        assert any(b != 0 for b in canvas._pixels)
    finally:
        await sm.stop()


@pytest.mark.asyncio
async def test_scene_manager_renders_apps_when_online() -> None:
    _RecordingApp.render_calls = 0
    canvas = SimulatorCanvas(320, 64, _noop_broadcast)
    sm = SceneManager(canvas, {"recording": _RecordingApp}, connectivity=_FakeConnectivity(online=True))
    await sm.set_playlist([PlaylistEntry(app_id="recording", config={}, duration=30.0)])
    await sm.start()
    try:
        await sm.render_frame()
        assert _RecordingApp.render_calls == 1
    finally:
        await sm.stop()
