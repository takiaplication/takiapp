import hashlib
import uuid
from fastapi import APIRouter, HTTPException

from database import get_db
from schemas.message import MessageCreate, MessageUpdate, MessageResponse

router = APIRouter(tags=["messages"])


def _content_hash(sender: str, text: str) -> str:
    """Deterministic short hash — identical sender+text across slides share the same hash."""
    key = f"{sender}|{text.strip()}".encode()
    return hashlib.sha256(key).hexdigest()[:12]


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
        # ── 1. Snapshot old messages (need content_hash for cross-slide sync)
        old_cursor = await db.execute(
            "SELECT sort_order, sender, text, content_hash FROM messages WHERE slide_id=? ORDER BY sort_order",
            (slide_id,),
        )
        old_msgs = [dict(r) for r in await old_cursor.fetchall()]

        # ── 2. Delete old, insert new with content_hash
        await db.execute("DELETE FROM messages WHERE slide_id=?", (slide_id,))

        for i, msg in enumerate(messages):
            msg_id = str(uuid.uuid4())
            c_hash = _content_hash(msg.sender, msg.text)
            sg_id = getattr(msg, "story_group_id", None)
            await db.execute(
                """INSERT INTO messages (id, slide_id, sort_order, sender, text, message_type,
                   show_timestamp, timestamp_text, read_receipt, emoji_reaction,
                   story_image_path, story_reply_label, content_hash, story_group_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg_id, slide_id, i, msg.sender, msg.text, msg.message_type,
                    int(msg.show_timestamp), msg.timestamp_text, msg.read_receipt, msg.emoji_reaction,
                    msg.story_image_path, msg.story_reply_label, c_hash, sg_id,
                ),
            )

        # ── 3. Cross-slide sync: text changes via content_hash
        #    Match old→new by sort_order. If text/sender changed, update all
        #    sibling messages on other slides that share the old content_hash.
        for i, msg in enumerate(messages):
            if i >= len(old_msgs):
                break
            old = old_msgs[i]
            old_hash = old.get("content_hash")
            if not old_hash:
                continue
            if msg.text != old["text"] or msg.sender != old["sender"]:
                new_hash = _content_hash(msg.sender, msg.text)
                sib_cursor = await db.execute(
                    """SELECT m.id, m.slide_id FROM messages m
                       JOIN slides s ON s.id = m.slide_id
                       WHERE s.project_id=? AND m.content_hash=? AND m.slide_id!=?""",
                    (project_id, old_hash, slide_id),
                )
                for sib in await sib_cursor.fetchall():
                    await db.execute(
                        "UPDATE messages SET text=?, sender=?, content_hash=? WHERE id=?",
                        (msg.text, msg.sender, new_hash, sib["id"]),
                    )
                    await db.execute(
                        "UPDATE slides SET rendered_path=NULL WHERE id=?",
                        (sib["slide_id"],),
                    )

        # ── 4. Cross-slide sync: story images via story_group_id
        for msg in messages:
            sg_id = getattr(msg, "story_group_id", None)
            if sg_id and msg.story_image_path:
                await db.execute(
                    """UPDATE messages SET story_image_path=?
                       WHERE story_group_id=? AND message_type='story_reply'
                       AND slide_id IN (
                           SELECT id FROM slides WHERE project_id=?
                       ) AND slide_id!=?""",
                    (msg.story_image_path, sg_id, project_id, slide_id),
                )
                await db.execute(
                    """UPDATE slides SET rendered_path=NULL
                       WHERE id IN (
                           SELECT DISTINCT slide_id FROM messages
                           WHERE story_group_id=? AND slide_id IN (
                               SELECT id FROM slides WHERE project_id=?
                           ) AND slide_id!=?
                       )""",
                    (sg_id, project_id, slide_id),
                )

        # Invalidate the cached render for this slide.
        await db.execute(
            "UPDATE slides SET rendered_path=NULL WHERE id=?", (slide_id,)
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "count": len(messages)}


@router.patch("/projects/{project_id}/messages/{message_id}", response_model=MessageResponse)
async def update_message(project_id: str, message_id: str, data: MessageUpdate):
    """Update a single message. If the text or sender changes, all messages in
    the same project that shared the OLD content_hash are updated too (cross-slide sync)."""
    db = await get_db()
    try:
        # Fetch current message (need old hash + project context)
        cursor = await db.execute(
            """SELECT m.*, s.project_id FROM messages m
               JOIN slides s ON s.id = m.slide_id
               WHERE m.id=?""",
            (message_id,),
        )
        old_row = await cursor.fetchone()
        if not old_row:
            raise HTTPException(status_code=404, detail="Message not found")

        old_hash = old_row["content_hash"]
        project_id_db = old_row["project_id"]

        # Build the update for this message
        updates = []
        params = []
        text_changed = False
        new_text = old_row["text"]
        new_sender = old_row["sender"]

        for field in ["sender", "text", "message_type", "timestamp_text", "read_receipt",
                       "emoji_reaction", "story_image_path", "story_reply_label"]:
            val = getattr(data, field, None)
            if val is not None:
                updates.append(f"{field}=?")
                params.append(val)
                if field == "text":
                    text_changed = True
                    new_text = val
                if field == "sender":
                    text_changed = True
                    new_sender = val
        if data.show_timestamp is not None:
            updates.append("show_timestamp=?")
            params.append(int(data.show_timestamp))

        if updates:
            # Recompute content_hash if text or sender changed
            if text_changed:
                new_hash = _content_hash(new_sender, new_text)
                updates.append("content_hash=?")
                params.append(new_hash)

                # ── CROSS-SLIDE SYNC ──────────────────────────────────
                # Find all OTHER messages in the same project with the same
                # old content_hash and update their text + hash too.
                if old_hash:
                    sync_cursor = await db.execute(
                        """SELECT m.id, m.slide_id FROM messages m
                           JOIN slides s ON s.id = m.slide_id
                           WHERE s.project_id=? AND m.content_hash=? AND m.id!=?""",
                        (project_id_db, old_hash, message_id),
                    )
                    siblings = await sync_cursor.fetchall()
                    for sib in siblings:
                        await db.execute(
                            "UPDATE messages SET text=?, sender=?, content_hash=? WHERE id=?",
                            (new_text, new_sender, new_hash, sib["id"]),
                        )
                        # Invalidate sibling slide renders
                        await db.execute(
                            "UPDATE slides SET rendered_path=NULL WHERE id=?",
                            (sib["slide_id"],),
                        )

            # Update the target message itself
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


@router.patch("/projects/{project_id}/story-image")
async def update_story_image(project_id: str, story_group_id: str, story_image_path: str):
    """Set the story image for ALL messages that share the same story_group_id.
    When a user adds a story photo on one slide, it propagates to all related slides."""
    db = await get_db()
    try:
        await db.execute(
            """UPDATE messages SET story_image_path=?
               WHERE story_group_id=? AND message_type='story_reply'
               AND slide_id IN (
                   SELECT id FROM slides WHERE project_id=?
               )""",
            (story_image_path, story_group_id, project_id),
        )
        # Invalidate all affected slide renders
        await db.execute(
            """UPDATE slides SET rendered_path=NULL
               WHERE id IN (
                   SELECT DISTINCT slide_id FROM messages
                   WHERE story_group_id=? AND slide_id IN (
                       SELECT id FROM slides WHERE project_id=?
                   )
               )""",
            (story_group_id, project_id),
        )
        await db.commit()
        return {"ok": True, "story_group_id": story_group_id}
    finally:
        await db.close()
