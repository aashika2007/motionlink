"""Checks on REAL downloaded TUMFTM data. Skipped when nothing is downloaded.

    python scripts/fetch_tumftm.py --tracks Spielberg Monza Silverstone
    python -m unittest tests.circuits.test_real_data -v
"""
import json
import unittest

import numpy as np

from backend.circuits import (available_circuits, calculate_curvature, compare_lines, estimate_performance,
                                load_circuit, offsets_from_path, line_from_offsets, drag_offsets, validate_path)
from backend.circuits.loader import data_dir

REAL = [c for c in available_circuits() if not c["name"].startswith("Test")]


@unittest.skipUnless(REAL, f"No real circuits in {data_dir()}. Run: python scripts/fetch_tumftm.py --tracks Spielberg")
class RealCircuitTests(unittest.TestCase):
    def test_manifest_hashes_match_files(self):
        import hashlib
        man = json.loads((data_dir() / "manifest.json").read_text())
        for rel, info in man["files"].items():
            data = (data_dir() / rel).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), info["sha256"], rel)

    def test_each_circuit(self):
        for meta in REAL:
            with self.subTest(circuit=meta["name"]):
                c = load_circuit(meta["id"])
                self.assertTrue(c.closed, "TUMFTM tracks are closed circuits")
                L = c.centreline_length_m
                self.assertTrue(1500 < L < 8000, f"implausible length {L:.0f} m (unit or parse error?)")
                w = c.width_left + c.width_right
                self.assertTrue(3 < w.min() and w.max() < 60, f"implausible widths {w.min():.1f}–{w.max():.1f} m")
                prof = calculate_curvature(c.centreline, closed=True)
                self.assertTrue(np.all(np.isfinite(prof.kappa)))
                self.assertGreater(float(np.abs(prof.kappa).max()), 1 / 300, "a real circuit has corners")
                est = estimate_performance(c.centreline, closed=True)
                self.assertTrue(np.isfinite(est["estimated_time_s"]))
                if c.raceline is not None:
                    # Source README: race lines lie within the track boundaries. Our boundaries
                    # use linear normals rather than TUMFTM's splines, so allow 0.5 m.
                    v = validate_path(c.raceline, c)
                    self.assertLess(v["max_excess_m"], 0.5, v["violations"][:3])
                    rk = calculate_curvature(c.raceline, closed=True).kappa
                    self.assertLess(float(np.abs(rk).mean()), float(np.abs(prof.kappa).mean()),
                                    "a minimum-curvature line should be less curved than the centreline")
                    off = offsets_from_path(c, c.raceline)
                    edited = line_from_offsets(c, drag_offsets(c, off, L * 0.3, -3.0, 50.0))
                    r = compare_lines(c, c.raceline, edited)
                    total = sum(s["estimated_time_delta_s"] for s in r["sections"])
                    self.assertAlmostEqual(total, r["estimated"]["time_delta_s"], delta=0.05)


if __name__ == "__main__":
    unittest.main()
