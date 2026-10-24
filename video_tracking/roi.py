"""Region-of-interest selection and validation. VIDEO-PIXEL space only.

A ROI is a bounding box (x, y, w, h): top-left corner plus size, in pixels.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

import cv2
import numpy as np

from .schema import InvalidROIError, MotionInkTrackingError

BBox = Tuple[int, int, int, int]
MIN_ROI_SIZE = 8  # pixels; smaller boxes give trackers nothing to lock onto


def validate_roi(
    bbox: Sequence[float],
    frame_width: int,
    frame_height: int,
    min_size: int = MIN_ROI_SIZE,
) -> BBox:
    """Check a bbox, clip it to the frame, and return integer (x, y, w, h).

    Raises InvalidROIError if it is malformed, empty, entirely outside the
    frame, or smaller than min_size after clipping.
    """
    try:
        x, y, w, h = [float(v) for v in bbox]
    except (TypeError, ValueError) as e:
        raise InvalidROIError(f"ROI must be four numbers (x, y, w, h); got {bbox!r}.") from e
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        raise InvalidROIError("ROI contains NaN or infinite values.")
    if w <= 0 or h <= 0:
        raise InvalidROIError("ROI has zero or negative width/height (selection cancelled?).")

    x0, y0 = max(0.0, x), max(0.0, y)
    x1, y1 = min(float(frame_width), x + w), min(float(frame_height), y + h)
    if x1 <= x0 or y1 <= y0:
        raise InvalidROIError(
            f"ROI {tuple(bbox)} lies outside the {frame_width}x{frame_height} frame."
        )

    ix0, iy0 = int(round(x0)), int(round(y0))
    ix1, iy1 = int(round(x1)), int(round(y1))
    iw, ih = ix1 - ix0, iy1 - iy0
    if iw < min_size or ih < min_size:
        raise InvalidROIError(
            f"ROI is too small ({iw}x{ih}px after clipping); minimum is {min_size}px per side."
        )
    return (ix0, iy0, iw, ih)


def bbox_from_point(
    cx: float, cy: float, size: int, frame_width: int, frame_height: int
) -> BBox:
    """Square ROI centred on a clicked point (video pixels).

    Useful when the UI lets the user click a car instead of dragging a box.
    The box is clipped to the frame, so near an edge it may be smaller.
    """
    half = size / 2.0
    return validate_roi((cx - half, cy - half, size, size), frame_width, frame_height)


def display_to_video_point(
    x: float, y: float,
    display_size: Tuple[int, int],
    video_size: Tuple[int, int],
) -> Tuple[float, float]:
    """Convert a point on a scaled display (e.g. an HTML <video> element)
    into video-pixel coordinates. Sizes are (width, height).

    The UI must call this before passing clicks/boxes into the tracker.
    """
    dw, dh = display_size
    vw, vh = video_size
    if dw <= 0 or dh <= 0:
        raise InvalidROIError("display_size must be positive.")
    return x * vw / dw, y * vh / dh


def display_to_video_bbox(
    bbox: Sequence[float],
    display_size: Tuple[int, int],
    video_size: Tuple[int, int],
) -> Tuple[float, float, float, float]:
    """Same as display_to_video_point, for an (x, y, w, h) box."""
    x, y, w, h = bbox
    sx, sy = video_size[0] / display_size[0], video_size[1] / display_size[1]
    return x * sx, y * sy, w * sx, h * sy


def select_roi_interactive(
    frame: np.ndarray,
    window_name: str = "Select object - drag a box, ENTER/SPACE confirm, C cancel",
    max_display_width: int = 1280,
) -> BBox:
    """Open an OpenCV window and let the user drag a box on `frame`.

    Returns a validated bbox in VIDEO pixels (scaling for large frames is
    undone internally). Raises InvalidROIError if cancelled, and
    MotionInkTrackingError if no GUI is available (headless install,
    SSH session, etc.).
    """
    if frame is None or frame.size == 0:
        raise InvalidROIError("No frame provided for ROI selection.")

    h, w = frame.shape[:2]
    scale = 1.0
    shown = frame
    if w > max_display_width:
        scale = max_display_width / float(w)
        shown = cv2.resize(frame, (int(w * scale), int(h * scale)))

    try:
        bx, by, bw, bh = cv2.selectROI(window_name, shown, showCrosshair=True, fromCenter=False)
    except cv2.error as e:
        raise MotionInkTrackingError(
            "Could not open a selection window (is OpenCV GUI support available?). "
            "Use bbox_from_point() or pass a bbox from the UI instead."
        ) from e
    finally:
        try:
            cv2.destroyWindow(window_name)
            cv2.waitKey(1)
        except cv2.error:
            pass

    if bw == 0 or bh == 0:
        raise InvalidROIError("ROI selection cancelled or empty.")
    return validate_roi((bx / scale, by / scale, bw / scale, bh / scale), w, h)


def select_rois_interactive(
    frame: np.ndarray, count: int = 1, id_prefix: str = "car"
) -> Dict[str, BBox]:
    """Select up to `count` objects one after another on the same frame.

    Returns {"car_1": bbox, "car_2": bbox, ...}. The first selection is
    mandatory (cancel -> InvalidROIError). Cancelling a later selection
    just stops and returns the objects chosen so far.
    """
    rois: Dict[str, BBox] = {}
    canvas = frame.copy()
    for i in range(1, count + 1):
        try:
            bbox = select_roi_interactive(
                canvas, window_name=f"Select {id_prefix}_{i} - ENTER confirm, C cancel"
            )
        except InvalidROIError:
            if i == 1:
                raise
            break
        rois[f"{id_prefix}_{i}"] = bbox
        x, y, w, h = bbox
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(canvas, f"{id_prefix}_{i}", (x, max(15, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return rois