from fastapi import APIRouter
from pydantic import BaseModel

from database import get_db

router = APIRouter(tags=["settings"])


class AppSettings(BaseModel):
    openai_api_key: str = ""


@router.get("/settings", response_model=AppSettings)
async def get_settings():
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT openai_api_key FROM app_settings WHERE id=1"
        )).fetchone()
    finally:
        await db.close()
    if not row:
        return AppSettings()
    return AppSettings(
        openai_api_key=row["openai_api_key"] if row["openai_api_key"] else "",
    )


@router.put("/settings", response_model=AppSettings)
async def update_settings(body: AppSettings):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE app_settings SET openai_api_key=? WHERE id=1",
            (body.openai_api_key,),
        )
        await db.commit()
    finally:
        await db.close()
    return await get_settings()
