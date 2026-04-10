"""
Meme Library — category-based shared pool of meme images and video clips.

Categories (fixed):
  opening        — always the first meme slot (hook / "watch me rizz")
  sport          — clean sports fragment
  coocked        — things went badly / cringe moment
  cooking        — things going very well / smooth/confident moment
  shoot_our_shot — bold message just sent, will it land?
  succes         — always the last meme slot (it worked out)

Endpoints:
  GET  /api/meme-library                 list items per category
  POST /api/meme-library/upload          upload to a specific category
  POST /api/projects/{id}/slides/{sid}/assign-library-meme
                                         assign a library meme to a meme slot
"""

import uuid
import cv2
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from config import MEME_LIBRARY_DIR
from database import get_db

router = APIRouter(tags=["meme-library"])

_IMAGE_EXTS  = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_VIDEO_EXTS  = {".mp4", ".mov", ".avi", ".webm"}
_ALLOWED     = _IMAGE_EXTS | _VIDEO_EXTS
_CATEGORIES  = ["opening", "sport", "coocked", "cooking", "shoot_our_shot", "succes"]

# Ensure all category folders exist
for _cat in _CATEGORIES:
    (MEME_LIBRARY_DIR / _cat).mkdir(parents=True, exist_ok=True)


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
    """Return all memes grouped by category."""
    items = []
    for cat in _CATEGORIES:
        cat_dir = MEME_LIBRARY_DIR / cat
        cat_dir.mkdir(exist_ok=True)
        for f in sorted(cat_dir.iterdir(), key=lambda p: p.name.lower()):
            if not f.is_file() or f.suffix.lower() not in _ALLOWED:
                continue
            items.append({
                "filename": f.name,
                "name":     f.stem,
                "url":      f"/meme-library/{cat}/{f.name}",
                "type":     _media_type(f),
                "category": cat,
            })
    return items


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/meme-library/upload")
async def upload_to_library(
    file: UploadFile = File(...),
    category: str    = Form("cooking"),
):
    """Upload a new image or video meme to a specific category folder."""
    if category not in _CATEGORIES:
        raise HTTPException(400, f"Invalid category '{category}'. Choose from: {_CATEGORIES}")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Allowed: {sorted(_ALLOWED)}")

    cat_dir = MEME_LIBRARY_DIR / category
    cat_dir.mkdir(exist_ok=True)

    dest = cat_dir / (file.filename or f"meme{suffix}")
    if dest.exists():
        dest = cat_dir / f"{uuid.uuid4().hex[:8]}_{file.filename}"

    dest.write_bytes(await file.read())

    return {
        "filename": dest.name,
        "name":     dest.stem,
        "url":      f"/meme-library/{category}/{dest.name}",
        "type":     _media_type(dest),
        "category": category,
    }


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/meme-library/{category}/{filename}")
async def delete_meme(category: str, filename: str):
    """Permanently delete a meme file from a category folder."""
    if category not in _CATEGORIES:
        raise HTTPException(400, f"Invalid category '{category}'")

    meme_path = MEME_LIBRARY_DIR / category / filename
    if not meme_path.exists():
        raise HTTPException(404, f"'{filename}' not found in category '{category}'")

    # Safety: only delete files with allowed extensions
    if meme_path.suffix.lower() not in _ALLOWED:
        raise HTTPException(400, "File type not allowed")

    meme_path.unlink()
    return {"ok": True, "deleted": filename, "category": category}


# ── Assign to slide ───────────────────────────────────────────────────────────

class AssignLibraryMemeRequest(BaseModel):
    category: str
    filename: str


@router.post("/projects/{project_id}/slides/{slide_id}/assign-library-meme")
async def assign_library_meme(
    project_id: str,
    slide_id:   str,
    body:       AssignLibraryMemeRequest,
):
    """
    Assign a library meme (from a specific category) to a meme slide.

    Sets source_frame_path, meme_category, and auto-calculates hold_duration_ms:
      - image meme  → 1 500 ms
      - video meme  → actual video duration
    """
    if body.category not in _CATEGORIES:
        raise HTTPException(400, f"Invalid category '{body.category}'")

    meme_path = MEME_LIBRARY_DIR / body.category / body.filename
    if not meme_path.exists():
        raise HTTPException(404, f"'{body.filename}' not found in category '{body.category}'")

    is_video = meme_path.suffix.lower() in _VIDEO_EXTS
    hold_ms  = _video_duration_ms(str(meme_path)) if is_video else 1500

    db = await get_db()
    try:
        await db.execute(
            """UPDATE slides
               SET source_frame_path=?, hold_duration_ms=?, rendered_path=NULL, meme_category=?
               WHERE id=? AND project_id=?""",
            (str(meme_path), hold_ms, body.category, slide_id, project_id),
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "slide_id":          slide_id,
        "source_frame_path": str(meme_path),
        "frame_url":         f"/meme-library/{body.category}/{meme_path.name}",
        "hold_duration_ms":  hold_ms,
        "meme_type":         "video" if is_video else "image",
        "meme_category":     body.category,
    }
