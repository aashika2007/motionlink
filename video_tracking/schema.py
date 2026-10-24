"""Shared data contract for MotionInk tracking output.

CONTRACT
--------
Each record:
    {"frame": 120, "timestamp": 4.0, "x": 320.0, "y": 210.0,
     "object_id": "car_1", "confidence": null,
     "bbox": [300, 190, 40, 40], "status": "tracked"}

- Coordinate space : video pixels (NOT circuit coordinates).
- Origin           : top-left of the frame, +x right, +y down.
- Position         : centre of the tracked bounding box.
- frame            : 0-based frame index in the source video.
- timestamp        : frame / fps, in seconds.
- Lost frames      : record is still emitted with x = y = None,
                     bbox = None, status = "lost".
- confidence       : None (OpenCV trackers give no calibrated score).
- bbox / status    : optional extras; consumers may ignore them.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

COORDINATE_SPACE = "video_pixels"
POSITION_REFERENCE = "bounding_box_centre"
ORIGIN = "top_left"

STATUS_TRACKED = "tracked"
STATUS_LOST = "lost"


class MotionInkTrackingError(Exception):
    """Base class for all errors raised by this module."""


class InvalidVideoError(MotionInkTrackingError):
    """Video missing, unreadable, empty, or has no decodable frames."""


class InvalidROIError(MotionInkTrackingError):
    """Selected region is empty, outside the frame, or too small."""


class TrackerUnavailableError(MotionInkTrackingError):
    """Requested OpenCV tracker is not available in this installation."""


@dataclass
class TrackingRecord:
    frame: int
    timestamp: float
    x: Optional[float]
    y: Optional[float]
    object_id: str
    confidence: Optional[float] = None
    bbox: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h)
    status: str = STATUS_TRACKED

    @property
    def is_tracked(self) -> bool:
        return self.status == STATUS_TRACKED and self.x is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame": int(self.frame),
            "timestamp": round(float(self.timestamp), 6),
            "x": None if self.x is None else round(float(self.x), 2),
            "y": None if self.y is None else round(float(self.y), 2),
            "object_id": self.object_id,
            "confidence": self.confidence,
            "bbox": None if self.bbox is None else [int(v) for v in self.bbox],
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TrackingRecord":
        bbox = d.get("bbox")
        return cls(
            frame=int(d["frame"]),
            timestamp=float(d["timestamp"]),
            x=d.get("x"),
            y=d.get("y"),
            object_id=str(d["object_id"]),
            confidence=d.get("confidence"),
            bbox=tuple(bbox) if bbox is not None else None,
            status=d.get("status", STATUS_TRACKED if d.get("x") is not None else STATUS_LOST),
        )


@dataclass
class ObjectSummary:
    """Per-object metadata about how a track started and ended."""
    object_id: str
    initial_bbox: Tuple[int, int, int, int]
    start_frame: int
    tracker: str
    end_reason: str = "unknown"  # end_of_video | lost_too_long | max_frames | stopped | read_error
    frames_tracked: int = 0
    frames_lost: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "object_id": self.object_id,
            "initial_bbox": list(self.initial_bbox),
            "start_frame": self.start_frame,
            "tracker": self.tracker,
            "end_reason": self.end_reason,
            "frames_tracked": self.frames_tracked,
            "frames_lost": self.frames_lost,
        }


@dataclass
class TrackingResult:
    video_path: str
    fps: float
    frame_count: Optional[int]
    width: int
    height: int
    fps_estimated: bool = False
    records: List[TrackingRecord] = field(default_factory=list)
    objects: Dict[str, ObjectSummary] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    # ---- access helpers -------------------------------------------------
    def object_ids(self) -> List[str]:
        return list(self.objects.keys())

    def records_for(self, object_id: str) -> List[TrackingRecord]:
        return [r for r in self.records if r.object_id == object_id]

    def trajectory(self, object_id: str, include_lost: bool = False) -> List[Tuple[float, float]]:
        """Ordered (x, y) video-pixel points for one object.

        Lost frames are skipped by default (no interpolation is invented).
        """
        pts = []
        for r in self.records_for(object_id):
            if r.is_tracked:
                pts.append((r.x, r.y))
            elif include_lost:
                pts.append((None, None))
        return pts

    # ---- serialisation --------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "format_version": 1,
            "video": {
                "path": self.video_path,
                "fps": self.fps,
                "fps_estimated": self.fps_estimated,
                "frame_count": self.frame_count,
                "width": self.width,
                "height": self.height,
            },
            "coordinate_space": COORDINATE_SPACE,
            "origin": ORIGIN,
            "position_reference": POSITION_REFERENCE,
            "objects": {k: v.to_dict() for k, v in self.objects.items()},
            "warnings": list(self.warnings),
            "records": [r.to_dict() for r in self.records],
        }

    def to_json(self, indent: Optional[int] = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    def save_csv(self, path: str) -> None:
        cols = ["frame", "timestamp", "x", "y", "object_id", "confidence", "status"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in self.records:
                d = r.to_dict()
                w.writerow(["" if d[c] is None else d[c] for c in cols])