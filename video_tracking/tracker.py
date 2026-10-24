"""OpenCV-based tracking of user-selected regions. VIDEO-PIXEL space only.

WHAT THIS IS
    A generic appearance-based tracker (CSRT / KCF / MIL). It follows the
    region the user selected from frame to frame.

WHAT THIS IS NOT
    It does not detect F1 cars, does not know what a car is, and does not
    handle camera cuts, heavy occlusion, or large scale/appearance changes
    reliably. After a cut or occlusion it may report "lost", or silently
    drift onto the wrong thing. OpenCV gives no confidence score, so drift
    cannot be detected automatically. Always review the overlay.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .roi import BBox, validate_roi
from .schema import (
    STATUS_LOST,
    STATUS_TRACKED,
    InvalidROIError,
    ObjectSummary,
    TrackerUnavailableError,
    TrackingRecord,
    TrackingResult,
)
from .video_io import VideoSource, frame_to_timestamp

DEFAULT_TRACKER = "CSRT"            # most accurate of the three, slower
TRACKER_PREFERENCE = ("CSRT", "KCF", "MIL")
DEFAULT_MAX_LOST_FRAMES = 30        # consecutive lost frames before giving up


# --------------------------------------------------------------------------
# Tracker factory (handles OpenCV version differences)
# --------------------------------------------------------------------------
def _find_factory(name: str) -> Optional[Callable[[], Any]]:
    name = name.upper()
    for ns in (cv2, getattr(cv2, "legacy", None)):
        if ns is None:
            continue
        fn = getattr(ns, f"Tracker{name}_create", None)
        if callable(fn):
            return fn
        cls = getattr(ns, f"Tracker{name}", None)
        if cls is not None and callable(getattr(cls, "create", None)):
            return cls.create
    return None


def available_trackers() -> List[str]:
    """Names from TRACKER_PREFERENCE that work in this OpenCV install."""
    return [n for n in TRACKER_PREFERENCE if _find_factory(n) is not None]


def create_tracker(name: str = DEFAULT_TRACKER):
    factory = _find_factory(name)
    if factory is None:
        raise TrackerUnavailableError(
            f"Tracker '{name}' is not available in OpenCV {cv2.__version__}. "
            f"Available: {available_trackers() or 'none'}. "
            "Install opencv-contrib-python (and uninstall plain opencv-python)."
        )
    return factory()


# --------------------------------------------------------------------------
# Multi-object tracker: one independent OpenCV tracker per object
# --------------------------------------------------------------------------
@dataclass
class _Track:
    object_id: str
    tracker: Any
    summary: ObjectSummary
    active: bool = True
    consecutive_lost: int = 0


class MultiObjectTracker:
    """Independent trackers, one per object, fed the same frames.

    Low-level API (also what a live UI preview should use):
        mot = MultiObjectTracker(fps, (width, height))
        recs = mot.start(frame_index, frame, {"car_1": bbox1, "car_2": bbox2})
        recs = mot.update(frame_index, frame)   # for each following frame
        mot.finish("end_of_video")

    Each start()/update() call returns the list of TrackingRecord for that
    frame (one per still-active object). Once an object is given up on
    (lost_too_long) it produces no further records.
    """

    def __init__(
        self,
        fps: float,
        frame_size: Tuple[int, int],
        tracker_name: str = DEFAULT_TRACKER,
        max_lost_frames: int = DEFAULT_MAX_LOST_FRAMES,
    ):
        self.fps = fps
        self.frame_w, self.frame_h = frame_size
        self.tracker_name = tracker_name.upper()
        self.max_lost_frames = max(0, int(max_lost_frames))
        self._tracks: Dict[str, _Track] = {}
        create_tracker(self.tracker_name)  # fail early if unavailable

    @property
    def summaries(self) -> Dict[str, ObjectSummary]:
        return {oid: t.summary for oid, t in self._tracks.items()}

    @property
    def any_active(self) -> bool:
        return any(t.active for t in self._tracks.values())

    # ---- start ----------------------------------------------------------
    def start(
        self, frame_index: int, frame: np.ndarray, rois: Dict[str, Any]
    ) -> List[TrackingRecord]:
        if not rois:
            raise InvalidROIError("At least one ROI is required.")
        records: List[TrackingRecord] = []
        for oid, raw in rois.items():
            bbox = validate_roi(raw, self.frame_w, self.frame_h)
            tracker = create_tracker(self.tracker_name)
            try:
                ok = tracker.init(frame, bbox)
            except cv2.error as e:
                raise InvalidROIError(f"Tracker could not initialise for '{oid}': {e}") from e
            if ok is False:  # some OpenCV versions return bool, others None
                raise InvalidROIError(f"Tracker refused to initialise for '{oid}'.")
            summary = ObjectSummary(oid, bbox, frame_index, self.tracker_name)
            self._tracks[oid] = _Track(oid, tracker, summary)
            x, y, w, h = bbox
            records.append(self._tracked_record(summary, frame_index, x, y, w, h))
        return records

    # ---- update ---------------------------------------------------------
    def update(self, frame_index: int, frame: np.ndarray) -> List[TrackingRecord]:
        out: List[TrackingRecord] = []
        ts = frame_to_timestamp(frame_index, self.fps)
        for t in self._tracks.values():
            if not t.active:
                continue
            box = self._safe_update(t, frame)
            if box is None:
                t.consecutive_lost += 1
                t.summary.frames_lost += 1
                out.append(TrackingRecord(
                    frame=frame_index, timestamp=ts, x=None, y=None,
                    object_id=t.object_id, confidence=None, bbox=None,
                    status=STATUS_LOST,
                ))
                if t.consecutive_lost >= self.max_lost_frames:
                    t.active = False
                    t.summary.end_reason = "lost_too_long"
            else:
                t.consecutive_lost = 0
                out.append(self._tracked_record(t.summary, frame_index, *box))
        return out

    def finish(self, reason: str) -> None:
        """Mark every still-active object as ended for `reason`."""
        for t in self._tracks.values():
            if t.active:
                t.active = False
                t.summary.end_reason = reason

    # ---- internals ------------------------------------------------------
    def _safe_update(self, t: _Track, frame: np.ndarray):
        """Run the tracker; return (x, y, w, h) floats, or None if lost/invalid."""
        try:
            ok, box = t.tracker.update(frame)
        except cv2.error:
            return None
        if not ok:
            return None
        try:
            x, y, w, h = [float(v) for v in box]
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(v) for v in (x, y, w, h)):
            return None
        if w < 2 or h < 2:
            return None
        cx, cy = x + w / 2.0, y + h / 2.0
        if not (0 <= cx < self.frame_w and 0 <= cy < self.frame_h):
            return None  # centre left the frame: treat as lost
        return x, y, w, h

    def _tracked_record(
        self, summary: ObjectSummary, frame_index: int, x, y, w, h
    ) -> TrackingRecord:
        summary.frames_tracked += 1
        return TrackingRecord(
            frame=frame_index,
            timestamp=frame_to_timestamp(frame_index, self.fps),
            x=x + w / 2.0,              # bounding-box CENTRE
            y=y + h / 2.0,
            object_id=summary.object_id,
            confidence=None,
            bbox=(int(round(x)), int(round(y)), int(round(w)), int(round(h))),
            status=STATUS_TRACKED,
        )


# --------------------------------------------------------------------------
# High-level entry point
# --------------------------------------------------------------------------
def track_video(
    video_path: str,
    rois: Dict[str, Any],
    start_frame: int = 0,
    end_frame: Optional[int] = None,
    tracker_name: str = DEFAULT_TRACKER,
    max_lost_frames: int = DEFAULT_MAX_LOST_FRAMES,
    progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
    on_frame: Optional[Callable[[int, np.ndarray, List[TrackingRecord]], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> TrackingResult:
    """Track one or more user-selected regions through a video.

    Args:
        video_path:  local video file.
        rois:        {"car_1": (x, y, w, h), "car_2": (...)} in VIDEO pixels,
                     drawn on the frame at `start_frame`.
        start_frame: frame the ROIs were selected on (0-based).
        end_frame:   exclusive stop frame; None = end of video.
        progress_callback(frame_index, frame_count_or_None): for progress bars.
        on_frame(frame_index, frame, records_for_this_frame): for live preview.
        should_stop(): return True to cancel; objects end with "stopped".

    Returns a TrackingResult. Raises InvalidVideoError / InvalidROIError /
    TrackerUnavailableError for bad input; tracking problems (lost objects,
    early end of video) are reported in the result, not raised.
    """
    with VideoSource(video_path) as src:
        info = src.info
        result = TrackingResult(
            video_path=video_path, fps=info.fps, frame_count=info.frame_count,
            width=info.width, height=info.height, fps_estimated=info.fps_estimated,
        )
        if info.fps_estimated:
            result.warnings.append(
                f"Video reported no valid FPS; assumed {info.fps}. Timestamps may be wrong."
            )

        mot = MultiObjectTracker(
            info.fps, (info.width, info.height), tracker_name, max_lost_frames
        )

        last_idx: Optional[int] = None
        stopped = False
        started = False

        for idx, frame in src.frames(start_frame, end_frame):
            if should_stop is not None and should_stop():
                stopped = True
                break
            if not started:
                recs = mot.start(idx, frame, rois)
                started = True
            else:
                recs = mot.update(idx, frame)
            result.records.extend(recs)
            last_idx = idx
            if on_frame is not None:
                on_frame(idx, frame, recs)
            if progress_callback is not None:
                progress_callback(idx, info.frame_count)
            if not mot.any_active:
                break

        if not started:
            raise InvalidROIError(
                f"No frame could be read at start_frame={start_frame}; cannot start tracking."
            )

        # Work out why tracking stopped for objects that are still active.
        if stopped:
            reason = "stopped"
        elif end_frame is not None and last_idx is not None and last_idx + 1 >= end_frame:
            reason = "max_frames"
        elif (info.frame_count is not None and last_idx is not None
              and last_idx + 1 < info.frame_count):
            reason = "read_error"
            result.warnings.append(
                f"Video stopped decoding at frame {last_idx + 1} of {info.frame_count}; "
                "the file may be truncated or corrupt."
            )
        else:
            reason = "end_of_video"
        mot.finish(reason)

        result.objects = mot.summaries
        for oid, s in result.objects.items():
            if s.end_reason == "lost_too_long":
                result.warnings.append(
                    f"{oid}: lost for {max_lost_frames}+ consecutive frames; tracking abandoned. "
                    "Possible camera cut, occlusion, or leaving the frame."
                )
            elif s.frames_lost:
                result.warnings.append(f"{oid}: {s.frames_lost} frame(s) lost during tracking.")
        return result