import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException

from config import STORAGE_DIR, MEME_LIBRARY_DIR
from database import get_db
from schemas.slide import SlideCreate, SlideUpdate, SlideReorder, SlideResponse

router = APIRouter(tags=["slides"])


def _to_frame_url(source_frame_path: Optional[str]) -> Optional[str]:
    """Convert an absolute source_frame_path to a browser-accessible URL."""
    if not source_frame_path:
        return None
    p = Path(source_frame_path)
    try:
        p.relative_to(MEME_LIBRARY_DIR)
        return f"/meme-library/{p.name}"
    except ValueError:
        pass
    try:
        rel = p.relative_to(STORAGE_DIR)
        return f"/files/{rel.as_posix()}"
    except ValueError:
        return None


def _row_to_response(r) -> dict:
    d = dict(r)
    d["is_active"]          = bool(d.get("is_active", 0))
    d["frame_type"]         = d.get("frame_type") or "dm"
    d["frame_url"]          = _to_frame_url(d.get("source_frame_path"))
    d["extracted_clip_url"] = _to_frame_url(d.get("extracted_clip_path"))
    return d


@router.get("/projects/{project_id}/slides", response_model=list[SlideResponse])
async def list_slides(project_id: str):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM slides WHERE project_id=? AND is_active=1 ORDER BY sort_order",
            (project_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_response(r) for r in rows]
    finally:
        await db.close()


@router.post("/projects/{project_id}/slides", response_model=SlideResponse)
async def create_slide(project_id: str, data: SlideCreate):
    slide_id = str(uuid.uuid4())
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 as next_order FROM slides WHERE project_id=?",
            (project_id,),
        )
        row = await cursor.fetchone()
        sort_order = row["next_order"]

        await db.execute(
            "INSERT INTO slides (id, project_id, sort_order, slide_type, frame_type, hold_duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
            (slide_id, project_id, sort_order, data.slide_type, data.frame_type, data.hold_duration_ms),
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM slides WHERE id=?", (slide_id,))
        row = await cursor.fetchone()
        return _row_to_response(row)
    finally:
        await db.close()


@router.patch("/projects/{project_id}/slides/reorder")
async def reorder_slides(project_id: str, data: SlideReorder):
    db = await get_db()
    try:
        for item in data.slides:
            await db.execute(
                "UPDATE slides SET sort_order=? WHERE id=? AND project_id=?",
                (item.sort_order, item.id, project_id),
            )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@router.patch("/projects/{project_id}/slides/{slide_id}", response_model=SlideResponse)
async def update_slide(project_id: str, slide_id: str, data: SlideUpdate):
    db = await get_db()
    try:
        updates = []
        params = []
        if data.hold_duration_ms is not None:
            updates.append("hold_duration_ms=?")
            params.append(data.hold_duration_ms)
        if data.is_active is not None:
            updates.append("is_active=?")
            params.append(int(data.is_active))
        if data.slide_type is not None:
            updates.append("slide_type=?")
            params.append(data.slide_type)

        if updates:
            params.append(slide_id)
            await db.execute(
                f"UPDATE slides SET {', '.join(updates)} WHERE id=?",
                params,
            )
            await db.commit()

        cursor = await db.execute("SELECT * FROM slides WHERE id=?", (slide_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Slide not found")
        return _row_to_response(row)
    finally:
        await db.close()


@router.delete("/projects/{project_id}/slides/{slide_id}")
async def delete_slide(project_id: str, slide_id: str):
    db = await get_db()
    try:
        await db.execute("DELETE FROM slides WHERE id=? AND project_id=?", (slide_id, project_id))
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@router.post("/projects/{project_id}/slides/{slide_id}/use-original-clip")
async def use_original_clip(project_id: str, slide_id: str):
    """Restore the auto-extracted meme clip as the active source for this slide."""
    import cv2 as _cv2
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT extracted_clip_path FROM slides WHERE id=? AND project_id=?",
            (slide_id, project_id),
        )).fetchone()
        if not row or not row["extracted_clip_path"]:
            raise HTTPException(status_code=404, detail="No extracted clip for this slide")
        clip_path = row["extracted_clip_path"]
        if not Path(clip_path).exists():
            raise HTTPException(status_code=404, detail="Extracted clip file not found on disk")

        # Compute actual clip duration
        cap    = _cv2.VideoCapture(clip_path)
        fps    = cap.get(_cv2.CAP_PROP_FPS) or 30
        frames = cap.get(_cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        hold_ms = max(500, int(frames / fps * 1000))

        await db.execute(
            "UPDATE slides SET source_frame_path=?, hold_duration_ms=?, rendered_path=NULL WHERE id=? AND project_id=?",
            (clip_path, hold_ms, slide_id, project_id),
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "frame_url":       _to_frame_url(clip_path),
        "hold_duration_ms": hold_ms,
    }
