"""Tests for the backend wrappers.

Run from the repo root:
    python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from video_tracking import InvalidROIError, InvalidVideoError, available_trackers
from video_tracking.cli import make_demo_video

from backend.tracking import get_path, track_object, track_objects
from backend.video_processor import get_frame, get_video_info, to_video_bbox


class TestVideoProcessor(unittest.TestCase):
    def test_info_and_frame(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "demo.mp4")
            make_demo_video(video)
            info = get_video_info(video)
            self.assertEqual((info["width"], info["height"]), (640, 360))
            self.assertAlmostEqual(info["fps"], 30.0, places=1)
            self.assertGreater(info["frame_count"], 80)
            frame = get_frame(video, 0)
            self.assertEqual(frame.shape[:2], (360, 640))
            png = get_frame(video, 5, out_path=os.path.join(d, "f.png"))
            self.assertTrue(os.path.isfile(png))

    def test_missing_file(self):
        with self.assertRaises(InvalidVideoError):
            get_video_info("does_not_exist.mp4")

    def test_bbox_scaling_and_validation(self):
        self.assertEqual(
            to_video_bbox((10, 10, 20, 20), (640, 360), (1280, 720)), (20, 20, 40, 40)
        )
        with self.assertRaises(InvalidROIError):
            to_video_bbox((5000, 5000, 40, 40), (640, 360), (640, 360))


@unittest.skipUnless(available_trackers(), "no OpenCV tracker available")
class TestTrackingWrappers(unittest.TestCase):
    def test_single_object(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "demo.mp4")
            rois = make_demo_video(video)
            result = track_object(video, rois["car_1"], object_id="car_1")
            self.assertEqual(result["coordinate_space"], "video_pixels")
            self.assertTrue(all(r["object_id"] == "car_1" for r in result["records"]))
            pts = get_path(result, "car_1")
            self.assertGreater(len(pts), 80)
            self.assertEqual(set(pts[0]), {"frame", "timestamp", "x", "y"})

    def test_two_objects(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "demo.mp4")
            rois = make_demo_video(video)
            result = track_objects(video, rois)
            self.assertEqual(set(result["objects"]), {"car_1", "car_2"})
            self.assertGreater(len(get_path(result, "car_2")), 80)


if __name__ == "__main__":
    unittest.main()