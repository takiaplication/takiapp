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


async def _recover_stuck_exports() -> None:
    """
    On startup: find any project stuck at status='approved' without a finished
    output.mp4 and restart the export job so it completes automatically.
    """
    from database import get_db  # noqa: PLC0415
    from config import PROJECTS_DIR  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    from routers.compositor import _start_export_job  # noqa: PLC0415

    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT id FROM projects WHERE status='approved'"
        )).fetchall()
    finally:
        await db.close()

    for row in rows:
        pid = row["id"]
        output = PROJECTS_DIR / pid / "output.mp4"
        if not output.exists():
            try:
                await _start_export_job(pid)
            except Exception:
                pass  # will surface as error in the job


async def _recover_pipeline_queue() -> None:
    """
    On startup: re-queue projects that were in 'queue' or 'processing' when the
    server last shut down.  'processing' projects are reset to 'queue' so they
    restart cleanly from the beginning.  Projects are re-enqueued in the order
    they were originally created so the sequence is preserved.
    Processing always happens ONE AT A TIME through the single queue worker.
    """
    from database import get_db  # noqa: PLC0415
    from routers.pipeline_router import _queue, _ensure_worker  # noqa: PLC0415

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
        await _queue.put(row["id"])

    if rows:
        _ensure_worker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await renderer.start()
    await _recover_stuck_exports()
    await _recover_pipeline_queue()
    yield
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
