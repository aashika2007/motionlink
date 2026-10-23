"""Compare a reference line with an edited line on the same circuit.

Geometry (length, curvature, lateral offset, track-limit checks) is computed from the
measured circuit data. Times and speeds come from performance.estimate_performance and
are SIMULATED ESTIMATES under the stated parameters.
"""
from __future__ import annotations

import numpy as np

from .geometry import calculate_curvature
from .performance import ESTIMATE_LABEL, estimate_performance
from .validation import project_to_centreline, validate_path


def detect_sections(circuit, corner_radius_m: float = 250.0, min_length_m: float = 30.0,
                    merge_gap_m: float = 40.0, step_m: float = 2.0, smoothing_m: float = 8.0) -> list[dict]:
    """Split the centreline into alternating straights and corners.

    A corner is a run where the centreline radius is below corner_radius_m. Short gaps are
    merged and tiny runs dropped. Labels are "Corner n"/"Straight n" in detection order:
    they are NOT official turn numbers.
    """
    prof = calculate_curvature(circuit.centreline, closed=circuit.closed, step_m=step_m, smoothing_m=smoothing_m)
    L = float(prof.s[-1] + prof.step_m) if circuit.closed else float(prof.s[-1])
    hot = np.abs(prof.kappa) > 1.0 / corner_radius_m
    n = len(hot)
    runs, i = [], 0
    while i < n:
        j = i
        while j + 1 < n and hot[j + 1] == hot[i]:
            j += 1
        runs.append([bool(hot[i]), prof.s[i], prof.s[j] + prof.step_m])
        i = j + 1

    def merge(runs, cond):
        out = []
        for r in runs:
            if out and (out[-1][0] == r[0] or cond(r)):
                out[-1][2] = r[2]
            else:
                out.append(r)
        return out

    runs = merge(runs, lambda r: not r[0] and r[2] - r[1] < merge_gap_m)   # short straights join corners
    runs = merge(runs, lambda r: r[0] and r[2] - r[1] < min_length_m)      # tiny corners join straights
    if circuit.closed and len(runs) > 1 and runs[0][0] == runs[-1][0]:      # same type across start/finish
        runs[0][1] = runs[-1][1] - L
        runs.pop()
    sections, counts = [], {True: 0, False: 0}
    for is_corner, a, b in runs:
        counts[is_corner] += 1
        mask = _in_range(prof.s, a, b, L, circuit.closed)
        sections.append({
            "label": f"{'Corner' if is_corner else 'Straight'} {counts[is_corner]}",
            "kind": "corner" if is_corner else "straight",
            "from_station_m": round(float(a % L if circuit.closed else a), 1),
            "to_station_m": round(float(b % L if circuit.closed and b > L else b), 1),
            "length_m": round(float(b - a), 1),
            "min_radius_m": (round(float(1 / np.abs(prof.kappa[mask]).max()), 1)
                             if mask.any() and np.abs(prof.kappa[mask]).max() > 0 else None),
            "_range": (float(a), float(b)),
        })
    return sections


def equal_sections(circuit, count: int) -> list[dict]:
    if count < 1:
        raise ValueError("Section count must be ≥ 1.")
    L = circuit.centreline_length_m
    edges = np.linspace(0, L, count + 1)
    return [{"label": f"Section {i + 1}", "kind": "distance", "from_station_m": round(float(a), 1),
             "to_station_m": round(float(b), 1), "length_m": round(float(b - a), 1), "min_radius_m": None,
             "_range": (float(a), float(b))} for i, (a, b) in enumerate(zip(edges[:-1], edges[1:]))]


def _in_range(s, a, b, L, closed):
    if closed:
        return ((s - a) % L) < (b - a)
    return (s >= a) & (s < b)


def compare_lines(circuit, reference_path, edited_path, parameters=None, *, sections="corners",
                  vehicle_half_width_m: float = 0.0, step_m: float = 2.0) -> dict:
    closed = circuit.closed
    ref = estimate_performance(reference_path, parameters, closed=closed, step_m=step_m)
    ed = estimate_performance(edited_path, parameters, closed=closed, step_m=step_m)
    secs = (detect_sections(circuit) if sections == "corners" else equal_sections(circuit, int(sections)))
    L = circuit.centreline_length_m

    def per_line(perf):
        pts = np.column_stack([perf["x_m"], perf["y_m"]])
        pr = project_to_centreline(pts, circuit)
        seg_len = np.full(len(perf["segment_time_s"]), perf["step_m"])
        st = pr.station_m[:len(seg_len)]
        return pr, st, seg_len

    pr_r, st_r, len_r = per_line(ref)
    pr_e, st_e, len_e = per_line(ed)
    out_sections = []
    for sec in secs:
        a, b = sec["_range"]
        mr = _in_range(st_r, a, b, L, closed)
        me = _in_range(st_e, a, b, L, closed)
        t_r, t_e = float(ref["segment_time_s"][mr].sum()), float(ed["segment_time_s"][me].sum())
        l_r, l_e = float(len_r[mr].sum()), float(len_e[me].sum())
        row = {k: v for k, v in sec.items() if not k.startswith("_")}
        row.update({
            "reference_length_m": round(l_r, 1), "edited_length_m": round(l_e, 1),
            "length_delta_m": round(l_e - l_r, 2),
            "reference_mean_offset_m": round(float(pr_r.lateral_m[:len(mr)][mr].mean()), 2) if mr.any() else None,
            "edited_mean_offset_m": round(float(pr_e.lateral_m[:len(me)][me].mean()), 2) if me.any() else None,
            "reference_min_speed_mps": round(float(ref["speed_mps"][mr].min()), 2) if mr.any() else None,
            "edited_min_speed_mps": round(float(ed["speed_mps"][me].min()), 2) if me.any() else None,
            "estimated_reference_time_s": round(t_r, 3), "estimated_edited_time_s": round(t_e, 3),
            "estimated_time_delta_s": round(t_e - t_r, 3),
        })
        out_sections.append(row)

    deltas = [r["estimated_time_delta_s"] for r in out_sections]
    gain = int(np.argmin(deltas)) if deltas else None
    loss = int(np.argmax(deltas)) if deltas else None
    total_delta = ed["estimated_time_s"] - ref["estimated_time_s"]
    summary = [f"Edited line is {abs(ed['length_m'] - ref['length_m']):.1f} m "
               f"{'longer' if ed['length_m'] > ref['length_m'] else 'shorter'} than the reference (measured geometry)."]
    summary.append(f"Estimated time difference: {total_delta:+.3f} s under the stated assumptions "
                   f"({'slower' if total_delta > 0 else 'faster'}).")
    if gain is not None and deltas[gain] < 0:
        summary.append(f"Largest estimated gain: {out_sections[gain]['label']} ({deltas[gain]:+.3f} s).")
    if loss is not None and deltas[loss] > 0:
        summary.append(f"Largest estimated loss: {out_sections[loss]['label']} ({deltas[loss]:+.3f} s).")
    v_ref = validate_path(reference_path, circuit, vehicle_half_width_m)
    v_ed = validate_path(edited_path, circuit, vehicle_half_width_m)
    if not v_ed["valid"]:
        summary.append(f"Edited line leaves the track limits by up to {v_ed['max_excess_m']:.2f} m; "
                       "its estimate is not meaningful there.")
    summary.append(ESTIMATE_LABEL)

    return {
        "label": ESTIMATE_LABEL,
        "measured": {
            "reference_length_m": ref["length_m"], "edited_length_m": ed["length_m"],
            "length_delta_m": round(ed["length_m"] - ref["length_m"], 2),
            "reference_mean_abs_curvature_1pm": round(float(np.abs(ref["kappa_1pm"]).mean()), 6),
            "edited_mean_abs_curvature_1pm": round(float(np.abs(ed["kappa_1pm"]).mean()), 6),
            "reference_validation": v_ref, "edited_validation": v_ed,
        },
        "estimated": {
            "reference_time_s": ref["estimated_time_s"], "edited_time_s": ed["estimated_time_s"],
            "time_delta_s": round(total_delta, 3), "parameters": ref["parameters"],
        },
        "sections": out_sections,
        "summary": summary,
        "reference_profile": ref, "edited_profile": ed,
    }
