import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import STORAGE_DIR, MEME_LIBRARY_DIR
from database import init_db
from services.dm_renderer import renderer
from routers import projects, slides, messages, renderer as renderer_router, jobs, assets, compositor
from routers import import_router
from routers import app_settings as app_settings_router
from routers import meme_library_router
from routers import pipeline_router


async def _cleanup_library_intermediates() -> None:
    """
    One-shot sweep on startup: free disk space by deleting the intermediate
    files (source.mp4, frames/, rendered/) of every project that has already
    been uploaded to Drive. These files are kept during editing but are not
    needed once the MP4 is safely in Drive.
    """
    from database import get_db  # noqa: PLC0415
    from routers.compositor import cleanup_project_intermediates  # noqa: PLC0415

    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT id FROM projects WHERE status='library' AND drive_url IS NOT NULL"
        )).fetchall()
    finally:
        await db.close()

    total_freed = 0
    for row in rows:
        try:
            total_freed += cleanup_project_intermediates(row["id"])
        except Exception as exc:
            print(f"[cleanup-sweep] {row['id']}: {exc}")

    if total_freed > 0:
        print(f"[cleanup-sweep] freed {total_freed // (1024*1024)} MB from "
              f"{len(rows)} library projects")


async def _recover_stuck_exports() -> None:
    """
    On startup: find any project stuck at status='approved' without a Drive URL
    and re-queue the export job so it completes automatically.

    The previous filter only checked for missing output.mp4, which missed the
    common case where an export crashed mid-flight while showing
    'Wachten op andere export…' — those cards stayed forever stuck because
    nothing in-process re-submits them after a Railway redeploy.

    Re-queueing approved projects without a drive_url covers BOTH:
      - Projects that never finished a local export (no output.mp4)
      - Projects that finished locally but failed during Drive upload
    The fresh _EXPORT_LOCK in the new process serialises them correctly, and
    render-all is idempotent so already-rendered slides are skipped.
    """
    from database import get_db  # noqa: PLC0415
    from routers.compositor import _start_export_job  # noqa: PLC0415

    db = await get_db()
    try:
        rows = await (await db.execute(
            """SELECT id FROM projects
               WHERE status='approved'
               AND (drive_url IS NULL OR drive_url='')
               ORDER BY created_at ASC"""
        )).fetchall()
    finally:
        await db.close()

    for row in rows:
        pid = row["id"]
        try:
            await _start_export_job(pid)
        except Exception as exc:
            print(f"[recover-export] {pid}: {exc}")

    if rows:
        print(f"[recover-export] re-queued {len(rows)} stuck export(s)")


async def _recover_pipeline_queue() -> None:
    """
    On startup: re-queue projects that were in 'queue' or 'processing' when the
    server last shut down.  'processing' projects are reset to 'queue' so they
    restart cleanly from the beginning.  Projects are re-enqueued in the order
    they were originally created so the sequence is preserved.
    Processing always happens ONE AT A TIME through the single queue worker.
    """
    from database import get_db  # noqa: PLC0415
    from routers.pipeline_router import _safe_enqueue, _ensure_worker  # noqa: PLC0415

    db = await get_db()
    try:
        # Reset any half-finished 'processing' projects back to 'queue'
        await db.execute(
            """UPDATE projects
               SET status='queue', pipeline_step='In wachtrij…',
                   updated_at=CURRENT_TIMESTAMP
               WHERE status='processing'""",
        )
        await db.commit()

        # Collect all queued projects in submission order
        rows = await (await db.execute(
            """SELECT id FROM projects
               WHERE status='queue'
               ORDER BY created_at ASC"""
        )).fetchall()
    finally:
        await db.close()

    for row in rows:
        await _safe_enqueue(row["id"])

    if rows:
        _ensure_worker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from config import STORAGE_DIR, DATABASE_PATH, PROJECTS_DIR  # noqa: PLC0415
    print(f"[startup] STORAGE_DIR  = {STORAGE_DIR}")
    print(f"[startup] DATABASE     = {DATABASE_PATH}")
    print(f"[startup] PROJECTS_DIR = {PROJECTS_DIR}")
    await init_db()
    await renderer.start()
    # Reclaim disk space BEFORE doing anything else — this is critical on
    # Railway where the volume fills up with old source.mp4 / frames / PNGs
    # from projects already safely uploaded to Drive.
    await _cleanup_library_intermediates()
    await _recover_stuck_exports()
    await _recover_pipeline_queue()

    # Start Telegram bot (no-op if TELEGRAM_BOT_TOKEN is not set).
    # Wrapped in try/except so any import or runtime error is non-fatal and
    # can never prevent the FastAPI app from starting.
    telegram_task = None
    try:
        from services.telegram_bot import start_bot  # noqa: PLC0415
        telegram_task = await start_bot()
    except Exception as _tg_err:
        print(f"[telegram] failed to start (non-fatal): {_tg_err}")

    yield

    # Graceful shutdown
    if telegram_task and not telegram_task.done():
        telegram_task.cancel()
        try:
            await telegram_task
        except Exception:
            pass
    await renderer.stop()


app = FastAPI(title="ReelFactory", version="0.1.0", lifespan=lifespan)

# Build allowed origins: always include localhost dev server +
# any extra origins supplied via ALLOWED_ORIGINS env var (comma-separated)
_extra = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_origins = ["http://localhost:5173"] + _extra

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",   # all Vercel preview/prod URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory=str(STORAGE_DIR)), name="files")
app.mount("/meme-library", StaticFiles(directory=str(MEME_LIBRARY_DIR)), name="meme-library")

app.include_router(projects.router, prefix="/api")
app.include_router(slides.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(renderer_router.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(compositor.router, prefix="/api")
app.include_router(import_router.router, prefix="/api")
app.include_router(app_settings_router.router, prefix="/api")
app.include_router(meme_library_router.router, prefix="/api")
app.include_router(pipeline_router.router, prefix="/api")
