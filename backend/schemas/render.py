from pydantic import BaseModel
from typing import Optional


class RenderSettings(BaseModel):
    other_username: str = "user"
    other_avatar_path: Optional[str] = None
    other_verified: bool = False
    self_username: str = "me"
    theme: str = "dark"
    transition_type: str = "crossfade"
    transition_duration_ms: int = 300
    default_hold_duration_ms: int = 3000
    output_fps: int = 30
    background_music_path: Optional[str] = None
    music_volume: float = 0.3


class RenderSettingsUpdate(BaseModel):
    other_username: Optional[str] = None
    other_avatar_path: Optional[str] = None
    other_verified: Optional[bool] = None
    self_username: Optional[str] = None
    theme: Optional[str] = None
    transition_type: Optional[str] = None
    transition_duration_ms: Optional[int] = None
    default_hold_duration_ms: Optional[int] = None
    output_fps: Optional[int] = None
    background_music_path: Optional[str] = None
    music_volume: Optional[float] = None


class DMMessage(BaseModel):
    text: str
    is_sender: bool
    show_timestamp: bool = False
    timestamp_text: Optional[str] = None
    read_receipt: Optional[str] = None
    emoji_reaction: Optional[str] = None
    story_image_base64: Optional[str] = None
    story_reply_label: Optional[str] = None


class DMConversation(BaseModel):
    contact_name: str = "user"
    contact_avatar_base64: Optional[str] = None
    contact_verified: bool = False
    active_status: Optional[str] = None
    messages: list[DMMessage] = []
    theme: str = "dark"
    status_bar_time: str = "9:41"
    battery_percent: int = 100
    show_typing: bool = False
