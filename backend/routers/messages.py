import uuid
from fastapi import APIRouter, HTTPException

from database import get_db
from schemas.message import MessageCreate, MessageUpdate, MessageResponse

router = APIRouter(tags=["messages"])


@router.get("/projects/{project_id}/slides/{slide_id}/messages", response_model=list[MessageResponse])
async def list_messages(project_id: str, slide_id: str):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM messages WHERE slide_id=? ORDER BY sort_order",
            (slide_id,),
        )
        rows = await cursor.fetchall()
        return [
            {**dict(r), "show_timestamp": bool(r["show_timestamp"])}
            for r in rows
        ]
    finally:
        await db.close()


@router.put("/projects/{project_id}/slides/{slide_id}/messages")
async def replace_messages(project_id: str, slide_id: str, messages: list[MessageCreate]):
    db = await get_db()
    try:
        # Delete existing messages
        await db.execute("DELETE FROM messages WHERE slide_id=?", (slide_id,))

        # Insert new messages
        for i, msg in enumerate(messages):
            msg_id = str(uuid.uuid4())
            await db.execute(
                """INSERT INTO messages (id, slide_id, sort_order, sender, text, message_type,
                   show_timestamp, timestamp_text, read_receipt, emoji_reaction,
                   story_image_path, story_reply_label)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg_id, slide_id, i, msg.sender, msg.text, msg.message_type,
                    int(msg.show_timestamp), msg.timestamp_text, msg.read_receipt, msg.emoji_reaction,
                    msg.story_image_path, msg.story_reply_label,
                ),
            )
        # Invalidate the cached render for this slide.
        # The export pipeline skips re-rendering when rendered_path exists.
        # Any message edit (especially adding/changing a story image) must
        # clear the cache so the next export picks up the new content.
        await db.execute(
            "UPDATE slides SET rendered_path=NULL WHERE id=?", (slide_id,)
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "count": len(messages)}


@router.patch("/projects/{project_id}/messages/{message_id}", response_model=MessageResponse)
async def update_message(project_id: str, message_id: str, data: MessageUpdate):
    db = await get_db()
    try:
        updates = []
        params = []
        for field in ["sender", "text", "message_type", "timestamp_text", "read_receipt", "emoji_reaction", "story_image_path", "story_reply_label"]:
            val = getattr(data, field, None)
            if val is not None:
                updates.append(f"{field}=?")
                params.append(val)
        if data.show_timestamp is not None:
            updates.append("show_timestamp=?")
            params.append(int(data.show_timestamp))

        if updates:
            params.append(message_id)
            await db.execute(
                f"UPDATE messages SET {', '.join(updates)} WHERE id=?",
                params,
            )
            # Invalidate the cached render of the parent slide
            await db.execute(
                "UPDATE slides SET rendered_path=NULL WHERE id=("
                "SELECT slide_id FROM messages WHERE id=?)",
                (message_id,),
            )
            await db.commit()

        cursor = await db.execute("SELECT * FROM messages WHERE id=?", (message_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Message not found")
        return {**dict(row), "show_timestamp": bool(row["show_timestamp"])}
    finally:
        await db.close()
