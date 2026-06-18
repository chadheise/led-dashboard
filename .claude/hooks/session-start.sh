#!/usr/bin/env bash
#
# SessionStart hook for led-dashboard.
#
# Pre-installs the Python and Node dependencies a code agent needs so that a
# fresh isolated / Claude Code on the web session arrives ready to run the
# engine, the UI, and the test suite -- without discovering missing deps
# mid-task.
#
# Idempotent: safe to run on every session start. Install chatter is sent to
# stderr (logs) rather than stdout so it does not flood the agent's context.
# Never hard-fails the session: a flaky network degrades to a warning.

set -uo pipefail

# Only run in the remote/web sandbox. Local developers manage their own env.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT"

warned=0

{
  echo "[session-start] led-dashboard environment setup starting"

  # --- Python engine: venv + runtime + dev (pytest, cairosvg) deps -----------
  if [ ! -d .venv ]; then
    python3 -m venv .venv || { echo "[session-start] WARN: venv creation failed"; warned=1; }
  fi
  if [ -x .venv/bin/pip ]; then
    .venv/bin/python -m pip install --upgrade pip \
      || { echo "[session-start] WARN: pip upgrade failed (continuing)"; warned=1; }
    .venv/bin/pip install -r engine/requirements.txt -r engine/requirements-dev.txt \
      || { echo "[session-start] WARN: python dependency install failed"; warned=1; }
  fi

  # --- UI: node deps (only if not already present) ---------------------------
  if [ ! -d ui/node_modules ]; then
    ( cd ui && npm install ) \
      || { echo "[session-start] WARN: npm install failed"; warned=1; }
  fi

  echo "[session-start] setup complete (warnings=$warned)"
} >&2

# Persist PYTHONPATH so ad-hoc `import canvas/apps/libraries...` works from any
# cwd (pytest already sets pythonpath=. via engine/pytest.ini for the suite).
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PYTHONPATH=\"$ROOT/engine\"" >> "$CLAUDE_ENV_FILE"
fi

# One concise line to the agent's context.
if [ "$warned" -eq 0 ]; then
  echo "led-dashboard deps ready: .venv (engine + dev requirements), ui/node_modules. PYTHONPATH set to engine/."
else
  echo "led-dashboard setup ran with warnings (see logs); some deps may need manual install."
fi

exit 0
