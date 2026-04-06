import asyncio
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, File, UploadFile
from pydantic import BaseModel

from config import STORAGE_DIR, PROJECTS_DIR
from database import get_db
from services.downloader import download_video
from services.frame_extractor import extract_scenes, SAMPLE_MS
from services.frame_classifier import classify_frame_ai
from services.ocr_service import (
    ocr_frame, classify_sender, filter_message_blocks,
    extract_messages_vision,
)
from services.translation_service import translate_text, batch_translate_conversation
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
        import cv2 as _cv2
        import numpy as _np
        import asyncio as _aio

        # ── STAGE 1 (0–40 %): capture every 250 ms — nothing missed ──────────
        async def _prog1(p: float, msg: str):
            await progress_callback(p * 0.40, msg)

        raw_frames = await extract_scenes(
            video_path, project_id,
            progress_callback=_prog1,
        )
        await progress_callback(0.40, f"Stage 1 done — {len(raw_frames)} raw samples captured")

        await progress_callback(0.40, "Stage 2 — deduplicating frames…")

        # ── STAGE 2: consecutive aHash deduplication ─────────────────────────
        #
        # Each frame is compared ONLY to the PREVIOUS KEPT frame.
        #
        # Why consecutive, not all-vs-all:
        #   All-vs-all with a loose threshold caused cascading merges.
        #   Example: slide A is kept. Slide B (new message, 8 bits from A)
        #   was kept too. Then slide C (new message, 8 bits from B but 16 from A)
        #   was correctly kept. But with all-vs-all + threshold 10, slide B
        #   itself gets compared to A: 8 < 10 → wrongly dropped. Half the
        #   DM slides disappeared.
        #
        #   Consecutive comparison: each frame compares to the previous kept
        #   frame only. A run of N identical frames (same slide) collapses
        #   to 1. The first genuinely different frame starts a new run.
        #   No cascading merges possible.
        #
        # Threshold 5 (out of 64 bits):
        #   Same frame, JPEG noise only       →  0–3 bits  → duplicate ✓
        #   Same slide, minor brightness      →  0–4 bits  → duplicate ✓
        #   New DM slide (one new message)    →  5–20 bits → kept      ✓
        #   New meme / app_ad slide           → 20–64 bits → kept      ✓

        _HS   = 8    # 8×8 = 64 bits per hash
        _SAME = 5    # consecutive distance < 5 → same run → skip

        def _ahash(path: str) -> Optional[_np.ndarray]:
            """
            64-bit average hash.
            Grayscale → crop 10–90 % vertically → resize 8×8 → binary (pixel > mean).
            Brightness-invariant: the threshold is the per-image mean, so bright
            and dim versions of the same slide produce identical binary patterns.
            """
            img = _cv2.imread(path, _cv2.IMREAD_GRAYSCALE)
            if img is None:
                return None
            h_px = img.shape[0]
            y0, y1 = int(h_px * 0.10), int(h_px * 0.90)
            crop = img[y0:y1, :]
            if crop.size == 0:
                return None
            small = _cv2.resize(crop, (_HS, _HS), interpolation=_cv2.INTER_AREA)
            return (small.flatten() > float(small.mean()))   # bool[64]

        unique_frames: list[str] = []
        prev_hash: Optional[_np.ndarray] = None   # hash of previous KEPT frame
        dup_count = 0

        for i, fp in enumerate(raw_frames):
            fhash = await _aio.to_thread(_ahash, fp)

            if fhash is None:
                # Unreadable — keep it so the user can review it
                unique_frames.append(fp)
                prev_hash = None
                continue

            dist = 0 if prev_hash is None else int(_np.sum(fhash != prev_hash))

            if prev_hash is None or dist >= _SAME:
                # Different from previous → new slide, start fresh run
                unique_frames.append(fp)
                prev_hash = fhash
            else:
                # Same as previous → duplicate within current run, skip
                dup_count += 1

            await progress_callback(
                0.40 + 0.20 * (i + 1) / max(len(raw_frames), 1),
                f"Dedup {i + 1}/{len(raw_frames)} — {dup_count} duplicates removed so far",
            )

        await progress_callback(
            0.60,
            f"Stage 2 done — {len(unique_frames)} unique frames "
            f"(removed {dup_count} duplicates from {len(raw_frames)} samples)",
        )

        # ── STAGE 3 (60–95 %): AI classify unique frames only ────────────────
        #
        # GPT-4o-mini vision runs only on the deduplicated set — much fewer
        # frames, faster, cheaper.

        await progress_callback(0.60, "Stage 3 — classifying unique frames with AI…")
        classified: list[tuple[str, str]] = []

        for i, fp in enumerate(unique_frames):
            ftype = await classify_frame_ai(fp)
            classified.append((fp, ftype))
            await progress_callback(
                0.60 + 0.35 * (i + 1) / max(len(unique_frames), 1),
                f"Classified {i + 1}/{len(unique_frames)}: {ftype}",
            )

        await progress_callback(0.95, f"Stage 3 done — {len(classified)} frames classified")

        # ── STAGE 3b: collapse consecutive meme runs + deduplicate app_ad ───────
        # - Track ALL frames of each meme run so we can cut the exact video segment.
        # - Consecutive meme frames → keep the first as representative.
        # - app_ad → keep only the very first occurrence.
        collapsed: list[tuple[str, str]] = []
        in_meme_run       = False
        current_meme_run: list[str] = []
        app_ad_seen       = False
        meme_frame_groups: dict[str, list[str]] = {}   # rep_frame → all frames

        for fp, ftype in classified:
            if ftype == "meme":
                if not in_meme_run:
                    in_meme_run = True
                    current_meme_run = [fp]
                else:
                    current_meme_run.append(fp)
            else:
                if in_meme_run:
                    rep = current_meme_run[0]
                    collapsed.append((rep, "meme"))
                    meme_frame_groups[rep] = current_meme_run[:]
                    current_meme_run = []
                    in_meme_run = False
                if ftype == "app_ad":
                    if not app_ad_seen:
                        collapsed.append((fp, "app_ad"))
                        app_ad_seen = True
                else:
                    collapsed.append((fp, ftype))

        # Flush any meme run at the very end of the video
        if in_meme_run and current_meme_run:
            rep = current_meme_run[0]
            collapsed.append((rep, "meme"))
            meme_frame_groups[rep] = current_meme_run[:]

        meme_slots   = sum(1 for _, t in collapsed if t == "meme")
        app_ad_slots = sum(1 for _, t in collapsed if t == "app_ad")
        dm_unique    = sum(1 for _, t in collapsed if t == "dm")
        await progress_callback(
            0.96,
            f"Collapsed → {dm_unique} DM + {meme_slots} meme + {app_ad_slots} app_ad = {len(collapsed)} total",
        )

        # ── STAGE 3c (96–99 %): extract meme video segments ──────────────────
        # For each meme run, cut the segment from the original video using
        # ffmpeg -c copy (no re-encode, near-instant).
        # Conservative trim: drop 1 frame from each end to avoid
        # transition blur / fade / opacity artefacts.
        import re         as _re
        import subprocess as _sp

        _SAMPLE_S  = SAMPLE_MS / 1000.0        # 0.25 s per frame
        _TRIM_S    = 1 * _SAMPLE_S              # 0.25 s trimmed from each end
        _MIN_DUR_S = 0.5                        # skip trim if result is shorter

        def _frame_ts_s(fp: str) -> float:
            """Timestamp of a frame_auto_NNNNNN file in seconds."""
            m = _re.search(r'frame_auto_(\d+)', fp)
            return int(m.group(1)) * _SAMPLE_S if m else 0.0

        def _ffmpeg_clip(src: str, dst: str, start: float, end: float) -> bool:
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}",
                "-to", f"{end:.3f}",
                "-i", src,
                "-c", "copy",
                dst,
            ]
            r = _sp.run(cmd, capture_output=True, timeout=120)
            return (r.returncode == 0
                    and Path(dst).exists()
                    and Path(dst).stat().st_size > 0)

        clips_dir = PROJECTS_DIR / project_id / "meme_clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        meme_clip_paths: dict[str, Optional[str]] = {}   # rep_frame → clip path

        meme_idx = 0
        for fp, ftype in collapsed:
            if ftype != "meme":
                continue
            frames_in_run = meme_frame_groups.get(fp, [fp])
            ts_start = _frame_ts_s(frames_in_run[0])
            ts_end   = _frame_ts_s(frames_in_run[-1]) + _SAMPLE_S

            seg_start = ts_start + _TRIM_S
            seg_end   = ts_end   - _TRIM_S
            if seg_end - seg_start < _MIN_DUR_S:
                seg_start, seg_end = ts_start, ts_end   # keep full segment

            clip_path = str(clips_dir / f"meme_seg_{meme_idx:03d}.mp4")
            ok = await _aio.to_thread(_ffmpeg_clip, video_path, clip_path, seg_start, seg_end)
            meme_clip_paths[fp] = clip_path if ok else None
            meme_idx += 1
            await progress_callback(
                0.96 + 0.03 * meme_idx / max(meme_slots, 1),
                f"Extracting meme clip {meme_idx}/{meme_slots} "
                f"({seg_end - seg_start:.1f}s)",
            )

        await progress_callback(0.99, f"Stage 3c done — {meme_idx} meme clips extracted")

        # ── STAGE 4 (99–100 %): single fast DB write ─────────────────────────
        db2 = await get_db()
        try:
            await db2.execute("DELETE FROM slides WHERE project_id=?", (project_id,))
            for i, (frame_path, ftype) in enumerate(collapsed):
                extracted_clip = None
                if ftype == "meme":
                    extracted_clip = meme_clip_paths.get(frame_path)
                    if extracted_clip and Path(extracted_clip).exists():
                        src = extracted_clip   # use extracted clip as default source
                        cap    = _cv2.VideoCapture(extracted_clip)
                        _fps   = cap.get(_cv2.CAP_PROP_FPS) or 30
                        _fr    = cap.get(_cv2.CAP_PROP_FRAME_COUNT)
                        cap.release()
                        default_hold = max(500, int(_fr / _fps * 1000))
                    else:
                        src            = None
                        extracted_clip = None
                        default_hold   = 1500
                elif ftype == "app_ad":
                    src          = None
                    default_hold = 1000
                else:
                    src          = frame_path
                    default_hold = 3000
                await db2.execute(
                    """INSERT INTO slides
                       (id, project_id, sort_order, slide_type, source_frame_path,
                        frame_type, is_active, hold_duration_ms, extracted_clip_path)
                       VALUES (?, ?, ?, 'dm', ?, ?, 1, ?, ?)""",
                    (str(uuid.uuid4()), project_id, i, src, ftype,
                     default_hold, extracted_clip),
                )
            await db2.commit()
        finally:
            await db2.close()

        return {
            "raw_frames":        len(raw_frames),
            "unique_frames":     len(unique_frames),
            "duplicates_removed": dup_count,
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
                # ── Fallback: EasyOCR + translate ───────────────────────
                import cv2 as _cv2_ocr  # noqa: PLC0415
                raw_blocks = await ocr_frame(frame_path)
                _img = await asyncio.to_thread(_cv2_ocr.imread, frame_path)
                img_h, img_w = (_img.shape[:2] if _img is not None else (1920, 1080))
                filtered_blocks, has_story_reply = filter_message_blocks(
                    raw_blocks, image_height=img_h, image_width=img_w,
                )
                raw_msgs = classify_sender(filtered_blocks, image_width=img_w)
                messages = []
                for m in raw_msgs:
                    translated = await translate_text(m["text"], target_lang="nl")
                    messages.append({"sender": m["sender"], "text": translated})

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

        # ── BATCH CONSISTENCY PASS ────────────────────────────────────────
        # After all slides are OCR'd individually, re-translate the whole
        # conversation in one call so the same slang is used consistently
        # across slides (e.g. "gooning" always → "raggen", not sometimes
        # "raggen" and sometimes "doen").

        await progress_callback(0.95, "Consistency pass — re-translating full conversation…")

        # Fetch every message that was just written
        db_batch = await get_db()
        try:
            batch_cursor = await db_batch.execute(
                """SELECT m.id, m.slide_id, m.sort_order, m.text
                   FROM messages m
                   JOIN slides s ON s.id = m.slide_id
                   WHERE s.project_id=?
                   ORDER BY s.sort_order, m.sort_order""",
                (project_id,),
            )
            all_msgs = await batch_cursor.fetchall()
        finally:
            await db_batch.close()

        if all_msgs:
            payload = [
                {"msg_id": r["id"], "slide_id": r["slide_id"],
                 "sort_order": r["sort_order"], "text": r["text"]}
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

        # ── POST-OCR CONTENT DEDUP ───────────────────────────────────────────
        # After OCR the messages in the DB are the ground truth.  Two DM
        # slides whose extracted messages are identical (same sender + text,
        # same order) are definitively the same conversation state captured
        # more than once.  Keep the first; deactivate all later copies.
        # This catches the residual duplicates that survived visual pHash
        # dedup (e.g. slightly different crop, mild OCR variation masked by
        # normalization).

        await progress_callback(0.97, "Content dedup — scanning for identical slides…")

        db_cd = await get_db()
        try:
            cd_cursor = await db_cd.execute(
                """SELECT s.id AS slide_id, s.sort_order AS slide_order,
                          m.sort_order AS msg_order, m.sender, m.text
                   FROM slides s
                   LEFT JOIN messages m ON m.slide_id = s.id
                   WHERE s.project_id = ? AND s.frame_type = 'dm' AND s.is_active = 1
                   ORDER BY s.sort_order, m.sort_order""",
                (project_id,),
            )
            cd_rows = await cd_cursor.fetchall()
        finally:
            await db_cd.close()

        # Build ordered message list per slide
        from collections import OrderedDict as _OD
        slide_msg_map: dict = _OD()
        for row in cd_rows:
            sid = row["slide_id"]
            if sid not in slide_msg_map:
                slide_msg_map[sid] = []
            if row["sender"] is not None:   # LEFT JOIN → None when no messages
                slide_msg_map[sid].append(f"{row['sender']}:{row['text']}")

        seen_fps: set = set()
        content_dups: list = []
        for sid, msgs in slide_msg_map.items():
            if not msgs:
                continue  # slides with 0 messages are left untouched
            fp = tuple(msgs)
            if fp in seen_fps:
                content_dups.append(sid)
            else:
                seen_fps.add(fp)

        if content_dups:
            db_cd2 = await get_db()
            try:
                for sid in content_dups:
                    await db_cd2.execute(
                        "UPDATE slides SET is_active=0 WHERE id=?", (sid,)
                    )
                await db_cd2.commit()
            finally:
                await db_cd2.close()
            await progress_callback(
                0.98,
                f"Content dedup — deactivated {len(content_dups)} duplicate slide(s)",
            )

        await progress_callback(1.0, f"Done — {len(dm_slides)} slides, {len(all_msgs)} messages")
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
            "SELECT COUNT(*) as cnt FROM slides WHERE project_id=?",
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
               FROM slides WHERE project_id=? ORDER BY sort_order""",
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
