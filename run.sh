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

# Refuse to start on an occupied port.
#
# Without this, uvicorn fails to bind, exits quietly, and whatever was already
# listening keeps serving — so you edit the backend, restart, and the browser
# still talks to the old process. That failure mode wastes a long time because
# everything *looks* fine: both URLs return 200.
port_in_use() {
  if command -v python > /dev/null 2>&1 || command -v python3 > /dev/null 2>&1; then
    "$PY" - "$1" <<'PYCHECK'
import socket, sys

# Probe both stacks: uvicorn listens on IPv4 here while Vite binds IPv6 only,
# so checking one address would miss the other.
port = int(sys.argv[1])
for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
    try:
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(0.4)
        if s.connect_ex((host, port)) == 0:
            sys.exit(1)          # something is listening
    except OSError:
        pass                      # family unavailable; try the next
    finally:
        s.close()
sys.exit(0)                       # port is free
PYCHECK
    return $?
  fi
  return 0
}

for check in "$API_PORT:API" "$UI_PORT:dashboard"; do
  p="${check%%:*}"; what="${check##*:}"
  if ! port_in_use "$p"; then
    echo "error: port $p is already in use, so the $what cannot start." >&2
    echo "       Something is already listening there — probably an earlier run." >&2
    echo "       Stop it first, or choose another port:" >&2
    echo "         API_PORT=8001 UI_PORT=5174 ./run.sh" >&2
    exit 1
  fi
done

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

# --reload: the dashboard already hot-reloads, and without the same on the API
# a backend edit leaves the browser talking to stale code while everything
# still returns 200. That mismatch is invisible and costly to debug.
#
# --host 127.0.0.1 is uvicorn's default and is stated anyway: the security model
# in app/security.py assumes loopback-only, and an assumption that lives in a
# default is one nobody sees before overriding it. Serving the dashboard to a
# conference network should be a deliberate edit here, not a flag someone adds
# without reading what it exposes.
( cd backend && "$PY_ABS" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --reload ) &
npm run dev --prefix frontend -- --port "$UI_PORT" &

wait
