"""Boot-display handoff.

start.sh keeps a "Starting engine..." frame on the LED matrix and passes its
PID via BOOT_DISPLAY_PID; the engine stops that process (``_release_boot_display``)
right before it claims the matrix, so the panel stays lit through startup.
"""
from __future__ import annotations

import signal
import subprocess

import main


def test_release_boot_display_noop_without_env(monkeypatch) -> None:
    monkeypatch.delenv("BOOT_DISPLAY_PID", raising=False)
    main._release_boot_display()  # must not raise


def test_release_boot_display_noop_on_garbage_pid(monkeypatch) -> None:
    monkeypatch.setenv("BOOT_DISPLAY_PID", "not-a-pid")
    main._release_boot_display()  # must not raise


def test_release_boot_display_handles_already_exited(monkeypatch) -> None:
    monkeypatch.setenv("BOOT_DISPLAY_PID", "999999")

    def _raise(_pid: int, _sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(main.os, "kill", _raise)
    main._release_boot_display()  # ProcessLookupError swallowed -> no raise


def test_release_boot_display_terminates_running_process(monkeypatch) -> None:
    proc = subprocess.Popen(["sleep", "30"])
    try:
        monkeypatch.setenv("BOOT_DISPLAY_PID", str(proc.pid))
        main._release_boot_display()
        # SIGTERM should have reached it; sleep exits with -SIGTERM.
        assert proc.wait(timeout=5) == -signal.SIGTERM
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
