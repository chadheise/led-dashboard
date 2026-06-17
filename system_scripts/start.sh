#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

# ── Boot display helpers ───────────────────────────────────────────────────────
# show_boot_msg launches boot_display.py in the background so the message stays
# on the LED matrix while the current startup step runs.  Each call kills the
# previous instance first.  stop_boot_display must be called before the engine
# starts so they don't both hold the rgbmatrix device.

BOOT_DISPLAY_PID=""

show_boot_msg() {
    # Kill the previous boot display, if any.
    if [ -n "$BOOT_DISPLAY_PID" ]; then
        kill "$BOOT_DISPLAY_PID" 2>/dev/null || true
        wait "$BOOT_DISPLAY_PID" 2>/dev/null || true
        BOOT_DISPLAY_PID=""
    fi

    local python="$VENV_DIR/bin/python3"
    if [ ! -x "$python" ]; then
        return  # venv not ready yet (first boot before pip install)
    fi

    CANVAS=$( $HARDWARE_MODE && echo hardware || echo "" ) \
    PYTHONPATH="$REPO_DIR/engine" \
        "$python" "$REPO_DIR/engine/boot_display.py" "$1" 2>/dev/null &
    BOOT_DISPLAY_PID=$!
}

stop_boot_display() {
    if [ -n "$BOOT_DISPLAY_PID" ]; then
        kill "$BOOT_DISPLAY_PID" 2>/dev/null || true
        wait "$BOOT_DISPLAY_PID" 2>/dev/null || true
        BOOT_DISPLAY_PID=""
    fi
}
# ──────────────────────────────────────────────────────────────────────────────

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

show_boot_msg "Updating dependencies..."
log "Installing engine dependencies..."
pip install -r engine/requirements.txt

# Build UI
show_boot_msg "Building UI..."
log "Installing UI dependencies..."
cd "$REPO_DIR/ui"
npm install --unsafe-perm

log "Building UI..."
npm run build

# Hardware mode requires rgbmatrix — install automatically if missing
if $HARDWARE_MODE && ! "$VENV_DIR/bin/python3" -c "import rgbmatrix" 2>/dev/null; then
    show_boot_msg "Installing drivers..."
    log "rgbmatrix not found — installing from source..."
    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TMP_DIR"' EXIT
    git clone --depth=1 https://github.com/hzeller/rpi-rgb-led-matrix.git "$TMP_DIR/rpi-rgb-led-matrix"
    # pyproject.toml is at the repo root, not in bindings/python
    "$VENV_DIR/bin/pip3" install "$TMP_DIR/rpi-rgb-led-matrix"
    if ! "$VENV_DIR/bin/python3" -c "import rgbmatrix" 2>/dev/null; then
        log "ERROR: rgbmatrix installation failed."
        log "Build tools may be missing: sudo apt-get install -y gcc python3-dev"
        log "bindings/python contents: $(ls "$TMP_DIR/rpi-rgb-led-matrix/bindings/python" 2>&1)"
        exit 1
    fi
    log "rgbmatrix installed successfully."
fi

# Lock CPU governor to performance so the rgbmatrix timing thread isn't starved
# by frequency scaling. Without this, refresh rate drops intermittently to ~22 Hz.
log "Setting CPU governor to performance..."
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null

# Hand off the display to the engine
show_boot_msg "Starting..."
stop_boot_display

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
    stop_boot_display
    kill "$ENGINE_PID" "$UI_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait "$ENGINE_PID" "$UI_PID"
