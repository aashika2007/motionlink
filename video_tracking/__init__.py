"""MotionInk video-processing and tracking module (Person 1).

Everything returned by this package is in VIDEO-PIXEL space.
Mapping to circuit coordinates belongs to a different module.
"""

from .roi import (
    bbox_from_point,
    display_to_video_bbox,
    display_to_video_point,
    select_roi_interactive,
    select_rois_interactive,
    validate_roi,
)
from .schema import (
    COORDINATE_SPACE,
    POSITION_REFERENCE,
    InvalidROIError,
    InvalidVideoError,
    MotionInkTrackingError,
    TrackerUnavailableError,
    TrackingRecord,
    TrackingResult,
)
from .tracker import (
    MultiObjectTracker,
    available_trackers,
    create_tracker,
    track_video,
)
from .video_io import VideoInfo, VideoSource, frame_to_timestamp, read_frame

__all__ = [
    "COORDINATE_SPACE",
    "POSITION_REFERENCE",
    "InvalidROIError",
    "InvalidVideoError",
    "MotionInkTrackingError",
    "TrackerUnavailableError",
    "TrackingRecord",
    "TrackingResult",
    "VideoInfo",
    "VideoSource",
    "frame_to_timestamp",
    "read_frame",
    "bbox_from_point",
    "display_to_video_bbox",
    "display_to_video_point",
    "select_roi_interactive",
    "select_rois_interactive",
    "validate_roi",
    "MultiObjectTracker",
    "available_trackers",
    "create_tracker",
    "track_video",
    "OverlayRenderer",
    "render_overlay_video",
    "save_trajectory_image",
]

from .overlay import (
    OverlayRenderer,
    render_overlay_video,
    save_trajectory_image,
)