import aiosqlite
from config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    source_url TEXT,
    video_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS slides (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL,
    slide_type TEXT DEFAULT 'dm',
    rendered_path TEXT,
    source_frame_path TEXT,
    is_active INTEGER DEFAULT 1,
    hold_duration_ms INTEGER DEFAULT 3000,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    slide_id TEXT NOT NULL REFERENCES slides(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL,
    sender TEXT NOT NULL DEFAULT 'other',
    text TEXT NOT NULL DEFAULT '',
    message_type TEXT DEFAULT 'text',
    show_timestamp INTEGER DEFAULT 0,
    timestamp_text TEXT,
    read_receipt TEXT,
    emoji_reaction TEXT,
    story_image_path TEXT,
    story_reply_label TEXT
);

CREATE TABLE IF NOT EXISTS render_settings (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    other_username TEXT DEFAULT 'user',
    other_avatar_path TEXT,
    other_verified INTEGER DEFAULT 0,
    self_username TEXT DEFAULT 'me',
    theme TEXT DEFAULT 'dark',
    transition_type TEXT DEFAULT 'crossfade',
    transition_duration_ms INTEGER DEFAULT 300,
    default_hold_duration_ms INTEGER DEFAULT 3000,
    output_fps INTEGER DEFAULT 30,
    background_music_path TEXT,
    music_volume REAL DEFAULT 0.3
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress REAL DEFAULT 0.0,
    progress_message TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    openai_api_key TEXT DEFAULT ''
);
INSERT OR IGNORE INTO app_settings (id, openai_api_key) VALUES (1, '');
"""


async def get_db() -> aiosqlite.Connection:
    # timeout=30: wait up to 30 s for any write lock to clear instead of
    # raising "database is locked" immediately.
    db = await aiosqlite.connect(str(DATABASE_PATH), timeout=30)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        # Migrations: add columns to existing DBs if they don't exist yet
        migrations = [
            ("messages", "story_image_path", "TEXT"),
            ("messages", "story_reply_label", "TEXT"),
            ("slides", "source_frame_path", "TEXT"),
            ("slides", "frame_type", "TEXT DEFAULT 'dm'"),
            ("slides", "extracted_clip_path", "TEXT"),
            ("slides", "meme_category", "TEXT"),
            ("projects", "source_url", "TEXT"),
            ("projects", "video_path", "TEXT"),
            ("projects", "pipeline_step", "TEXT"),
            ("projects", "pipeline_error", "TEXT"),
        ]
        for table, col, definition in migrations:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            except Exception:
                pass  # Column already exists
        await db.commit()
    finally:
        await db.close()
