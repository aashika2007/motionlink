"""Development server for the circuit module only (not the MotionInk app).

    python dev_server.py            then open http://127.0.0.1:5001/api/circuits

Lets Person 3 try the JSON API before integrating the blueprint into the main app.
"""
import os

from flask import Flask, jsonify

from motionink.circuits.api import circuits_bp
from motionink.circuits.loader import available_circuits, data_dir

app = Flask(__name__)
app.register_blueprint(circuits_bp)


@app.get("/")
def index():
    return jsonify(
        module="MotionInk circuit module (Person 2) dev server",
        data_dir=str(data_dir()),
        circuits=available_circuits(),
        try_these=["/api/circuits", "/api/circuits/<id>",
                   "POST /api/circuits/<id>/analyze  {\"line\": \"raceline\"}",
                   "POST /api/circuits/<id>/compare  {\"reference\": \"raceline\", \"edited\": {\"offsets\": [...]}}"],
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    if not available_circuits():
        print("No circuits downloaded yet. Run: python scripts/fetch_tumftm.py --tracks Spielberg")
    print(f"Circuit API on http://127.0.0.1:{port}  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=port, debug=False)
