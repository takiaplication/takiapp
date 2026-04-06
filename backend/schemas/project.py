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
    created_at: str
    updated_at: str
