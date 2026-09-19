#!/usr/bin/env bash
#
# Start the QMAFIB platform.
#
#   API        http://localhost:8000   (interactive docs at /docs)
#   Dashboard  http://localhost:5173
#
# Works on macOS, Linux, and Windows under Git Bash / WSL. Creates the
# virtualenv and installs dependencies on first run. Ctrl-C stops both servers.
#
set -uo pipefail
cd "$(dirname "$0")"

API_PORT=${API_PORT:-8000}
UI_PORT=${UI_PORT:-5173}

# A virtualenv puts Python in bin/ on Unix and Scripts/ on Windows. Check both
# rather than assuming, or Git Bash users get a confusing "recreating venv".
venv_python() {
  if   [ -x backend/.venv/bin/python ];         then echo backend/.venv/bin/python
  elif [ -x backend/.venv/Scripts/python.exe ]; then echo backend/.venv/Scripts/python.exe
  else echo ""
  fi
}

# Likewise, `python3` does not exist on a default Windows install.
host_python() {
  for candidate in python3 python py; do
    if command -v "$candidate" > /dev/null 2>&1; then echo "$candidate"; return; fi
  done
  echo ""
}

PY=$(venv_python)

if [ -z "$PY" ]; then
  BOOTSTRAP=$(host_python)
  if [ -z "$BOOTSTRAP" ]; then
    echo "error: no Python found on PATH. Install Python 3.11+ and try again." >&2
    exit 1
  fi
  echo "No virtualenv found — creating backend/.venv …"
  "$BOOTSTRAP" -m venv backend/.venv --system-site-packages || {
    echo "error: could not create the virtualenv." >&2
    exit 1
  }
  PY=$(venv_python)
  [ -n "$PY" ] || { echo "error: virtualenv created but no interpreter found." >&2; exit 1; }
  echo "Installing backend dependencies …"
  "$PY" -m pip install -q -r backend/requirements.txt || {
    echo "error: dependency install failed." >&2
    exit 1
  }
fi

if ! command -v npm > /dev/null 2>&1; then
  echo "error: npm not found. Install Node 18+ to run the dashboard." >&2
  echo "       The backend alone still works: $PY -m uvicorn app.main:app --port $API_PORT" >&2
  exit 1
fi

if [ ! -d frontend/node_modules ]; then
  echo "Installing dashboard dependencies (first run only, ~30s) …"
  npm install --prefix frontend || { echo "error: npm install failed." >&2; exit 1; }
fi

# Absolute path: the API is launched from inside backend/.
PY_ABS="$PWD/$PY"

cleanup() {
  echo
  echo "Stopping servers …"
  kill 0 2>/dev/null
}
trap cleanup EXIT INT TERM

echo
echo "  API        http://localhost:$API_PORT      (docs at /docs)"
echo "  Dashboard  http://localhost:$UI_PORT"
echo
echo "  Ctrl-C to stop both."
echo

( cd backend && "$PY_ABS" -m uvicorn app.main:app --port "$API_PORT" ) &
npm run dev --prefix frontend -- --port "$UI_PORT" &

wait
