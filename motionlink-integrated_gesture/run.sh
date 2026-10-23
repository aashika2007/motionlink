#!/usr/bin/env bash
# MotionLink: install, get circuit data on first run, start the app.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
"$PY" -m pip install -r requirements.txt
if [ ! -f backend/circuits/data/tumftm/manifest.json ]; then
  echo "Downloading real circuit data from TUMFTM..."
  "$PY" scripts/fetch_tumftm.py --tracks Spielberg Monza Silverstone
fi
PORT="${PORT:-5000}"
if "$PY" -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1', $PORT)) == 0 else 1)"; then PORT=5050; fi
( sleep 2; (open "http://127.0.0.1:$PORT" || xdg-open "http://127.0.0.1:$PORT") >/dev/null 2>&1 ) &
PORT="$PORT" exec "$PY" app.py
