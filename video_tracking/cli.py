"""Demo / test command for the MotionInk tracker.

Run from the repo root (the folder containing video_tracking/):

    # 1. No footage needed: synthetic self-test
    python -m video_tracking.cli --demo

    # 2. Real video, pick the car(s) with the mouse
    python -m video_tracking.cli race.mp4
    python -m video_tracking.cli race.mp4 --objects 2 --start-frame 120

    # 3. Real video, no GUI (box = x,y,w,h in video pixels)
    python -m video_tracking.cli race.mp4 --roi 300,190,40,40 --roi 500,200,40,40
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

import cv2
import numpy as np

from .overlay import render_overlay_video, save_trajectory_image
from .roi import select_rois_interactive
from .schema import MotionInkTrackingError
from .tracker import DEFAULT_TRACKER, available_trackers, track_video
from .video_io import VideoSource


def _parse_roi(text: str):
    try:
        x, y, w, h = [float(p) for p in text.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError("ROI must be 'x,y,w,h' (four numbers).")
    return (x, y, w, h)


def make_demo_video(path: str, frames: int = 90, fps: float = 30.0):
    """Synthetic clip: textured noise background, two textured squares
    moving independently. Returns their frame-0 boxes."""
    w, h, size = 640, 360, 40
    rng = np.random.default_rng(1)
    bg = cv2.GaussianBlur(rng.integers(60, 120, (h, w, 3), dtype=np.uint8), (5, 5), 0)
    patch1 = rng.integers(0, 255, (size, size, 3), dtype=np.uint8)
    patch2 = rng.integers(0, 255, (size, size, 3), dtype=np.uint8)

    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        raise MotionInkTrackingError("Could not create the demo video (mp4v codec unavailable).")
    boxes0 = {}
    try:
        for i in range(frames):
            frame = bg.copy()
            x1, y1 = 40 + i * 5, int(120 + 40 * np.sin(i / 10))
            x2, y2 = 560 - i * 5, int(240 - 40 * np.sin(i / 10))
            frame[y1:y1 + size, x1:x1 + size] = patch1
            frame[y2:y2 + size, x2:x2 + size] = patch2
            writer.write(frame)
            if i == 0:
                boxes0 = {"car_1": (x1, y1, size, size),
                          "car_2": (x2, y2, size, size)}
    finally:
        writer.release()
    return boxes0

def _grab_frame(video_path: str, index: int):
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            raise MotionInkTrackingError(f"Could not open video: {video_path}")
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, index))
        ok, frame = cap.read()
        if not ok:
            raise MotionInkTrackingError(f"Could not read frame {index} from {video_path}")
        return frame
    finally:
        cap.release()


def _progress(done: int, total: Optional[int]) -> None:
    msg = f"\r  frame {done}" + (f"/{total}" if total else "")
    print(msg, end="", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m video_tracking.cli",
        description="Track one or more moving objects in a video.",
    )
    p.add_argument("video", nargs="?", help="input video (omit when using --demo)")
    p.add_argument("--demo", action="store_true", help="run on a generated synthetic clip")
    p.add_argument("--objects", type=int, default=1,
                   help="how many objects to pick with the mouse (default 1)")
    p.add_argument("--roi", action="append", type=_parse_roi, metavar="x,y,w,h",
                   help="object box in video pixels; repeat for more objects (skips the GUI)")
    p.add_argument("--start-frame", type=int, default=0)
    p.add_argument("--end-frame", type=int, default=None)
    p.add_argument("--tracker", default=DEFAULT_TRACKER,
                   help=f"tracker algorithm (available: {', '.join(available_trackers()) or 'none'})")
    p.add_argument("--max-lost-frames", type=int, default=30,
                   help="abandon an object after this many consecutive lost frames")
    p.add_argument("--out-dir", default="tracking_output")
    p.add_argument("--trail-length", type=int, default=None,
                   help="limit the trail drawn in the overlay video (frames)")
    p.add_argument("--no-video", action="store_true",
                   help="skip the annotated overlay video (still image + data only)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)

    try:
        if not available_trackers():
            raise MotionInkTrackingError(
                "No OpenCV tracker available. Install: pip install opencv-contrib-python")

        # 1. Source video + starting boxes
        if args.demo:
            video = os.path.join(args.out_dir, "demo.mp4")
            rois = make_demo_video(video)
            print(f"Generated demo video: {video}")
        else:
            if not args.video:
                build_parser().error("give a video file, or use --demo")
            video = args.video
            if args.roi:
                rois = {f"car_{i + 1}": r for i, r in enumerate(args.roi)}
            else:
                frame = _grab_frame(video, args.start_frame)
                rois = select_rois_interactive(frame, count=args.objects)
            if not rois:
                raise MotionInkTrackingError("No objects were selected.")

        # 2. Track
        print(f"Tracking {len(rois)} object(s) with {args.tracker} ...")
        result = track_video(
            video, rois,
            start_frame=args.start_frame,
            end_frame=args.end_frame,
            tracker_name=args.tracker,
            max_lost_frames=args.max_lost_frames,
            progress_callback=_progress,
        )
        print()

        # 3. Save data
        stem = os.path.splitext(os.path.basename(video))[0]
        json_path = os.path.join(args.out_dir, f"{stem}_tracking.json")
        result.save_json(json_path)
        print(f"Saved {json_path}")
        if hasattr(result, "save_csv"):
            csv_path = os.path.join(args.out_dir, f"{stem}_tracking.csv")
            result.save_csv(csv_path)
            print(f"Saved {csv_path}")

        # 4. Overlays
        png_path = os.path.join(args.out_dir, f"{stem}_trajectory.png")
        save_trajectory_image(result, png_path)
        print(f"Saved {png_path}")
        if not args.no_video:
            mp4_path = os.path.join(args.out_dir, f"{stem}_overlay.mp4")
            render_overlay_video(result, mp4_path, trail_length=args.trail_length)
            print(f"Saved {mp4_path}")

        for oid in result.object_ids():
            print(f"  {oid}: ended because '{result.objects[oid].end_reason}'")
        return 0

    except MotionInkTrackingError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())