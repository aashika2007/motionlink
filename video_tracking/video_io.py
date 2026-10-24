"""Video loading and frame access. Pure video space; no circuit logic."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Iterator, Optional, Tuple

import cv2
import numpy as np

from .schema import InvalidVideoError

DEFAULT_FALLBACK_FPS = 30.0


@dataclass
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    fps_estimated: bool          # True if the file reported no valid FPS
    frame_count: Optional[int]   # None if the container doesn't report it
    duration: Optional[float]    # seconds, None if frame_count unknown


def frame_to_timestamp(frame_index: int, fps: float) -> float:
    """Single place where timestamps are computed (frame / fps, seconds)."""
    return frame_index / fps


class VideoSource:
    """Validated wrapper around cv2.VideoCapture.

    Usage:
        with VideoSource("race.mp4") as src:
            print(src.info)
            for idx, frame in src.frames(start_frame=0):
                ...
    """

    def __init__(self, path: str):
        if not isinstance(path, str) or not path:
            raise InvalidVideoError("Video path must be a non-empty string.")
        if not os.path.isfile(path):
            raise InvalidVideoError(f"Video file not found: {path}")
        if os.path.getsize(path) == 0:
            raise InvalidVideoError(f"Video file is empty: {path}")

        self._cap = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            self._cap.release()
            raise InvalidVideoError(
                f"OpenCV could not open '{path}'. The file may be corrupt, "
                "not a video, or use an unsupported codec."
            )

        # Verify at least one frame decodes (some bad files open but yield nothing).
        ok, first = self._cap.read()
        if not ok or first is None:
            self._cap.release()
            raise InvalidVideoError(f"'{path}' opened but no frames could be decoded.")
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        h, w = first.shape[:2]
        fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        fps_estimated = False
        if not math.isfinite(fps) or fps <= 1e-3 or fps > 1000:
            fps, fps_estimated = DEFAULT_FALLBACK_FPS, True

        raw_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame_count = raw_count if raw_count > 0 else None
        duration = (frame_count / fps) if frame_count else None

        self.info = VideoInfo(path, w, h, fps, fps_estimated, frame_count, duration)

    # ---- context manager ------------------------------------------------
    def __enter__(self) -> "VideoSource":
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # ---- frame access ---------------------------------------------------
    def seek(self, frame_index: int) -> None:
        if frame_index < 0:
            raise InvalidVideoError("frame_index must be >= 0.")
        if self.info.frame_count is not None and frame_index >= self.info.frame_count:
            raise InvalidVideoError(
                f"frame_index {frame_index} is beyond the end of the video "
                f"({self.info.frame_count} frames)."
            )
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

    def read_frame_at(self, frame_index: int) -> np.ndarray:
        """Return a single BGR frame (e.g. for ROI selection)."""
        self.seek(frame_index)
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise InvalidVideoError(f"Could not read frame {frame_index}.")
        return frame

    def frames(
        self, start_frame: int = 0, end_frame: Optional[int] = None
    ) -> Iterator[Tuple[int, np.ndarray]]:
        """Yield (frame_index, BGR frame) from start_frame up to end_frame
        (exclusive). Stops cleanly at end of video or on a failed read."""
        self.seek(start_frame)
        idx = start_frame
        while end_frame is None or idx < end_frame:
            ok, frame = self._cap.read()
            if not ok or frame is None:
                return  # end of video (or unreadable frame) -> caller infers reason
            yield idx, frame
            idx += 1


def read_frame(path: str, frame_index: int = 0) -> np.ndarray:
    """Convenience: open a video, return one frame, close it."""
    with VideoSource(path) as src:
        return src.read_frame_at(frame_index)