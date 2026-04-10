from pydantic import BaseModel
from typing import Optional


class SlideCreate(BaseModel):
    slide_type: str = "dm"
    frame_type: str = "dm"
    hold_duration_ms: int = 3000


class SlideUpdate(BaseModel):
    hold_duration_ms: Optional[int] = None
    is_active: Optional[bool] = None
    slide_type: Optional[str] = None


class SlideReorderItem(BaseModel):
    id: str
    sort_order: int


class SlideReorder(BaseModel):
    slides: list[SlideReorderItem]


class SlideResponse(BaseModel):
    id: str
    project_id: str
    sort_order: int
    slide_type: str
    frame_type: str = "dm"                    # "dm" | "meme" | "app_ad"
    frame_url: Optional[str] = None           # URL of the currently active source
    extracted_clip_url: Optional[str] = None  # URL of the auto-extracted meme clip
    rendered_path: Optional[str] = None
    is_active: bool
    hold_duration_ms: int
    meme_category: Optional[str] = None       # e.g. "opening" | "cooking" | "succes" …
