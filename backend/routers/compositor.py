import asyncio
import random
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from database import get_db
from config import PROJECTS_DIR, MEME_LIBRARY_DIR
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
                # ── Meme slide: pick a random file from the library category ──
                cat     = r["meme_category"] if "meme_category" in r.keys() and r["meme_category"] else "cooking"
                cat_dir = MEME_LIBRARY_DIR / cat
                _video_exts = {".mp4", ".mov", ".avi", ".webm"}
                _img_exts   = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
                _all_exts   = _video_exts | _img_exts
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

        # Mark project as 'library' once export succeeds
        db_done = await get_db()
        try:
            await db_done.execute(
                """UPDATE projects SET status='library', pipeline_step='Export klaar',
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (project_id,),
            )
            await db_done.commit()
        finally:
            await db_done.close()

        return str(output_path)

    await job_manager.submit(job_id, do_export)
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
