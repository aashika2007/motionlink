"""Racing-line geometry: path length, uniform resampling and curvature.

Coordinate convention (circuit frame)
-------------------------------------
Paths are (N, 2) arrays of [x, y] in **metres** in a right-handed planar frame
with **y pointing up** (the TUMFTM convention). This is NOT video pixel space:
canvas/video coordinates have y pointing down and units of pixels.

Sign convention: positive curvature = turning left (counter-clockwise) when
travelling in the order the points are given.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def as_path(path, *, min_points: int = 2) -> np.ndarray:
    try:
        p = np.asarray(path, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("A path must be a list of [x, y] number pairs.") from exc
    if p.ndim != 2 or p.shape[1] != 2:
        raise ValueError("A path must be a list of [x, y] pairs.")
    if len(p) < min_points:
        raise ValueError(f"A path needs at least {min_points} points.")
    if not np.all(np.isfinite(p)):
        raise ValueError("Path coordinates must be finite numbers.")
    return p


def _drop_repeats(p: np.ndarray) -> np.ndarray:
    keep = np.concatenate([[True], np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-9])
    return p[keep]


def looks_closed(path, tol_factor: float = 3.0) -> bool:
    """True when the gap from last to first point is comparable to normal spacing."""
    p = _drop_repeats(as_path(path))
    if len(p) < 4:
        return False
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    return float(np.linalg.norm(p[-1] - p[0])) <= tol_factor * float(np.median(seg))


def segment_lengths(path, closed: bool = False) -> np.ndarray:
    p = as_path(path)
    q = np.vstack([p, p[:1]]) if closed else p
    return np.linalg.norm(np.diff(q, axis=0), axis=1)


def calculate_path_length(path, closed: bool = False) -> float:
    """Polyline length in metres. closed=True adds the last→first segment."""
    return float(segment_lengths(path, closed).sum())


def cumulative_distance(path, closed: bool = False) -> np.ndarray:
    """Station (arc length) of each point; for closed paths also returns no wrap point."""
    seg = segment_lengths(path, closed)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    return s[:-1] if closed else s


def resample(path, step_m: float, closed: bool = False):
    """Resample to (almost) uniform arc-length spacing.

    Returns (points, s, step) where step is the actual spacing used.
    Closed paths do not repeat the first point at the end.
    """
    if step_m <= 0:
        raise ValueError("step_m must be > 0.")
    p = _drop_repeats(as_path(path))
    if len(p) < 2:
        raise ValueError("A path needs at least 2 distinct points.")
    q = np.vstack([p, p[:1]]) if closed else p
    c = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(q, axis=0), axis=1))])
    total = c[-1]
    if total <= 0:
        raise ValueError("The path has zero length.")
    if closed:
        n = max(8, int(round(total / step_m)))
        s = np.linspace(0.0, total, n, endpoint=False)
    else:
        n = max(2, int(round(total / step_m)) + 1)
        s = np.linspace(0.0, total, n)
    pts = np.column_stack([np.interp(s, c, q[:, 0]), np.interp(s, c, q[:, 1])])
    step = total / n if closed else total / (n - 1)
    return pts, s, float(step)


def _gaussian_smooth(values: np.ndarray, sigma_samples: float, closed: bool) -> np.ndarray:
    if sigma_samples < 0.5 or len(values) < 3:
        return values.copy()
    radius = int(np.ceil(3 * sigma_samples))
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (x / sigma_samples) ** 2)
    kernel /= kernel.sum()
    if closed:
        radius = min(radius, len(values) - 1)
        kernel = kernel[len(kernel) // 2 - radius: len(kernel) // 2 + radius + 1]
        kernel /= kernel.sum()
        padded = np.concatenate([values[-radius:], values, values[:radius]])
    else:
        padded = np.pad(values, radius, mode="reflect" if len(values) > radius else "edge")
    return np.convolve(padded, kernel, mode="valid")


def _derivative(v: np.ndarray, h: float, closed: bool) -> np.ndarray:
    if closed:
        return (np.roll(v, -1) - np.roll(v, 1)) / (2 * h)
    return np.gradient(v, h)


@dataclass
class CurvatureProfile:
    s: np.ndarray            # station along the resampled path [m]
    x: np.ndarray            # resampled (unsmoothed) coordinates [m]
    y: np.ndarray
    kappa: np.ndarray        # signed curvature [1/m], + = left turn, exact 0 on straights
    step_m: float
    smoothing_m: float
    zero_tol: float
    closed: bool

    @property
    def radius(self) -> np.ndarray:
        """Turn radius [m]; inf where curvature was treated as zero."""
        with np.errstate(divide="ignore"):
            return np.where(self.kappa == 0, np.inf, 1.0 / np.abs(self.kappa))

    @property
    def points(self) -> np.ndarray:
        return np.column_stack([self.x, self.y])


def calculate_curvature(path, closed: bool = False, step_m: float = 2.0, smoothing_m: float = 4.0,
                        zero_tol: float = 1e-4) -> CurvatureProfile:
    """Signed curvature that tolerates noisy or hand-edited points.

    1. Resample to uniform arc length (step_m), so point density doesn't bias derivatives.
    2. Gaussian-smooth x(s) and y(s) with sigma = smoothing_m (periodic for closed paths).
       Smoothing also slightly under-states very tight corners: for radius R the smoothed
       radius is about R·exp(-σ²/2R²), e.g. ~3.5% for R = 15 m, σ = 4 m.
    3. κ = (x'y'' − y'x'') / (x'² + y'²)^1.5 with central differences.
    4. |κ| < zero_tol (default 1e-4 1/m, i.e. radius > 10 km) is set to exactly 0, so
       straights report infinite radius instead of noise-sized huge radii.
    """
    if smoothing_m < 0 or zero_tol < 0:
        raise ValueError("smoothing_m and zero_tol must be ≥ 0.")
    pts, s, h = resample(path, step_m, closed)
    n = len(pts)
    if n < 5:
        kappa = np.zeros(n)
    else:
        sig = smoothing_m / h
        xs = _gaussian_smooth(pts[:, 0], sig, closed)
        ys = _gaussian_smooth(pts[:, 1], sig, closed)
        dx, dy = _derivative(xs, h, closed), _derivative(ys, h, closed)
        ddx, ddy = _derivative(dx, h, closed), _derivative(dy, h, closed)
        denom = np.power(dx * dx + dy * dy, 1.5)
        denom[denom < 1e-12] = np.inf
        kappa = (dx * ddy - dy * ddx) / denom
        kappa[np.abs(kappa) < zero_tol] = 0.0
    return CurvatureProfile(s=s, x=pts[:, 0], y=pts[:, 1], kappa=kappa, step_m=h,
                            smoothing_m=smoothing_m, zero_tol=zero_tol, closed=closed)


def tangents(path, closed: bool = False) -> np.ndarray:
    p = as_path(path)
    if closed:
        d = np.roll(p, -1, axis=0) - np.roll(p, 1, axis=0)
    else:
        d = np.gradient(p, axis=0)
    norm = np.linalg.norm(d, axis=1, keepdims=True)
    norm[norm < 1e-12] = 1.0
    return d / norm


def left_normals(path, closed: bool = False) -> np.ndarray:
    """Unit normals to the LEFT of travel in a y-up frame."""
    t = tangents(path, closed)
    return np.column_stack([-t[:, 1], t[:, 0]])
