import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from database import get_db
from config import PROJECTS_DIR
from schemas.render import RenderSettings, RenderSettingsUpdate, DMConversation, DMMessage
from services.dm_renderer import renderer
from services.job_manager import job_manager

router = APIRouter(tags=["renderer"])


@router.get("/projects/{project_id}/settings", response_model=RenderSettings)
async def get_settings(project_id: str):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM render_settings WHERE project_id=?", (project_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Settings not found")
        d = dict(row)
        d["other_verified"] = bool(d["other_verified"])
        d.pop("project_id", None)
        return d
    finally:
        await db.close()


@router.put("/projects/{project_id}/settings", response_model=RenderSettings)
async def update_settings(project_id: str, data: RenderSettingsUpdate):
    db = await get_db()
    try:
        updates = []
        params = []
        # Fields that visually affect the DM render (not just video settings)
        visual_fields = {"other_username", "other_avatar_path", "other_verified", "self_username", "theme"}
        changed_visual = False

        for field, val in data.model_dump(exclude_none=True).items():
            if field == "other_verified":
                val = int(val)
            updates.append(f"{field}=?")
            params.append(val)
            if field in visual_fields:
                changed_visual = True

        if updates:
            params.append(project_id)
            await db.execute(
                f"UPDATE render_settings SET {', '.join(updates)} WHERE project_id=?",
                params,
            )
            # When visual settings change (theme, username, avatar…) all cached DM
            # slide PNGs are stale — clear them so the next export re-renders them.
            if changed_visual:
                await db.execute(
                    "UPDATE slides SET rendered_path=NULL "
                    "WHERE project_id=? AND (frame_type='dm' OR frame_type IS NULL)",
                    (project_id,),
                )
            await db.commit()

        cursor = await db.execute(
            "SELECT * FROM render_settings WHERE project_id=?", (project_id,)
        )
        row = await cursor.fetchone()
        d = dict(row)
        d["other_verified"] = bool(d["other_verified"])
        d.pop("project_id", None)
        return d
    finally:
        await db.close()


async def _build_conversation_for_slide(project_id: str, slide_id: str) -> DMConversation:
    """Build a DMConversation from DB data for a given slide."""
    db = await get_db()
    try:
        # Get settings
        cursor = await db.execute(
            "SELECT * FROM render_settings WHERE project_id=?", (project_id,)
        )
        settings = dict(await cursor.fetchone())

        # Get messages
        cursor = await db.execute(
            "SELECT * FROM messages WHERE slide_id=? ORDER BY sort_order", (slide_id,)
        )
        msg_rows = await cursor.fetchall()

        import base64 as b64lib

        messages = []
        for r in msg_rows:
            # Load story image as base64 if path exists
            story_b64 = None
            story_path = r["story_image_path"] if "story_image_path" in r.keys() else None
            if story_path and Path(story_path).exists():
                story_b64 = b64lib.b64encode(Path(story_path).read_bytes()).decode()

            messages.append(DMMessage(
                text=r["text"],
                is_sender=r["sender"] == "self",
                show_timestamp=bool(r["show_timestamp"]),
                timestamp_text=r["timestamp_text"],
                read_receipt=r["read_receipt"],
                emoji_reaction=r["emoji_reaction"],
                story_image_base64=story_b64,
                story_reply_label=r["story_reply_label"] if "story_reply_label" in r.keys() else None,
            ))

        return DMConversation(
            contact_name=settings["other_username"],
            contact_verified=bool(settings["other_verified"]),
            messages=messages,
            theme=settings["theme"],
        )
    finally:
        await db.close()


@router.get("/test-font")
async def test_font():
    """GET this in a browser to see exactly what font Playwright renders.
    Opens directly: https://takiapp-production.up.railway.app/api/test-font
    """
    from schemas.render import DMConversation, DMMessage
    conversation = DMConversation(
        contact_name="testuser",
        contact_verified=False,
        messages=[
            DMMessage(text="This is SF Pro Text", is_sender=False),
            DMMessage(text="Testing the font on Railway 😎🔥", is_sender=True),
            DMMessage(text="ABCDEFGHIJKLMNOPQRSTUVWXYZ", is_sender=False),
            DMMessage(text="abcdefghijklmnopqrstuvwxyz 0123456789", is_sender=True),
        ],
        theme="dark",
    )
    png_bytes = await renderer.render_slide(conversation)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/test-font-debug")
async def test_font_debug():
    """Returns JSON diagnostics about font loading on this server.
    Opens directly: https://takiapp-production.up.railway.app/api/test-font-debug
    """
    info = await renderer.get_font_debug_info()
    return info


@router.post("/projects/{project_id}/render-preview/{slide_id}")
async def render_preview(project_id: str, slide_id: str):
    """Render a single slide and return PNG."""
    conversation = await _build_conversation_for_slide(project_id, slide_id)
    png_bytes = await renderer.render_slide(conversation)
    return Response(content=png_bytes, media_type="image/png")


@router.post("/projects/{project_id}/render-all")
async def render_all_slides(project_id: str):
    """Render all active slides. Returns job_id."""
    job_id = await job_manager.create_job(project_id, "render")

    async def do_render(progress_callback):
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM slides WHERE project_id=? AND is_active=1 ORDER BY sort_order",
                (project_id,),
            )
            slide_rows = await cursor.fetchall()
        finally:
            await db.close()

        total = len(slide_rows)
        for i, slide_row in enumerate(slide_rows):
            sid = slide_row["id"]
            conversation = await _build_conversation_for_slide(project_id, sid)
            png_bytes = await renderer.render_slide(conversation)

            # Save rendered PNG — use slide UUID so filenames never collide across re-exports
            rendered_dir = PROJECTS_DIR / project_id / "rendered"
            rendered_dir.mkdir(exist_ok=True)
            out_path = rendered_dir / f"slide_{sid}.png"
            out_path.write_bytes(png_bytes)

            # Update slide with rendered path
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE slides SET rendered_path=? WHERE id=?",
                    (str(out_path), sid),
                )
                await db.commit()
            finally:
                await db.close()

            await progress_callback((i + 1) / total, f"Rendered slide {i + 1}/{total}")

    await job_manager.submit(job_id, do_render)
    return {"job_id": job_id}
