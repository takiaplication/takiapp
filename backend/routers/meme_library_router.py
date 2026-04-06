"""
Meme Library — shared pool of Dutch meme images and video clips.

Endpoints:
  GET  /api/meme-library              list all items
  POST /api/meme-library/upload       upload a new meme to the library
  POST /api/projects/{id}/slides/{sid}/assign-library-meme
                                      assign a library meme to a meme slot
  POST /api/projects/{id}/slides/{sid}/save-clip-to-library
                                      save auto-extracted clip to shared library
"""

import json
import uuid
import shutil
import cv2
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from config import MEME_LIBRARY_DIR
from database import get_db

router = APIRouter(tags=["meme-library"])

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".webm"}
_ALLOWED    = _IMAGE_EXTS | _VIDEO_EXTS


def _media_type(path: Path) -> str:
    return "video" if path.suffix.lower() in _VIDEO_EXTS else "image"


def _video_duration_ms(path: str) -> int:
    """Return video duration in milliseconds via OpenCV."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return 3000
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return max(1000, int(frames / fps * 1000))


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/meme-library")
async def list_memes():
    """Return all memes stored in the shared library."""
    items = []
    for f in sorted(MEME_LIBRARY_DIR.iterdir(), key=lambda p: p.name.lower()):
        if f.suffix.lower() not in _ALLOWED:
            continue
        items.append({
            "filename": f.name,
            "name": f.stem,
            "url":  f"/meme-library/{f.name}",
            "type": _media_type(f),
        })
    return items


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/meme-library/upload")
async def upload_to_library(file: UploadFile = File(...)):
    """Upload a new image or video meme to the shared library."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Allowed: {sorted(_ALLOWED)}")

    dest = MEME_LIBRARY_DIR / (file.filename or f"meme{suffix}")
    if dest.exists():
        dest = MEME_LIBRARY_DIR / f"{uuid.uuid4().hex[:8]}_{file.filename}"

    dest.write_bytes(await file.read())

    return {
        "filename": dest.name,
        "name":     dest.stem,
        "url":      f"/meme-library/{dest.name}",
        "type":     _media_type(dest),
    }


# ── Assign to slide ───────────────────────────────────────────────────────────

class AssignLibraryMemeRequest(BaseModel):
    filename: str   # filename inside MEME_LIBRARY_DIR


@router.post("/projects/{project_id}/slides/{slide_id}/assign-library-meme")
async def assign_library_meme(
    project_id: str,
    slide_id:   str,
    body:       AssignLibraryMemeRequest,
):
    """
    Assign a library meme to a meme slide.

    Sets source_frame_path and auto-calculates hold_duration_ms:
      - image meme  → 1 500 ms
      - video meme  → actual video duration
    """
    meme_path = MEME_LIBRARY_DIR / body.filename
    if not meme_path.exists():
        raise HTTPException(404, f"'{body.filename}' not found in meme library")

    is_video = meme_path.suffix.lower() in _VIDEO_EXTS
    hold_ms  = _video_duration_ms(str(meme_path)) if is_video else 1500

    db = await get_db()
    try:
        await db.execute(
            """UPDATE slides
               SET source_frame_path=?, hold_duration_ms=?, rendered_path=NULL
               WHERE id=? AND project_id=?""",
            (str(meme_path), hold_ms, slide_id, project_id),
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "slide_id":          slide_id,
        "source_frame_path": str(meme_path),
        "frame_url":         f"/meme-library/{meme_path.name}",
        "hold_duration_ms":  hold_ms,
        "meme_type":         "video" if is_video else "image",
    }


# ── Save extracted clip to library ────────────────────────────────────────────

@router.post("/projects/{project_id}/slides/{slide_id}/save-clip-to-library")
async def save_clip_to_library(project_id: str, slide_id: str):
    """
    Copy the auto-extracted meme clip for this slide into the shared meme
    library and write a JSON sidecar with provenance metadata.

    Returns the new LibraryMeme object so the frontend can add it to the list.
    """
    db = await get_db()
    try:
        # fetch slide + project in one query
        row = await db.execute_fetchall(
            """SELECT s.extracted_clip_path, p.name AS project_name, p.source_url
               FROM slides s
               JOIN projects p ON p.id = s.project_id
               WHERE s.id = ? AND s.project_id = ?""",
            (slide_id, project_id),
        )
    finally:
        await db.close()

    if not row:
        raise HTTPException(404, "Slide not found")

    r = row[0]
    clip_path = r["extracted_clip_path"] if hasattr(r, "__getitem__") else r[0]
    project_name = r["project_name"] if hasattr(r, "__getitem__") else r[1]
    source_url   = r["source_url"]    if hasattr(r, "__getitem__") else r[2]

    if not clip_path or not Path(clip_path).exists():
        raise HTTPException(404, "No extracted clip available for this slide")

    src = Path(clip_path)

    # Build a unique destination filename inside MEME_LIBRARY_DIR
    stem = f"meme_{uuid.uuid4().hex[:8]}{src.suffix}"
    dest = MEME_LIBRARY_DIR / stem
    shutil.copy2(src, dest)

    # Write JSON sidecar with provenance
    meta = {
        "source_url":   source_url or "",
        "project_id":   project_id,
        "project_name": project_name or "",
        "slide_id":     slide_id,
        "date_added":   datetime.now(timezone.utc).isoformat(),
    }
    dest.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    return {
        "filename": dest.name,
        "name":     dest.stem,
        "url":      f"/meme-library/{dest.name}",
        "type":     _media_type(dest),
    }
