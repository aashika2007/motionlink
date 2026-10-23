"""Racing-line editing helpers in circuit metres.

A line is represented as one lateral offset per centreline point (+ = left of travel),
so clamping to the track limits is exact and cheap:  -(w_right - m) ≤ d ≤ (w_left - m),
with m = vehicle_half_width_m. The UI (Person 3) can drag in metres and call these
functions; it never needs to re-implement the boundary maths.
"""
from __future__ import annotations

import numpy as np

from .geometry import as_path, cumulative_distance
from .validation import project_to_centreline


def offset_limits(circuit, vehicle_half_width_m: float = 0.0):
    lo = -(circuit.width_right - vehicle_half_width_m)
    hi = circuit.width_left - vehicle_half_width_m
    if np.any(hi < lo):
        raise ValueError("vehicle_half_width_m is wider than half the track at some point.")
    return lo, hi


def clamp_offsets(circuit, offsets, vehicle_half_width_m: float = 0.0) -> np.ndarray:
    d = np.asarray(offsets, dtype=float)
    if d.shape != (len(circuit.centreline),):
        raise ValueError(f"Expected {len(circuit.centreline)} offsets (one per centreline point).")
    lo, hi = offset_limits(circuit, vehicle_half_width_m)
    return np.clip(d, lo, hi)


def line_from_offsets(circuit, offsets, vehicle_half_width_m: float = 0.0, clamp: bool = True) -> np.ndarray:
    d = clamp_offsets(circuit, offsets, vehicle_half_width_m) if clamp else np.asarray(offsets, float)
    return circuit.centreline + circuit.normals_left * d[:, None]


def offsets_from_path(circuit, path) -> np.ndarray:
    """Lateral offset of an existing line (e.g. the reference race line) at each
    centreline station, by projecting the line and interpolating periodically."""
    pr = project_to_centreline(as_path(path), circuit)
    order = np.argsort(pr.station_m)
    s, d = pr.station_m[order], pr.lateral_m[order]
    s_c = cumulative_distance(circuit.centreline, circuit.closed)
    if circuit.closed:
        L = circuit.centreline_length_m
        s = np.concatenate([s - L, s, s + L])
        d = np.concatenate([d, d, d])
    return np.interp(s_c, s, d)


def drag_offsets(circuit, offsets, station_m: float, delta_m: float, radius_m: float = 40.0,
                 vehicle_half_width_m: float = 0.0) -> np.ndarray:
    """Push the line sideways by delta_m at station_m with a smooth Gaussian falloff
    (sigma = radius_m along the track), then clamp to the track limits."""
    if radius_m <= 0:
        raise ValueError("radius_m must be > 0.")
    d = np.asarray(offsets, dtype=float).copy()
    s_c = cumulative_distance(circuit.centreline, circuit.closed)
    gap = np.abs(s_c - station_m)
    if circuit.closed:
        L = circuit.centreline_length_m
        gap = np.minimum(gap, L - gap)
    d += delta_m * np.exp(-0.5 * (gap / radius_m) ** 2)
    return clamp_offsets(circuit, d, vehicle_half_width_m)


def drag_to_point(circuit, offsets, grab_xy, target_xy, radius_m: float = 40.0,
                  vehicle_half_width_m: float = 0.0) -> np.ndarray:
    """Mouse/pinch drag in circuit metres: the line point nearest grab_xy moves sideways
    so its offset matches target_xy's offset at the same station."""
    grab = project_to_centreline([grab_xy], circuit)
    target = project_to_centreline([target_xy], circuit)
    s_c = cumulative_distance(circuit.centreline, circuit.closed)
    current = float(np.interp(grab.station_m[0], s_c, np.asarray(offsets, float)))
    return drag_offsets(circuit, offsets, float(grab.station_m[0]), float(target.lateral_m[0]) - current,
                        radius_m, vehicle_half_width_m)
