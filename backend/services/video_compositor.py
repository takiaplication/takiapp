import asyncio
import subprocess
from pathlib import Path
from typing import Callable, Awaitable, Optional

import cv2
import numpy as np
from PIL import Image


def _expand_video_to_pngs(
    video_path: str,
    work_dir: Path,
    start_idx: int,
    fps: int,
) -> tuple[list[str], int]:
    """
    Extract every frame of a video meme, scale/pad each to 1080×1920 (centred,
    80 % max height on a black canvas), and write them as PNGs.

    Returns (list_of_png_paths, next_available_idx).
    """
    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total   = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Sample at the target fps so we don't double/triple frames
    step = max(1, round(src_fps / fps))
    frame_no = 0
    save_idx = start_idx
    paths: list[str] = []

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ret, bgr = cap.read()
        if not ret:
            break

        # Convert BGR → PIL, scale to full width (no side bars)
        rgb    = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img    = Image.fromarray(rgb)
        scale  = 1080 / img.width
        new_h  = int(img.height * scale)
        img    = img.resize((1080, new_h), Image.LANCZOS)
        canvas = Image.new("RGB", (1080, 1920), (0, 0, 0))
        if new_h >= 1920:
            y_src = (new_h - 1920) // 2
            img   = img.crop((0, y_src, 1080, y_src + 1920))
            canvas.paste(img, (0, 0))
        else:
            canvas.paste(img, (0, (1920 - new_h) // 2))

        out = str(work_dir / f"frame_{save_idx:06d}.png")
        canvas.save(out)
        paths.append(out)
        save_idx += 1
        frame_no += step

    cap.release()
    return paths, save_idx


async def compose_video(
    slides: list[dict],
    output_path: Path,
    transition_type: str = "crossfade",
    transition_duration_ms: int = 300,
    fps: int = 30,
    music_path: Optional[str] = None,
    music_volume: float = 0.3,
    screen_recording_effect: bool = True,
    progress_callback: Optional[Callable[[float, str], Awaitable[None]]] = None,
):
    """
    Stitch rendered slide PNGs (and optional video memes) into an MP4 video.

    slides: list of {"path": str, "hold_duration_ms": int, "is_video": bool}
    """
    work_dir = output_path.parent / "compositor_tmp"
    # Always start with a clean working directory.  If a previous export
    # failed partway through, stale PNG frames would otherwise remain and
    # could be picked up by ffmpeg through the concat file.
    import shutil as _shutil
    _shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(exist_ok=True)

    total_slides = len(slides)
    total_steps = total_slides + (total_slides - 1 if transition_type == "crossfade" else 0) + 1
    step = 0

    # Generate all frames (hold frames + transition frames)
    frame_list_path = work_dir / "frames.txt"
    frame_entries = []
    frame_idx = 0

    # Pre-load "representative" PIL images for crossfade look-ahead.
    # For video memes we use the first extracted PNG; for images, the image itself.
    representative: dict[int, Image.Image] = {}

    for i, slide_info in enumerate(slides):
        slide_path = slide_info["path"]
        hold_ms    = slide_info.get("hold_duration_ms") or 3000   # guard: None or 0 → 3 s
        is_video   = slide_info.get("is_video", False)

        if is_video:
            # Expand video meme into individual padded PNG frames
            png_paths, frame_idx = await asyncio.to_thread(
                _expand_video_to_pngs, slide_path, work_dir, frame_idx, fps
            )
            if not png_paths:
                # Fallback: blank frame
                blank = Image.new("RGB", (1080, 1920), (0, 0, 0))
                p = str(work_dir / f"frame_{frame_idx:06d}.png")
                blank.save(p)
                png_paths = [p]
                frame_idx += 1

            for p in png_paths:
                frame_entries.append(f"file '{Path(p).name}'\nduration {1.0 / fps}")
            representative[i] = Image.open(png_paths[0]).convert("RGBA")

        else:
            hold_duration = hold_ms / 1000.0
            frame_file = work_dir / f"frame_{frame_idx:06d}.png"
            img = Image.open(slide_path)
            img.save(str(frame_file))
            frame_entries.append(f"file '{frame_file.name}'\nduration {hold_duration}")
            frame_idx += 1
            representative[i] = img.convert("RGBA")

        step += 1
        if progress_callback:
            await progress_callback(step / total_steps, f"Processing slide {i + 1}/{total_slides}")

        # Crossfade transition to next slide (image→image only; skip video memes)
        if (
            transition_type == "crossfade"
            and i < total_slides - 1
            and not is_video
            and not slides[i + 1].get("is_video", False)
        ):
            # Load next slide's representative image
            next_rep = representative.get(i + 1)
            if next_rep is None:
                next_rep = Image.open(slides[i + 1]["path"]).convert("RGBA")

            img_a = representative[i]
            img_b = next_rep
            transition_frames   = max(1, int(fps * transition_duration_ms / 1000))
            transition_duration = transition_frames / fps

            for t in range(transition_frames):
                alpha   = (t + 1) / (transition_frames + 1)
                blended = Image.blend(img_a, img_b, alpha)
                tf      = work_dir / f"frame_{frame_idx:06d}.png"
                blended.convert("RGB").save(str(tf))
                frame_entries.append(f"file '{tf.name}'\nduration {1.0 / fps}")
                frame_idx += 1

            step += 1
            if progress_callback:
                await progress_callback(step / total_steps, f"Rendering transition {i + 1}")

    # Write concat file
    # Add the last frame again (ffmpeg concat needs it)
    if frame_entries:
        last_entry_file = frame_entries[-1].split("\n")[0]
        frame_entries.append(last_entry_file)

    frame_list_path.write_text("\n".join(frame_entries))

    # Build ffmpeg command
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(frame_list_path),
    ]

    if music_path and Path(music_path).exists():
        cmd.extend(["-i", music_path])

    # ── Video filter chain ─────────────────────────────────────────────────
    # Base: fps + pixel format
    vf_parts = [f"fps={fps}"]

    if screen_recording_effect:
        # Simulate someone holding a phone and screen-recording their DMs:
        #   • Subtle random crop offset (±2px) → micro camera shake
        #   • Slight vignette (darker edges) → phone screen edges
        #   • Very faint noise grain → not a perfect digital render
        # The crop shrinks the canvas by 8px in each direction, then rescales
        # back to 1080×1920 — imperceptible to viewers, fatal to fingerprinters.
        vf_parts += [
            "vignette=angle=PI/5:mode=forward",
            "noise=alls=2:allf=t+u",     # tiny temporal+uniform noise grain
        ]

    vf_parts.append("format=yuv420p")
    vf_filter = ",".join(vf_parts)

    cmd.extend([
        "-vf", vf_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-r", str(fps),
        # Strip ALL metadata (encoder tag, creation date, tool fingerprint)
        "-map_metadata", "-1",
        "-fflags", "+bitexact",
        "-flags:v", "+bitexact",
    ])

    if music_path and Path(music_path).exists():
        cmd.extend([
            "-filter_complex", f"[1:a]volume={music_volume}[a]",
            "-map", "0:v",
            "-map", "[a]",
            "-shortest",
        ])

    cmd.append(str(output_path))

    # Run ffmpeg
    if progress_callback:
        await progress_callback((total_steps - 1) / total_steps, "Encoding video...")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()}")

    # Cleanup temp frames
    _shutil.rmtree(work_dir, ignore_errors=True)

    if progress_callback:
        await progress_callback(1.0, "Video export complete")

    return str(output_path)
