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

# Pull latest code (run as chadheise so their SSH key and known_hosts are used)
log "Pulling latest code from GitHub..."
cd "$REPO_DIR"
sudo -u chadheise git pull origin main

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
npm install --unsafe-perm

log "Building UI..."
npm run build

# Hardware mode requires rgbmatrix — install automatically if missing
if $HARDWARE_MODE && ! "$VENV_DIR/bin/python3" -c "import rgbmatrix" 2>/dev/null; then
    log "rgbmatrix not found — installing from source..."
    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TMP_DIR"' EXIT
    git clone --depth=1 https://github.com/hzeller/rpi-rgb-led-matrix.git "$TMP_DIR/rpi-rgb-led-matrix"
    # --no-build-isolation required: setup.py references C sources via relative paths
    # that break when pip copies files to a temporary build directory
    "$VENV_DIR/bin/pip3" install --no-build-isolation "$TMP_DIR/rpi-rgb-led-matrix/bindings/python"
    if ! "$VENV_DIR/bin/python3" -c "import rgbmatrix" 2>/dev/null; then
        log "ERROR: rgbmatrix installation failed. Ensure build tools are installed:"
        log "  sudo apt-get install -y gcc python3-dev"
        exit 1
    fi
    log "rgbmatrix installed successfully."
fi

# Start engine
log "Starting engine on :8000..."
cd "$REPO_DIR/engine"
if $HARDWARE_MODE; then
    CANVAS=hardware PREVIEW_ENABLED=$PREVIEW_ENABLED "$VENV_DIR/bin/python3" main.py &
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
