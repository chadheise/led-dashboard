"""Tests for the "No wifi connection" overlay and its connectivity check."""
from __future__ import annotations

import asyncio
import logging
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


def test_hysteresis_stays_online_until_threshold_consecutive_failures() -> None:
    monitor = ConnectivityMonitor(failure_threshold=3)

    monitor._record(False)
    assert monitor.is_online is True  # 1 failure
    monitor._record(False)
    assert monitor.is_online is True  # 2 failures
    monitor._record(False)
    assert monitor.is_online is False  # 3rd consecutive failure -> offline


def test_single_success_recovers_from_offline() -> None:
    monitor = ConnectivityMonitor(failure_threshold=2)
    monitor._record(False)
    monitor._record(False)
    assert monitor.is_online is False

    monitor._record(True)
    assert monitor.is_online is True


def test_transient_blip_resets_the_failure_count() -> None:
    """A success between failures must reset the counter, so scattered blips
    that never reach the threshold consecutively don't accumulate into offline."""
    monitor = ConnectivityMonitor(failure_threshold=3)
    monitor._record(False)   # 1
    monitor._record(True)    # reset
    monitor._record(False)   # 1 again
    monitor._record(False)   # 2
    assert monitor.is_online is True  # never 3 in a row


def test_going_offline_and_recovering_are_logged(caplog) -> None:
    monitor = ConnectivityMonitor(failure_threshold=2)
    with caplog.at_level(logging.INFO, logger="connectivity"):
        monitor._record(False)
        monitor._record(False)  # -> offline (warning)
        monitor._record(True)   # -> online (info)

    messages = [r.message for r in caplog.records]
    assert any("unreachable" in m for m in messages)
    assert any("reachable again" in m for m in messages)


def test_offline_heartbeat_logs_periodically(monkeypatch, caplog) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr(connectivity_module.time, "monotonic", lambda: clock["t"])

    monitor = ConnectivityMonitor(failure_threshold=1, offline_log_interval=60.0)
    with caplog.at_level(logging.WARNING, logger="connectivity"):
        monitor._record(False)   # t=1000 -> offline
        clock["t"] = 1030.0
        monitor._record(False)   # +30s, under interval -> no heartbeat
        clock["t"] = 1070.0
        monitor._record(False)   # +70s since last log -> heartbeat

    heartbeats = [r for r in caplog.records if "still offline" in r.message]
    assert len(heartbeats) == 1


def test_draw_offline_message_renders_non_blank_pixels() -> None:
    canvas = SimulatorCanvas(320, 64, _noop_broadcast)
    canvas.clear()

    draw_offline_message(canvas)

    assert any(b != 0 for b in canvas._pixels)


def test_draw_offline_message_caches_composed_image_per_size(monkeypatch) -> None:
    """render_frame() calls this every frame while offline (up to config fps),
    so it must not rebuild the icon/text from scratch each time — that CPU
    cost competes with the timing-sensitive hardware matrix driver."""
    connectivity_module._message_cache.clear()
    calls = 0
    orig_build = connectivity_module._build_offline_message_image

    def _counting_build(w: int, h: int):
        nonlocal calls
        calls += 1
        return orig_build(w, h)

    monkeypatch.setattr(connectivity_module, "_build_offline_message_image", _counting_build)

    canvas = SimulatorCanvas(320, 64, _noop_broadcast)
    for _ in range(5):
        draw_offline_message(canvas)
    assert calls == 1

    other_canvas = SimulatorCanvas(128, 32, _noop_broadcast)
    draw_offline_message(other_canvas)
    assert calls == 2


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
