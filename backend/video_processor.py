"""Video helpers for the MotionInk UI.

Everything here works in VIDEO PIXELS (origin top-left, x right, y down).
Nothing here knows about circuit coordinates.

Run Python from the repo root so that `video_tracking` can be imported.
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple, Union

import cv2
import numpy as np

from video_tracking import (
    InvalidROIError,
    InvalidVideoError,
    display_to_video_bbox,
    display_to_video_point,
    validate_roi,
)

BBox = Tuple[float, float, float, float]  # x, y, w, h (top-left corner + size)


def get_video_info(video_path: str) -> Dict[str, Union[int, float, None]]:
    """Return basic facts about a video.

    Returns: {"fps", "frame_count", "width", "height", "duration_s"}
    Raises:  InvalidVideoError if the file is missing, empty or unreadable.
    """
    if not os.path.isfile(video_path):
        raise InvalidVideoError(f"Video file not found: {video_path}")
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            raise InvalidVideoError(f"OpenCV could not open '{video_path}'.")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        cap.release()
    if width <= 0 or height <= 0:
        raise InvalidVideoError(f"'{video_path}' has no readable frames.")
    duration = (frame_count / fps) if fps > 0 and frame_count > 0 else None
    return {
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration_s": duration,
    }


def get_frame(
    video_path: str, frame_index: int = 0, out_path: Optional[str] = None
) -> Union[np.ndarray, str]:
    """Grab one frame so the UI can show it for drawing a box.

    If `out_path` is given, the frame is saved as an image and the path is
    returned; otherwise the frame (BGR numpy array) is returned.
    """
    get_video_info(video_path)  # validates the file
    cap = cv2.VideoCapture(video_path)
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(frame_index)))
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise InvalidVideoError(
            f"Could not read frame {frame_index} from '{video_path}'."
        )
    if out_path is None:
        return frame
    if not cv2.imwrite(out_path, frame):
        raise InvalidVideoError(f"Could not write image to '{out_path}'.")
    return out_path


def to_video_bbox(
    bbox_display: BBox,
    display_size: Tuple[int, int],
    video_size: Tuple[int, int],
) -> BBox:
    """Convert a box drawn on a scaled preview into validated video pixels.

    bbox_display: (x, y, w, h) in the coordinates the user drew in.
    display_size: (width, height) of the preview shown in the UI.
    video_size:   (width, height) of the real video (from get_video_info).
    Raises InvalidROIError if the box is invalid or outside the frame.
    """
    scaled = display_to_video_bbox(bbox_display, display_size, video_size)
    return validate_roi(scaled, video_size[0], video_size[1])


def to_video_point(
    x: float, y: float, display_size: Tuple[int, int], video_size: Tuple[int, int]
) -> Tuple[float, float]:
    """Convert one display point (e.g. a click) to video pixels."""
    return display_to_video_point(x, y, display_size, video_size)


__all__ = [
    "InvalidROIError",
    "InvalidVideoError",
    "get_video_info",
    "get_frame",
    "to_video_bbox",
    "to_video_point",
]