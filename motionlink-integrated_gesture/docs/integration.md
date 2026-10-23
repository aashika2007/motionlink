# MotionLink integration

## Run

Windows: double-click `run.bat`. macOS/Linux: `./run.sh`. Or by hand:

```bash
pip install -r requirements.txt
python scripts/fetch_tumftm.py --tracks Spielberg Monza Silverstone   # once, needs internet
python app.py                                                          # http://127.0.0.1:5000
```

Open the app through the server URL. Opening `frontend/index.html` directly as a file can't reach the API.

## How the pieces connect

```
browser ── frontend/index.html, app.js (Person 3), circuit-editor.js (circuit panel)
   │  fetch /api/...
app.py (Flask) ── serves frontend/ and registers blueprints
   ├── /api/circuits/...   backend/circuits/   (Person 2)  ← working
   └── tracking routes     backend/tracking.py (Person 1)  ← register in app.py's marked block
```

- `backend/circuit_data.py`, `racing_line.py` and `performance_model.py` re-export Person 2's functions from `backend/circuits/`.
- `backend/tracking.py` and `video_processor.py` are untouched (still empty) for Person 1.
- `frontend/circuit-editor.js` drives the circuit panel and the analysis panel using the existing element ids:
  - `circuit-canvas`, `canvas-label`, `circuit-status` (circuit panel)
  - `analysis-workspace`, `.analysis-empty` (analysis panel)
- The only change to Person 3's files is one line in `index.html`: `<script src="circuit-editor.js"></script>` after `app.js`. `gestures.js` is loaded on demand by `circuit-editor.js`.

If you rename those ids or restructure the panels, update the `getElementById` calls at the top of `circuit-editor.js`. Person 3 can restyle or replace it; the API contract is in `docs/circuits_api.md`.

## Hand gestures (optional)

1. Click **Hand gestures: off** in the circuit panel and allow camera access.
2. A small mirrored preview appears, along with a lime cursor on the canvas.
3. **Pinch** (thumb and index finger) near the green line to grab it, **move your hand** to bend it, and **open your fingers** to drop it. The comparison updates when you let go.
4. Moving your hand out of view also drops the line.

How it works:
- **Files:** `frontend/gestures.js` loads MediaPipe Hand Landmarker from jsDelivr the first time the button is pressed. It tries version 0.10.14 first, then the latest release.
- **Pinch detection:** pinch means thumb–index distance below 0.33 × palm size, and release means above 0.48. The gap between the two stops flicker. The cursor is smoothed, and the outer 12% of the camera frame is ignored so the canvas edges are easy to reach.
- **Shared code path:** gestures and the mouse call the same `grab` / `move` / `release` functions in `circuit-editor.js`, so editing behaves identically. The grab radius is 28 px for a hand and 14 px for the mouse.
- **Needs:** internet on first use (MediaPipe CDN and model), a webcam, and the page opened at `http://127.0.0.1:5000`, because browsers only allow cameras on localhost or HTTPS.
- **Fallback:** if the camera or model is unavailable, the canvas says so and the mouse keeps working.

## Coordinates

- **Circuit API:** metres, y up.
- **Canvas and video:** pixels, y down.
- **Converting:** `circuit-editor.js` converts with `makeView().toCanvas` / `toMetres`.
- **Video tracks:** keep them in pixels unless a real calibration maps them onto the circuit.

## Tests

```bash
python -m unittest discover -s tests -t .
```

Circuit-module tests always run. The real-data tests run once data is downloaded.
