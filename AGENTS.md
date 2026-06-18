# AGENTS.md

This repo is a Raspberry-Pi RGB LED wall controller: a Python engine
(`engine/`) renders a rotating playlist of display apps to LED panels (or a
WebSocket simulator), with a React UI (`ui/`) for control.

**The full agent guide lives in [`CLAUDE.md`](./CLAUDE.md)** — repo layout,
environment setup, how to run, and the LED-display snapshot-test workflow. Read
it first.

Quick reference:

```bash
# Setup (or let .claude/hooks/session-start.sh do it in remote sessions)
python3 -m venv .venv
.venv/bin/pip install -r engine/requirements.txt -r engine/requirements-dev.txt
( cd ui && npm install )

# Test (run pytest from engine/)
cd engine && ../.venv/bin/python -m pytest

# After an intentional change to LED output, re-bless golden snapshots:
cd engine && ../.venv/bin/python -m pytest --snapshot-update   # then review + commit goldens
```

No CI or linter is configured; the gates are `pytest` (engine) and
`tsc --noEmit` / `npm run build` (UI). Develop in the simulator — physical LED
hardware (`rpi-rgb-led-matrix`) is not required for development or tests.
