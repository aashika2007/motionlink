"""MotionLink server: serves the frontend and the backend APIs.

    python app.py        then open http://127.0.0.1:5000

Owners:
- Circuit API (/api/circuits/...): Person 2, backend/circuits/
- Tracking/video API: Person 1, register it in the marked block below
- Frontend (frontend/): Person 3
"""
import os

from flask import Flask, jsonify, send_from_directory

from backend.circuits.api import circuits_bp
from backend.circuits.loader import available_circuits, data_dir

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(HERE, "frontend")

app = Flask(__name__, static_folder=FRONTEND, static_url_path="")
app.register_blueprint(circuits_bp)

# --- Person 1: register tracking/video routes here, e.g.
# from backend.tracking import tracking_bp
# app.register_blueprint(tracking_bp)


@app.get("/")
def index():
    return send_from_directory(FRONTEND, "index.html")


@app.get("/api/health")
def health():
    return jsonify(ok=True, circuits=[c["name"] for c in available_circuits()], circuit_data_dir=str(data_dir()))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    if not available_circuits():
        print("No circuit data yet. Run: python scripts/fetch_tumftm.py --tracks Spielberg")
    print(f"MotionLink running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
