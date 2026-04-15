import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
FONTS_DIR = BASE_DIR / "fonts"

# ── Persistent storage ────────────────────────────────────────────────────────
# On Railway the volume is mounted at /app/storage.  Set STORAGE_PATH env var
# to point there (or any other persistent directory).  Falls back to
# <project_root>/storage for local development.
STORAGE_DIR = Path(os.environ.get("STORAGE_PATH", str(BASE_DIR / "storage")))
PROJECTS_DIR = STORAGE_DIR / "projects"
MEME_LIBRARY_DIR = STORAGE_DIR / "meme_library"   # shared Dutch meme library
DATABASE_PATH = STORAGE_DIR / "reelfactory.db"

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
MEME_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
