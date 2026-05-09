# led-dashboard

RGB LED wall display controller — Raspberry Pi 4 driving 10× HUB75 P5 panels (320×64 px).

## Quickstart

### Engine (Python)

```bash
cd engine
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py          # starts FastAPI on :8000
```

### UI (React)

```bash
cd ui
npm install
npm run dev             # starts Vite on :5173, proxies /api and /ws to :8000
```

Open `http://localhost:5173` to see the live simulator preview.

## Project layout

```
engine/
  canvas/         base Canvas ABC + SimulatorCanvas (WebSocket broadcast)
  api/            FastAPI app, /ws/preview WebSocket, ConnectionManager
  plugins/        display plugins (Phase 2+)
  helpers/        StaticScreen, TimedSequence, Marquee (Phase 3+)
  main.py         entry point — render loop + uvicorn
  config.yaml     display dimensions, FPS, server settings

ui/
  src/
    components/   DisplayPreview.tsx — WebSocket client + <canvas> renderer
    pages/        (Phase 2+)
  vite.config.ts  dev proxy → engine
```

## Development phases

1. **Simulator + WebSocket preview** ← current
2. Plugin system + four starter plugins (Stocks, Sports, Flights, Text)
3. Display helpers (StaticScreen, TimedSequence, Marquee) + font rendering
4. Hardware integration (HardwareCanvas → real panels)
5. Polish — config persistence, hot-reload, systemd service, API auth
