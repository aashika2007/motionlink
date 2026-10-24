"""Trajectory overlay rendering. VIDEO-PIXEL space only.

Draws bounding boxes, labels and trajectory trails on frames, and can
write an annotated video or a still image. Nothing here maps to circuit
coordinates.
"""

from __future__ import annotations

import os
from bisect import bisect_right
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .schema import MotionInkTrackingError, TrackingRecord, TrackingResult
from .video_io import VideoSource

# BGR colours, assigned to objects in order of appearance.
PALETTE = [(0, 255, 0), (0, 165, 255), (255, 128, 0), (255, 0, 255), (0, 255, 255)]


def _segments(records: List[TrackingRecord]) -> List[List[Tuple[int, int]]]:
    """Split records into continuous runs of (x, y) points.

    A lost frame breaks the line, so the overlay never draws a fake
    straight segment across a gap (no interpolation is invented).
    """
    segs: List[List[Tuple[int, int]]] = []
    cur: List[Tuple[int, int]] = []
    for r in records:
        if r.is_tracked:
            cur.append((int(round(r.x)), int(round(r.y))))
        elif cur:
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    return segs


class OverlayRenderer:
    """Draws overlays for one TrackingResult.

    Usage:
        renderer = OverlayRenderer(result, trail_length=None)
        annotated = renderer.draw(frame, frame_index)   # returns a copy
    """

    def __init__(self, result: TrackingResult, trail_length: Optional[int] = None,
                 draw_boxes: bool = True, draw_labels: bool = True):
        self.result = result
        self.trail_length = trail_length  # None = whole trajectory so far
        self.draw_boxes = draw_boxes
        self.draw_labels = draw_labels
        self._by_obj: Dict[str, List[TrackingRecord]] = {}
        self._frames: Dict[str, List[int]] = {}
        self._colors: Dict[str, Tuple[int, int, int]] = {}
        for i, oid in enumerate(result.object_ids()):
            recs = sorted(result.records_for(oid), key=lambda r: r.frame)
            self._by_obj[oid] = recs
            self._frames[oid] = [r.frame for r in recs]
            self._colors[oid] = PALETTE[i % len(PALETTE)]

    def draw(self, frame: np.ndarray, frame_index: int) -> np.ndarray:
        out = frame.copy()
        label_row = 0
        for oid, recs in self._by_obj.items():
            color = self._colors[oid]
            n = bisect_right(self._frames[oid], frame_index)
            if n == 0:
                continue  # this object hasn't started yet
            visible = recs[:n]
            if self.trail_length is not None:
                visible = visible[-self.trail_length:]

            for seg in _segments(visible):
                if len(seg) >= 2:
                    cv2.polylines(out, [np.array(seg, np.int32)], False, color, 2, cv2.LINE_AA)

            current = recs[n - 1]
            on_this_frame = current.frame == frame_index
            if on_this_frame and current.is_tracked:
                cx, cy = int(round(current.x)), int(round(current.y))
                cv2.circle(out, (cx, cy), 4, color, -1, cv2.LINE_AA)
                if self.draw_boxes and current.bbox is not None:
                    x, y, w, h = current.bbox
                    cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)
                if self.draw_labels:
                    cv2.putText(out, oid, (cx + 6, max(15, cy - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
            elif self.draw_labels:
                state = "LOST" if on_this_frame else "ENDED"
                cv2.putText(out, f"{oid}: {state}", (10, 25 + 24 * label_row),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
                label_row += 1
        return out


def render_overlay_video(
    result: TrackingResult,
    output_path: str,
    trail_length: Optional[int] = None,
    codec: str = "mp4v",
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Write an annotated copy of the tracked section of the video.

    Covers from the first to the last tracked frame. Returns output_path.
    Note: 'mp4v' files often do NOT play inside a browser <video> tag
    (browsers want H.264). For web playback, draw the overlay in the UI
    from the JSON instead, or re-encode with ffmpeg.
    """
    if not result.records:
        raise MotionInkTrackingError("No tracking records to render.")
    start = min(r.frame for r in result.records)
    end = max(r.frame for r in result.records) + 1

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)

    renderer = OverlayRenderer(result, trail_length)
    with VideoSource(result.video_path) as src:
        writer = cv2.VideoWriter(
            output_path, cv2.VideoWriter_fourcc(*codec), result.fps,
            (src.info.width, src.info.height),
        )
        if not writer.isOpened():
            raise MotionInkTrackingError(
                f"Could not open video writer for '{output_path}' with codec '{codec}'. "
                "Try a different codec (e.g. 'XVID' with an .avi path)."
            )
        try:
            for idx, frame in src.frames(start, end):
                writer.write(renderer.draw(frame, idx))
                if progress_callback is not None:
                    progress_callback(idx - start + 1, end - start)
        finally:
            writer.release()
    return output_path


def save_trajectory_image(
    result: TrackingResult, output_path: str, frame_index: Optional[int] = None
) -> str:
    """Save one still frame with the COMPLETE trajectories drawn on it.

    frame_index = background frame (default: the first tracked frame).
    Handy as a quick sanity check and as a preview image for the UI.
    """
    if not result.records:
        raise MotionInkTrackingError("No tracking records to render.")
    last = max(r.frame for r in result.records)
    if frame_index is None:
        frame_index = min(r.frame for r in result.records)
    with VideoSource(result.video_path) as src:
        frame = src.read_frame_at(frame_index)
    img = OverlayRenderer(result, None, draw_boxes=False).draw(frame, last)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if not cv2.imwrite(output_path, img):
        raise MotionInkTrackingError(f"Could not write image to '{output_path}'.")
    return output_path