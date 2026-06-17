#!/usr/bin/env python3
"""Monitor a momentary GPIO button and halt the system when it is pressed.

Runs as a systemd service (see shutdown-button.service). All output goes to
the journal, so `journalctl -u shutdown-button` shows whether the monitor
started cleanly and what happened on each press.
"""
import subprocess
import sys
import time

import RPi.GPIO as GPIO

BUTTON_PIN = 25
# Absolute path: systemd units run with a minimal PATH that may not include the
# directory holding `shutdown`.
SHUTDOWN_CMD = ["/sbin/shutdown", "-h", "now"]


def main() -> int:
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    print(f"Shutdown button monitor started on BCM pin {BUTTON_PIN}", flush=True)

    try:
        while True:
            GPIO.wait_for_edge(BUTTON_PIN, GPIO.FALLING)
            time.sleep(0.1)  # debounce
            if GPIO.input(BUTTON_PIN) == GPIO.LOW:
                print("Button pressed — initiating shutdown", flush=True)
                try:
                    subprocess.run(SHUTDOWN_CMD, check=True)
                except Exception as exc:  # noqa: BLE001 — log and keep monitoring
                    print(f"Shutdown command failed: {exc}", file=sys.stderr, flush=True)
    finally:
        GPIO.cleanup()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — surface startup errors to the journal
        print(f"Shutdown button monitor crashed: {exc}", file=sys.stderr, flush=True)
        raise
