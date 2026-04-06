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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await renderer.start()
    yield
    await renderer.stop()


app = FastAPI(title="ReelFactory", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
