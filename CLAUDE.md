# CLAUDE.md — agent guide to led-dashboard

Context for coding agents working in this repo. Goal: make a change, test it
(including the LED-display snapshot tests), and commit — without re-deriving the
project layout or hunting for missing dependencies.

## What this is

A controller for a wall of HUB75 RGB LED panels driven by a Raspberry Pi. It
renders a rotating playlist of **display apps** (stocks, sports, flights,
weather, text, countdown, spotify, world clock, …) to a logical canvas
(production layout is 320×64). Two render targets:

- **Simulator** (default, no hardware): streams frames over a WebSocket to the
  React UI for live preview. Full parity with hardware for development/tests.
- **Hardware** (`CANVAS=hardware`): drives physical panels via the
  `rpi-rgb-led-matrix` C library. Only needed on the Pi.

You almost never need hardware — develop and test entirely in the simulator.

## Repo map

```
engine/              Python backend (FastAPI + async render loop)
  main.py              Entry point: loads config.yaml, builds canvas, serves API
  app_base.py          DisplayApp ABC: subclass with fetch_data() + render_frame()
  scene_manager.py     Playlist rotation + per-app fetch loops + render cadence
  state.py             Persists modules/playlists/configs to data/state.json
  config.yaml          Display size, fps, server port, hardware/panel layout
  apps/                One package per display app; registered in apps/__init__.py
  libraries/           Shared integrations + rendering (text_renderer, layout,
                       espn_sports, open_meteo, yahoo_finance, opensky, …)
  canvas/              base.py (Canvas ABC), simulator.py, hardware.py
  api/                 FastAPI server.py, routes.py, websocket.py
  tests/               pytest suite + golden-snapshot framework (see below)
ui/                  React + Vite + TypeScript control panel (src/main.tsx)
system_scripts/      Pi startup orchestration (start.sh) + systemd units
.claude/             SessionStart hook that installs deps (committed)
```

## Environment setup

A **SessionStart hook** (`.claude/hooks/session-start.sh`) installs everything
automatically in remote/web sessions. To set up manually:

```bash
# Python engine (from repo root)
python3 -m venv .venv
.venv/bin/pip install -r engine/requirements.txt -r engine/requirements-dev.txt
# UI
cd ui && npm install
```

- **Python**: FastAPI, uvicorn, Pillow, pydantic, httpx, websockets, pyyaml,
  watchfiles, timezonefinder, cairosvg. Dev: pytest, pytest-asyncio, cairosvg.
- **Node/UI**: React, Vite, TypeScript, Leaflet, tz-lookup.
- **`rpi-rgb-led-matrix`** (NOT on PyPI; built from source, needs gcc +
  python3-dev) is **only** imported by `canvas/hardware.py` in hardware mode.
  Skip it for dev and tests.

## Running locally

```bash
# Engine on :8000 (simulator). HOT_RELOAD watches apps/ + libraries/.
cd engine && HOT_RELOAD=true ../.venv/bin/python main.py
# UI on :3000, proxies /api and /ws to :8000
cd ui && npm run dev
```

Env vars: `CANVAS` (`hardware` to use panels; default simulator), `HOT_RELOAD`,
`PREVIEW_ENABLED` (`false` disables WebSocket broadcast), `PYTHONPATH`.

## Testing

pytest, fully offline (no network). Config: `engine/pytest.ini`
(`testpaths=tests`, `pythonpath=.`). **Run from the `engine/` directory:**

```bash
cd engine
../.venv/bin/python -m pytest            # full suite (~3000 tests)
../.venv/bin/python -m pytest tests/test_app_snapshots.py   # one module
```

Hardware is mocked by `canvas/simulator.py::SimulatorCanvas` (in-memory pixel
buffer). Apps are rendered headless and fed mock data via fixture `seed`
callables, so `fetch_data()` never runs in tests. Time-dependent apps render
with `datetime.now()` frozen to `tests/snaptest/clock.py::FIXED_NOW`.

### LED-display snapshot tests (read this before changing any render code)

Visual output is locked by **golden PNGs** in
`engine/tests/snapshots/{app_id}/{fixture_id}_{w}x{h}.png`, compared
pixel-for-pixel. Any change to how an app draws will fail these tests until you
re-bless the goldens. Workflow when you intentionally change the display:

```bash
cd engine
../.venv/bin/python -m pytest --snapshot-update     # re-bless goldens
# Review what changed before committing:
PYTHONPATH=. ../.venv/bin/python -m tests.snaptest.contact_sheet --app sports --scale 3
#   -> writes tests/output/{app}_h32.png / _h64.png (every fixture × width, upscaled)
```

On a mismatch the failure message points at
`engine/tests/output/diff/{case}_{expected,actual,diff}.png` (magenta =
changed pixels). **Commit updated goldens together with the code change** so the
visual delta is reviewable in the diff.

Caveat: `--snapshot-update` can rewrite PNG *bytes* even with no visual change
if the local Pillow version re-encodes differently. If the suite was green
before the update, those byte-only changes are noise — `git checkout` them and
only commit goldens that reflect a real visual change (confirm via the contact
sheet / diff images).

`tests/test_sports_layout.py` adds structural assertions (no overlap/clipping,
required elements present) via the `libraries/layout` `PlacedBox` audit trail —
these catch layout regressions that pixels alone might not.

The authoritative, detailed guide is **`engine/tests/README.md`** — consult it
for adding snapshot coverage to a new app and for the logo-fixture system.

## Adding a display app (high level)

1. Create `engine/apps/<name>/app.py` with a `DisplayApp` subclass (set `id`,
   `name`, `config_schema`; implement async `fetch_data()` + `render_frame()`).
2. Register it in `engine/apps/__init__.py` (`APP_REGISTRY`).
3. Add a snapshot fixture suite per `engine/tests/README.md` ("Adding snapshot
   coverage for another app"), generate goldens with `--snapshot-update`, review
   the contact sheet, and commit.

Reuse existing helpers in `engine/libraries/` (e.g. `text_renderer` for fonts,
`layout` for placement, `canvas_utils`) rather than re-implementing.

## Conventions & gotchas

- **No CI and no linter/formatter** are configured. The effective gates are
  `pytest` (engine) and `tsc --noEmit` / `npm run build` (UI, `ui/`). Run them
  before committing.
- Run pytest from `engine/`, not the repo root (relies on `pythonpath=.`).
- `engine/data/state.json` is gitignored runtime state, created on first run —
  not code; don't commit it.
- `engine/tests/output/` (diffs, contact sheets) is gitignored; goldens in
  `engine/tests/snapshots/` ARE committed.
- Match the existing style of the file you're editing; bitmap fonts and assets
  under `engine/libraries/text_renderer/fonts/` ship with the repo.
