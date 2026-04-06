import uuid
import shutil
from fastapi import APIRouter, HTTPException

from database import get_db
from config import PROJECTS_DIR
from schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse

router = APIRouter(tags=["projects"])


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
