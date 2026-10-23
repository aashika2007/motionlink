"""Flask blueprint for the circuit module. Register with:

    from backend.circuits.api import circuits_bp
    app.register_blueprint(circuits_bp)            # routes under /api/circuits

All coordinates are circuit metres (y up). Infinite values (e.g. radius on a straight)
are sent as null.
"""
from __future__ import annotations

import math

import numpy as np
from flask import Blueprint, jsonify, request

from .compare import compare_lines
from .editing import drag_offsets, drag_to_point, line_from_offsets, offsets_from_path
from .geometry import calculate_curvature, calculate_path_length
from .loader import available_circuits, load_circuit
from .performance import estimate_performance
from .validation import validate_path

circuits_bp = Blueprint("circuits", __name__, url_prefix="/api/circuits")


def jsonable(obj, max_points=None):
    """Convert numpy values to JSON types; decimate long arrays; inf/nan → None."""
    if isinstance(obj, dict):
        return {k: jsonable(v, max_points) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v, max_points) for v in obj]
    if isinstance(obj, np.ndarray):
        arr = obj
        if max_points and arr.ndim >= 1 and len(arr) > max_points:
            arr = arr[np.linspace(0, len(arr) - 1, max_points).round().astype(int)]
        return jsonable(arr.tolist())
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if not math.isfinite(f) else float(f"{f:.7g}")  # keep small curvatures precise
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Send a JSON object.")
    return data


def _line(circuit, spec, name):
    """A line is "raceline", "centreline", {"offsets": [...]} or [[x, y], ...] in metres."""
    if spec == "raceline":
        if circuit.raceline is None:
            raise ValueError(f"{circuit.name} has no reference race line in the dataset.")
        return circuit.raceline
    if spec == "centreline":
        return circuit.centreline
    if isinstance(spec, dict) and "offsets" in spec:
        return line_from_offsets(circuit, spec["offsets"])
    if isinstance(spec, list):
        return spec
    raise ValueError(f"'{name}' must be \"raceline\", \"centreline\", {{\"offsets\": [...]}} or a list of [x, y].")


@circuits_bp.errorhandler(ValueError)
def _bad(exc):
    return jsonify(error=str(exc)), 400


@circuits_bp.errorhandler(FileNotFoundError)
def _missing(exc):
    return jsonify(error=str(exc)), 404


@circuits_bp.get("")
def list_circuits():
    return jsonify(circuits=available_circuits())


@circuits_bp.get("/<cid>")
def get_circuit(cid):
    c = load_circuit(cid)
    data = c.summary()
    data.update(centreline=c.centreline, left_boundary=c.left_boundary, right_boundary=c.right_boundary,
                width_left=c.width_left, width_right=c.width_right, raceline=c.raceline,
                raceline_offsets=offsets_from_path(c, c.raceline) if c.raceline is not None else None)
    return jsonify(jsonable(data))


@circuits_bp.post("/<cid>/analyze")
def analyze(cid):
    c, b = load_circuit(cid), _body()
    line = _line(c, b.get("line", "raceline"), "line")
    prof = calculate_curvature(line, closed=c.closed)
    perf = estimate_performance(line, b.get("parameters"), closed=c.closed)
    return jsonify(jsonable({
        "length_m": calculate_path_length(line, c.closed),
        "curvature": {"s_m": prof.s, "kappa_1pm": prof.kappa, "radius_m": prof.radius,
                      "max_abs_kappa_1pm": float(np.abs(prof.kappa).max())},
        "validation": validate_path(line, c, float(b.get("vehicle_half_width_m", 0.0))),
        "performance": perf,
    }, max_points=int(b.get("max_points", 1500))))


@circuits_bp.post("/<cid>/compare")
def compare(cid):
    c, b = load_circuit(cid), _body()
    res = compare_lines(c, _line(c, b.get("reference", "raceline"), "reference"),
                        _line(c, b.get("edited"), "edited"), b.get("parameters"),
                        sections=b.get("sections", "corners"),
                        vehicle_half_width_m=float(b.get("vehicle_half_width_m", 0.0)))
    return jsonify(jsonable(res, max_points=int(b.get("max_points", 1500))))


@circuits_bp.post("/<cid>/drag")
def drag(cid):
    """Body: {offsets, station_m, delta_m, radius_m?, vehicle_half_width_m?} → new offsets + line."""
    c, b = load_circuit(cid), _body()
    try:
        new = drag_offsets(c, b["offsets"], float(b["station_m"]), float(b["delta_m"]),
                           float(b.get("radius_m", 40.0)), float(b.get("vehicle_half_width_m", 0.0)))
    except KeyError as exc:
        raise ValueError(f"Missing field {exc}.") from exc
    return jsonify(jsonable({"offsets": new, "line": line_from_offsets(c, new)}))


@circuits_bp.post("/<cid>/drag-to-point")
def drag_point(cid):
    """Body: {offsets, grab_xy: [x, y], target_xy: [x, y], radius_m?, vehicle_half_width_m?}
    (all metres) → new offsets + line. For mouse/pinch drags converted to circuit metres."""
    c, b = load_circuit(cid), _body()
    try:
        new = drag_to_point(c, b["offsets"], [float(v) for v in b["grab_xy"]], [float(v) for v in b["target_xy"]],
                            float(b.get("radius_m", 40.0)), float(b.get("vehicle_half_width_m", 0.0)))
    except KeyError as exc:
        raise ValueError(f"Missing field {exc}.") from exc
    return jsonify(jsonable({"offsets": new, "line": line_from_offsets(c, new)}))
