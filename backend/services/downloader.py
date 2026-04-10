import asyncio
import shutil
from pathlib import Path
from typing import Optional, Callable

from config import PROJECTS_DIR

# Prefer the Homebrew-managed binary (kept up to date by `brew upgrade`).
# Fall back to whatever is on PATH if the Homebrew path doesn't exist.
_HOMEBREW_YTDLP = "/opt/homebrew/bin/yt-dlp"
_YTDLP = _HOMEBREW_YTDLP if Path(_HOMEBREW_YTDLP).exists() else "yt-dlp"


async def download_video(
    url: str,
    project_id: str,
    progress_callback: Optional[Callable] = None,
) -> str:
    """
    Download a video with yt-dlp and return the absolute path to source.mp4.

    Instagram-specific options are included by default:
      • Reads cookies from Chrome so private / stories / reels content works.
      • Falls back gracefully if the browser cookie read fails.
      • Captures stderr so the real error is included in the exception.
    """
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    final_path = project_dir / "source.mp4"
    output_template = str(project_dir / "source.%(ext)s")

    # Remove any stale source file from a previous attempt
    for suffix in (".mp4", ".mkv", ".webm", ".avi", ".mov"):
        stale = project_dir / f"source{suffix}"
        if stale.exists():
            stale.unlink()

    cmd = [
        _YTDLP,
        "--no-playlist",
        # Best MP4+audio; fall back to any best quality
        "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        # Instagram / TikTok need cookies from the browser for private content
        "--cookies-from-browser", "chrome",
        # Spoof a real browser user-agent (Instagram blocks yt-dlp defaults)
        "--user-agent",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36",
        "--add-header", "Accept-Language:nl-NL,nl;q=0.9,en;q=0.8",
        "--output", output_template,
        "--newline",       # one progress line per stdout flush — easy to parse
        "--no-warnings",
        url,
    ]

    if progress_callback:
        await progress_callback(0.0, "Starting download…")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,   # capture separately so it's in the error
    )

    # Read stdout for progress, accumulate stderr for error reporting
    stderr_lines: list[str] = []

    async def _read_stderr():
        async for raw in process.stderr:
            stderr_lines.append(raw.decode("utf-8", errors="replace").rstrip())

    stderr_task = asyncio.create_task(_read_stderr())

    last_progress = 0.0
    async for raw in process.stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        if "[download]" in line and "%" in line:
            try:
                pct = float(line.split("%")[0].split()[-1]) / 100.0
                if pct > last_progress:
                    last_progress = pct
                    if progress_callback:
                        await progress_callback(
                            min(pct * 0.9, 0.9),
                            f"Downloading: {int(pct * 100)}%",
                        )
            except (ValueError, IndexError):
                pass

    await process.wait()
    await stderr_task

    if process.returncode != 0:
        # Try once more without --cookies-from-browser (works for public content)
        if "--cookies-from-browser" in cmd:
            if progress_callback:
                await progress_callback(0.0, "Retrying without browser cookies…")
            cmd_no_cookie = [
                a for a in cmd
                if a not in ("--cookies-from-browser", "chrome")
            ]
            process2 = await asyncio.create_subprocess_exec(
                *cmd_no_cookie,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stderr2: list[str] = []

            async def _read_stderr2():
                async for raw in process2.stderr:
                    stderr2.append(raw.decode("utf-8", errors="replace").rstrip())

            t2 = asyncio.create_task(_read_stderr2())
            async for raw in process2.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if "[download]" in line and "%" in line:
                    try:
                        pct = float(line.split("%")[0].split()[-1]) / 100.0
                        if pct > last_progress:
                            last_progress = pct
                            if progress_callback:
                                await progress_callback(
                                    min(pct * 0.9, 0.9),
                                    f"Downloading: {int(pct * 100)}%",
                                )
                    except (ValueError, IndexError):
                        pass

            await process2.wait()
            await t2

            if process2.returncode != 0:
                err_detail = "\n".join((stderr_lines + stderr2)[-20:]) or "(no output)"
                raise RuntimeError(
                    f"yt-dlp failed (exit {process2.returncode}).\n\n{err_detail}"
                )
        else:
            err_detail = "\n".join(stderr_lines[-20:]) or "(no output)"
            raise RuntimeError(
                f"yt-dlp failed (exit {process.returncode}).\n\n{err_detail}"
            )

    # Normalise to source.mp4
    for suffix in (".mp4", ".mkv", ".webm", ".avi", ".mov"):
        candidate = project_dir / f"source{suffix}"
        if candidate.exists() and candidate != final_path:
            shutil.move(str(candidate), str(final_path))
            break

    if not final_path.exists():
        raise RuntimeError("Downloaded file not found after yt-dlp finished")

    if progress_callback:
        await progress_callback(1.0, "Download complete")

    return str(final_path)
