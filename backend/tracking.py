"""Tracking entry points for the MotionInk UI / app.py.

Typical use from app.py:

    from backend.video_processor import get_video_info, get_frame, to_video_bbox
    from backend.tracking import track_object, get_path

    info = get_video_info(path)
    bbox = to_video_bbox(drawn_box, preview_size, (info["width"], info["height"]))
    result = track_object(path, bbox)          # JSON-serialisable dict
    points = get_path(result, "car_1")         # [{frame, timestamp, x, y}, ...]

Record format (all coordinates are VIDEO PIXELS, origin top-left):
    {"frame": 12, "timestamp": 0.4, "x": 64.5, "y": 144.5,
     "object_id": "car_1", "confidence": None,
     "bbox": [x, y, w, h], "status": "tracked" | "lost"}
x, y are the bounding-box CENTRE. Lost frames have x = y = None.
An object abandoned after too many lost frames stops producing records.

Run Python from the repo root so that `video_tracking` can be imported.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional, Sequence

from video_tracking import (
    InvalidROIError,
    InvalidVideoError,
    available_trackers,
    track_video,
)
from video_tracking.overlay import render_overlay_video, save_trajectory_image
from video_tracking.schema import MotionInkTrackingError

DEFAULT_MAX_LOST_FRAMES = 30


def run_tracking(
    video_path: str,
    rois: Dict[str, Sequence[float]],
    start_frame: int = 0,
    end_frame: Optional[int] = None,
    tracker_name: str = "CSRT",
    max_lost_frames: int = DEFAULT_MAX_LOST_FRAMES,
    progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
):
    """Track objects and return the raw TrackingResult (used for overlays)."""
    if not available_trackers():
        raise MotionInkTrackingError(
            "No OpenCV tracker available. Install: pip install opencv-contrib-python"
        )
    return track_video(
        video_path,
        {oid: tuple(box) for oid, box in rois.items()},
        start_frame=start_frame,
        end_frame=end_frame,
        tracker_name=tracker_name,
        max_lost_frames=max_lost_frames,
        progress_callback=progress_callback,
        should_stop=should_stop,
    )


def result_to_dict(result) -> Dict[str, Any]:
    """Convert a TrackingResult to the documented JSON-style dict."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "result.json")
        result.save_json(path)
        with open(path, encoding="utf-8") as f:
            return json.load(f)


def track_objects(
    video_path: str, rois: Dict[str, Sequence[float]], **kwargs
) -> Dict[str, Any]:
    """Track one or more objects. `rois` = {"car_1": (x, y, w, h), ...}
    in video pixels. Keyword args are passed to run_tracking
    (start_frame, end_frame, tracker_name, max_lost_frames, ...).

    Returns the full result dict: format_version, video, coordinate_space,
    origin, position_reference, objects, warnings, records.
    """
    return result_to_dict(run_tracking(video_path, rois, **kwargs))


def track_object(
    video_path: str,
    bbox: Sequence[float],
    object_id: str = "car_1",
    **kwargs,
) -> Dict[str, Any]:
    """Track a single object from one starting box (x, y, w, h)."""
    return track_objects(video_path, {object_id: tuple(bbox)}, **kwargs)


def get_path(
    result: Dict[str, Any], object_id: str, tracked_only: bool = True
) -> List[Dict[str, Any]]:
    """Trajectory points for one object, in frame order.

    With tracked_only=True (default) lost frames are skipped, so every
    returned point has numeric x and y. This is the list to hand to the
    scoring / comparison code.
    """
    points = []
    for r in result.get("records", []):
        if r.get("object_id") != object_id:
            continue
        if tracked_only and (r.get("status") != "tracked" or r.get("x") is None):
            continue
        points.append(
            {
                "frame": r["frame"],
                "timestamp": r["timestamp"],
                "x": r["x"],
                "y": r["y"],
            }
        )
    return points


def render_trajectory_image(result, out_path: str, frame_index: Optional[int] = None) -> str:
    """Save the trajectory overlay as a still image. `result` is the raw
    TrackingResult from run_tracking (not the dict)."""
    return save_trajectory_image(result, out_path, frame_index=frame_index)


def render_trajectory_video(
    result, out_path: str, trail_length: Optional[int] = None
) -> str:
    """Save an annotated video with trails. `result` is the raw
    TrackingResult from run_tracking (not the dict)."""
    return render_overlay_video(result, out_path, trail_length=trail_length)


__all__ = [
    "InvalidROIError",
    "InvalidVideoError",
    "MotionInkTrackingError",
    "run_tracking",
    "result_to_dict",
    "track_objects",
    "track_object",
    "get_path",
    "render_trajectory_image",
    "render_trajectory_video",
]