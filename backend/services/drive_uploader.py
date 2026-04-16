"""
Google Drive uploader.

Reads two environment variables:
  GOOGLE_SERVICE_ACCOUNT_JSON  — full JSON string of the service account key
  GOOGLE_DRIVE_FOLDER_ID       — ID of the parent folder in Drive

Uploads the MP4 into a daily sub-folder named YYYY-MM-DD (created on demand),
makes the file publicly readable, and returns the shareable Drive URL.

If either env var is missing the upload is silently skipped and None is returned
so the export still succeeds on setups without Drive configured.
"""

import asyncio
import json
import os
from datetime import date
from pathlib import Path
from typing import Optional


async def upload_to_drive(mp4_path: Path, filename: str) -> Optional[str]:
    """
    Async wrapper — runs the blocking Google API calls in a thread.
    Returns the shareable Drive URL, or None if Drive is not configured.
    """
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()

    if not sa_json or not folder_id:
        return None  # Drive not configured — skip silently

    return await asyncio.to_thread(_upload_sync, mp4_path, filename, sa_json, folder_id)


def _upload_sync(mp4_path: Path, filename: str, sa_json: str, parent_folder_id: str) -> str:
    """Blocking upload — runs inside asyncio.to_thread."""
    from google.oauth2 import service_account          # type: ignore
    from googleapiclient.discovery import build        # type: ignore
    from googleapiclient.http import MediaFileUpload   # type: ignore

    sa_info = json.loads(sa_json)
    credentials = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    # ── Find or create daily folder (YYYY-MM-DD) ──────────────────────────
    today = date.today().strftime("%Y-%m-%d")
    query = (
        f"name='{today}' and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"'{parent_folder_id}' in parents and "
        f"trashed=false"
    )
    results = service.files().list(q=query, fields="files(id)", pageSize=1).execute()
    folders = results.get("files", [])

    if folders:
        daily_folder_id = folders[0]["id"]
    else:
        folder_meta = {
            "name": today,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_folder_id],
        }
        folder = service.files().create(body=folder_meta, fields="id").execute()
        daily_folder_id = folder["id"]

    # ── Upload the MP4 ────────────────────────────────────────────────────
    file_meta = {"name": filename, "parents": [daily_folder_id]}
    media = MediaFileUpload(str(mp4_path), mimetype="video/mp4", resumable=True)
    uploaded = service.files().create(
        body=file_meta, media_body=media, fields="id"
    ).execute()
    file_id = uploaded["id"]

    # Make it readable by anyone with the link
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    return f"https://drive.google.com/file/d/{file_id}/view"
