"""
app_settings.py
===============
The OpenAI API key is no longer stored in the database.
Set OPENAI_API_KEY as an environment variable on Railway instead.
This router is kept as a stub for any future settings.
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["settings"])


class AppSettings(BaseModel):
    pass


@router.get("/settings", response_model=AppSettings)
async def get_settings():
    return AppSettings()


@router.put("/settings", response_model=AppSettings)
async def update_settings(body: AppSettings):
    return AppSettings()
