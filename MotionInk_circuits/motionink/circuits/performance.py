"""Simplified performance estimate for a line (a SIMULATED ESTIMATE, not a lap time).

Model: quasi-steady-state point mass.
1. Corner speed limit from curvature:  v_lim = min(v_max, sqrt(a_lat_max / |κ|)).
2. Forward pass (acceleration):   v[i+1] ≤ sqrt(v[i]² + 2·a_x·ds)
   Backward pass (braking):       v[i]   ≤ sqrt(v[i+1]² + 2·a_b·ds)
   With combined_grip, longitudinal capability shrinks with lateral use (friction
   ellipse): a_x = a_max·sqrt(1 − (v²|κ| / a_lat_max)²).
3. Segment time dt = ds / mean(v[i], v[i+1]); total = Σ dt.

Not modelled: aero downforce/drag varying with speed, power curve, gears, tyres,
mass, elevation, banking, driver, traffic. Every parameter is an assumption supplied by
the user; nothing here is measured from a car. Use results to compare lines under the
same assumptions, never as a real lap time.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .geometry import calculate_curvature

ESTIMATE_LABEL = "Simulated estimate from a simplified point-mass model with assumed parameters — not a real lap time."


@dataclass
class VehicleParameters:
    a_lat_max_mps2: float      # cornering acceleration limit
    a_accel_max_mps2: float    # traction/power-limited acceleration
    a_brake_max_mps2: float    # braking deceleration (positive number)
    v_max_mps: float           # top speed cap
    combined_grip: bool = True
    note: str = "user-supplied assumption"

    def validate(self) -> "VehicleParameters":
        for k in ("a_lat_max_mps2", "a_accel_max_mps2", "a_brake_max_mps2", "v_max_mps"):
            v = getattr(self, k)
            if not (isinstance(v, (int, float)) and np.isfinite(v) and v > 0):
                raise ValueError(f"{k} must be a positive number.")
        return self

    @classmethod
    def from_dict(cls, d: dict | None) -> "VehicleParameters":
        if not d:
            return ILLUSTRATIVE_PARAMETERS
        base = asdict(ILLUSTRATIVE_PARAMETERS)
        unknown = set(d) - set(base)
        if unknown:
            raise ValueError(f"Unknown parameter(s): {', '.join(sorted(unknown))}.")
        base.update(d)
        if "note" not in d:
            base["note"] = "user-supplied assumption"
        try:
            for k in ("a_lat_max_mps2", "a_accel_max_mps2", "a_brake_max_mps2", "v_max_mps"):
                base[k] = float(base[k])
        except (TypeError, ValueError) as exc:
            raise ValueError("Vehicle parameters must be numbers.") from exc
        return cls(**base).validate()


# Round numbers chosen only so the demo runs. They are NOT measured or published values
# for any car; replace them with your own assumptions.
ILLUSTRATIVE_PARAMETERS = VehicleParameters(
    a_lat_max_mps2=30.0, a_accel_max_mps2=10.0, a_brake_max_mps2=35.0, v_max_mps=90.0,
    combined_grip=True,
    note="illustrative round-number assumptions for the demo; not measured data for any real car",
)


def _speed_profile(kappa, ds, p: VehicleParameters, closed: bool, v_start):
    n = len(kappa)
    absk = np.abs(kappa)
    with np.errstate(divide="ignore"):
        v_lim = np.where(absk > 0, np.sqrt(p.a_lat_max_mps2 / np.maximum(absk, 1e-12)), np.inf)
    v_lim = np.minimum(v_lim, p.v_max_mps)

    def avail(a_max, v, k):
        if not p.combined_grip:
            return a_max
        use = (v * v * k) / p.a_lat_max_mps2
        return a_max * np.sqrt(max(0.0, 1.0 - min(1.0, use) ** 2))

    if closed:
        # Start where the speed is pinned by the corner limit, so one forward and one
        # backward pass are consistent across the start/finish wrap.
        r = int(np.argmin(v_lim))
        order = np.roll(np.arange(n), -r)
        vl, kk = v_lim[order], absk[order]
        v = vl.copy()
        for i in range(n - 1):
            v[i + 1] = min(v[i + 1], np.sqrt(v[i] ** 2 + 2 * avail(p.a_accel_max_mps2, v[i], kk[i]) * ds))
        # wrap: the point after the last is the first (v[0] = its limit)
        v[-1] = min(v[-1], np.sqrt(v[0] ** 2 + 2 * avail(p.a_brake_max_mps2, v[0], kk[0]) * ds))
        for i in range(n - 2, -1, -1):
            v[i] = min(v[i], np.sqrt(v[i + 1] ** 2 + 2 * avail(p.a_brake_max_mps2, v[i + 1], kk[i + 1]) * ds))
        out = np.empty(n)
        out[order] = v
        return out, v_lim
    v = v_lim.copy()
    if v_start is not None:
        v[0] = min(v[0], float(v_start))
    for i in range(n - 1):
        v[i + 1] = min(v[i + 1], np.sqrt(v[i] ** 2 + 2 * avail(p.a_accel_max_mps2, v[i], absk[i]) * ds))
    for i in range(n - 2, -1, -1):
        v[i] = min(v[i], np.sqrt(v[i + 1] ** 2 + 2 * avail(p.a_brake_max_mps2, v[i + 1], absk[i + 1]) * ds))
    return v, v_lim


def estimate_performance(path, parameters: VehicleParameters | dict | None = None, *, closed: bool = False,
                         step_m: float = 2.0, smoothing_m: float = 4.0, v_start_mps: float | None = None) -> dict:
    """Speed profile and travel-time estimate for a line in circuit metres.

    For open paths, v_start_mps=None means a flying start at the first point's corner
    limit; pass 0 for a standing start.
    """
    p = parameters if isinstance(parameters, VehicleParameters) else VehicleParameters.from_dict(parameters)
    p.validate()
    prof = calculate_curvature(path, closed=closed, step_m=step_m, smoothing_m=smoothing_m)
    ds = prof.step_m
    v, v_lim = _speed_profile(prof.kappa, ds, p, closed, v_start_mps)
    v_next = np.roll(v, -1) if closed else v[1:]
    v_here = v if closed else v[:-1]
    v_mean = np.maximum((v_here + v_next) / 2, 1e-6)
    dt = ds / v_mean
    a_long = (v_next ** 2 - v_here ** 2) / (2 * ds)
    total = float(dt.sum())
    length = ds * len(dt)
    i_min = int(np.argmin(v))
    limited = np.isclose(v, v_lim, rtol=1e-6)
    return {
        "label": ESTIMATE_LABEL,
        "is_estimate": True,
        "model": "quasi-steady-state point mass, curvature speed limit + accel/brake passes"
                 + (" with friction ellipse" if p.combined_grip else ""),
        "parameters": asdict(p),
        "closed": closed,
        "step_m": ds,
        "length_m": round(length, 2),
        "estimated_time_s": round(total, 3),
        "mean_speed_mps": round(length / total, 3),
        "min_speed_mps": round(float(v[i_min]), 3),
        "min_speed_station_m": round(float(prof.s[i_min]), 1),
        "max_speed_mps": round(float(v.max()), 3),
        "fraction_at_corner_limit": round(float((limited & (np.abs(prof.kappa) > 0)).mean()), 4),
        "fraction_at_v_max": round(float(np.isclose(v, p.v_max_mps).mean()), 4),
        # arrays (numpy) for further processing; api.py converts to lists
        "s_m": prof.s, "x_m": prof.x, "y_m": prof.y, "kappa_1pm": prof.kappa,
        "speed_mps": v, "speed_limit_mps": v_lim, "segment_time_s": dt, "a_long_mps2": a_long,
    }
