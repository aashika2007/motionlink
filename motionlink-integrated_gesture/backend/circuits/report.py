"""Print a verification report for downloaded circuits.

    python -m backend.circuits.report Spielberg Monza
    python -m backend.circuits.report --all

Everything under "Measured" comes from the dataset; everything under "Estimate" is the
simplified model with the illustrative parameters.
"""
from __future__ import annotations

import sys

import numpy as np

from .compare import detect_sections
from .geometry import calculate_curvature, segment_lengths
from .loader import available_circuits, load_circuit
from .performance import ILLUSTRATIVE_PARAMETERS, estimate_performance
from .validation import validate_path


def report(cid: str) -> bool:
    c = load_circuit(cid)
    s = c.summary()
    seg = segment_lengths(c.centreline, c.closed)
    print(f"\n=== {c.name} ({s['series']}) ===")
    print(f"Source: {c.source['dataset']} {c.source['track_file']} (commit {c.source['commit'] or 'unknown'})")
    print(f"sha256: {c.source['track_sha256']}")
    print("Measured (dataset geometry)")
    print(f"  points {s['points']}, spacing {seg.min():.2f}–{seg.max():.2f} m (median {np.median(seg):.2f})")
    print(f"  closed loop: {c.closed} (start/end gap {c.source['start_gap_m']} m)")
    print(f"  centreline length: {s['centreline_length_m'] / 1000:.3f} km  <- compare with the published lap length")
    print(f"  track width: {s['track_width_m']['min']}–{s['track_width_m']['max']} m (mean {s['track_width_m']['mean']})")
    prof = calculate_curvature(c.centreline, closed=c.closed)
    print(f"  centreline min radius: {1 / np.abs(prof.kappa).max():.1f} m; "
          f"detected corners: {sum(x['kind'] == 'corner' for x in detect_sections(c))}")
    ok = True
    if c.raceline is not None:
        v = validate_path(c.raceline, c)
        rp = calculate_curvature(c.raceline, closed=c.closed)
        print(f"  reference race line: {s['raceline_length_m'] / 1000:.3f} km, inside limits: {v['valid']} "
              f"(max excess {v['max_excess_m']} m, min margin {v['min_margin_m']} m)")
        print(f"  mean |curvature|: race line {np.abs(rp.kappa).mean():.5f} vs centreline {np.abs(prof.kappa).mean():.5f} 1/m")
        ok = v["max_excess_m"] < 0.5
    else:
        print("  reference race line: not in dataset")
    line = c.raceline if c.raceline is not None else c.centreline
    e = estimate_performance(line, ILLUSTRATIVE_PARAMETERS, closed=c.closed)
    print("Estimate (illustrative parameters, NOT a lap time)")
    print(f"  {e['estimated_time_s']:.1f} s, mean {e['mean_speed_mps'] * 3.6:.0f} km/h, "
          f"min {e['min_speed_mps'] * 3.6:.0f} km/h at {e['min_speed_station_m']:.0f} m")
    return ok


def main(argv):
    ids = [c["name"] for c in available_circuits()] if (not argv or argv == ["--all"]) else argv
    if not ids:
        sys.exit("No circuits downloaded. Run: python scripts/fetch_tumftm.py --tracks Spielberg")
    results = [report(i) for i in ids]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
