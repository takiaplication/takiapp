"""
Google Drive uploader.

Reads two environment variables:
  GOOGLE_SERVICE_ACCOUNT_JSON  — full JSON string of the service account key
  GOOGLE_DRIVE_FOLDER_ID       — ID of the parent folder in Drive
                                 (can be a normal folder OR a Shared Drive folder)

Uploads the MP4 into a daily sub-folder named YYYY-MM-DD (created on demand),
makes the file publicly readable, and returns the shareable Drive URL.

If either env var is missing the upload is silently skipped and None is returned
so the export still succeeds on setups without Drive configured.

IMPORTANT: every call passes supportsAllDrives=True + includeItemsFromAllDrives=True
so the same code works on personal Drive, shared folders, AND Shared Drives.
"""

import asyncio
import json
import os
import traceback
from datetime import date
from pathlib import Path
from typing import Optional


async def upload_to_drive(mp4_path: Path, filename: str) -> Optional[str]:
    """
    Async wrapper — runs the blocking Google API calls in a thread.
    Returns the shareable Drive URL, or None if Drive is not configured
    or if the upload failed (error is logged; export still succeeds).
    """
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()

    if not sa_json or not folder_id:
        return None  # Drive not configured — skip silently

    if not mp4_path.exists():
        print(f"[drive] file not found: {mp4_path}")
        return None

    try:
        return await asyncio.to_thread(_upload_sync, mp4_path, filename, sa_json, folder_id)
    except Exception as exc:
        print(f"[drive] upload failed: {exc}")
        traceback.print_exc()
        return None


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

    file_size_mb = mp4_path.stat().st_size / (1024 * 1024)
    print(f"[drive] uploading {filename} ({file_size_mb:.1f} MB) → parent {parent_folder_id}")

    # ── Find or create daily folder (YYYY-MM-DD) ──────────────────────────
    today = date.today().strftime("%Y-%m-%d")
    # Escape single quotes in the name per Drive API v3 query syntax
    safe_today = today.replace("'", "\\'")
    query = (
        f"name='{safe_today}' and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"'{parent_folder_id}' in parents and "
        f"trashed=false"
    )
    results = service.files().list(
        q=query,
        fields="files(id, name)",
        pageSize=1,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    folders = results.get("files", [])

    if folders:
        daily_folder_id = folders[0]["id"]
        print(f"[drive] reusing daily folder {today} (id={daily_folder_id})")
    else:
        folder_meta = {
            "name": today,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_folder_id],
        }
        folder = service.files().create(
            body=folder_meta,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        daily_folder_id = folder["id"]
        print(f"[drive] created daily folder {today} (id={daily_folder_id})")

    # ── Upload the MP4 ────────────────────────────────────────────────────
    file_meta = {"name": filename, "parents": [daily_folder_id]}
    media = MediaFileUpload(
        str(mp4_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=8 * 1024 * 1024,  # 8 MB chunks
    )

    request = service.files().create(
        body=file_meta,
        media_body=media,
        fields="id, name, size, parents, webViewLink",
        supportsAllDrives=True,
    )

    # Drive the resumable upload to completion manually so we get real
    # progress reporting and so we notice if it stalls. next_chunk()
    # returns (status, response) where response is None until the final
    # chunk completes.
    response = None
    while response is None:
        status, response = request.next_chunk(num_retries=3)
        if status:
            print(f"[drive] upload progress: {int(status.progress() * 100)}%")

    file_id = response["id"]
    print(
        f"[drive] upload complete: id={file_id} name={response.get('name')} "
        f"size={response.get('size')} parents={response.get('parents')}"
    )

    # ── Sanity check: the file really is inside the daily folder ─────────
    try:
        got = service.files().get(
            fileId=file_id,
            fields="id, parents, size, trashed",
            supportsAllDrives=True,
        ).execute()
        if daily_folder_id not in (got.get("parents") or []):
            print(
                f"[drive] WARNING: uploaded file parents={got.get('parents')} "
                f"does not include expected folder {daily_folder_id}"
            )
        if got.get("trashed"):
            print("[drive] WARNING: uploaded file is trashed")
    except Exception as ver_err:
        print(f"[drive] verify step failed (non-fatal): {ver_err}")

    # ── Make the file readable by anyone with the link ───────────────────
    try:
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute()
    except Exception as perm_err:
        # Not fatal — on some Shared Drives anyone-with-link is disallowed
        # by admin policy. The file still exists and is shareable with the
        # Drive's members; we just can't flip it to public-read.
        print(f"[drive] could not set public-read permission (non-fatal): {perm_err}")

    # Prefer the webViewLink returned by the API — it's the canonical URL
    # that respects Shared Drive context. Fall back to the classic pattern.
    return response.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
