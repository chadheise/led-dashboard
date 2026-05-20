#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"
HARDWARE_MODE=true
PREVIEW_ENABLED=true

for arg in "$@"; do
    case "$arg" in
        --simulator)   HARDWARE_MODE=false ;;
        --no-preview)  PREVIEW_ENABLED=false ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2; }

log "=== LED Dashboard Startup ==="
log "Repo: $REPO_DIR"
log "Canvas mode: $( $HARDWARE_MODE && echo hardware || echo simulator )"
log "Preview: $( $PREVIEW_ENABLED && echo enabled || echo disabled )"

# Pull latest code
log "Pulling latest code from GitHub..."
cd "$REPO_DIR"
git pull origin main

# Python virtual environment
if [ ! -d "$VENV_DIR" ]; then
    log "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

log "Installing engine dependencies..."
pip install -r engine/requirements.txt

# Build UI
log "Installing UI dependencies..."
cd "$REPO_DIR/ui"
npm install

log "Building UI..."
npm run build

# Hardware mode requires rgbmatrix, which must be compiled and installed manually
if $HARDWARE_MODE && ! "$VENV_DIR/bin/python3" -c "import rgbmatrix" 2>/dev/null; then
    log "ERROR: rgbmatrix is not installed. Build and install it from source:"
    log "  git clone https://github.com/hzeller/rpi-rgb-led-matrix.git"
    log "  cd rpi-rgb-led-matrix/bindings/python"
    log "  make build-python PYTHON=$VENV_DIR/bin/python3"
    log "  make install-python PYTHON=$VENV_DIR/bin/python3"
    exit 1
fi

# Start engine
log "Starting engine on :8000..."
cd "$REPO_DIR/engine"
if $HARDWARE_MODE; then
    CANVAS=hardware PREVIEW_ENABLED=$PREVIEW_ENABLED sudo -E "$VENV_DIR/bin/python3" main.py &
else
    "$VENV_DIR/bin/python3" main.py &
fi
ENGINE_PID=$!

# Start UI preview server (serves the built dist/)
log "Starting UI server on :3000..."
cd "$REPO_DIR/ui"
npm run preview -- --host 0.0.0.0 --port 3000 &
UI_PID=$!

log "Services started. Engine PID=$ENGINE_PID, UI PID=$UI_PID"

cleanup() {
    log "Shutting down services..."
    kill "$ENGINE_PID" "$UI_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait "$ENGINE_PID" "$UI_PID"
