#!/usr/bin/env bash
# Person 2 circuit module: install, download real data, verify, test.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
"$PY" -m pip install -r requirements-circuits.txt
TRACKS=${*:-"Spielberg Monza Silverstone"}
"$PY" scripts/fetch_tumftm.py --tracks $TRACKS
"$PY" -m motionink.circuits.report $TRACKS || true
"$PY" -m unittest discover -s tests -t . -v
echo "All done. Start the API with: $PY dev_server.py"
