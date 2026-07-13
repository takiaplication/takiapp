"""
pipeline_router.py
==================
Global auto-pipeline for ReelFactory.

POST /pipeline          — submit 1-10 URLs; creates projects, queues them.
POST /projects/{id}/pipeline/retry  — retry a failed project.
POST /projects/{id}/approve         — "Good to go"; triggers export + library.

Projects run ONE AT A TIME in the order they were submitted.
"""

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import PROJECTS_DIR
from database import get_db
from services.job_manager import job_manager

router = APIRouter(tags=["pipeline"])

# ── Global single-project queue ────────────────────────────────────────────────
_queue: asyncio.Queue[str] = asyncio.Queue()
_worker_task: Optional[asyncio.Task] = None

# Hard guarantee: only one _run_pipeline may execute at a time, regardless of
# how many worker tasks exist or how _ensure_worker is called.
_pipeline_lock = asyncio.Lock()

# Set of project IDs that are already in the queue (prevents duplicates).
_queued_ids: set[str] = set()


def _ensure_worker() -> None:
    """Lazily start the background queue worker.
    Safe to call multiple times — only one worker task is ever alive."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_queue_worker())


async def _safe_enqueue(project_id: str) -> None:
    """Add project_id to the queue only if it is not already queued or processing."""
    if project_id not in _queued_ids:
        _queued_ids.add(project_id)
        await _queue.put(project_id)


async def _set_status(
    project_id: str,
    status: str,
    step: str = "",
    error: str = "",
) -> None:
    db = await get_db()
    try:
        await db.execute(
            """UPDATE projects
               SET status=?, pipeline_step=?, pipeline_error=?,
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (status, step or None, error or None, project_id),
        )
        await db.commit()
    finally:
        await db.close()


# ── Autonomous quality gate ───────────────────────────────────────────────────

async def validate_project_for_publish(project_id: str) -> list[str]:
    """
    Automated pre-publish checks for hands-off mode. Returns a list of
    human-readable issues; empty list means the project is safe to export
    and post without a human looking at it.

    Checks:
      1. At least one active slide.
      2. No empty DM slides — every active dm slide has ≥1 message with
         actual text (an empty screen is the #1 failure mode of OCR).
      3. No blank messages — no active dm slide where >half the messages
         are empty strings.
      4. Story replies have a story photo that exists on disk (single-use
         pool may have run dry).
      5. Meme slides can be filled: either a remembered meme_source_path
         exists or their category folder has at least one file.
    """
    from config import MEME_LIBRARY_DIR  # noqa: PLC0415

    issues: list[str] = []
    db = await get_db()
    try:
        slides = await (await db.execute(
            """SELECT id, frame_type, meme_category, meme_source_path
               FROM slides WHERE project_id=? AND is_active=1
               ORDER BY sort_order""",
            (project_id,),
        )).fetchall()

        if not slides:
            return ["geen actieve slides"]

        for idx, s in enumerate(slides, start=1):
            ftype = (s["frame_type"] if "frame_type" in s.keys() else "dm") or "dm"

            if ftype == "dm":
                msgs = await (await db.execute(
                    """SELECT text, message_type, story_image_path
                       FROM messages WHERE slide_id=? ORDER BY sort_order""",
                    (s["id"],),
                )).fetchall()
                texted = [m for m in msgs if (m["text"] or "").strip()]
                if not msgs or not texted:
                    issues.append(f"slide {idx}: leeg DM-scherm (geen tekst)")
                elif len(texted) < len(msgs) / 2:
                    issues.append(f"slide {idx}: meer dan de helft van de berichten is leeg")
                for m in msgs:
                    if m["message_type"] == "story_reply":
                        sp = m["story_image_path"]
                        if not sp or not Path(sp).exists():
                            issues.append(
                                f"slide {idx}: story-reply zonder story-foto "
                                "(story-library leeg? vul aan via Assets)"
                            )
                            break

            elif ftype == "meme":
                stored = s["meme_source_path"] if "meme_source_path" in s.keys() else None
                if stored and Path(stored).exists():
                    continue
                cat = (s["meme_category"] if "meme_category" in s.keys() else None) or "cooking"
                cat_dir = MEME_LIBRARY_DIR / cat
                has_files = cat_dir.exists() and any(
                    f.is_file() for f in cat_dir.iterdir()
                )
                if not has_files:
                    issues.append(f"slide {idx}: meme-categorie '{cat}' is leeg")
    finally:
        await db.close()

    return issues


async def autoclean_empty_dm_slides(project_id: str) -> int:
    """
    Delete DM slides that carry no visible text — blank chat screens left
    behind when OCR found nothing on a frame. Meme / app_ad slides are
    image-based and never removed. Messages cascade-delete with the slide.
    Returns the number of slides removed.

    This is what keeps the factory fully hands-off: instead of parking a
    video with an empty screen in Review for a human to fix, we simply drop
    the empty screen and carry on.
    """
    db = await get_db()
    try:
        slides = await (await db.execute(
            "SELECT id, frame_type, slide_type FROM slides WHERE project_id=?",
            (project_id,),
        )).fetchall()

        removed = 0
        for s in slides:
            ftype = (s["frame_type"] if "frame_type" in s.keys() else None) \
                or (s["slide_type"] if "slide_type" in s.keys() else None) or "dm"
            if ftype != "dm":
                continue  # keep image slides (meme / app_ad)
            msgs = await (await db.execute(
                "SELECT text FROM messages WHERE slide_id=?", (s["id"],)
            )).fetchall()
            has_text = any((m["text"] or "").strip() for m in msgs)
            if not has_text:
                await db.execute("DELETE FROM slides WHERE id=?", (s["id"],))
                removed += 1

        if removed:
            await db.commit()
        return removed
    finally:
        await db.close()


# ── Full pipeline for one project ─────────────────────────────────────────────

async def _run_pipeline(project_id: str) -> None:
    """Download → extract frames → OCR/translate/app_ad → status='review'."""
    from services.downloader import download_video           # noqa: PLC0415
    from routers.import_router import (                      # noqa: PLC0415
        run_extract_pipeline,
        run_ocr_pipeline,
    )

    # ── Load project ────────────────────────────────────────────────────────
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT source_url, video_path FROM projects WHERE id=?", (project_id,)
        )).fetchone()
    finally:
        await db.close()

    if not row:
        return

    url = row["source_url"]
    video_path = row["video_path"] if "video_path" in row.keys() else None

    # ── STEP 1: Download video ───────────────────────────────────────────────
    if not video_path or not Path(video_path).exists():
        await _set_status(project_id, "processing", "Video downloaden…")
        try:
            async def _noop(p: float, msg: str) -> None: pass
            video_path = await download_video(url, project_id, _noop)
            db2 = await get_db()
            try:
                await db2.execute(
                    "UPDATE projects SET video_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (video_path, project_id),
                )
                await db2.commit()
            finally:
                await db2.close()
        except Exception as exc:
            await _set_status(project_id, "error", "Video downloaden…", str(exc))
            return

    # ── STEP 2-6: Extract + classify frames ────────────────────────────────
    await _set_status(project_id, "processing", "Frames extraheren & classificeren…")
    try:
        step_pct = 0.0

        async def _extract_progress(p: float, msg: str) -> None:
            nonlocal step_pct
            step_pct = p
            # Update step message on major milestones only (reduce DB writes)
            if abs(p - round(p, 1)) < 0.01:
                await _set_status(project_id, "processing", f"Frames: {msg[:80]}")

        await run_extract_pipeline(project_id, video_path, _extract_progress)
    except Exception as exc:
        await _set_status(project_id, "error", "Frames extraheren…", str(exc))
        return

    # ── STEP 7-10: OCR, dedup, translate, app_ad ───────────────────────────
    await _set_status(project_id, "processing", "Tekst lezen & vertalen…")
    try:
        async def _ocr_progress(p: float, msg: str) -> None:
            if abs(p - round(p, 1)) < 0.01:
                await _set_status(project_id, "processing", f"OCR: {msg[:80]}")

        await run_ocr_pipeline(project_id, _ocr_progress)
    except Exception as exc:
        await _set_status(project_id, "error", "OCR & vertaling…", str(exc))
        return

    # ── Auto-clean: verwijder lege screens (DM-slides zonder tekst) ────────
    try:
        removed = await autoclean_empty_dm_slides(project_id)
        if removed:
            print(f"[autoclean] {project_id}: {removed} leeg screen verwijderd")
    except Exception as clean_err:
        print(f"[autoclean] {project_id}: mislukt: {clean_err}")

    # ── Story photo: one per video, single-use, identical across slides ────
    try:
        from routers.story_library_router import claim_story_photo  # noqa: PLC0415
        db_st = await get_db()
        try:
            has_story = await (await db_st.execute(
                """SELECT 1 FROM messages m
                   JOIN slides s ON s.id = m.slide_id
                   WHERE s.project_id=? AND m.message_type='story_reply'
                   LIMIT 1""",
                (project_id,),
            )).fetchone()
        finally:
            await db_st.close()
        if has_story:
            await claim_story_photo(project_id)
    except Exception as story_err:
        print(f"[story] claim failed for {project_id}: {story_err}")

    # ── Done — move to Review (or straight to export with AUTO_APPROVE=1) ──
    import os  # noqa: PLC0415
    if os.getenv("AUTO_APPROVE") == "1":
        # Hands-off mode: NO human in the loop. Empty screens are already
        # deleted above, so we don't park anything in Review. The only thing
        # that can stop a video is having literally nothing left to show —
        # then it goes to 'error' (a human "good to go" couldn't fix that
        # anyway), never to Review.
        db_cnt = await get_db()
        try:
            cnt = await (await db_cnt.execute(
                "SELECT COUNT(*) AS c FROM slides WHERE project_id=? AND is_active=1",
                (project_id,),
            )).fetchone()
        finally:
            await db_cnt.close()
        if not cnt or cnt["c"] == 0:
            await _set_status(
                project_id, "error", "Geen bruikbare slides",
                "Alle screens waren leeg na OCR — niets om te posten.",
            )
            return

        await _set_status(project_id, "approved", "Video exporteren… (auto)")
        from routers.compositor import _start_export_job  # noqa: PLC0415
        export_job_id = await _start_export_job(project_id)
        # Strictly sequential factory: hold the pipeline lock until this
        # video is fully exported, uploaded to Post Bridge and wiped from
        # disk. Only then may the queue worker pick up the next project —
        # so at any moment at most ONE project exists beyond the queue.
        await job_manager.wait(export_job_id)
    else:
        await _set_status(project_id, "review", "Klaar voor review")


# ── Queue worker ───────────────────────────────────────────────────────────────

async def _queue_worker() -> None:
    """Process projects strictly one at a time from the queue."""
    while True:
        project_id = await _queue.get()
        _queued_ids.discard(project_id)
        try:
            # _pipeline_lock ensures that even if a second worker task were
            # ever started by accident, it cannot begin processing until the
            # current project is fully finished.
            async with _pipeline_lock:
                await _run_pipeline(project_id)
        except Exception:
            pass  # errors already handled inside _run_pipeline
        finally:
            _queue.task_done()


# ── Endpoints ──────────────────────────────────────────────────────────────────

class PipelineSubmitRequest(BaseModel):
    urls: List[str]


@router.post("/pipeline")
async def submit_pipeline(body: PipelineSubmitRequest):
    """
    Accept 1-10 URLs. Creates one project per URL, sets status='queue',
    and enqueues them for sequential processing.
    Returns the list of created project IDs.
    """
    if not body.urls:
        raise HTTPException(status_code=400, detail="At least one URL required")
    if len(body.urls) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 URLs per submission")

    created = []

    for url in body.urls:
        url = url.strip()
        if not url:
            continue

        project_id = str(uuid.uuid4())
        project_dir = PROJECTS_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "rendered").mkdir(exist_ok=True)
        (project_dir / "memes").mkdir(exist_ok=True)

        name = datetime.now().strftime("%Y-%m-%d %H:%M")

        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO projects (id, name, status, source_url, pipeline_step)
                   VALUES (?, ?, 'queue', ?, 'In wachtrij…')""",
                (project_id, name, url),
            )
            await db.execute(
                "INSERT INTO render_settings (project_id) VALUES (?)",
                (project_id,),
            )
            await db.commit()
        finally:
            await db.close()

        await _safe_enqueue(project_id)
        created.append(project_id)

    _ensure_worker()

    return {"project_ids": created, "queued": len(created)}


@router.post("/projects/{project_id}/pipeline/retry")
async def retry_pipeline(project_id: str):
    """Re-queue a failed (error) project for another pipeline run."""
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT status FROM projects WHERE id=?", (project_id,)
        )).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
    finally:
        await db.close()

    # Refuse to re-queue if already in queue or actively processing —
    # this prevents duplicate entries and parallel processing.
    if row["status"] in ("queue", "processing"):
        raise HTTPException(
            status_code=409,
            detail="Project is already queued or processing",
        )

    await _set_status(project_id, "queue", "In wachtrij (opnieuw)…", "")
    await _safe_enqueue(project_id)
    _ensure_worker()
    return {"ok": True}


@router.post("/projects/{project_id}/approve")
async def approve_project(project_id: str):
    """
    User clicked 'Good to go'. Marks project as 'approved' and
    automatically starts the video export. When export finishes,
    the compositor sets status='library'.
    """
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT status FROM projects WHERE id=?", (project_id,)
        )).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
    finally:
        await db.close()

    await _set_status(project_id, "approved", "Video exporteren…")

    # Trigger export via compositor (returns job_id which we ignore here —
    # the compositor will set status='library' on completion).
    from routers.compositor import _start_export_job  # noqa: PLC0415
    await _start_export_job(project_id)

    return {"ok": True}


@router.post("/projects/{project_id}/reexport")
async def reexport_project(project_id: str):
    """
    Manually re-trigger export for a project stuck in 'approved' state.
    Useful when the server was restarted mid-export.
    """
    from pathlib import Path  # noqa: PLC0415
    from config import PROJECTS_DIR  # noqa: PLC0415
    from routers.compositor import _start_export_job  # noqa: PLC0415

    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT status FROM projects WHERE id=?", (project_id,)
        )).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
    finally:
        await db.close()

    # Reset error state and restart export
    await _set_status(project_id, "approved", "Video exporteren… (herstart)", "")
    await _start_export_job(project_id)
    return {"ok": True}


@router.post("/projects/{project_id}/regenerate")
async def regenerate_project(project_id: str):
    """
    Rebuild the MP4 for a library project from its stored state.
    No source video required — reuses slides, messages, meme picks, and
    render settings straight from the database.

    Steps:
      1. Clear rendered_path on every slide so Playwright / meme renders fresh.
      2. Regenerate each app_ad slide's source PNG (cleanup deleted them once
         the project was safely uploaded to Drive).
      3. Clear drive_url and pipeline_error so the new export gets a fresh
         Drive link and a clean status line.
      4. Flip status back to 'approved' and submit the export job.
    """
    from routers.compositor import _start_export_job  # noqa: PLC0415
    from routers.import_router import rerender_appad_slide  # noqa: PLC0415

    db = await get_db()
    try:
        proj = await (await db.execute(
            "SELECT status FROM projects WHERE id=?", (project_id,)
        )).fetchone()
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
    finally:
        await db.close()

    # Only library projects are regenerable — everything else is still editable
    # and has its own flow (approve, re-export, etc.).
    if proj["status"] != "library":
        raise HTTPException(
            status_code=409,
            detail=f"Only library projects can be regenerated (current status: {proj['status']})",
        )

    # ── Step 1: clear stale rendered paths so everything re-renders fresh ──
    db = await get_db()
    try:
        await db.execute(
            "UPDATE slides SET rendered_path=NULL WHERE project_id=?",
            (project_id,),
        )
        await db.commit()
    finally:
        await db.close()

    # ── Step 2: regenerate every app_ad slide's source PNG ────────────────
    db = await get_db()
    try:
        appad_slides = await (await db.execute(
            """SELECT id FROM slides
               WHERE project_id=? AND frame_type='app_ad' AND is_active=1
               ORDER BY sort_order""",
            (project_id,),
        )).fetchall()
    finally:
        await db.close()

    for s in appad_slides:
        try:
            await rerender_appad_slide(project_id, s["id"])
        except ValueError as exc:
            # A single bad app_ad should not block regeneration —
            # the export will raise its own clear error if truly needed.
            print(f"[regenerate] skipping app_ad {s['id']}: {exc}")

    # ── Step 3: clear drive_url + error so the new export starts clean ────
    db = await get_db()
    try:
        await db.execute(
            """UPDATE projects
               SET drive_url=NULL, pipeline_error=NULL,
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (project_id,),
        )
        await db.commit()
    finally:
        await db.close()

    # ── Step 4: flip to approved + start export ───────────────────────────
    await _set_status(project_id, "approved", "Video regenereren…", "")
    await _start_export_job(project_id)

    return {"ok": True}
