import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.circuits import (ILLUSTRATIVE_PARAMETERS, VehicleParameters, calculate_curvature,
                                calculate_path_length, compare_lines, detect_sections, drag_offsets,
                                estimate_performance, line_from_offsets, load_circuit, offsets_from_path,
                                project_to_centreline, validate_path, available_circuits)
from backend.circuits.loader import parse_tumftm_csv
from tests.circuits import fixtures as fx

ROOT = Path(__file__).resolve().parents[2]


def circle(r=50.0, n=400, ccw=True, noise=0.0, seed=0):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    if not ccw:
        t = -t
    p = np.column_stack([r * np.cos(t), r * np.sin(t)])
    if noise:
        p += np.random.default_rng(seed).normal(0, noise, p.shape)
    return p


class GeometryTests(unittest.TestCase):
    def test_path_length(self):
        self.assertAlmostEqual(calculate_path_length([[0, 0], [3, 4], [3, 10]]), 11.0)
        self.assertAlmostEqual(calculate_path_length([[0, 0], [1, 0], [1, 1], [0, 1]], closed=True), 4.0)
        self.assertAlmostEqual(calculate_path_length(circle(), closed=True), 2 * math.pi * 50, delta=0.2)

    def test_circle_curvature_and_sign(self):
        k = calculate_curvature(circle(), closed=True).kappa
        self.assertAlmostEqual(float(k.mean()), 1 / 50, delta=0.02 / 100)
        k_cw = calculate_curvature(circle(ccw=False), closed=True).kappa
        self.assertTrue(np.all(k_cw < 0), "clockwise = right turns = negative curvature")

    def test_noisy_circle_is_robust(self):
        prof = calculate_curvature(circle(noise=0.15), closed=True, smoothing_m=6.0)
        self.assertAlmostEqual(float(np.median(prof.kappa)), 0.02, delta=0.0006)
        self.assertLess(float(np.std(prof.kappa)), 0.004)

    def test_straight_is_exactly_zero(self):
        prof = calculate_curvature([[0, 0], [100, 0], [250, 0]])
        self.assertTrue(np.all(prof.kappa == 0))
        self.assertTrue(np.all(np.isinf(prof.radius)))
        noisy = np.column_stack([np.linspace(0, 300, 301), np.random.default_rng(1).normal(0, 0.01, 301)])
        self.assertLess(float(np.abs(calculate_curvature(noisy).kappa).max()), 2e-3)

    def test_uneven_point_spacing_does_not_bias(self):
        t = np.sort(np.random.default_rng(3).uniform(0, 2 * np.pi, 300))
        p = np.column_stack([80 * np.cos(t), 80 * np.sin(t)])
        self.assertAlmostEqual(float(np.median(calculate_curvature(p, closed=True).kappa)), 1 / 80, delta=3e-4)

    def test_bad_input(self):
        for bad in ([[0, 0]], [[0, 0, 0]], [["a", 1], [2, 3]], [[0, float("nan")], [1, 1]]):
            with self.assertRaises(ValueError):
                calculate_curvature(bad)


class PerformanceTests(unittest.TestCase):
    def test_constant_radius_corner_speed(self):
        p = VehicleParameters(30.0, 10.0, 35.0, 90.0)
        r = estimate_performance(circle(), p, closed=True)
        v = math.sqrt(30 * 50)
        self.assertAlmostEqual(r["min_speed_mps"], v, delta=v * 0.01)
        self.assertAlmostEqual(r["estimated_time_s"], 2 * math.pi * 50 / v, delta=0.1)
        self.assertTrue(r["is_estimate"])
        self.assertIn("not a real lap time", r["label"])

    def test_standing_start_matches_kinematics(self):
        p = VehicleParameters(30.0, 10.0, 35.0, 90.0, combined_grip=False)
        r = estimate_performance([[0, 0], [400, 0]], p, v_start_mps=0.0)
        self.assertAlmostEqual(r["estimated_time_s"], math.sqrt(2 * 400 / 10), delta=1e-3)

    def test_limits_respected_and_braking_happens(self):
        p = ILLUSTRATIVE_PARAMETERS
        r = estimate_performance(fx.stadium(), p, closed=True)
        self.assertLessEqual(float(r["a_long_mps2"].max()), p.a_accel_max_mps2 + 1e-6)
        self.assertGreaterEqual(float(r["a_long_mps2"].min()), -p.a_brake_max_mps2 - 1e-6)
        self.assertLess(float(r["a_long_mps2"].min()), -1.0, "should brake before the corners")
        self.assertTrue(np.all(r["speed_mps"] <= r["speed_limit_mps"] + 1e-9))

    def test_closed_loop_independent_of_start_point(self):
        c = fx.stadium()
        a = estimate_performance(c, closed=True)["estimated_time_s"]
        b = estimate_performance(np.roll(c, 37, axis=0), closed=True)["estimated_time_s"]
        self.assertAlmostEqual(a, b, delta=a * 0.005)

    def test_friction_ellipse_is_not_faster(self):
        c = fx.stadium()
        on = estimate_performance(c, VehicleParameters(30, 10, 35, 90, True), closed=True)
        off = estimate_performance(c, VehicleParameters(30, 10, 35, 90, False), closed=True)
        self.assertGreaterEqual(on["estimated_time_s"], off["estimated_time_s"])

    def test_parameter_validation(self):
        with self.assertRaises(ValueError):
            VehicleParameters.from_dict({"a_lat_max_mps2": -1})
        with self.assertRaises(ValueError):
            VehicleParameters.from_dict({"grip": 2})
        self.assertEqual(VehicleParameters.from_dict({"v_max_mps": 70}).note, "user-supplied assumption")


class FixtureCircuitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = fx.build_fixture_dir(cls.tmp.name)
        cls.c = load_circuit("teststadium", cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_loader(self):
        c = self.c
        self.assertTrue(c.closed)
        self.assertAlmostEqual(c.centreline_length_m, fx.STADIUM_LENGTH, delta=1.0)
        self.assertIsNotNone(c.raceline)
        self.assertEqual(len(c.source["track_sha256"]), 64)
        names = [x["name"] for x in available_circuits(self.dir)]
        self.assertEqual(names, ["TestEight", "TestStadium"])
        with self.assertRaises(FileNotFoundError) as cm:
            load_circuit("monza", self.dir)
        self.assertIn("fetch_tumftm.py", str(cm.exception))

    def test_boundaries_are_on_the_correct_sides(self):
        # Bottom straight heads east; left is +y (inside of a CCW stadium).
        i = 10
        self.assertAlmostEqual(self.c.left_boundary[i][1], fx.HALF_WIDTH, delta=1e-6)
        self.assertAlmostEqual(self.c.right_boundary[i][1], -fx.HALF_WIDTH, delta=1e-6)

    def test_parse_variants(self):
        d = Path(self.tmp.name) / "parse"
        d.mkdir()
        (d / "plain.csv").write_text("x_m,y_m\n0,0\n1,0\n2,0\n3,0\n")
        self.assertEqual(parse_tumftm_csv(d / "plain.csv", 2).shape, (4, 2))
        (d / "bad.csv").write_text("0,0,1\n1,0,1\n2,0,1\n3,0,1\n")
        with self.assertRaises(ValueError):
            parse_tumftm_csv(d / "bad.csv", 4)

    def test_validation(self):
        c = self.c
        self.assertTrue(validate_path(c.centreline, c)["valid"])
        self.assertTrue(validate_path(c.raceline, c)["valid"])
        d = np.full(len(c.centreline), 5.0)
        self.assertTrue(validate_path(line_from_offsets(c, d), c)["valid"])
        bad = validate_path(line_from_offsets(c, d), c, vehicle_half_width_m=1.5)
        self.assertFalse(bad["valid"])
        self.assertAlmostEqual(bad["max_excess_m"], 0.5, delta=0.05)
        d2 = np.zeros(len(c.centreline))
        d2[40:60] = -8.0
        r = validate_path(line_from_offsets(c, d2, clamp=False), c)
        self.assertFalse(r["valid"])
        self.assertEqual(len(r["violations"]), 1)
        self.assertEqual(r["violations"][0]["side"], "right")
        self.assertAlmostEqual(r["violations"][0]["max_excess_m"], 2.0, delta=0.05)

    def test_corner_cut_between_sparse_points_is_caught(self):
        c = self.c
        cut = [[250, 0], [350, 100]]  # chord across the first corner
        self.assertFalse(validate_path(cut, c, closed=False)["valid"])

    def test_figure_eight_projection_follows_branch(self):
        e = load_circuit("testeight", self.dir)
        pr = project_to_centreline(e.centreline, e)
        steps = np.diff(pr.station_m) % e.centreline_length_m
        self.assertTrue(np.all(steps < 10.0), "station must advance smoothly through the crossover")
        self.assertTrue(validate_path(e.centreline, e)["valid"])

    def test_offset_lines_through_crossover(self):
        # Regression: the figure-eight starts at its crossover, where a line 5 m left of
        # one branch sits on top of the other branch. Heading-aware projection must keep
        # it on its own branch.
        from backend.circuits import drag_to_point
        e = load_circuit("testeight", self.dir)
        n = len(e.centreline)
        for val in (-5.0, -2.0, 2.0, 5.0):
            v = validate_path(line_from_offsets(e, np.full(n, val)), e)
            self.assertTrue(v["valid"], (val, v["max_excess_m"]))
        out = validate_path(line_from_offsets(e, np.full(n, 7.0), clamp=False), e)
        self.assertFalse(out["valid"])
        self.assertAlmostEqual(out["max_excess_m"], 2.0, delta=0.1)
        # Drag right at the crossover moves the grabbed branch only.
        line = line_from_offsets(e, np.zeros(n))
        moved = drag_to_point(e, np.zeros(n), line[0], line[0] + e.normals_left[0] * 3, radius_m=10)
        self.assertAlmostEqual(moved[0], 3.0, delta=1e-6)
        self.assertAlmostEqual(moved[n // 2], 0.0, delta=1e-6)  # the other pass through the crossing

    def test_editing(self):
        c = self.c
        off = offsets_from_path(c, c.raceline)
        back = line_from_offsets(c, off)
        self.assertLess(float(np.abs(back - c.raceline).max()), 0.1)
        dragged = drag_offsets(c, off, station_m=100.0, delta_m=50.0, radius_m=30.0)
        self.assertAlmostEqual(float(dragged.max()), fx.HALF_WIDTH)  # clamped at the left edge
        self.assertTrue(validate_path(line_from_offsets(c, dragged), c)["valid"])

    def test_sections_and_compare(self):
        c = self.c
        secs = detect_sections(c)
        kinds = [s["kind"] for s in secs]
        self.assertEqual(kinds.count("corner"), 2)
        self.assertEqual(kinds.count("straight"), 2)
        self.assertAlmostEqual(sum(s["length_m"] for s in secs), c.centreline_length_m, delta=4)
        for s in secs:
            if s["kind"] == "corner":
                self.assertAlmostEqual(s["min_radius_m"], fx.RADIUS, delta=4)

        edited = line_from_offsets(c, drag_offsets(c, offsets_from_path(c, c.raceline), 400.0, -6.0, 40.0))
        r = compare_lines(c, c.raceline, edited)
        est = r["estimated"]
        self.assertAlmostEqual(sum(x["estimated_time_delta_s"] for x in r["sections"]), est["time_delta_s"], delta=0.02)
        self.assertAlmostEqual(sum(x["estimated_reference_time_s"] for x in r["sections"]), est["reference_time_s"], delta=0.02)
        self.assertTrue(r["measured"]["edited_validation"]["valid"])
        self.assertIn("not a real lap time", r["summary"][-1])
        r10 = compare_lines(c, c.raceline, edited, sections=10)
        self.assertEqual(len(r10["sections"]), 10)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from backend.circuits.api import circuits_bp
        cls.tmp = tempfile.TemporaryDirectory()
        fx.build_fixture_dir(cls.tmp.name)
        os.environ["MOTIONINK_CIRCUIT_DATA"] = cls.tmp.name
        app = Flask(__name__)
        app.register_blueprint(circuits_bp)
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("MOTIONINK_CIRCUIT_DATA", None)
        cls.tmp.cleanup()

    def strict(self, resp):
        json.dumps(resp.get_json(), allow_nan=False)  # no NaN/Infinity leaks
        return resp.get_json()

    def test_endpoints(self):
        lst = self.strict(self.client.get("/api/circuits"))
        self.assertEqual(len(lst["circuits"]), 2)
        c = self.strict(self.client.get("/api/circuits/TestStadium"))
        n = c["points"]
        self.assertEqual(len(c["left_boundary"]), n)
        self.assertEqual(len(c["raceline_offsets"]), n)
        a = self.strict(self.client.post("/api/circuits/TestStadium/analyze", json={"line": "raceline"}))
        self.assertTrue(a["validation"]["valid"])
        cl = self.strict(self.client.post("/api/circuits/TestStadium/analyze", json={"line": "centreline"}))
        self.assertIsNone(cl["curvature"]["radius_m"][75], "mid-straight → infinite radius → null")
        self.assertAlmostEqual(min(r for r in cl["curvature"]["radius_m"] if r), fx.RADIUS, delta=3)
        d = self.strict(self.client.post("/api/circuits/TestStadium/drag", json={
            "offsets": c["raceline_offsets"], "station_m": 120, "delta_m": 3}))
        dp = self.strict(self.client.post("/api/circuits/TestStadium/drag-to-point", json={
            "offsets": [0.0] * n, "grab_xy": [150, 0], "target_xy": [150, 4], "radius_m": 30}))
        self.assertAlmostEqual(max(dp["offsets"]), 4.0, delta=0.05)  # moved 4 m to the left (+y on this straight)
        cmp_ = self.strict(self.client.post("/api/circuits/TestStadium/compare", json={
            "reference": "raceline", "edited": {"offsets": d["offsets"]}, "sections": "corners"}))
        self.assertIn("time_delta_s", cmp_["estimated"])
        self.assertEqual(self.client.get("/api/circuits/monza").status_code, 404)
        self.assertEqual(self.client.post("/api/circuits/TestEight/analyze", json={"line": "raceline"}).status_code, 400)
        self.assertEqual(self.client.post("/api/circuits/TestStadium/compare", json={"edited": 5}).status_code, 400)


class FetchScriptTests(unittest.TestCase):
    def test_git_blob_sha(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import fetch_tumftm
        self.assertEqual(fetch_tumftm.git_blob_sha(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_import_from_clone(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            fx.build_fixture_dir(src)
            (Path(src) / "LICENSE").write_text("test licence")
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_tumftm.py"), "--from-clone", src,
                                "--tracks", "teststadium", "--out", out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            man = json.loads((Path(out) / "manifest.json").read_text())
            self.assertIn("tracks/TestStadium.csv", man["files"])
            self.assertIn("racelines/TestStadium.csv", man["files"])
            self.assertTrue(load_circuit("teststadium", out).raceline is not None)


if __name__ == "__main__":
    unittest.main()
