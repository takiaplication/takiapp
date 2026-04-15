from pydantic import BaseModel
from typing import Optional


class MessageCreate(BaseModel):
    sender: str = "other"
    text: str = ""
    message_type: str = "text"
    show_timestamp: bool = False
    timestamp_text: Optional[str] = None
    read_receipt: Optional[str] = None
    emoji_reaction: Optional[str] = None
    story_image_path: Optional[str] = None
    story_reply_label: Optional[str] = None
    story_group_id: Optional[str] = None


class MessageUpdate(BaseModel):
    sender: Optional[str] = None
    text: Optional[str] = None
    message_type: Optional[str] = None
    show_timestamp: Optional[bool] = None
    timestamp_text: Optional[str] = None
    read_receipt: Optional[str] = None
    emoji_reaction: Optional[str] = None
    story_image_path: Optional[str] = None
    story_reply_label: Optional[str] = None


class MessageResponse(BaseModel):
    id: str
    slide_id: str
    sort_order: int
    sender: str
    text: str
    message_type: str
    show_timestamp: bool
    timestamp_text: Optional[str] = None
    read_receipt: Optional[str] = None
    emoji_reaction: Optional[str] = None
    story_image_path: Optional[str] = None
    story_reply_label: Optional[str] = None
    content_hash: Optional[str] = None
    story_group_id: Optional[str] = None
