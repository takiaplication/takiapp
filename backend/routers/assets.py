import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from config import PROJECTS_DIR

router = APIRouter(tags=["assets"])


@router.post("/projects/{project_id}/upload-avatar")
async def upload_avatar(project_id: str, file: UploadFile = File(...)):
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    avatar_path = project_dir / "avatar.png"
    content = await file.read()
    avatar_path.write_bytes(content)

    return {"path": str(avatar_path)}


@router.post("/projects/{project_id}/upload-meme")
async def upload_meme(project_id: str, file: UploadFile = File(...)):
    meme_dir = PROJECTS_DIR / project_id / "memes"
    meme_dir.mkdir(exist_ok=True)

    filename = f"{uuid.uuid4()}{Path(file.filename).suffix}" if file.filename else f"{uuid.uuid4()}.png"
    meme_path = meme_dir / filename
    content = await file.read()
    meme_path.write_bytes(content)

    return {"path": str(meme_path), "filename": filename}


@router.post("/projects/{project_id}/upload-story")
async def upload_story(project_id: str, file: UploadFile = File(...)):
    stories_dir = PROJECTS_DIR / project_id / "stories"
    stories_dir.mkdir(exist_ok=True)

    suffix = Path(file.filename).suffix if file.filename else ".jpg"
    story_path = stories_dir / f"{uuid.uuid4()}{suffix}"
    content = await file.read()
    story_path.write_bytes(content)

    return {"path": str(story_path)}


@router.post("/projects/{project_id}/upload-music")
async def upload_music(project_id: str, file: UploadFile = File(...)):
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    music_path = project_dir / "music.mp3"
    content = await file.read()
    music_path.write_bytes(content)

    return {"path": str(music_path)}
