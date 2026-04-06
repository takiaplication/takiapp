from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
PROJECTS_DIR = STORAGE_DIR / "projects"
MEME_LIBRARY_DIR = STORAGE_DIR / "meme_library"   # shared Dutch meme library
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATABASE_PATH = STORAGE_DIR / "reelfactory.db"

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
MEME_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
