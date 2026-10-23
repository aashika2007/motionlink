"""Project lines onto a circuit's centreline and check them against track limits."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import as_path, resample


@dataclass
class Projection:
    station_m: np.ndarray     # distance along the centreline [m], in [0, centreline length)
    lateral_m: np.ndarray     # signed offset from centreline [m], + = left of travel
    width_left_m: np.ndarray  # track width to the left at that station [m]
    width_right_m: np.ndarray
    distance_m: np.ndarray    # |offset|, i.e. distance to the centreline


def _segments(circuit):
    c = circuit.centreline
    if circuit.closed:
        a, b = c, np.roll(c, -1, axis=0)
    else:
        a, b = c[:-1], c[1:]
    seg = b - a
    seglen = np.linalg.norm(seg, axis=1)
    seglen[seglen < 1e-12] = 1e-12
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    return a, seg, seglen, cum


def _project_block(P, a, seg, seglen):
    """Nearest point on each candidate segment for each point P."""
    ap = P[:, None, :] - a[None]
    t = np.clip((ap * seg[None]).sum(2) / (seglen[None] ** 2), 0.0, 1.0)
    proj = a[None] + t[..., None] * seg[None]
    d2 = ((P[:, None, :] - proj) ** 2).sum(2)
    return d2, t


def project_to_centreline(points, circuit, window_m: float = 80.0) -> Projection:
    """Sequential projection.

    The first point uses a global nearest-segment search. Each later point searches only
    segments within ±window_m of the previous station, so lines through crossovers
    (e.g. a figure-eight circuit) keep following the branch they are on. If the windowed
    match is clearly worse than the global one (a jump, e.g. a new lap start), the global
    match is used.
    """
    P = as_path(points, min_points=1)
    a, seg, seglen, cum = _segments(circuit)
    m = len(a)
    L = cum[-1]
    mean_seg = L / m
    win = max(3, int(np.ceil(window_m / mean_seg)))
    idx = np.empty(len(P), int)
    tt = np.empty(len(P))

    d2, t = _project_block(P[:1], a, seg, seglen)
    prev = int(d2[0].argmin())
    idx[0], tt[0] = prev, t[0, prev]
    for i in range(1, len(P)):
        cand = (np.arange(prev - win, prev + win + 1) % m) if circuit.closed else \
            np.arange(max(0, prev - win), min(m, prev + win + 1))
        d2w, tw = _project_block(P[i:i + 1], a[cand], seg[cand], seglen[cand])
        j = int(d2w[0].argmin())
        best_d2, best_seg, best_t = d2w[0, j], int(cand[j]), tw[0, j]
        if best_d2 > (3 * mean_seg + 30.0) ** 2:  # lost the branch: fall back to global
            d2g, tg = _project_block(P[i:i + 1], a, seg, seglen)
            g = int(d2g[0].argmin())
            if d2g[0, g] < best_d2:
                best_d2, best_seg, best_t = d2g[0, g], g, tg[0, g]
        idx[i], tt[i], prev = best_seg, best_t, best_seg

    foot = a[idx] + tt[:, None] * seg[idx]
    v = P - foot
    direction = seg[idx] / seglen[idx][:, None]
    cross = direction[:, 0] * v[:, 1] - direction[:, 1] * v[:, 0]   # + = left in y-up frame
    dist = np.linalg.norm(v, axis=1)
    lateral = np.sign(cross) * dist
    nxt = (idx + 1) % len(circuit.centreline)
    wl = (1 - tt) * circuit.width_left[idx] + tt * circuit.width_left[nxt]
    wr = (1 - tt) * circuit.width_right[idx] + tt * circuit.width_right[nxt]
    station = (cum[idx] + tt * seglen[idx]) % L if circuit.closed else cum[idx] + tt * seglen[idx]
    return Projection(station_m=station, lateral_m=lateral, width_left_m=wl, width_right_m=wr, distance_m=dist)


def validate_path(path, circuit, vehicle_half_width_m: float = 0.0, closed: bool | None = None,
                  check_step_m: float = 1.0) -> dict:
    """Check that a line stays inside the track limits.

    The line is densified to check_step_m first, so long straight segments that cut a
    corner are still caught. A point is outside when its lateral offset exceeds the
    track width on that side minus vehicle_half_width_m (a user assumption; 0 checks the
    line itself rather than the car's edges).
    """
    if vehicle_half_width_m < 0:
        raise ValueError("vehicle_half_width_m must be ≥ 0.")
    closed = circuit.closed if closed is None else closed
    pts, s_line, _ = resample(path, check_step_m, closed)
    pr = project_to_centreline(pts, circuit)
    allow_l = pr.width_left_m - vehicle_half_width_m
    allow_r = pr.width_right_m - vehicle_half_width_m
    excess_l = pr.lateral_m - allow_l
    excess_r = -pr.lateral_m - allow_r
    excess = np.maximum(np.maximum(excess_l, excess_r), 0.0)
    outside = excess > 1e-6

    spans = []
    if outside.any():
        idx = np.flatnonzero(outside)
        breaks = np.flatnonzero(np.diff(idx) > 1)
        starts = np.concatenate([[idx[0]], idx[breaks + 1]])
        ends = np.concatenate([idx[breaks], [idx[-1]]])
        if closed and len(starts) > 1 and starts[0] == 0 and ends[-1] == len(pts) - 1:
            starts, ends = starts[1:], np.concatenate([ends[1:-1], [ends[0]]])  # merge wrap-around
        for a, b in zip(starts, ends):
            rng = np.arange(a, b + 1) if b >= a else np.concatenate([np.arange(a, len(pts)), np.arange(0, b + 1)])
            k = rng[excess[rng].argmax()]
            spans.append({
                "from_station_m": round(float(pr.station_m[a]), 1),
                "to_station_m": round(float(pr.station_m[b]), 1),
                "length_m": round(float(len(rng) * check_step_m), 1),
                "max_excess_m": round(float(excess[k]), 3),
                "side": "left" if excess_l[k] > excess_r[k] else "right",
            })
    return {
        "valid": not outside.any(),
        "checked_points": int(len(pts)),
        "check_step_m": check_step_m,
        "vehicle_half_width_m": vehicle_half_width_m,
        "fraction_outside": round(float(outside.mean()), 4),
        "max_excess_m": round(float(excess.max()), 3),
        "min_margin_m": round(float(np.minimum(allow_l - pr.lateral_m, allow_r + pr.lateral_m).min()), 3),
        "violations": spans,
        "basis": "measured track geometry (TUMFTM centreline + satellite-derived widths)",
    }
