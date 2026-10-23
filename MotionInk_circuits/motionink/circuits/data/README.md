# Circuit data

This folder ships **empty on purpose**. Real data is downloaded, never typed in:

```bash
python scripts/fetch_tumftm.py --list
python scripts/fetch_tumftm.py --tracks Spielberg Monza Silverstone
```

Files land in `data/tumftm/` (or `$MOTIONINK_CIRCUIT_DATA`) with a `manifest.json` recording the commit, URL, git blob SHA-1 (checked against GitHub) and SHA-256 of every file, plus the dataset's `LICENSE`.

## Source

TUMFTM racetrack-database, https://github.com/TUMFTM/racetrack-database, Chair of Automotive Technology, Technical University of Munich. Licence: **LGPL-3.0**. Keep the downloaded `LICENSE` file and credit the source in the demo.

What the source README says, in summary:

- **Tracks** (`tracks/<Name>.csv`, columns `x_m, y_m, w_tr_right_m, w_tr_left_m`). Centrelines come from OpenStreetMap GPS points and were smoothed, so they are not exactly mid-track. Widths to the right and left of travel were extracted from satellite images.
- **Race lines** (`racelines/<Name>.csv`, columns `x_m, y_m`). They were computed with TUMFTM's minimum-curvature optimisation and lie within the track boundaries. They are **not telemetry** and **not a proven fastest line**.
- **Data quality** varies by circuit with the quality of the GPS and satellite source.

## Coordinate system and conversions

- **Units and frame:** metres, planar, right-handed, **y up**.
- **Origin and orientation:** not documented by the source. Treat both as arbitrary and don't assume x is east.
- **Boundaries are derived, not stored.** `left = centre + n_left · w_left` and `right = centre − n_left · w_right`, where `n_left` is the unit tangent rotated +90°. TUMFTM's own tools use spline normals, so boundaries can differ by centimetres in tight corners.
- **Closing point:** if a file repeats its first point at the end, the duplicate is dropped. Circuits are treated as closed loops.
- **No other conversions** are made. No reprojection, scaling or offsets.

## Not used

- **FastF1 and OpenF1:** no telemetry is loaded by this module.
- **Video:** video pixels are a different space. Mapping them onto circuit metres needs a genuine calibration (e.g. a homography from at least 4 surveyed points), which this module does not do.
