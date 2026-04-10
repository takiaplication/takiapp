"""
Stage 1: Extract frames from a video at 2 fps (every 500 ms).

Sampling at 500 ms gives one frame per half-second; duplicates are handled
downstream via text-fingerprint dedup after OCR (no visual dedup).
"""

import asyncio
import cv2
from pathlib import Path
from typing import List, Optional, Callable

from config import PROJECTS_DIR

# Sample every SAMPLE_MS milliseconds.
# 333 ms ≈ 3 fps  →  a 60-second video → up to 180 raw samples.
SAMPLE_MS = 333


async def extract_scenes(
    video_path: str,
    project_id: str,
    progress_callback: Optional[Callable] = None,
) -> List[str]:
    """
    Capture one frame every SAMPLE_MS milliseconds from *video_path*.

    Returns a list of absolute JPEG paths in chronological order.
    All previous auto-extracted frames for the project are removed first;
    manual captures (frame_manual_*.jpg) are preserved.
    """
    frames_dir = PROJECTS_DIR / project_id / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Remove old auto-extracts; keep manual captures
    for old in frames_dir.glob("frame_auto_*.jpg"):
        old.unlink()

    if progress_callback:
        await progress_callback(0.02, "Opening video…")

    def _extract() -> List[str]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_ms = int(total_frames / fps * 1000)

        saved: List[str] = []
        idx = 0
        ms = 0

        while ms <= duration_ms:
            cap.set(cv2.CAP_PROP_POS_MSEC, ms)
            ret, frame = cap.read()
            if not ret:
                break

            p = str(frames_dir / f"frame_auto_{idx:06d}.jpg")
            cv2.imwrite(p, frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            saved.append(p)
            idx += 1
            ms += SAMPLE_MS

        cap.release()
        return saved

    saved_paths = await asyncio.to_thread(_extract)

    if progress_callback:
        await progress_callback(1.0, f"Captured {len(saved_paths)} raw samples")

    return saved_paths


async def capture_frame_at(
    video_path: str,
    project_id: str,
    time_seconds: float,
) -> str:
    """
    Grab a single frame at *time_seconds* using ffmpeg.
    Saved as frame_manual_XXXXXX.jpg; returns the absolute path.
    """
    frames_dir = PROJECTS_DIR / project_id / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    next_idx = len(list(frames_dir.glob("frame_manual_*.jpg")))
    out_path = str(frames_dir / f"frame_manual_{next_idx:06d}.jpg")

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(time_seconds),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        out_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    if not Path(out_path).exists():
        raise RuntimeError(f"Failed to capture frame at {time_seconds}s")

    return out_path


def get_video_duration(video_path: str) -> float:
    """Return video duration in seconds via OpenCV."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return float(total_frames / fps) if fps > 0 else 0.0
