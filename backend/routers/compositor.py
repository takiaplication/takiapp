import asyncio
import random
import shutil
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from database import get_db
from config import PROJECTS_DIR, MEME_LIBRARY_DIR

# ── Global export serialization ────────────────────────────────────────────
# Only ONE export may actually run at a time. Rendering every slide through
# Playwright + ffmpeg is CPU/RAM-heavy enough that running two in parallel
# risks OOM kills and disk exhaustion (each export writes ~100-200 MB of
# intermediates). Approve-clicks on multiple projects enqueue behind this
# lock; the UI shows "Wachten op andere export…" for the ones that are
# waiting.
_EXPORT_LOCK = asyncio.Lock()


def _wipe_targets(project_dir: Path, names: list[str]) -> int:
    """Remove the given files/folders under project_dir. Returns bytes freed."""
    freed = 0
    for name in names:
        t = project_dir / name
        try:
            if t.is_file():
                freed += t.stat().st_size
                t.unlink()
            elif t.is_dir():
                for p in t.rglob("*"):
                    if p.is_file():
                        try:
                            freed += p.stat().st_size
                        except OSError:
                            pass
                shutil.rmtree(t, ignore_errors=True)
        except Exception as exc:
            print(f"[cleanup] {project_dir.name}: could not remove {t.name}: {exc}")
    return freed


# Heavy intermediates that are useless once the MP4 is built. These are wiped
# right after export finishes — success OR failure — so disk usage stays flat
# even when Drive uploads are broken.
_POST_EXPORT_INTERMEDIATES = [
    "source.mp4",   # downloaded video, 10–50 MB
    "frames",       # one frame per 500 ms, ~30 MB
    "rendered",     # per-slide PNGs, ~25 MB
    "memes",        # per-slide uploaded meme images
    "transitions",  # pre-rendered crossfade frames
]


def cleanup_project_intermediates(project_id: str) -> int:
    """
    Delete the heavy intermediates (source.mp4, frames/, rendered/, memes/,
    transitions/) for a single project. Keeps output.mp4 + thumbnail.jpg.
    Safe to call multiple times; no-op on missing files.
    Returns the number of bytes freed.
    """
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        return 0
    return _wipe_targets(project_dir, _POST_EXPORT_INTERMEDIATES)


def cleanup_project_output(project_id: str) -> int:
    """Delete output.mp4 for a single project (only call after Drive succeeded)."""
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        return 0
    return _wipe_targets(project_dir, ["output.mp4"])


def sweep_all_intermediates(skip_project_id: Optional[str] = None) -> dict:
    """
    Emergency volume-cleanup sweep. Does three things:

      1. Deletes every project folder on disk whose ID is NOT in the `projects`
         table any more (orphans left behind by partial deletes / crashes).
      2. For each project still in the DB: wipes intermediates
         (source.mp4, frames/, rendered/, memes/, transitions/).
      3. For each project that already has drive_url set: wipes output.mp4
         too (it's safely in Drive, no reason to keep the local copy).

    The currently-processing project (passed via skip_project_id) is left
    completely alone so a live export can't have files yanked out from under
    it.

    Returns diagnostic counts for the UI.
    """
    import sqlite3
    from config import DATABASE_PATH  # noqa: PLC0415

    if not PROJECTS_DIR.exists():
        return {
            "freed_bytes": 0,
            "projects_cleaned": 0,
            "orphans_removed": 0,
            "outputs_removed": 0,
        }

    # ── Read the DB synchronously — we're inside asyncio.to_thread ──────
    known_ids: set[str] = set()
    uploaded_ids: set[str] = set()
    try:
        conn = sqlite3.connect(str(DATABASE_PATH))
        try:
            cur = conn.execute("SELECT id, drive_url FROM projects")
            for row in cur.fetchall():
                pid = row[0]
                known_ids.add(pid)
                if row[1]:
                    uploaded_ids.add(pid)
        finally:
            conn.close()
    except Exception as exc:
        print(f"[sweep] could not read DB ({exc}); falling back to 'keep all'")
        # If we can't read the DB, be conservative — don't delete any folder.
        known_ids = {d.name for d in PROJECTS_DIR.iterdir() if d.is_dir()}

    freed = 0
    touched = 0
    orphans = 0
    outputs = 0

    for d in PROJECTS_DIR.iterdir():
        if not d.is_dir():
            continue
        if skip_project_id and d.name == skip_project_id:
            continue

        # ── (1) Orphan folder: nuke the whole thing ──────────────────────
        if d.name not in known_ids:
            try:
                total = 0
                for p in d.rglob("*"):
                    if p.is_file():
                        try:
                            total += p.stat().st_size
                        except OSError:
                            pass
                shutil.rmtree(d, ignore_errors=True)
                freed += total
                orphans += 1
                print(f"[sweep] removed orphan folder {d.name} ({total // (1024*1024)} MB)")
            except Exception as exc:
                print(f"[sweep] failed to remove orphan {d.name}: {exc}")
            continue

        # ── (2) Known project: wipe intermediates ────────────────────────
        got = _wipe_targets(d, _POST_EXPORT_INTERMEDIATES)
        if got:
            touched += 1
            freed += got

        # ── (3) Already in Drive: wipe local output.mp4 too ──────────────
        if d.name in uploaded_ids:
            got_out = _wipe_targets(d, ["output.mp4"])
            if got_out:
                outputs += 1
                freed += got_out

    return {
        "freed_bytes": freed,
        "projects_cleaned": touched,
        "orphans_removed": orphans,
        "outputs_removed": outputs,
    }
from services.job_manager import job_manager
from services.video_compositor import compose_video
from services.dm_renderer import renderer
from routers.renderer import _build_conversation_for_slide

router = APIRouter(tags=["compositor"])


async def _start_export_job(project_id: str) -> str:
    """
    Core export helper — creates the job, submits it, returns job_id.
    Callable from pipeline_router (approve) as well as the HTTP endpoint.
    On success sets project status='library'.
    """
    job_id = await job_manager.create_job(project_id, "export")

    async def do_export(progress_callback):
        from PIL import Image, ImageOps

        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM slides WHERE project_id=? AND is_active=1 ORDER BY sort_order",
                (project_id,),
            )
            slide_rows = await cursor.fetchall()

            cursor = await db.execute(
                "SELECT * FROM render_settings WHERE project_id=?", (project_id,)
            )
            settings = dict(await cursor.fetchone())
        finally:
            await db.close()

        if not slide_rows:
            raise ValueError("No active slides to export")

        rendered_dir = PROJECTS_DIR / project_id / "rendered"
        rendered_dir.mkdir(exist_ok=True)

        total = len(slide_rows)
        slides = []

        for i, r in enumerate(slide_rows):
            await progress_callback(i / total * 0.8, f"Preparing slide {i + 1}/{total}…")

            rendered_path = r["rendered_path"] if r["rendered_path"] else None
            frame_type = r["frame_type"] if "frame_type" in r.keys() else "dm"

            if rendered_path and Path(rendered_path).exists():
                # Already rendered — use as-is
                out_path = rendered_path

            elif frame_type == "meme":
                # ── Meme slide ────────────────────────────────────────────
                # Prefer the file that was picked last time (stored in
                # meme_source_path). This makes "Regenerate video" deterministic
                # even after the local rendered PNG was cleaned up. If no prior
                # choice exists, pick a random file from the category and
                # remember it for next time.
                cat     = r["meme_category"] if "meme_category" in r.keys() and r["meme_category"] else "cooking"
                cat_dir = MEME_LIBRARY_DIR / cat
                _video_exts = {".mp4", ".mov", ".avi", ".webm"}
                _img_exts   = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
                _all_exts   = _video_exts | _img_exts

                stored_source = r["meme_source_path"] if "meme_source_path" in r.keys() else None
                if stored_source and Path(stored_source).exists():
                    source = stored_source
                else:
                    candidates  = [
                        f for f in cat_dir.iterdir()
                        if f.is_file() and f.suffix.lower() in _all_exts
                    ] if cat_dir.exists() else []
                    if not candidates:
                        raise ValueError(
                            f"Meme library folder '{cat}' is empty or missing. "
                            f"Add files to {cat_dir}"
                        )
                    source = str(random.choice(candidates))
                    # Remember the pick so regenerate produces the same result.
                    db_mm = await get_db()
                    try:
                        await db_mm.execute(
                            "UPDATE slides SET meme_source_path=? WHERE id=?",
                            (source, r["id"]),
                        )
                        await db_mm.commit()
                    finally:
                        await db_mm.close()

                def _render_image_meme(src: str, dst: str) -> None:
                    """Scale to full 1080 px width; black bars top/bottom only."""
                    img = Image.open(src).convert("RGB")
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
                    canvas.save(dst)

                is_video_meme = Path(source).suffix.lower() in _video_exts
                if is_video_meme:
                    out_path = source          # pass raw video through; composer reads duration
                else:
                    out_path = str(rendered_dir / f"meme_{r['id']}.png")
                    await asyncio.to_thread(_render_image_meme, source, out_path)
                    db2 = await get_db()
                    try:
                        await db2.execute(
                            "UPDATE slides SET rendered_path=? WHERE id=?", (out_path, r["id"])
                        )
                        await db2.commit()
                    finally:
                        await db2.close()

            elif frame_type == "app_ad":
                # ── App-ad slide: use the captured source frame directly ──
                source = r["source_frame_path"] if "source_frame_path" in r.keys() else None
                if not source or not Path(source).exists():
                    raise ValueError(
                        f"Slide {r['id']} (app_ad) has no source frame. "
                        "Open the Frames step and upload your image."
                    )

                def _render_image_meme(src: str, dst: str) -> None:  # noqa: F811
                    """Scale to full 1080 px width; black bars top/bottom only."""
                    img = Image.open(src).convert("RGB")
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
                    canvas.save(dst)

                is_video_meme = Path(source).suffix.lower() in {".mp4", ".mov", ".avi", ".webm"}
                if is_video_meme:
                    out_path = source
                else:
                    out_path = str(rendered_dir / f"appad_{r['id']}.png")
                    await asyncio.to_thread(_render_image_meme, source, out_path)
                    db2 = await get_db()
                    try:
                        await db2.execute(
                            "UPDATE slides SET rendered_path=? WHERE id=?", (out_path, r["id"])
                        )
                        await db2.commit()
                    finally:
                        await db2.close()

            else:
                # DM slide: render via Playwright with per-slide jitter
                from services.dm_renderer import _make_jitter  # noqa: PLC0415
                conversation = await _build_conversation_for_slide(project_id, r["id"])
                png_bytes = await renderer.render_slide(
                    conversation,
                    jitter=_make_jitter(conversation.theme),
                )
                # Use slide UUID so filenames never collide across re-exports
                out_path = str(rendered_dir / f"slide_{r['id']}.png")
                Path(out_path).write_bytes(png_bytes)

                db2 = await get_db()
                try:
                    await db2.execute(
                        "UPDATE slides SET rendered_path=? WHERE id=?", (out_path, r["id"])
                    )
                    await db2.commit()
                finally:
                    await db2.close()

            slides.append({
                "path":             out_path,
                "hold_duration_ms": r["hold_duration_ms"],
                "is_video":         frame_type in ("meme", "app_ad") and Path(out_path).suffix.lower() in {".mp4", ".mov", ".avi", ".webm"},
            })

        output_path = PROJECTS_DIR / project_id / "output.mp4"

        async def _compose_progress(p: float, msg: str) -> None:
            await progress_callback(0.8 + p * 0.2, msg)

        await compose_video(
            slides=slides,
            output_path=output_path,
            transition_type=settings["transition_type"],
            transition_duration_ms=settings["transition_duration_ms"],
            fps=settings["output_fps"],
            music_path=settings.get("background_music_path"),
            music_volume=settings["music_volume"],
            screen_recording_effect=True,   # always on — anti TikTok fingerprinting
            progress_callback=_compose_progress,
        )

        # Extract first-frame thumbnail from the finished MP4
        thumb_path = str(PROJECTS_DIR / project_id / "thumbnail.jpg")
        try:
            thumb_proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", str(output_path),
                "-vframes", "1",
                "-q:v", "3",
                thumb_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await thumb_proc.wait()
            if not Path(thumb_path).exists():
                thumb_path = None  # ffmpeg failed silently — carry on
        except Exception:
            thumb_path = None

        # ── Free disk space NOW — intermediates are dead weight once the
        #     output MP4 is on disk. We do this BEFORE Drive upload so even a
        #     Drive failure can't leave 100+ MB of garbage behind. Only
        #     output.mp4 + thumbnail.jpg survive this step.
        freed_early = await asyncio.to_thread(cleanup_project_intermediates, project_id)
        if freed_early:
            print(f"[cleanup] {project_id}: freed {freed_early // (1024*1024)} MB post-export")

        # ── Google Drive upload ───────────────────────────────────────────
        await progress_callback(0.97, "Uploaden naar Google Drive…")
        drive_url: Optional[str] = None
        drive_error: Optional[str] = None
        try:
            from services.drive_uploader import upload_to_drive, DriveUploadError  # noqa: PLC0415
            project_name = project_id[:8]
            # Fetch the project name for a nicer filename
            db_name = await get_db()
            try:
                name_row = await (await db_name.execute(
                    "SELECT name FROM projects WHERE id=?", (project_id,)
                )).fetchone()
                if name_row and name_row["name"]:
                    project_name = name_row["name"].replace("/", "-")[:60]
            finally:
                await db_name.close()

            today = __import__("datetime").date.today().strftime("%Y-%m-%d")
            filename = f"{today}_{project_name}.mp4"
            try:
                drive_url = await upload_to_drive(output_path, filename)
            except DriveUploadError as de:
                drive_error = str(de)
                print(f"[drive] upload FAILED: {drive_error}")

            if drive_url:
                # Drive has the MP4 — drop the local copy too.
                await asyncio.to_thread(cleanup_project_output, project_id)
                await progress_callback(0.99, f"Drive upload klaar → {drive_url}")
            elif drive_error:
                # Keep the local MP4 as a fallback so the user can still
                # download it while they sort out the Drive configuration.
                await progress_callback(0.99, "Drive upload mislukt — MP4 bewaard")
        except Exception as drive_err:
            # Defensive — should rarely trigger since DriveUploadError is
            # already caught above. Keep the MP4 so the user isn't stuck.
            drive_error = f"Unexpected Drive error: {drive_err}"
            print(f"[drive] unexpected error (non-fatal): {drive_err}")

        # Mark project as 'library' once export succeeds.
        # If Drive failed we still park the project in the Library column so
        # the user can manage it, but we surface the error via pipeline_error.
        db_done = await get_db()
        try:
            await db_done.execute(
                """UPDATE projects SET status='library',
                   pipeline_step=?, pipeline_error=?,
                   thumbnail_path=?, drive_url=?,
                   updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (
                    "Export klaar" if not drive_error else "Drive upload mislukt",
                    drive_error,
                    thumb_path,
                    drive_url,
                    project_id,
                ),
            )
            await db_done.commit()
        finally:
            await db_done.close()

        return drive_url or str(output_path)

    async def do_export_with_error_capture(progress_callback):
        # If another export is already running, mark this one as waiting
        # in the UI. The `async with _EXPORT_LOCK` below is what actually
        # serializes — the status update is just so the user knows why
        # nothing is happening yet.
        if _EXPORT_LOCK.locked():
            wait_db = await get_db()
            try:
                await wait_db.execute(
                    """UPDATE projects SET pipeline_step=?, pipeline_error=NULL,
                       updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    ("Wachten op andere export…", project_id),
                )
                await wait_db.commit()
            finally:
                await wait_db.close()
            await progress_callback(0.0, "Wachten op andere export…")

        try:
            async with _EXPORT_LOCK:
                await progress_callback(0.0, "Export start…")
                return await do_export(progress_callback)
        except Exception as exc:
            # Clean up partial intermediates so a failed export doesn't hoard
            # disk space forever. This is the single most important line for
            # keeping the Railway volume from filling up on repeated ENOSPC /
            # OOM / Playwright failures.
            try:
                freed = await asyncio.to_thread(cleanup_project_intermediates, project_id)
                if freed:
                    print(f"[cleanup] {project_id}: freed {freed // (1024*1024)} MB after export failure")
            except Exception as cleanup_err:
                print(f"[cleanup] post-failure cleanup errored: {cleanup_err}")

            # Keep status='approved' so the card stays in the Approved column —
            # we never want to redo the full pipeline (download/OCR/etc.) just
            # because the export step failed. The user can retry export from
            # the card's "Opnieuw exporteren" button.
            err_db = await get_db()
            try:
                await err_db.execute(
                    """UPDATE projects SET status='approved', pipeline_step='Export mislukt',
                       pipeline_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (str(exc), project_id),
                )
                await err_db.commit()
            finally:
                await err_db.close()
            raise

    await job_manager.submit(job_id, do_export_with_error_capture)
    return job_id


@router.post("/projects/{project_id}/export")
async def export_video(project_id: str):
    """Start video composition. Auto-renders missing DM/meme slides. Returns job_id."""
    job_id = await _start_export_job(project_id)
    return {"job_id": job_id}


@router.get("/projects/{project_id}/export/download")
async def download_video(project_id: str):
    output_path = PROJECTS_DIR / project_id / "output.mp4"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Export not found. Run export first.")
    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=f"reelfactory_{project_id[:8]}.mp4",
    )


@router.post("/admin/cleanup-volume")
async def admin_cleanup_volume():
    """
    Emergency volume cleanup. Three-phase sweep:
      1. Remove whole project folders whose ID is no longer in the DB
         (orphans left behind by partial deletes / crashes).
      2. Wipe heavy intermediates (source.mp4, frames/, rendered/, memes/,
         transitions/) for every remaining project.
      3. Wipe output.mp4 for every project with drive_url set (safely in
         Drive already).
    output.mp4 + thumbnail.jpg are preserved for projects without Drive.
    Safe to hit even while projects are processing.
    """
    result = await asyncio.to_thread(sweep_all_intermediates, None)
    return {
        "ok": True,
        "freed_mb": result["freed_bytes"] // (1024 * 1024),
        "projects_cleaned": result["projects_cleaned"],
        "orphans_removed": result["orphans_removed"],
        "outputs_removed": result["outputs_removed"],
    }
