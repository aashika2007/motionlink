# Circuit module handoff (Person 2 → team)

## Files I own

```
backend/circuits/__init__.py      public API
backend/circuits/loader.py        load_circuit, available_circuits, Circuit
backend/circuits/geometry.py      calculate_path_length, calculate_curvature, resample
backend/circuits/validation.py    validate_path, project_to_centreline
backend/circuits/performance.py   estimate_performance, VehicleParameters
backend/circuits/editing.py       offsets ↔ lines, drag helpers (boundary-clamped)
backend/circuits/compare.py       compare_lines, detect_sections
backend/circuits/api.py           Flask blueprint (optional integration surface)
backend/circuits/report.py        verification report CLI
backend/circuits/data/README.md   data provenance; downloaded data goes in data/tumftm/
scripts/fetch_tumftm.py             data import
tests/circuits/                     tests (+ tests/__init__.py, tests/circuits/__init__.py)
```

I don't touch tracking, video or frontend files. `motionink/__init__.py` in my zip is an empty placeholder. If the repo already has one, keep yours. All imports inside `circuits/` are relative, so the folder can move if our package name differs.

Dependencies: `numpy` (module), `flask` (only for `api.py`). Python ≥ 3.9.

## Setup (once, needs internet)

```bash
python scripts/fetch_tumftm.py --list                       # what exists, which have race lines
python scripts/fetch_tumftm.py --tracks Spielberg Monza      # download + verify hashes
python -m backend.circuits.report Spielberg Monza          # human-readable verification
python -m unittest discover -s tests -t .                    # incl. real-data tests
```

If the GitHub API rate-limits you, run `git clone https://github.com/TUMFTM/racetrack-database` and then `python scripts/fetch_tumftm.py --from-clone racetrack-database --tracks Spielberg`. Commit `backend/circuits/data/tumftm/` so the demo laptop doesn't need the network.

## Coordinate conventions (please read)

| Space | Units | Axes | Owner |
|---|---|---|---|
| Circuit | metres | x right, **y up** | me |
| Video / canvas | pixels | x right, **y down** | Person 1 / 3 |

My functions only accept and return **circuit metres**. Don't pass video pixel tracks into them. If we want a video track on the circuit, that needs a real calibration (a homography from ≥ 4 known track points), and the UI must say whether it's calibrated. Without that, video results stay in pixels.

Sign conventions:
- Lateral offset **+ = left** of travel.
- Curvature **+ = left turn**.
- Radius is `null` on straights, meaning |κ| < 1e-4 1/m (radius > 10 km).

Canvas transform for Person 3 (fit the circuit, flip y):

```js
function makeView(bounds, canvasW, canvasH, pad = 20) {
  const w = bounds.max_x - bounds.min_x, h = bounds.max_y - bounds.min_y;
  const s = Math.min((canvasW - 2 * pad) / w, (canvasH - 2 * pad) / h);
  const ox = (canvasW - s * w) / 2, oy = (canvasH - s * h) / 2;
  return {
    toCanvas: ([x, y]) => [ox + (x - bounds.min_x) * s, oy + (bounds.max_y - y) * s],
    toMetres: ([px, py]) => [bounds.min_x + (px - ox) / s, bounds.max_y - (py - oy) / s],
  };
}
```

## Python API

```python
from backend.circuits import *

c = load_circuit("spielberg")            # case-insensitive TUMFTM name
c.centreline, c.left_boundary, c.right_boundary, c.raceline   # (N,2) metres; raceline may be None
c.width_left, c.width_right, c.closed, c.summary(), c.source   # source: URL, commit, sha256, notes

calculate_path_length(path, closed=False) -> float  # metres
calculate_curvature(path, closed=False, step_m=2.0, smoothing_m=4.0, zero_tol=1e-4) -> CurvatureProfile
    # .s .x .y .kappa .radius  (uniformly resampled)
validate_path(path, circuit, vehicle_half_width_m=0.0, closed=None) -> dict
    # valid, max_excess_m, min_margin_m, fraction_outside, violations[{from_station_m, to_station_m, side, max_excess_m}]
estimate_performance(path, parameters=None, *, closed=False, step_m=2.0, v_start_mps=None) -> dict
    # estimated_time_s, speed_mps[], segment_time_s[], label, is_estimate=True, parameters
compare_lines(circuit, reference_path, edited_path, parameters=None, *, sections="corners"|int) -> dict
    # measured{...}, estimated{...}, sections[...], summary[...]

offsets_from_path(circuit, path) -> offsets[N]     # one lateral offset per centreline point
line_from_offsets(circuit, offsets) -> (N,2)        # clamped to the track limits
drag_offsets(circuit, offsets, station_m, delta_m, radius_m=40) -> offsets
drag_to_point(circuit, offsets, grab_xy, target_xy, radius_m=40) -> offsets
```

The `parameters` dict takes the keys `a_lat_max_mps2`, `a_accel_max_mps2`, `a_brake_max_mps2`, `v_max_mps` and `combined_grip`. If you omit it, `ILLUSTRATIVE_PARAMETERS` is used. Those are round demo numbers, **not real car data**.

## HTTP API (register the blueprint)

```python
from backend.circuits.api import circuits_bp
app.register_blueprint(circuits_bp)
```

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/circuits` | none | `{circuits: [{id, name, series, has_raceline}]}` |
| GET | `/api/circuits/<id>` | none | summary + `centreline`, `left_boundary`, `right_boundary`, `raceline`, `raceline_offsets`, `bounds_m`, `source` |
| POST | `/api/circuits/<id>/analyze` | `{line, parameters?, vehicle_half_width_m?}` | `length_m`, `curvature`, `validation`, `performance` |
| POST | `/api/circuits/<id>/compare` | `{reference?, edited, parameters?, sections?}` | `measured`, `estimated`, `sections`, `summary`, profiles |
| POST | `/api/circuits/<id>/drag` | `{offsets, station_m, delta_m, radius_m?}` | `{offsets, line}` |
| POST | `/api/circuits/<id>/drag-to-point` | `{offsets, grab_xy, target_xy, radius_m?}` | `{offsets, line}` |

A `line`, `reference` or `edited` value can be any of:
- `"raceline"`
- `"centreline"`
- `{"offsets": [...]}`
- `[[x, y], ...]` in metres

Errors come back as `{error}` with status 400 (bad input) or 404 (circuit not downloaded). Long arrays are decimated to `max_points` (default 1500). NaN/Infinity are never sent.

Suggested editor loop:
1. Load the circuit with `GET /api/circuits/<id>` and draw the boundaries and race line.
2. Start editing from `offsets = raceline_offsets` (or zeros if there's no race line).
3. On drag, convert the mouse to metres with `toMetres`, call `drag-to-point`, and redraw `line`.
4. On release, call `compare` with `{"reference": "raceline", "edited": {"offsets": offsets}}`.

## What the UI must show

- **Times and speeds:** show `label` next to every one ("Simulated estimate … not a real lap time"), plus the parameters used.
- **Race line:** call it "Reference line (TUMFTM minimum-curvature)", never "fastest line" or "real racing line".
- **Section names:** "Corner n" / "Straight n" are detected sections, not official turn numbers.
- **Geometry vs estimates:** lengths, curvature and track-limit checks are measured geometry. Times are model estimates.
- **Credit:** show "Circuit data: TUMFTM racetrack-database (LGPL-3.0)".

## Questions for the team

1. Person 3, is the backend Flask with our package named `motionink`? If not, send me `app.py` or the equivalent and I'll adapt the blueprint.
2. Which circuit matches the F1 clip we're demoing? I'll run the report on it and check its data quality.
3. Person 1, do we have, or want, a calibrated video-to-circuit mapping? If not, video tracks stay in pixels and I won't align them.
