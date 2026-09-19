#!/usr/bin/env bash
# Start the QMAFIB platform: API on :8000, dashboard on :5173.
# macOS / Linux.  Windows: use run.ps1
set -euo pipefail

cd "$(dirname "$0")"
PY=backend/.venv/bin/python

if [ ! -x "$PY" ]; then
  echo "No virtualenv found. Creating one…"
  python3 -m venv backend/.venv --system-site-packages
  "$PY" -m pip install -q -r backend/requirements.txt
fi

if [ ! -d frontend/node_modules ]; then
  echo "Installing dashboard dependencies…"
  npm install --prefix frontend
fi

cleanup() { echo; echo "Stopping…"; kill 0; }
trap cleanup EXIT INT TERM

echo "API       → http://localhost:8000  (docs at /docs)"
echo "Dashboard → http://localhost:5173"
echo

( cd backend && exec ../"$PY" -m uvicorn app.main:app --port 8000 ) &
npm run dev --prefix frontend &

wait
