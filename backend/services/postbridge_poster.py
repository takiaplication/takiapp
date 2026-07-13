"""
Post Bridge uploader — schedules finished reels on TikTok via the official
Post Bridge API (https://api.post-bridge.com/reference).

Flow per video:
  1. POST /v1/media/create-upload-url  {mime_type, size_bytes, name}
     → {media_id, upload_url}
  2. PUT the raw MP4 bytes to upload_url (signed URL, no auth header)
  3. POST /v1/posts {caption, scheduled_at, media:[media_id],
                     social_accounts:[tiktok_account_id]}

Scheduling: exactly one post per day, at a random minute between 12:00 and
19:00 Europe/Brussels. The next free day is derived from the maximum
scheduled_at already stored in the projects table, so queueing 20 reels in
one afternoon spreads them over the next 20 days automatically.

Env vars:
  POSTBRIDGE_API_KEY             pb_live_… key (Bearer auth). Absent → skip.
  POSTBRIDGE_TIKTOK_ACCOUNT_ID   optional; numeric id of the TikTok account.
                                 When unset the first connected TikTok
                                 account is auto-discovered via
                                 GET /v1/social-accounts.
  POSTBRIDGE_CAPTION             optional caption; default hashtags below.
  AUTO_POST_TIKTOK               set to "0" to disable posting without
                                 removing the API key.
"""

import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

API_BASE = "https://api.post-bridge.com/v1"
DEFAULT_CAPTION = "#rizz #texting #viral"

_BRUSSELS = ZoneInfo("Europe/Brussels")
_WINDOW_START_H = 12   # 12:00 Brussels
_WINDOW_END_H = 19     # 19:00 Brussels
_MIN_LEAD_MINUTES = 30  # never schedule closer than 30 min from now


class PostBridgeError(RuntimeError):
    """Raised on a real Post Bridge failure (not on 'not configured')."""


def is_configured() -> bool:
    return bool(
        os.environ.get("POSTBRIDGE_API_KEY", "").strip()
        and os.environ.get("AUTO_POST_TIKTOK", "1").strip() != "0"
    )


def _headers() -> dict:
    key = os.environ.get("POSTBRIDGE_API_KEY", "").strip()
    return {"Authorization": f"Bearer {key}"}


def compute_next_slot(last_scheduled_utc: Optional[datetime]) -> datetime:
    """
    Pick the next publish moment (returned as tz-aware UTC datetime):

      - one slot per calendar day (Brussels time)
      - random minute inside the 12:00–19:00 window
      - today is only used when the remaining window is still ≥30 min away
      - otherwise: the day after the last scheduled post (or tomorrow)
    """
    now_bxl = datetime.now(_BRUSSELS)

    # First candidate day: today, or the day after the latest scheduled post
    if last_scheduled_utc is not None:
        last_bxl = last_scheduled_utc.astimezone(_BRUSSELS)
        candidate = (last_bxl + timedelta(days=1)).date()
        if candidate < now_bxl.date():
            candidate = now_bxl.date()
    else:
        candidate = now_bxl.date()

    window_start = datetime(candidate.year, candidate.month, candidate.day,
                            _WINDOW_START_H, 0, tzinfo=_BRUSSELS)
    window_end = datetime(candidate.year, candidate.month, candidate.day,
                          _WINDOW_END_H, 0, tzinfo=_BRUSSELS)

    earliest = now_bxl + timedelta(minutes=_MIN_LEAD_MINUTES)
    effective_start = max(window_start, earliest)

    if effective_start >= window_end:
        # Today's window is gone — move to the next day, full window
        candidate = candidate + timedelta(days=1)
        window_start = datetime(candidate.year, candidate.month, candidate.day,
                                _WINDOW_START_H, 0, tzinfo=_BRUSSELS)
        window_end = datetime(candidate.year, candidate.month, candidate.day,
                              _WINDOW_END_H, 0, tzinfo=_BRUSSELS)
        effective_start = window_start

    # Random minute inside [effective_start, window_end)
    span_minutes = int((window_end - effective_start).total_seconds() // 60)
    offset = random.randint(0, max(span_minutes - 1, 0))
    slot_bxl = effective_start + timedelta(minutes=offset)
    return slot_bxl.astimezone(timezone.utc)


async def _discover_tiktok_account_id(client: httpx.AsyncClient) -> int:
    forced = os.environ.get("POSTBRIDGE_TIKTOK_ACCOUNT_ID", "").strip()
    if forced:
        return int(forced)

    resp = await client.get(f"{API_BASE}/social-accounts", headers=_headers())
    if resp.status_code != 200:
        raise PostBridgeError(
            f"Cannot list Post Bridge social accounts: "
            f"HTTP {resp.status_code} {resp.text[:300]}"
        )
    payload = resp.json()
    accounts = payload.get("data", payload) if isinstance(payload, dict) else payload
    for acc in accounts or []:
        platform = str(acc.get("platform", "")).lower()
        if "tiktok" in platform:
            return int(acc["id"])
    raise PostBridgeError(
        "No TikTok account connected in Post Bridge. Connect @takiaiofficial "
        "under Connections, or set POSTBRIDGE_TIKTOK_ACCOUNT_ID."
    )


async def schedule_post(
    mp4_path: Path,
    scheduled_at_utc: datetime,
    caption: Optional[str] = None,
) -> dict:
    """
    Upload the MP4 to Post Bridge and create a scheduled TikTok post.
    Returns {"post_id": str, "scheduled_at": iso_utc, "media_id": str}.
    Raises PostBridgeError on any failure.
    """
    if not mp4_path.exists():
        raise PostBridgeError(f"Local file not found: {mp4_path}")

    caption = caption or os.environ.get("POSTBRIDGE_CAPTION", "").strip() or DEFAULT_CAPTION
    size = mp4_path.stat().st_size

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
        account_id = await _discover_tiktok_account_id(client)

        # 1. signed upload URL
        r1 = await client.post(
            f"{API_BASE}/media/create-upload-url",
            headers=_headers(),
            json={"mime_type": "video/mp4", "size_bytes": size, "name": mp4_path.name},
        )
        if r1.status_code not in (200, 201):
            raise PostBridgeError(
                f"create-upload-url failed: HTTP {r1.status_code} {r1.text[:300]}"
            )
        up = r1.json()
        media_id, upload_url = up["media_id"], up["upload_url"]

        # 2. upload the raw bytes (signed URL — no auth header)
        with open(mp4_path, "rb") as fh:
            r2 = await client.put(
                upload_url,
                content=fh.read(),
                headers={"Content-Type": "video/mp4"},
            )
        if r2.status_code not in (200, 201, 204):
            raise PostBridgeError(
                f"media upload failed: HTTP {r2.status_code} {r2.text[:300]}"
            )

        # 3. create the scheduled post
        iso_utc = scheduled_at_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r3 = await client.post(
            f"{API_BASE}/posts",
            headers=_headers(),
            json={
                "caption": caption,
                "scheduled_at": iso_utc,
                "media": [media_id],
                "social_accounts": [account_id],
            },
        )
        if r3.status_code not in (200, 201):
            raise PostBridgeError(
                f"create post failed: HTTP {r3.status_code} {r3.text[:300]}"
            )
        post = r3.json()
        post_id = str(post.get("id") or (post.get("data") or {}).get("id") or "")

    print(
        f"[postbridge] scheduled '{mp4_path.name}' → post {post_id} "
        f"at {iso_utc} (account {account_id})"
    )
    return {"post_id": post_id, "scheduled_at": iso_utc, "media_id": media_id}


async def next_slot_from_db() -> datetime:
    """Read the latest scheduled_at from the DB and compute the next slot."""
    from database import get_db  # noqa: PLC0415

    db = await get_db()
    try:
        row = await (await db.execute(
            """SELECT MAX(scheduled_at) AS latest FROM projects
               WHERE scheduled_at IS NOT NULL AND scheduled_at != ''"""
        )).fetchone()
    finally:
        await db.close()

    last: Optional[datetime] = None
    if row and row["latest"]:
        try:
            raw = row["latest"].replace("Z", "+00:00")
            last = datetime.fromisoformat(raw)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        except ValueError:
            last = None
    return compute_next_slot(last)
