"""
Story Library — single-use pool of story photos.

A story photo is used for the "Reageerde op je verhaal" bubble in DM slides.
Every photo may be used in EXACTLY ONE video: when the pipeline claims a
photo for a project it is copied into the project folder (so re-renders and
regenerate keep working) and the original is deleted from the library. Once
the pool is empty the pipeline parks new story-reply projects in Review with
a clear error instead of producing a video with an empty story bubble.

Endpoints:
  GET    /api/story-library            list available (unused) photos + count
  POST   /api/story-library/upload     upload one photo
  DELETE /api/story-library/{filename} remove a photo manually

Music Library — reusable pool of background audio tracks.
Unlike story photos these are NOT single-use: a random track is picked at
export time when the project has no explicit background music set.

  GET    /api/music-library            list tracks
  POST   /api/music-library/upload     upload one track
  DELETE /api/music-library/{filename} remove a track
"""

import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File

from config import (
    STORY_LIBRARY_DIR, MUSIC_LIBRARY_DIR, APP_INTRO_LIBRARY_DIR, PROJECTS_DIR,
)
from database import get_db

router = APIRouter(tags=["story-library"])

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".ogg"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}


# ── Story photos ─────────────────────────────────────────────────────────────

def _story_files() -> list[Path]:
    if not STORY_LIBRARY_DIR.exists():
        return []
    return sorted(
        (f for f in STORY_LIBRARY_DIR.iterdir()
         if f.is_file() and f.suffix.lower() in _IMAGE_EXTS),
        key=lambda p: p.name.lower(),
    )


@router.get("/story-library")
async def list_story_photos():
    files = _story_files()
    return {
        "count": len(files),
        "items": [
            {"filename": f.name, "url": f"/files/story_library/{f.name}"}
            for f in files
        ],
    }


@router.post("/story-library/upload")
async def upload_story_photo(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _IMAGE_EXTS:
        raise HTTPException(
            400, f"Unsupported file type '{suffix}'. Allowed: {sorted(_IMAGE_EXTS)}"
        )
    dest = STORY_LIBRARY_DIR / (file.filename or f"story{suffix}")
    if dest.exists():
        dest = STORY_LIBRARY_DIR / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    dest.write_bytes(await file.read())
    return {"filename": dest.name, "url": f"/files/story_library/{dest.name}"}


@router.delete("/story-library/{filename}")
async def delete_story_photo(filename: str):
    # Path-traversal guard: resolve and require the file to be inside the dir
    target = (STORY_LIBRARY_DIR / filename).resolve()
    if STORY_LIBRARY_DIR.resolve() not in target.parents:
        raise HTTPException(400, "Invalid filename")
    if not target.exists():
        raise HTTPException(404, f"'{filename}' not found in story library")
    if target.suffix.lower() not in _IMAGE_EXTS:
        raise HTTPException(400, "File type not allowed")
    target.unlink()
    return {"ok": True, "deleted": filename}


async def claim_story_photo(project_id: str) -> Optional[str]:
    """
    Take the OLDEST photo from the story library for this project:
      1. Copy it into the project folder as story_<name> (survives cleanup
         of the library and lets regenerate reproduce the same video).
      2. Delete the original from the library — a photo is used exactly once.
      3. Assign it to EVERY story_reply message of the project so the story
         is identical across all slides of this one video.

    Returns the project-local path, or None when the library is empty.
    If the project already has a story photo assigned (e.g. re-run of the
    pipeline), that existing photo is reused and NO new photo is claimed.
    """
    db = await get_db()
    try:
        existing = await (await db.execute(
            """SELECT m.story_image_path FROM messages m
               JOIN slides s ON s.id = m.slide_id
               WHERE s.project_id=? AND m.message_type='story_reply'
                 AND m.story_image_path IS NOT NULL AND m.story_image_path != ''
               LIMIT 1""",
            (project_id,),
        )).fetchone()
    finally:
        await db.close()

    if existing and existing["story_image_path"] and Path(existing["story_image_path"]).exists():
        photo_path = existing["story_image_path"]
    else:
        files = _story_files()
        if not files:
            return None
        source = files[0]  # oldest first — FIFO through the pool
        project_dir = PROJECTS_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        dest = project_dir / f"story_{source.name}"
        shutil.copy2(str(source), str(dest))
        source.unlink()  # single-use: gone from the library forever
        photo_path = str(dest)
        print(f"[story] claimed '{source.name}' for project {project_id}")

    db = await get_db()
    try:
        await db.execute(
            """UPDATE messages SET story_image_path=?
               WHERE message_type='story_reply'
                 AND slide_id IN (SELECT id FROM slides WHERE project_id=?)""",
            (photo_path, project_id),
        )
        await db.commit()
    finally:
        await db.close()

    return photo_path


# ── Music tracks ─────────────────────────────────────────────────────────────

def _music_files() -> list[Path]:
    if not MUSIC_LIBRARY_DIR.exists():
        return []
    return sorted(
        (f for f in MUSIC_LIBRARY_DIR.iterdir()
         if f.is_file() and f.suffix.lower() in _AUDIO_EXTS),
        key=lambda p: p.name.lower(),
    )


@router.get("/music-library")
async def list_music():
    files = _music_files()
    return {
        "count": len(files),
        "items": [
            {"filename": f.name, "url": f"/files/music_library/{f.name}"}
            for f in files
        ],
    }


@router.post("/music-library/upload")
async def upload_music(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _AUDIO_EXTS:
        raise HTTPException(
            400, f"Unsupported file type '{suffix}'. Allowed: {sorted(_AUDIO_EXTS)}"
        )
    dest = MUSIC_LIBRARY_DIR / (file.filename or f"track{suffix}")
    if dest.exists():
        dest = MUSIC_LIBRARY_DIR / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    dest.write_bytes(await file.read())
    return {"filename": dest.name, "url": f"/files/music_library/{dest.name}"}


@router.delete("/music-library/{filename}")
async def delete_music(filename: str):
    target = (MUSIC_LIBRARY_DIR / filename).resolve()
    if MUSIC_LIBRARY_DIR.resolve() not in target.parents:
        raise HTTPException(400, "Invalid filename")
    if not target.exists():
        raise HTTPException(404, f"'{filename}' not found in music library")
    if target.suffix.lower() not in _AUDIO_EXTS:
        raise HTTPException(400, "File type not allowed")
    target.unlink()
    return {"ok": True, "deleted": filename}


def pick_random_music() -> Optional[str]:
    """Random track path for exports without explicit background music."""
    import random
    files = _music_files()
    return str(random.choice(files)) if files else None


# ── App-intro clips (screen recording of opening the Taki app) ───────────────
# Reusable pool of short videos inserted right BEFORE every app-promo (app_ad)
# slide, so each promo is preceded by "me opening the app on my phone".

def _app_intro_files() -> list[Path]:
    if not APP_INTRO_LIBRARY_DIR.exists():
        return []
    return sorted(
        (f for f in APP_INTRO_LIBRARY_DIR.iterdir()
         if f.is_file() and f.suffix.lower() in _VIDEO_EXTS),
        key=lambda p: p.name.lower(),
    )


@router.get("/app-intro-library")
async def list_app_intros():
    files = _app_intro_files()
    return {
        "count": len(files),
        "items": [
            {"filename": f.name, "url": f"/files/app_intro_library/{f.name}"}
            for f in files
        ],
    }


@router.post("/app-intro-library/upload")
async def upload_app_intro(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _VIDEO_EXTS:
        raise HTTPException(
            400, f"Unsupported file type '{suffix}'. Allowed: {sorted(_VIDEO_EXTS)}"
        )
    dest = APP_INTRO_LIBRARY_DIR / (file.filename or f"intro{suffix}")
    if dest.exists():
        dest = APP_INTRO_LIBRARY_DIR / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    dest.write_bytes(await file.read())
    return {"filename": dest.name, "url": f"/files/app_intro_library/{dest.name}"}


@router.delete("/app-intro-library/{filename}")
async def delete_app_intro(filename: str):
    target = (APP_INTRO_LIBRARY_DIR / filename).resolve()
    if APP_INTRO_LIBRARY_DIR.resolve() not in target.parents:
        raise HTTPException(400, "Invalid filename")
    if not target.exists():
        raise HTTPException(404, f"'{filename}' not found in app-intro library")
    if target.suffix.lower() not in _VIDEO_EXTS:
        raise HTTPException(400, "File type not allowed")
    target.unlink()
    return {"ok": True, "deleted": filename}


def pick_app_intro() -> Optional[str]:
    """Random app-intro clip path, or None when the pool is empty."""
    import random
    files = _app_intro_files()
    return str(random.choice(files)) if files else None
