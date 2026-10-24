"""Tests for the MotionInk tracking module.

Run from the repo root:
    python -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import video_tracking.tracker as tracker_mod
from video_tracking import (
    InvalidROIError,
    InvalidVideoError,
    MultiObjectTracker,
    TrackingRecord,
    VideoSource,
    available_trackers,
    display_to_video_bbox,
    display_to_video_point,
    track_video,
    validate_roi,
)
from video_tracking.cli import make_demo_video


class TestValidation(unittest.TestCase):
    def test_missing_file(self):
        with self.assertRaises(InvalidVideoError):
            VideoSource("does_not_exist.mp4")

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "empty.mp4")
            open(p, "wb").close()
            with self.assertRaises(InvalidVideoError):
                VideoSource(p)

    def test_garbage_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "fake.mp4")
            with open(p, "wb") as f:
                f.write(b"this is not a video" * 100)
            with self.assertRaises(InvalidVideoError):
                VideoSource(p)

    def test_roi_valid_and_clipped(self):
        self.assertEqual(validate_roi((10, 10, 50, 40), 640, 360), (10, 10, 50, 40))
        # partly outside -> clipped to the frame
        self.assertEqual(validate_roi((-10, 0, 50, 40), 640, 360), (0, 0, 40, 40))

    def test_roi_invalid(self):
        for bad in [(0, 0, 0, 0), (700, 10, 50, 50), (10, 10, 3, 3),
                    (1, 2, 3), ("a", 1, 2, 3), (float("nan"), 0, 10, 10)]:
            with self.assertRaises(InvalidROIError, msg=str(bad)):
                validate_roi(bad, 640, 360)

    def test_display_scaling(self):
        self.assertEqual(display_to_video_point(100, 50, (640, 360), (1280, 720)), (200, 100))
        self.assertEqual(display_to_video_bbox((10, 10, 20, 20), (640, 360), (1280, 720)),
                         (20, 20, 40, 40))


class TestRecord(unittest.TestCase):
    def test_roundtrip_and_lost(self):
        r = TrackingRecord(5, 0.1667, 100.0, 50.0, "car_1", None, (80, 30, 40, 40))
        self.assertEqual(TrackingRecord.from_dict(r.to_dict()).to_dict(), r.to_dict())
        lost = TrackingRecord(6, 0.2, None, None, "car_1", status="lost")
        d = lost.to_dict()
        self.assertIsNone(d["x"])
        self.assertEqual(d["status"], "lost")
        self.assertFalse(lost.is_tracked)


class _FakeTracker:
    """Reports success for `ok_frames` updates, then failure."""
    def __init__(self, ok_frames):
        self.ok_frames, self.calls = ok_frames, 0

    def init(self, frame, bbox):
        return True

    def update(self, frame):
        self.calls += 1
        if self.calls <= self.ok_frames:
            return True, (10 + self.calls, 10, 20, 20)
        return False, (0, 0, 0, 0)


class TestLostHandling(unittest.TestCase):
    def setUp(self):
        self._orig = tracker_mod.create_tracker
        tracker_mod.create_tracker = lambda name="CSRT": _FakeTracker(ok_frames=2)

    def tearDown(self):
        tracker_mod.create_tracker = self._orig

    def test_lost_then_abandoned(self):
        frame = np.zeros((100, 100, 3), np.uint8)
        mot = MultiObjectTracker(30.0, (100, 100), "CSRT", max_lost_frames=3)
        start = mot.start(0, frame, {"car_1": (10, 10, 20, 20)})
        self.assertEqual(start[0].status, "tracked")

        statuses = []
        for i in range(1, 8):
            recs = mot.update(i, frame)
            statuses.append([r.status for r in recs])
        # 2 tracked, 3 lost, then abandoned (no records at all)
        self.assertEqual(statuses[:2], [["tracked"], ["tracked"]])
        self.assertEqual(statuses[2:5], [["lost"], ["lost"], ["lost"]])
        self.assertEqual(statuses[5:], [[], []])
        self.assertEqual(mot.summaries["car_1"].end_reason, "lost_too_long")
        self.assertFalse(mot.any_active)

    def test_timestamps(self):
        frame = np.zeros((100, 100, 3), np.uint8)
        mot = MultiObjectTracker(25.0, (100, 100), "CSRT")
        mot.start(0, frame, {"car_1": (10, 10, 20, 20)})
        rec = mot.update(50, frame)[0]
        self.assertAlmostEqual(rec.timestamp, 2.0)


@unittest.skipUnless(available_trackers(), "no OpenCV tracker available")
class TestRealTracking(unittest.TestCase):
    def test_two_objects_on_synthetic_video(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "demo.mp4")
            rois = make_demo_video(video)
            result = track_video(video, rois)

            self.assertEqual(set(result.object_ids()), {"car_1", "car_2"})
            for oid in ("car_1", "car_2"):
                self.assertEqual(result.objects[oid].end_reason, "end_of_video")

            # Compare against the known ground-truth centres from the generator.
            size, worst = 40, 0.0
            for r in result.records:
                if not r.is_tracked:
                    continue
                i = r.frame
                if r.object_id == "car_1":
                    gx, gy = 40 + i * 5 + size / 2, int(120 + 40 * np.sin(i / 10)) + size / 2
                else:
                    gx, gy = 560 - i * 5 + size / 2, int(240 - 40 * np.sin(i / 10)) + size / 2
                worst = max(worst, abs(r.x - gx), abs(r.y - gy))
            self.assertLess(worst, 12.0, f"worst centre error {worst:.1f}px")

            # Output format
            path = os.path.join(d, "out.json")
            result.save_json(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["coordinate_space"], "video_pixels")
            self.assertEqual(data["position_reference"], "bounding_box_centre")
            for key in ("frame", "timestamp", "x", "y", "object_id", "confidence"):
                self.assertIn(key, data["records"][0])

    def test_end_frame_limit(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "demo.mp4")
            rois = make_demo_video(video)
            result = track_video(video, rois, end_frame=20)
            self.assertEqual(max(r.frame for r in result.records), 19)
            self.assertEqual(result.objects["car_1"].end_reason, "max_frames")

    def test_bad_roi_raises(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "demo.mp4")
            make_demo_video(video)
            with self.assertRaises(InvalidROIError):
                track_video(video, {"car_1": (5000, 5000, 40, 40)})


if __name__ == "__main__":
    unittest.main()