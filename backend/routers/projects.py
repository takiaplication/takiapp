import io
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from database import get_db
from config import PROJECTS_DIR, STORAGE_DIR
from schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse, LibraryItem

router = APIRouter(tags=["projects"])


def _thumb_to_url(thumb_path: Optional[str]) -> Optional[str]:
    """Convert an absolute thumbnail_path to a /files/… URL."""
    if not thumb_path or not Path(thumb_path).exists():
        return None
    try:
        rel = Path(thumb_path).relative_to(STORAGE_DIR)
        return f"/files/{rel.as_posix()}"
    except ValueError:
        return None


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM projects ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.post("/projects", response_model=ProjectResponse)
async def create_project(data: ProjectCreate):
    project_id = str(uuid.uuid4())
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "rendered").mkdir(exist_ok=True)
    (project_dir / "memes").mkdir(exist_ok=True)

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            (project_id, data.name),
        )
        # Create default render settings
        await db.execute(
            "INSERT INTO render_settings (project_id) VALUES (?)",
            (project_id,),
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        return dict(row)
    finally:
        await db.close()


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, data: ProjectUpdate):
    db = await get_db()
    try:
        if data.name is not None:
            await db.execute(
                "UPDATE projects SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (data.name, project_id),
            )
        if data.views is not None:
            # Clamp to non-negative — a negative view count makes no sense
            views = max(0, int(data.views))
            await db.execute(
                "UPDATE projects SET views=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (views, project_id),
            )
        await db.commit()

        cursor = await db.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        return dict(row)
    finally:
        await db.close()


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")

        await db.execute("DELETE FROM projects WHERE id=?", (project_id,))
        await db.commit()
    finally:
        await db.close()

    # Remove project files
    project_dir = PROJECTS_DIR / project_id
    if project_dir.exists():
        shutil.rmtree(project_dir)

    return {"ok": True}


# ---------------------------------------------------------------------------
# Library — all completed (status='library') projects
# ---------------------------------------------------------------------------

@router.get("/library", response_model=list[LibraryItem])
async def list_library():
    """Return every project with status='library', newest first."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, name, created_at, thumbnail_path, drive_url, views
               FROM projects
               WHERE status='library'
               ORDER BY created_at DESC""",
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    return [
        LibraryItem(
            id=r["id"],
            name=r["name"],
            created_at=r["created_at"],
            thumbnail_url=_thumb_to_url(r["thumbnail_path"] if "thumbnail_path" in r.keys() else None),
            download_url=f"/api/projects/{r['id']}/export/download",
            drive_url=r["drive_url"] if "drive_url" in r.keys() else None,
            views=int(r["views"]) if "views" in r.keys() and r["views"] is not None else 0,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# JSON serialization — canonical project-as-data
# ---------------------------------------------------------------------------

async def _build_project_json(project_id: str) -> Optional[dict]:
    """
    Build the canonical JSON representation of a project.
    Includes every field needed to rebuild the MP4 from scratch:
      - project metadata (views, source_url, drive_url, status, dates)
      - render_settings (theme, transitions, music, fps, …)
      - every slide in sort order with:
          • frame_type (dm | meme | app_ad)
          • hold_duration_ms, is_active
          • meme_category + meme_source_path (which exact file was used)
          • app_ad source_frame_path
          • full ordered messages list for DM slides
    Returns None if the project does not exist.
    """
    db = await get_db()
    try:
        proj = await (await db.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        )).fetchone()
        if not proj:
            return None

        settings = await (await db.execute(
            "SELECT * FROM render_settings WHERE project_id=?", (project_id,)
        )).fetchone()

        slide_rows = await (await db.execute(
            "SELECT * FROM slides WHERE project_id=? ORDER BY sort_order",
            (project_id,),
        )).fetchall()

        msg_rows = await (await db.execute(
            """SELECT m.*
               FROM messages m
               JOIN slides s ON s.id = m.slide_id
               WHERE s.project_id=?
               ORDER BY s.sort_order, m.sort_order""",
            (project_id,),
        )).fetchall()
    finally:
        await db.close()

    # Group messages by slide_id for fast lookup
    msgs_by_slide: dict = {}
    for m in msg_rows:
        msgs_by_slide.setdefault(m["slide_id"], []).append({
            "sort_order":        m["sort_order"],
            "sender":            m["sender"],
            "text":              m["text"],
            "message_type":      m["message_type"],
            "show_timestamp":    bool(m["show_timestamp"]),
            "timestamp_text":    m["timestamp_text"],
            "read_receipt":      m["read_receipt"],
            "emoji_reaction":    m["emoji_reaction"],
            "story_image_path":  m["story_image_path"] if "story_image_path" in m.keys() else None,
            "story_reply_label": m["story_reply_label"] if "story_reply_label" in m.keys() else None,
            "content_hash":      m["content_hash"] if "content_hash" in m.keys() else None,
            "story_group_id":    m["story_group_id"] if "story_group_id" in m.keys() else None,
        })

    def _row_get(row, key, default=None):
        return row[key] if key in row.keys() else default

    slides_out = []
    for s in slide_rows:
        frame_type = _row_get(s, "frame_type", "dm") or "dm"
        slides_out.append({
            "id":                 s["id"],
            "sort_order":         s["sort_order"],
            "frame_type":         frame_type,
            "slide_type":         _row_get(s, "slide_type", "dm"),
            "is_active":          bool(s["is_active"]),
            "hold_duration_ms":   s["hold_duration_ms"],
            "meme_category":      _row_get(s, "meme_category"),
            "meme_source_path":   _row_get(s, "meme_source_path"),
            "source_frame_path":  _row_get(s, "source_frame_path"),
            "messages":           msgs_by_slide.get(s["id"], []),
        })

    project_meta = {
        "id":             proj["id"],
        "name":           proj["name"],
        "status":         proj["status"],
        "source_url":     _row_get(proj, "source_url"),
        "drive_url":      _row_get(proj, "drive_url"),
        "views":          int(_row_get(proj, "views", 0) or 0),
        "created_at":     proj["created_at"],
        "updated_at":     proj["updated_at"],
    }

    render_settings = dict(settings) if settings else {}

    return {
        "schema_version": 1,
        "project":        project_meta,
        "render_settings": render_settings,
        "slides":         slides_out,
    }


@router.get("/projects/{project_id}/json")
async def get_project_json(project_id: str):
    """Return the full project JSON — enough to regenerate the MP4."""
    data = await _build_project_json(project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return data


# ---------------------------------------------------------------------------
# Export-all-JSON — ZIP of every library project's JSON, named by date
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("_", value).strip("_") or "project"


@router.get("/library/export-all")
async def export_all_library_json():
    """
    Download a ZIP containing one JSON file per library project.
    Each entry is named '<YYYY-MM-DD>_<slug>.json'.
    """
    db = await get_db()
    try:
        rows = await (await db.execute(
            """SELECT id, name, created_at FROM projects
               WHERE status='library' ORDER BY created_at DESC""",
        )).fetchall()
    finally:
        await db.close()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        used_names: set = set()
        for r in rows:
            data = await _build_project_json(r["id"])
            if data is None:
                continue

            # created_at looks like '2026-04-18 16:25:00' — take first 10 chars
            date_prefix = (r["created_at"] or "")[:10] or "no-date"
            slug = _slugify(r["name"] or r["id"][:8])[:60]
            base = f"{date_prefix}_{slug}"
            name = f"{base}.json"
            i = 2
            while name in used_names:
                name = f"{base}_{i}.json"
                i += 1
            used_names.add(name)

            zf.writestr(name, json.dumps(data, ensure_ascii=False, indent=2))

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="reelfactory_library_json.zip"',
        },
    )
