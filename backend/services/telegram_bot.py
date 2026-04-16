"""
Telegram bot service.

Polls the Telegram Bot API for new messages (long-polling, 30 s timeout).
When a message contains a TikTok or Instagram URL it submits it to the
ReelFactory pipeline and replies "✅ Toegevoegd aan queue".

Requires env var:  TELEGRAM_BOT_TOKEN
If the token is absent the bot is silently disabled — FastAPI starts normally.
"""

import asyncio
import os
import re
from typing import Optional

import httpx

# ── URL pattern ───────────────────────────────────────────────────────────────
# Matches TikTok (tiktok.com, vm.tiktok.com, vt.tiktok.com) and
# Instagram (instagram.com, instagr.am) URLs anywhere in a message.
_URL_RE = re.compile(
    r"https?://(?:www\.)?"
    r"(?:"
    r"tiktok\.com/\S+|"
    r"vm\.tiktok\.com/\S+|"
    r"vt\.tiktok\.com/\S+|"
    r"instagram\.com/\S+|"
    r"instagr\.am/\S+"
    r")",
    re.IGNORECASE,
)


async def start_bot() -> Optional[asyncio.Task]:
    """
    Start the Telegram polling loop as a background asyncio Task.
    Returns the Task (so the caller can cancel it on shutdown),
    or None when TELEGRAM_BOT_TOKEN is not set.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("[telegram] TELEGRAM_BOT_TOKEN not set — bot disabled")
        return None

    task = asyncio.create_task(_poll_loop(token), name="telegram-bot")
    print("[telegram] Bot started (long-polling)")
    return task


async def _poll_loop(token: str) -> None:
    """Long-poll the Telegram Bot API forever."""
    base_url = f"https://api.telegram.org/bot{token}"
    offset = 0

    # Separate client per poll cycle keeps connections clean across errors.
    while True:
        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                while True:
                    updates = await _get_updates(client, base_url, offset)
                    for update in updates:
                        offset = update["update_id"] + 1
                        asyncio.create_task(_handle_update(client, base_url, update))
        except asyncio.CancelledError:
            print("[telegram] Bot stopped")
            return
        except Exception as exc:
            print(f"[telegram] poll error — retrying in 5 s: {exc}")
            await asyncio.sleep(5)


async def _get_updates(client: httpx.AsyncClient, base_url: str, offset: int) -> list:
    """Call getUpdates with a 30-second long-poll timeout."""
    try:
        resp = await client.get(
            f"{base_url}/getUpdates",
            params={
                "offset": offset,
                "timeout": 30,
                "allowed_updates": ["message", "channel_post"],
            },
            timeout=35.0,  # slightly longer than Telegram's server-side timeout
        )
        data = resp.json()
        if data.get("ok"):
            return data.get("result", [])
    except httpx.ReadTimeout:
        pass  # normal — no messages in 30 s
    except Exception as exc:
        print(f"[telegram] getUpdates error: {exc}")
        await asyncio.sleep(2)
    return []


async def _handle_update(client: httpx.AsyncClient, base_url: str, update: dict) -> None:
    """Process a single Telegram update."""
    # Support both private/group messages and channel posts
    message = update.get("message") or update.get("channel_post")
    if not message:
        return

    chat_id = message["chat"]["id"]
    text = (message.get("text") or message.get("caption") or "").strip()

    if not text:
        return

    # Extract all TikTok / Instagram URLs from the message
    urls = list(dict.fromkeys(_URL_RE.findall(text)))  # deduplicate, preserve order
    if not urls:
        return

    # Submit to the pipeline (direct in-process call — no HTTP round-trip)
    try:
        from routers.pipeline_router import submit_pipeline, PipelineSubmitRequest  # noqa: PLC0415

        result = await submit_pipeline(PipelineSubmitRequest(urls=urls[:10]))
        queued = result.get("queued", len(urls))

        if queued == 1:
            reply = "✅ Toegevoegd aan queue"
        else:
            reply = f"✅ {queued} video's toegevoegd aan queue"

    except Exception as exc:
        print(f"[telegram] pipeline error for chat {chat_id}: {exc}")
        reply = f"❌ Fout bij toevoegen: {exc}"

    await _send_message(client, base_url, chat_id, reply)


async def _send_message(
    client: httpx.AsyncClient,
    base_url: str,
    chat_id: int,
    text: str,
) -> None:
    """Send a text reply to a Telegram chat."""
    try:
        await client.post(
            f"{base_url}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10.0,
        )
    except Exception as exc:
        print(f"[telegram] sendMessage error (chat {chat_id}): {exc}")
