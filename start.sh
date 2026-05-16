#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2; }

log "=== LED Dashboard Startup ==="
log "Repo: $REPO_DIR"

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

# Start engine
log "Starting engine on :8000..."
cd "$REPO_DIR/engine"
python3 main.py &
ENGINE_PID=$!

# Start UI preview server (serves the built dist/)
log "Starting UI server on :8080..."
cd "$REPO_DIR/ui"
npm run preview -- --host 0.0.0.0 --port 8080 &
UI_PID=$!

log "Services started. Engine PID=$ENGINE_PID, UI PID=$UI_PID"

cleanup() {
    log "Shutting down services..."
    kill "$ENGINE_PID" "$UI_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait "$ENGINE_PID" "$UI_PID"
