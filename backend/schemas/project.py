from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ProjectCreate(BaseModel):
    name: str


class ProjectUpdate(BaseModel):
    name: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    status: str
    source_url: Optional[str] = None
    pipeline_step: Optional[str] = None
    pipeline_error: Optional[str] = None
    thumbnail_path: Optional[str] = None
    created_at: str
    updated_at: str


class LibraryItem(BaseModel):
    id: str
    name: str
    created_at: str
    thumbnail_url: Optional[str] = None
    download_url: str
