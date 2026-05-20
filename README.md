# led-dashboard

RGB LED wall display controller — Raspberry Pi 4 driving a configurable number of HUB75 panels (e.g. 10× P5 panels for a 320×64 px display).

The system renders display apps (stocks, sports, flights, text) to a canvas. In simulator mode it streams frames over WebSocket to a browser-based preview; in hardware mode it drives real HUB75 LED panels via the `rpi-rgb-led-matrix` library.

## Quickstart

### Engine (Python)

```bash
cd engine
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py          # starts FastAPI on :8000 (simulator mode)
```

#### Hardware mode (Raspberry Pi + HUB75)

Hardware mode requires the `rpi-rgb-led-matrix` Python bindings, which are not on PyPI and must be compiled from source. `start.sh` handles this automatically — if the module is missing it clones the repo, builds, and installs it into the venv before starting the engine.

If the auto-install fails, it usually means the build tools are missing. Install them first:

```bash
sudo apt-get install -y gcc python3-dev
```

Then re-run `start.sh` and it will retry the install.

> **Note:** `start.sh` uses `sudo -E` to run the engine (required for GPIO access). If `sudo` prompts for a password non-interactively, add a `NOPASSWD` entry via `sudo visudo`:
> ```
> chadheise ALL=(ALL) NOPASSWD: ALL
> ```

Set `CANVAS=hardware` to drive the physical LED panels instead of broadcasting to the WebSocket simulator. The library requires root, so use `sudo -E` to preserve the environment variable:

```bash
CANVAS=hardware sudo -E .venv/bin/python3 main.py
```

Or use `start.sh`, which defaults to hardware mode and handles `sudo` automatically:

```bash
./start.sh
```

To run in simulator mode instead (e.g. for local development without panels):

```bash
./start.sh --simulator
```

Hardware parameters (chain length, GPIO slowdown, HAT mapping) are read from the `hardware:` block in `config.yaml`. In hardware mode the engine writes pixels to both the physical panels and the WebSocket stream, so the UI preview continues to work.

#### Hot-reload (development)

To avoid restarting the engine on every code change, set `HOT_RELOAD=true`. The engine watches `apps/` and `libraries/` for `.py` file changes and automatically reloads the affected code within about one second of saving.

```bash
HOT_RELOAD=true .venv/bin/python main.py
```

The server stays running, the WebSocket connection is preserved, and the display updates immediately with the new code. Syntax errors are logged without crashing the engine — fix and save to retry.

### UI (React)

```bash
cd ui
npm install
npm run dev             # starts Vite on :5173, proxies /api and /ws to :8000
```

Open `http://localhost:5173` to see the live simulator preview.

## Architecture

The system is split into a Python **engine** and a React **UI** that communicate over HTTP REST and WebSocket.

```
┌─────────────────────────────────────────────────────────┐
│                        Engine                           │
│                                                         │
│  ┌───────────┐    ┌──────────────┐    ┌─────────────┐  │
│  │  Display  │───▶│ SceneManager │───▶│   Canvas    │  │
│  │   Apps    │    │  (rotation)  │    │ (simulator) │  │
│  └───────────┘    └──────────────┘    └──────┬──────┘  │
│        │                                      │         │
│  ┌─────▼──────┐                    WebSocket  │         │
│  │ Libraries  │                    broadcast  │         │
│  └────────────┘                               │         │
│                                               │         │
│  ┌───────────────────────────────────────┐    │         │
│  │           FastAPI / REST              │    │         │
│  │  modules · playlists · settings       │    │         │
│  └───────────────────────────────────────┘    │         │
└──────────────────────────────────────────────┼──────────┘
                                               │
                                          ┌────▼────┐
                                          │   UI    │
                                          │ (React) │
                                          └─────────┘
```

### Data flow

1. `main.py` loads `config.yaml`, creates a `SimulatorCanvas` (or `HardwareCanvas` when `CANVAS=hardware`) and a `SceneManager`, then starts a FastAPI server.
2. The render loop calls `scene_manager.render_frame()` at the configured FPS (default 30).
3. `SceneManager` rotates through a playlist of `DisplayApp` instances, calling each app's `render_frame()` in turn.
4. Each `DisplayApp` independently fetches external data on its own `refresh_interval` (e.g. every 60 s), then draws to the shared `Canvas`.
5. After each frame, `SimulatorCanvas.render()` packs the pixel buffer into a binary WebSocket message (4-byte header: width + height as big-endian uint16, followed by raw RGB bytes) and broadcasts it to all connected clients.
6. The React UI subscribes to the WebSocket and paints each frame onto an HTML `<canvas>` element, scaling it up for visibility.
7. The REST API lets the UI manage modules, playlists, per-app settings, and library credentials, all persisted to `data/state.json`.

## Folder structure

```
led-dashboard/
├── engine/
│   ├── main.py              # Entry point — wires everything together, starts uvicorn
│   ├── plugin_base.py       # DisplayApp ABC (all display apps inherit from this)
│   ├── scene_manager.py     # Playlist rotation, per-app fetch loops, render orchestration
│   ├── state.py             # Persistent state store (modules, playlists) → data/state.json
│   ├── config.yaml          # Display dimensions, FPS, server host/port, seed playlist
│   ├── requirements.txt
│   │
│   ├── canvas/
│   │   ├── base.py          # Canvas ABC (set_pixel / clear / render)
│   │   ├── simulator.py     # SimulatorCanvas — broadcasts frames over WebSocket
│   │   └── hardware.py      # HardwareCanvas — drives HUB75 panels via rpi-rgb-led-matrix
│   │
│   ├── api/
│   │   ├── server.py        # FastAPI app factory
│   │   ├── routes.py        # REST endpoints (modules, playlists, settings, preview)
│   │   ├── websocket.py     # WebSocket connection manager + /ws/preview endpoint
│   │   └── preview.py       # Ephemeral preview canvas (used while editing a module)
│   │
│   ├── apps/                # Display apps (one subdirectory per app)
│   │   ├── stocks/          # Yahoo Finance stock ticker
│   │   ├── sports/          # ESPN live scores
│   │   ├── flights/         # Nearby aircraft via OpenSky + FlightAware enrichment
│   │   └── text/            # Static or scrolling text message
│   │
│   ├── libraries/           # Shared data / rendering libraries
│   │   ├── base.py          # Library ABC
│   │   ├── canvas_utils/    # PIL compositing helpers (blit, parse_color)
│   │   ├── espn_sports/     # ESPN API — game scores + team logos
│   │   ├── flightaware/     # FlightAware AeroAPI — flight enrichment
│   │   ├── opensky/         # OpenSky Network — real-time aircraft positions
│   │   ├── text_renderer/   # PIL text rendering (LoRes bitmap + Roboto variable fonts)
│   │   └── yahoo_finance/   # Yahoo Finance — stock quotes + company logos
│   │
│   └── data/                # Runtime data (gitignored blobs, cached logos, state)
│       ├── state.json        # Persisted modules, playlists, app/library configs
│       ├── espn_sports/      # Cached team logos (PNG, organised by league)
│       └── yahoo_finance/    # Cached company logos (PNG)
│
└── ui/
    ├── src/
    │   ├── App.tsx           # Root layout + nav (Playlists / Modules / Settings)
    │   ├── theme.ts          # Shared color and font constants
    │   ├── pages/
    │   │   ├── Playlists.tsx # List and manage saved playlists
    │   │   ├── Playlist.tsx  # Edit a single playlist; live simulator preview
    │   │   ├── Modules.tsx   # List and manage saved modules
    │   │   ├── Plugins.tsx   # Browse available apps
    │   │   ├── Preview.tsx   # Full-screen simulator view
    │   │   ├── Runs.tsx      # (playlist run history)
    │   │   └── Settings.tsx  # Per-app global config + library credentials
    │   └── components/
    │       ├── DisplayPreview.tsx   # WebSocket client + <canvas> LED renderer
    │       ├── AppForm.tsx          # Generic JSON-schema-driven app config form
    │       ├── AppIcon.tsx          # Inline SVG icon renderer for apps/libraries
    │       ├── DurationInput.tsx    # Human-friendly duration field (e.g. "30s")
    │       ├── LocationMapInput.tsx # Map-based lat/lon picker for flights app
    │       ├── ModuleSelect.tsx     # Dropdown to pick a saved module
    │       ├── MultiPicker.tsx      # Multi-select for teams, tickers, etc.
    │       ├── PluginForm.tsx       # Form wrapper for a specific app's config schema
    │       ├── TeamPicker.tsx       # Sport-aware team search + select
    │       └── TransportControls.tsx # Play/pause/prev/next playlist controls
    ├── vite.config.ts        # Dev proxy: /api and /ws → engine :8000
    └── package.json
```

## Engine modules

### `plugin_base.py` — DisplayApp

Abstract base class for all display apps. Subclasses declare class-level metadata (`id`, `name`, `config_schema`, `libraries`) and implement two async methods:

- `fetch_data()` — called on `refresh_interval` (default 60 s); pull external data and cache it on `self`.
- `render_frame()` — called every frame; draw the current cached data onto `self.canvas`.

Optional lifecycle hooks: `on_activate()` / `on_deactivate()` (called when the playlist switches to/from this app).

### `scene_manager.py` — SceneManager

Owns the active playlist and drives the render loop:

- Instantiates one `DisplayApp` per playlist entry from the app registry.
- Runs an independent `asyncio` fetch-loop per app so all apps refresh their data concurrently, even when not on-screen.
- Rotates to the next app after each entry's `duration` elapses, calling `on_deactivate` / `on_activate` around the switch.
- Supports pause/resume and manual prev/next navigation (used by the transport controls in the UI).

### `state.py` — StateStore

Persists application state to `data/state.json` using atomic write (write to `.tmp`, then rename). Manages three entity types:

- **Modules** — named, reusable app configurations (e.g. "Cubs scores", "FAANG stocks").
- **Playlists** — ordered lists of module references, each with a display duration.
- **App / library configs** — global settings per app or library (e.g. API keys, default location).

### `canvas/` — Canvas abstraction

`Canvas` (ABC) exposes `set_pixel(x, y, r, g, b)`, `clear()`, and `async render()`.

`SimulatorCanvas` stores pixels in a flat `bytearray` and on `render()` packs a binary frame (`>HH` header + raw RGB) and broadcasts it to all WebSocket clients.

`HardwareCanvas` writes pixels to an `rpi-rgb-led-matrix` off-screen canvas and calls `SwapOnVSync` on each `render()` to push the frame to the physical panels. It is selected by setting `CANVAS=hardware` at startup.

### `api/` — FastAPI server

| Path | Description |
|---|---|
| `GET /api/apps` | List available display apps and their config schemas |
| `GET/POST /api/modules` | Create / list saved modules |
| `PUT/DELETE /api/modules/{id}` | Update or delete a module |
| `GET/POST /api/playlists` | Create / list playlists |
| `PUT/DELETE /api/playlists/{id}` | Update or delete a playlist |
| `POST /api/playlists/{id}/activate` | Set a playlist as active |
| `GET /api/status` | Current scene index, paused state, scene count |
| `POST /api/control` | Pause, resume, prev, next |
| `GET/PUT /api/settings/apps/{id}` | Per-app global config |
| `GET/PUT /api/settings/libraries/{id}` | Per-library config (API keys, etc.) |
| `POST/DELETE /api/preview` | Start / stop an ephemeral edit preview |
| `WS /ws/preview` | WebSocket — streams binary LED frames to the browser |

## Display apps

### `apps/stocks/` — Stocks

Displays a rotating ticker of stock quotes. Each card shows the company logo (PNG cached from Yahoo Finance / Simple Icons SVG), ticker symbol, current price, and percentage change (green/red). Supports preset groups (FAANG, Dow 30, S&P 500 indices, etc.) or custom tickers.

Uses: `yahoo_finance`, `text_renderer`, `canvas_utils`

### `apps/sports/` — Sports

Shows live game scores from ESPN for any supported league (NFL, NBA, MLB, NHL, NCAAF, WNBA, MLS, and more). Displays team logos, scores, game status, and time/quarter. Favourite teams are listed first; games are sorted by status (live → upcoming → final).

Uses: `espn_sports`, `text_renderer`, `canvas_utils`

### `apps/flights/` — Flights

Displays aircraft currently overhead within a configurable radius of a chosen location. Shows callsign, altitude, speed, heading, and (if a FlightAware API key is configured) airline, origin/destination, and aircraft type. Cycles through nearby aircraft every few seconds.

Uses: `opensky`, `flightaware`, `text_renderer`, `canvas_utils`

### `apps/text/` — Text Display

Renders a static or horizontally-scrolling text message in a configurable color and font size. A simple utility app useful as a spacer or announcement slide in a playlist.

Uses: `text_renderer`, `canvas_utils`

## Libraries

Libraries are shared, stateless helpers that display apps import directly. They extend the `Library` ABC (`libraries/base.py`) and expose a `global_config_schema` for credentials or defaults that are configured once per library in the Settings page.

### `libraries/canvas_utils/` — Canvas Utils

Low-level PIL compositing helpers:

- `blit(canvas, img, x_offset)` — copy a PIL `Image` onto the `Canvas` with an optional horizontal offset (used for scrolling).
- `parse_color(hex)` — convert a CSS hex string to an `(r, g, b)` tuple.

### `libraries/espn_sports/` — ESPN Sports

Fetches live and recent game scores from the public ESPN API. Supports all major North American leagues and many soccer competitions. Team logos are downloaded from ESPN and cached locally for 30 days. `leagues.json` maps league IDs to human-readable labels; `ncaaf_conferences.json` filters NCAAF to a specific conference.

### `libraries/flightaware/` — FlightAware AeroAPI

Optional flight enrichment via the FlightAware AeroAPI (requires a free or paid API key). Given a flight callsign or ICAO hex, returns airline name, origin and destination airports, and aircraft type. Used by the Flights app to augment raw OpenSky position data.

### `libraries/opensky/` — OpenSky Network

Queries the OpenSky Network REST API for real-time aircraft state vectors within a bounding box. Supports optional OAuth authentication (Client ID + Secret) for higher rate limits. Converts a centre point + radius (km) to a lat/lon bounding box internally.

### `libraries/text_renderer/` — Text Renderer

PIL-based text rendering optimised for small LED displays:

- **LoRes fonts** — a curated set of bitmap-style OpenType fonts (sizes 9, 12, 15, 22, 28 px) that look crisp at low resolution.
- **Roboto variable font** — used for sizes above 28 px where LoRes fonts are unavailable.
- `render_text(text, color, size)` → `Image` — the primary entry point used by all apps.
- Auto-selects the closest available LoRes size, falling back to Roboto for larger sizes.

### `libraries/yahoo_finance/` — Yahoo Finance

Fetches real-time stock quotes (price, change, % change) from the Yahoo Finance API. Resolves company logos by looking up the ticker in `ticker_simple_icons.json` (Simple Icons slug + brand color) or `ticker_domain.json` (company domain for favicon fallback), then downloads and caches SVG/PNG logos. `preset_groups.json` defines named watchlists (FAANG, Dow 30, etc.) and `index_symbols.json` maps index names (S&P 500, Nasdaq, etc.) to their constituent tickers.

## Adding a new app

An app is a `DisplayApp` subclass that fetches data and draws frames. Follow these steps:

**1. Create the module**

```
engine/apps/myapp/
    __init__.py   # empty
    plugin.py     # your DisplayApp subclass
```

**2. Implement the class**

```python
# engine/apps/myapp/plugin.py
from __future__ import annotations
from typing import Any, ClassVar
from canvas.base import Canvas
from plugin_base import DisplayApp
from libraries.canvas_utils.library import blit, parse_color
from libraries.text_renderer.library import render_text

class MyApp(DisplayApp):
    id: ClassVar[str] = "myapp"           # unique slug used in state.json and the API
    name: ClassVar[str] = "My App"        # displayed in the UI
    description: ClassVar[str] = "..."
    icon: ClassVar[str] = '<svg .../>>'   # inline SVG, uses currentColor
    libraries: ClassVar[list[str]] = []   # library IDs this app depends on
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "My App",
        "properties": {
            "my_option": {"type": "string", "title": "My option", "default": "hello"},
        },
        "required": [],
    }

    def __init__(self, config, canvas, global_config=None, library_configs=None):
        super().__init__(config, canvas, global_config, library_configs)
        self._data: list = []           # cached fetch results

    async def fetch_data(self) -> None:
        # Called on self.refresh_interval (default 60 s). Pull external data
        # and store it on self so render_frame can use it.
        self._data = [...]

    async def render_frame(self) -> None:
        # Called every frame. Draw onto self.canvas using set_pixel or blit.
        img = render_text(self.config.get("my_option", ""), (255, 255, 255), 16)
        blit(self.canvas, img)
```

Class-variable reference:

| Attribute | Type | Required | Notes |
|---|---|---|---|
| `id` | `str` | yes | Unique slug; used in `state.json`, URL paths, and `APP_REGISTRY` |
| `name` | `str` | yes | Human-readable label shown in the UI |
| `description` | `str` | no | Short sentence shown in the app browser |
| `icon` | `str` | no | Inline SVG string; uses `currentColor` so the UI can theme it |
| `libraries` | `list[str]` | no | Library IDs the app uses; the UI shows a warning if any are unconfigured |
| `config_schema` | `dict` | yes | JSON Schema for per-module config; drives the auto-generated form in the UI |
| `global_config_schema` | `dict` | no | JSON Schema for app-level settings (API keys, defaults) stored once per app |

**Using a library inside an app**

Instantiate the library in `__init__`, passing its config slice from `self.library_configs`:

```python
from libraries.yahoo_finance.library import YahooFinanceLibrary

class MyApp(DisplayApp):
    libraries: ClassVar[list[str]] = ["yahoo_finance"]

    def __init__(self, config, canvas, global_config=None, library_configs=None):
        super().__init__(config, canvas, global_config, library_configs)
        self._finance = YahooFinanceLibrary(self.library_configs.get("yahoo_finance", {}))
```

**3. Register the app**

Add the import and entry to `engine/apps/__init__.py`:

```python
from apps.myapp.plugin import MyApp

APP_REGISTRY: dict[str, type] = {
    ...
    MyApp.id: MyApp,
}
```

The app immediately appears in the UI's app browser and can be added to any module.

---

## Adding a new library

A library is a reusable helper that encapsulates an external API or a shared rendering utility. Follow these steps:

**1. Create the module**

```
engine/libraries/mylib/
    __init__.py   # empty
    library.py    # your Library subclass
```

**2. Implement the class**

```python
# engine/libraries/mylib/library.py
from __future__ import annotations
from typing import Any, ClassVar
from libraries.base import Library

class MyLibrary(Library):
    id: ClassVar[str] = "mylib"
    name: ClassVar[str] = "My Library"
    description: ClassVar[str] = "..."
    icon: ClassVar[str] = '<svg .../>'
    global_config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "My Library",
        "properties": {
            "api_key": {"type": "string", "title": "API Key", "default": ""},
        },
    }

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # self.config contains the values saved in Settings → Libraries

    async def fetch_something(self, query: str) -> list[dict[str, Any]]:
        api_key = self.config.get("api_key", "")
        # ... call external API ...
        return []
```

If the library needs no global configuration (e.g. it only wraps local rendering logic), set `global_config_schema = {}` and the Settings page will not show a form for it.

**3. Register the library**

Add the import and entry to `engine/libraries/__init__.py`:

```python
from libraries.mylib.library import MyLibrary

LIBRARY_REGISTRY: dict[str, type[Library]] = {
    ...
    "mylib": MyLibrary,
}
```

The library now appears on the Settings page. Any app that lists `"mylib"` in its `libraries` class var will receive the saved config in `library_configs["mylib"]` at construction time.

---

## Configuration

`engine/config.yaml` controls display hardware dimensions and the seed playlist shown on first run:

```yaml
display:
  width: 320      # total pixel width (e.g. 10 × 32 px panels)
  height: 64      # total pixel height
  fps: 30
  brightness: 80  # 0–100; used by hardware canvas

server:
  host: "0.0.0.0"
  port: 8000

playlist:         # optional seed playlist (used only on first run)
  - app_id: text
    config:
      message: "LED Wall Display"
      scroll: true
    duration: 30

hardware:         # used only when CANVAS=hardware
  rows: 64
  cols: 320
  chain_length: 10
  gpio_slowdown: 4          # tuned for Pi 4; lower for Pi 5
  hardware_mapping: adafruit-hat
```

After first run, all state is stored in `data/state.json` and managed through the UI.

## Development phases

1. **Simulator + WebSocket preview** ✓
2. **Plugin system + starter apps** (Stocks, Sports, Flights, Text) ✓
3. **Display helpers + font rendering** ✓
4. **Hardware integration** — `HardwareCanvas` via `rpi-rgb-led-matrix`; select with `CANVAS=hardware` ✓
5. **Polish** — config persistence, hot-reload ✓, systemd service, API auth
