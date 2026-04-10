import asyncio
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, File, UploadFile
from pydantic import BaseModel

from config import STORAGE_DIR, PROJECTS_DIR
from database import get_db
from services.downloader import download_video
from services.frame_extractor import extract_scenes
from services.frame_classifier import classify_frame_ai
from services.ocr_service import (
    ocr_frame, classify_sender, filter_message_blocks,
    extract_messages_vision,
)
from services.translation_service import batch_translate_conversation
from services.job_manager import job_manager


def _to_url_path(abs_path: Optional[str]) -> Optional[str]:
    """Convert an absolute storage path to a /files/... URL path."""
    if not abs_path:
        return None
    try:
        rel = Path(abs_path).relative_to(STORAGE_DIR)
        return f"/files/{rel.as_posix()}"
    except ValueError:
        return None

router = APIRouter(tags=["import"])


class ImportUrlRequest(BaseModel):
    url: str


class ExtractFramesRequest(BaseModel):
    pass  # threshold is fixed internally; every second of the video is inspected


class OcrRequest(BaseModel):
    translate_to: Optional[str] = "nl"   # always Dutch by default


class SetFrameTypeRequest(BaseModel):
    frame_type: str   # "dm" | "meme"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/import/url")
async def import_url(project_id: str, body: ImportUrlRequest):
    """Start a yt-dlp download job for the given URL."""
    db = await get_db()
    try:
        row = await (await db.execute("SELECT id FROM projects WHERE id=?", (project_id,))).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
    finally:
        await db.close()

    job_id = await job_manager.create_job(project_id, "import")

    async def _download(progress_callback, **_):
        video_path = await download_video(body.url, project_id, progress_callback)
        db2 = await get_db()
        try:
            await db2.execute(
                "UPDATE projects SET source_url=?, video_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (body.url, video_path, project_id),
            )
            await db2.commit()
        finally:
            await db2.close()
        return video_path

    await job_manager.submit(job_id, _download)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Frame extraction
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/import/extract-frames")
async def extract_frames(project_id: str, body: ExtractFramesRequest = ExtractFramesRequest()):
    """Extract scene keyframes from the downloaded video, classify each frame, and create slides."""
    db = await get_db()
    try:
        row = await (await db.execute("SELECT video_path FROM projects WHERE id=?", (project_id,))).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        video_path = row["video_path"] if "video_path" in row.keys() else None
    finally:
        await db.close()

    if not video_path or not Path(video_path).exists():
        raise HTTPException(status_code=400, detail="No video downloaded for this project yet")

    job_id = await job_manager.create_job(project_id, "extract_frames")

    async def _extract(progress_callback, **_):
        # ── STAGE 1 (0–40 %): capture one frame every 500 ms (2 fps) ─────────
        async def _prog1(p: float, msg: str):
            await progress_callback(p * 0.40, msg)

        raw_frames = await extract_scenes(
            video_path, project_id,
            progress_callback=_prog1,
        )
        await progress_callback(0.40, f"Stage 1 done — {len(raw_frames)} raw samples captured")

        # ── STAGE 2 (40–95 %): AI classify every frame ────────────────────────
        # No visual dedup — GPT-4o-mini sees all frames.
        # Text-fingerprint dedup runs later in the OCR step.
        await progress_callback(0.40, "Stage 2 — classifying all frames with AI…")
        classified: list[tuple[str, str]] = []

        for i, fp in enumerate(raw_frames):
            ftype = await classify_frame_ai(fp)
            classified.append((fp, ftype))
            await progress_callback(
                0.40 + 0.55 * (i + 1) / max(len(raw_frames), 1),
                f"Classified {i + 1}/{len(raw_frames)}: {ftype}",
            )

        await progress_callback(0.95, f"Stage 2 done — {len(classified)} frames classified")

        # ── STAGE 3 (95–99 %): collapse consecutive meme runs + dedup app_ad ──
        # - Consecutive meme frames → keep only the first as representative.
        # - app_ad → keep only the very first occurrence.
        # - DM frames → keep ALL (text dedup runs in the OCR step).
        collapsed: list[tuple[str, str]] = []
        in_meme_run = False
        app_ad_seen = False

        for fp, ftype in classified:
            if ftype == "meme":
                if not in_meme_run:
                    in_meme_run = True
                    collapsed.append((fp, "meme"))
                # else: continuation of current meme run → skip
            else:
                if in_meme_run:
                    in_meme_run = False
                if ftype == "app_ad":
                    if not app_ad_seen:
                        collapsed.append((fp, "app_ad"))
                        app_ad_seen = True
                else:  # dm
                    collapsed.append((fp, ftype))

        # Flush trailing meme run (video ends on a meme)
        # (already appended on entry; nothing extra needed)

        meme_slots   = sum(1 for _, t in collapsed if t == "meme")
        app_ad_slots = sum(1 for _, t in collapsed if t == "app_ad")
        dm_slots     = sum(1 for _, t in collapsed if t == "dm")
        await progress_callback(
            0.99,
            f"Collapsed → {dm_slots} DM + {meme_slots} meme + {app_ad_slots} app_ad = {len(collapsed)} total",
        )

        # ── STAGE 4 (99–100 %): single fast DB write ─────────────────────────
        db2 = await get_db()
        try:
            await db2.execute("DELETE FROM slides WHERE project_id=?", (project_id,))
            for i, (frame_path, ftype) in enumerate(collapsed):
                if ftype == "meme":
                    default_hold = 1500
                elif ftype == "app_ad":
                    default_hold = 1000
                else:  # dm
                    default_hold = 3000
                await db2.execute(
                    """INSERT INTO slides
                       (id, project_id, sort_order, slide_type, source_frame_path,
                        frame_type, is_active, hold_duration_ms)
                       VALUES (?, ?, ?, 'dm', ?, ?, 1, ?)""",
                    (str(uuid.uuid4()), project_id, i, frame_path, ftype, default_hold),
                )
            await db2.commit()
        finally:
            await db2.close()

        return {
            "raw_frames": len(raw_frames),
            "classified": len(classified),
            "collapsed":  len(collapsed),
        }

    await job_manager.submit(job_id, _extract)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Override frame type
# ---------------------------------------------------------------------------

@router.patch("/projects/{project_id}/slides/{slide_id}/frame-type")
async def set_frame_type(project_id: str, slide_id: str, body: SetFrameTypeRequest):
    """Manually override the frame_type classification for a single slide."""
    if body.frame_type not in ("dm", "meme", "app_ad"):
        raise HTTPException(status_code=400, detail="frame_type must be 'dm', 'meme', or 'app_ad'")
    db = await get_db()
    try:
        # Also clear any cached render — the new type may render completely differently
        await db.execute(
            "UPDATE slides SET frame_type=?, rendered_path=NULL WHERE id=? AND project_id=?",
            (body.frame_type, slide_id, project_id),
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Upload custom meme image / video for a meme slot
# ---------------------------------------------------------------------------

_ALLOWED_MEME_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".avi"}

@router.post("/projects/{project_id}/slides/{slide_id}/upload-meme")
async def upload_meme(project_id: str, slide_id: str, file: UploadFile = File(...)):
    """
    Upload a custom meme image or video for a meme slot.
    Saves the file, updates source_frame_path, clears any previously rendered path.
    """
    suffix = Path(file.filename or "meme.jpg").suffix.lower()
    if suffix not in _ALLOWED_MEME_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{suffix}'")

    memes_dir = PROJECTS_DIR / project_id / "memes"
    memes_dir.mkdir(parents=True, exist_ok=True)

    out_path = str(memes_dir / f"{slide_id}{suffix}")
    content = await file.read()
    Path(out_path).write_bytes(content)

    db = await get_db()
    try:
        await db.execute(
            "UPDATE slides SET source_frame_path=?, rendered_path=NULL WHERE id=? AND project_id=?",
            (out_path, slide_id, project_id),
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "frame_url": _to_url_path(out_path),
        "source_frame_path": out_path,
    }


# ---------------------------------------------------------------------------
# OCR  (always translates to Dutch)
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/import/run-ocr")
async def run_ocr(project_id: str, body: OcrRequest = OcrRequest()):
    """
    Run OCR on DM slides only, translate to Dutch, populate messages.
    Meme slides are skipped — their source image is used directly.
    """
    job_id = await job_manager.create_job(project_id, "ocr")

    async def _ocr(progress_callback, **_):
        db2 = await get_db()
        try:
            cursor = await db2.execute(
                "SELECT id, source_frame_path, frame_type FROM slides WHERE project_id=? ORDER BY sort_order",
                (project_id,),
            )
            slides = await cursor.fetchall()
        finally:
            await db2.close()

        total = len(slides)
        dm_slides  = [s for s in slides if (s["frame_type"] if "frame_type" in s.keys() else "dm") == "dm"]

        for idx, slide in enumerate(dm_slides):
            slide_id = slide["id"]
            frame_path = slide["source_frame_path"] if "source_frame_path" in slide.keys() else None

            await progress_callback(idx / max(len(dm_slides), 1), f"OCR frame {idx + 1}/{len(dm_slides)}")

            if not frame_path or not Path(frame_path).exists():
                continue

            # ── OCR: GPT-4o vision (primary) or EasyOCR (fallback) ────────
            #
            # Vision path  — one API call: reads text, classifies sender,
            #                translates to Dutch street slang, detects story reply.
            # Fallback path — EasyOCR + coordinate-based classification +
            #                 GPT-4o-mini translation (separate calls, slower).

            # Resolve API key (same helper used by translation & classifier)
            _ocr_api_key = ""
            try:
                from database import get_db as _get_db2  # noqa: PLC0415
                _db_tmp = await _get_db2()
                try:
                    _row = await (await _db_tmp.execute(
                        "SELECT openai_api_key FROM app_settings WHERE id=1"
                    )).fetchone()
                    if _row and _row["openai_api_key"]:
                        _ocr_api_key = _row["openai_api_key"]
                finally:
                    await _db_tmp.close()
            except Exception:
                pass
            if not _ocr_api_key:
                import os as _os
                _ocr_api_key = _os.getenv("OPENAI_API_KEY", "")

            if _ocr_api_key:
                # ── Primary: GPT-4o vision ──────────────────────────────
                messages, has_story_reply = await extract_messages_vision(
                    frame_path, _ocr_api_key
                )
            else:
                # ── Fallback: EasyOCR (raw text, no per-message translation) ──
                import cv2 as _cv2_ocr  # noqa: PLC0415
                raw_blocks = await ocr_frame(frame_path)
                _img = await asyncio.to_thread(_cv2_ocr.imread, frame_path)
                img_h, img_w = (_img.shape[:2] if _img is not None else (1920, 1080))
                filtered_blocks, has_story_reply = filter_message_blocks(
                    raw_blocks, image_height=img_h, image_width=img_w,
                )
                raw_msgs = classify_sender(filtered_blocks, image_width=img_w)
                # Collect raw text — single batch translation happens below
                messages = [{"sender": m["sender"], "text": m["text"]} for m in raw_msgs]

            # Auto-create story_reply layout when detected
            if has_story_reply and messages:
                messages[0]["message_type"] = "story_reply"
                messages[0]["story_reply_label"] = "Reageerde op je verhaal"
            # ── end OCR ───────────────────────────────────────────────

            db3 = await get_db()
            try:
                await db3.execute("DELETE FROM messages WHERE slide_id=?", (slide_id,))
                for sort_i, m in enumerate(messages):
                    msg_type = m.get("message_type", "text")
                    label    = m.get("story_reply_label")
                    await db3.execute(
                        """INSERT INTO messages
                           (id, slide_id, sort_order, sender, text, message_type,
                            show_timestamp, timestamp_text, read_receipt, emoji_reaction,
                            story_image_path, story_reply_label)
                           VALUES (?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL, NULL, ?)""",
                        (str(uuid.uuid4()), slide_id, sort_i,
                         m["sender"], m["text"], msg_type, label),
                    )
                await db3.commit()
            finally:
                await db3.close()

        # ── PRE-TRANSLATION TEXT DEDUP ────────────────────────────────────
        # Dedup using raw OCR text BEFORE paying for batch translation.
        # Normalise: casefold + strip all whitespace + strip punctuation.
        # This catches slides that are identical even when OCR introduced
        # minor spacing differences (e.g. "dankje" vs "dank je").

        await progress_callback(0.93, "Tekst dedup — duplicaten verwijderen vóór vertaling…")

        import re as _re_dd

        def _normalise(text: str) -> str:
            t = text.casefold()
            t = _re_dd.sub(r"\s+", "", t)     # remove all whitespace
            t = _re_dd.sub(r"[^\w]", "", t)   # remove punctuation
            return t

        db_prededup = await get_db()
        try:
            _pd_cursor = await db_prededup.execute(
                """SELECT s.id AS slide_id, s.sort_order AS slide_order,
                          m.sort_order AS msg_order, m.text
                   FROM slides s
                   LEFT JOIN messages m ON m.slide_id = s.id
                   WHERE s.project_id = ? AND s.frame_type = 'dm' AND s.is_active = 1
                   ORDER BY s.sort_order, m.sort_order""",
                (project_id,),
            )
            _pd_rows = await _pd_cursor.fetchall()
        finally:
            await db_prededup.close()

        # Build one normalised fingerprint per slide (concat of all message texts)
        from collections import OrderedDict as _OD_pd
        _slide_txt: dict = _OD_pd()
        for row in _pd_rows:
            sid = row["slide_id"]
            if sid not in _slide_txt:
                _slide_txt[sid] = []
            if row["text"] is not None:
                _slide_txt[sid].append(_normalise(row["text"]))

        _seen_txt_fps: set = set()
        _pre_txt_dups: list = []
        for sid, normed in _slide_txt.items():
            if not normed:
                continue          # slide with 0 messages → leave alone
            fp = "".join(normed)
            if fp in _seen_txt_fps:
                _pre_txt_dups.append(sid)
            else:
                _seen_txt_fps.add(fp)

        if _pre_txt_dups:
            db_prededup2 = await get_db()
            try:
                for sid in _pre_txt_dups:
                    await db_prededup2.execute(
                        "UPDATE slides SET is_active=0 WHERE id=?", (sid,)
                    )
                await db_prededup2.commit()
            finally:
                await db_prededup2.close()
            await progress_callback(
                0.94,
                f"Tekst dedup — {len(_pre_txt_dups)} duplicaat/duplicaten verwijderd",
            )

        # ── SINGLE BATCH TRANSLATION ──────────────────────────────────────
        # Translate the entire conversation in ONE GPT call so that every
        # occurrence of the same slang gets the same Dutch equivalent.
        # OCR above intentionally extracted raw (untranslated) text so that
        # this pass is the sole translation step.
        # Only active (non-deduped) slides are translated.

        await progress_callback(0.95, "Vertalen — volledige conversatie in één batch…")

        # Fetch every raw message that was just written, with slide sort_order
        db_batch = await get_db()
        try:
            batch_cursor = await db_batch.execute(
                """SELECT m.id, m.slide_id, m.sort_order, m.sender, m.text,
                          s.sort_order AS slide_order
                   FROM messages m
                   JOIN slides s ON s.id = m.slide_id
                   WHERE s.project_id=? AND s.is_active=1
                   ORDER BY s.sort_order, m.sort_order""",
                (project_id,),
            )
            all_msgs = await batch_cursor.fetchall()
        finally:
            await db_batch.close()

        if all_msgs:
            # Build payload: slide = slide sort_order, index = message sort_order
            payload = [
                {
                    "msg_id":   r["id"],
                    "slide_id": r["slide_id"],
                    "slide":    r["slide_order"],
                    "index":    r["sort_order"],
                    "sender":   r["sender"],
                    "text":     r["text"],
                }
                for r in all_msgs
            ]
            consistent = await batch_translate_conversation(payload)

            # Write back only changed texts
            db_batch2 = await get_db()
            try:
                changed = [
                    (c["text"], c["msg_id"])
                    for orig, c in zip(payload, consistent)
                    if orig["text"] != c["text"]
                ]
                for new_text, msg_id in changed:
                    await db_batch2.execute(
                        "UPDATE messages SET text=? WHERE id=?", (new_text, msg_id)
                    )
                if changed:
                    await db_batch2.commit()
            finally:
                await db_batch2.close()

        await progress_callback(1.0, f"Done — {len(dm_slides)} DM slides, {len(all_msgs)} messages translated")
        return {"slides_processed": total, "dm_slides": len(dm_slides)}

    await job_manager.submit(job_id, _ocr)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/import/status")
async def import_status(project_id: str):
    """Return download/frame-extraction status for a project."""
    db = await get_db()
    try:
        row = await (await db.execute("SELECT source_url, video_path FROM projects WHERE id=?", (project_id,))).fetchone()
        cnt_row = await (await db.execute(
            "SELECT COUNT(*) as cnt FROM slides WHERE project_id=? AND is_active=1",
            (project_id,),
        )).fetchone()
    finally:
        await db.close()

    source_url = None
    has_video = False
    if row:
        keys = row.keys()
        source_url = row["source_url"] if "source_url" in keys else None
        vp = row["video_path"] if "video_path" in keys else None
        has_video = bool(vp and Path(vp).exists())

    return {
        "source_url": source_url,
        "has_video": has_video,
        "frame_count": cnt_row["cnt"] if cnt_row else 0,
    }


# ---------------------------------------------------------------------------
# Slides with frame paths + frame_type (for FramesStep UI)
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/import/frames")
async def list_frames(project_id: str):
    """Return slides with frame_url and frame_type for the frames review UI."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, sort_order, source_frame_path, frame_type, is_active, hold_duration_ms
               FROM slides WHERE project_id=? AND is_active=1 ORDER BY sort_order""",
            (project_id,),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    return [
        {
            "id": r["id"],
            "sort_order": r["sort_order"],
            "source_frame_path": r["source_frame_path"] if "source_frame_path" in r.keys() else None,
            "frame_url": _to_url_path(r["source_frame_path"] if "source_frame_path" in r.keys() else None),
            "frame_type": r["frame_type"] if "frame_type" in r.keys() else "dm",
            "is_active": bool(r["is_active"]),
            "hold_duration_ms": r["hold_duration_ms"],
        }
        for r in rows
    ]
