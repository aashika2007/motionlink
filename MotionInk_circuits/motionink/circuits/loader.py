"""Load real circuit geometry from TUMFTM racetrack-database files.

Source: https://github.com/TUMFTM/racetrack-database (LGPL-3.0), downloaded with
``python scripts/fetch_tumftm.py``. This module never ships or invents data: it reads
only files present in the data directory.

File formats (from the source README)
- tracks/<Name>.csv     x_m, y_m, w_tr_right_m, w_tr_left_m
  Smoothed OSM-derived centreline plus track widths to the right and left of the
  direction of travel, measured from satellite imagery.
- racelines/<Name>.csv  x_m, y_m
  Minimum-curvature race line from TUMFTM's optimiser. It is NOT telemetry and NOT a
  proven fastest line.

Frame: planar metres, right-handed, y up. Origin and orientation relative to true north
are not documented by the source, so they are treated as arbitrary.
Boundaries are derived here as centre ± width × unit normal (left normal = tangent
rotated +90°), matching how the dataset defines the widths.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .geometry import as_path, calculate_path_length, left_normals, looks_closed

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "tumftm"
SOURCE_URL = "https://github.com/TUMFTM/racetrack-database"
LICENSE = "LGPL-3.0"
FRAME = "TUMFTM local planar frame: metres, right-handed, y up; origin/orientation arbitrary"

# Series listed for each circuit in the source README (used for display only).
SERIES = {
    "Austin": "F1", "BrandsHatch": "DTM", "Budapest": "F1", "Catalunya": "F1", "Hockenheim": "F1, DTM",
    "IMS": "IndyCar", "Melbourne": "F1", "MexicoCity": "F1", "Montreal": "F1", "Monza": "F1",
    "MoscowRaceway": "DTM", "Norisring": "DTM", "Nuerburgring": "DTM", "Oschersleben": "DTM",
    "Sakhir": "F1", "SaoPaulo": "F1", "Sepang": "F1", "Shanghai": "F1", "Silverstone": "F1",
    "Sochi": "F1", "Spa": "F1", "Spielberg": "F1", "Suzuka": "F1", "YasMarina": "F1", "Zandvoort": "DTM",
}


def data_dir(override=None) -> Path:
    return Path(override or os.environ.get("MOTIONINK_CIRCUIT_DATA") or DEFAULT_DATA_DIR)


def parse_tumftm_csv(path, columns: int) -> np.ndarray:
    """Parse a TUMFTM CSV: '#'-prefixed or non-numeric header lines are skipped."""
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for lineno, row in enumerate(csv.reader(fh), 1):
            if not row or not "".join(row).strip() or row[0].lstrip().startswith("#"):
                continue
            try:
                vals = [float(v) for v in row]
            except ValueError:
                if not rows:  # a plain header line
                    continue
                raise ValueError(f"{path}: non-numeric data on line {lineno}.")
            if len(vals) != columns:
                raise ValueError(f"{path}: expected {columns} columns, found {len(vals)} on line {lineno}.")
            rows.append(vals)
    if len(rows) < 4:
        raise ValueError(f"{path}: only {len(rows)} data rows.")
    arr = np.array(rows)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{path}: contains non-finite values.")
    return arr


def _sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class Circuit:
    id: str
    name: str
    centreline: np.ndarray        # (N, 2) metres
    width_right: np.ndarray       # (N,) metres, right of travel
    width_left: np.ndarray        # (N,) metres, left of travel
    raceline: np.ndarray | None   # (M, 2) metres, minimum-curvature reference, if provided
    closed: bool = True
    source: dict = field(default_factory=dict)

    @property
    def normals_left(self) -> np.ndarray:
        return left_normals(self.centreline, self.closed)

    @property
    def left_boundary(self) -> np.ndarray:
        return self.centreline + self.normals_left * self.width_left[:, None]

    @property
    def right_boundary(self) -> np.ndarray:
        return self.centreline - self.normals_left * self.width_right[:, None]

    @property
    def centreline_length_m(self) -> float:
        return calculate_path_length(self.centreline, self.closed)

    @property
    def bounds(self) -> dict:
        allp = np.vstack([self.left_boundary, self.right_boundary])
        lo, hi = allp.min(0), allp.max(0)
        return {"min_x": float(lo[0]), "min_y": float(lo[1]), "max_x": float(hi[0]), "max_y": float(hi[1])}

    def summary(self) -> dict:
        w = self.width_left + self.width_right
        return {
            "id": self.id, "name": self.name, "series": SERIES.get(self.name),
            "closed": self.closed, "points": int(len(self.centreline)),
            "centreline_length_m": round(self.centreline_length_m, 1),
            "track_width_m": {"min": round(float(w.min()), 2), "mean": round(float(w.mean()), 2),
                              "max": round(float(w.max()), 2)},
            "has_raceline": self.raceline is not None,
            "raceline_length_m": (round(calculate_path_length(self.raceline, self.closed), 1)
                                  if self.raceline is not None else None),
            "bounds_m": self.bounds, "frame": FRAME, "units": "m", "source": self.source,
        }


def _manifest(directory: Path) -> dict:
    f = directory / "manifest.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def available_circuits(directory=None) -> list[dict]:
    """Circuits whose track file is actually present on disk."""
    d = data_dir(directory)
    tracks = sorted((d / "tracks").glob("*.csv")) if (d / "tracks").is_dir() else []
    return [{"id": p.stem.lower(), "name": p.stem, "series": SERIES.get(p.stem),
             "has_raceline": (d / "racelines" / p.name).exists()} for p in tracks]


def _resolve(circuit_id: str, d: Path) -> Path:
    want = str(circuit_id).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    for p in (d / "tracks").glob("*.csv") if (d / "tracks").is_dir() else []:
        if p.stem.lower() == want:
            return p
    have = ", ".join(c["name"] for c in available_circuits(d)) or "none"
    raise FileNotFoundError(
        f"Circuit '{circuit_id}' is not downloaded. Available: {have}. "
        f"Run: python scripts/fetch_tumftm.py --tracks {circuit_id}")


def load_circuit(circuit_id: str, directory=None) -> Circuit:
    """Load centreline, widths and (if present) race line for a downloaded circuit."""
    d = data_dir(directory)
    track_file = _resolve(circuit_id, d)
    arr = parse_tumftm_csv(track_file, 4)
    centre = as_path(arr[:, :2])
    w_right, w_left = arr[:, 2], arr[:, 3]
    if np.any(w_right <= 0) or np.any(w_left <= 0):
        raise ValueError(f"{track_file}: track widths must be positive.")
    closed = looks_closed(centre)
    gap = float(np.linalg.norm(centre[-1] - centre[0]))
    if closed and gap < 1e-6:  # explicit duplicate closing point
        centre, w_right, w_left = centre[:-1], w_right[:-1], w_left[:-1]

    raceline = None
    rl_file = d / "racelines" / track_file.name
    if rl_file.exists():
        rl = parse_tumftm_csv(rl_file, 2)
        if closed and np.linalg.norm(rl[-1] - rl[0]) < 1e-6:
            rl = rl[:-1]
        raceline = as_path(rl)

    man = _manifest(d).get("files", {})
    source = {
        "dataset": SOURCE_URL, "license": LICENSE,
        "commit": _manifest(d).get("commit"),
        "track_file": f"tracks/{track_file.name}", "track_sha256": _sha256(track_file),
        "raceline_file": f"racelines/{rl_file.name}" if raceline is not None else None,
        "raceline_sha256": _sha256(rl_file) if raceline is not None else None,
        "downloaded_from": man.get(f"tracks/{track_file.name}", {}).get("url"),
        "start_gap_m": round(gap, 3),
        "notes": ["Centreline is smoothed OSM GPS data and not exactly mid-track.",
                  "Widths were extracted from satellite images; accuracy varies by circuit.",
                  "Race line is TUMFTM's minimum-curvature result, not telemetry or a fastest line."],
    }
    return Circuit(id=track_file.stem.lower(), name=track_file.stem, centreline=centre,
                   width_right=w_right.astype(float), width_left=w_left.astype(float),
                   raceline=raceline, closed=closed, source=source)
