"""
Google Drive uploader.

Reads these environment variables:
  GOOGLE_SERVICE_ACCOUNT_JSON  — full JSON string of the service account key
  GOOGLE_DRIVE_FOLDER_ID       — ID of the parent folder in Drive
                                 (works best with a Shared Drive folder)
  GOOGLE_DRIVE_USER_EMAIL      — (optional) email to share each uploaded file
                                 with, so you always see the file in your own
                                 Drive UI even when the SA owns it

Uploads the MP4 into a daily sub-folder named YYYY-MM-DD (created on demand)
and returns the shareable Drive URL.

IMPORTANT — service account quota gotcha
----------------------------------------
A Google service account has **0 GB of personal Drive storage**. If you point
GOOGLE_DRIVE_FOLDER_ID at a folder inside a user's personal "My Drive", Google
creates folder/file *metadata* successfully but rejects the actual upload bytes
with `storageQuotaExceeded`. Result: an empty daily folder and no video.

Fix: either
  1. Put GOOGLE_DRIVE_FOLDER_ID inside a **Shared Drive** (Team Drive) and add
     the service account as a member with "Content manager" role — Shared
     Drives have their own storage pool independent of the SA.
  2. Or switch to OAuth with a user refresh token.

This module tries to detect the quota failure and raises DriveUploadError
with a clear remediation hint so the failure is surfaced to the user.
"""

import asyncio
import json
import os
import traceback
from datetime import date
from pathlib import Path
from typing import Optional


class DriveUploadError(RuntimeError):
    """Raised on a real Drive upload failure (not on 'Drive not configured')."""


async def upload_to_drive(mp4_path: Path, filename: str) -> Optional[str]:
    """
    Async wrapper — runs the blocking Google API calls in a thread.

    Returns:
      - None if Drive is not configured (missing env vars) → silent skip
      - the shareable Drive URL on success

    Raises:
      - DriveUploadError on any real failure (quota, permission, size mismatch,
        network). The caller should catch this and surface the message to the
        user rather than silently dropping it.
    """
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    share_email = os.environ.get("GOOGLE_DRIVE_USER_EMAIL", "").strip() or None

    if not sa_json or not folder_id:
        return None  # Drive not configured — skip silently

    if not mp4_path.exists():
        raise DriveUploadError(f"Local file not found: {mp4_path}")

    try:
        return await asyncio.to_thread(
            _upload_sync, mp4_path, filename, sa_json, folder_id, share_email
        )
    except DriveUploadError:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise DriveUploadError(f"Drive upload failed: {exc}") from exc


def _upload_sync(
    mp4_path: Path,
    filename: str,
    sa_json: str,
    parent_folder_id: str,
    share_email: Optional[str],
) -> str:
    """Blocking upload — runs inside asyncio.to_thread."""
    from google.oauth2 import service_account          # type: ignore
    from googleapiclient.discovery import build        # type: ignore
    from googleapiclient.errors import HttpError       # type: ignore
    from googleapiclient.http import MediaFileUpload   # type: ignore

    sa_info = json.loads(sa_json)
    sa_email = sa_info.get("client_email", "<unknown>")
    credentials = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    local_size = mp4_path.stat().st_size
    print(
        f"[drive] uploading '{filename}' "
        f"({local_size / (1024 * 1024):.1f} MB) "
        f"SA={sa_email} → parent_folder_id={parent_folder_id}"
    )

    # ── Step 0: verify the parent folder is reachable and identify drive type
    try:
        parent = service.files().get(
            fileId=parent_folder_id,
            fields="id, name, driveId, mimeType, capabilities",
            supportsAllDrives=True,
        ).execute()
        in_shared_drive = bool(parent.get("driveId"))
        can_add_children = (parent.get("capabilities") or {}).get("canAddChildren", False)
        print(
            f"[drive] parent folder: name={parent.get('name')!r} "
            f"shared_drive={in_shared_drive} canAddChildren={can_add_children}"
        )
        if not can_add_children:
            raise DriveUploadError(
                f"Service account {sa_email} cannot write to folder "
                f"{parent.get('name')!r} ({parent_folder_id}). "
                "Grant it 'Content manager' / 'Editor' access on the folder."
            )
    except HttpError as he:
        raise DriveUploadError(
            f"Cannot access GOOGLE_DRIVE_FOLDER_ID={parent_folder_id}. "
            f"Did you share the folder with {sa_email}? Error: {he}"
        ) from he

    # ── Step 1: find or create the daily folder (YYYY-MM-DD) ─────────────
    today = date.today().strftime("%Y-%m-%d")
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
        folder = service.files().create(
            body={
                "name": today,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_folder_id],
            },
            fields="id",
            supportsAllDrives=True,
        ).execute()
        daily_folder_id = folder["id"]
        print(f"[drive] created daily folder {today} (id={daily_folder_id})")

    # ── Step 2: resumable upload, chunked, with progress logging ─────────
    media = MediaFileUpload(
        str(mp4_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=8 * 1024 * 1024,
    )
    request = service.files().create(
        body={"name": filename, "parents": [daily_folder_id]},
        media_body=media,
        fields="id, name, size, parents, webViewLink",
        supportsAllDrives=True,
    )

    response = None
    try:
        while response is None:
            status, response = request.next_chunk(num_retries=3)
            if status:
                print(f"[drive] upload progress: {int(status.progress() * 100)}%")
    except HttpError as he:
        body = ""
        try:
            body = he.content.decode("utf-8", errors="replace")
        except Exception:
            pass
        # Detect the SA-on-personal-Drive quota failure and give a real fix.
        if "storageQuotaExceeded" in body or "storage quota" in body.lower():
            raise DriveUploadError(
                "Google Drive refused the upload with 'storageQuotaExceeded'. "
                "A service account has 0 GB of personal Drive storage, so it "
                "cannot write file bytes into a folder that lives in a user's "
                "'My Drive'. Fix: move GOOGLE_DRIVE_FOLDER_ID to a Shared "
                f"Drive (Team Drive) and add {sa_email} as 'Content manager'. "
                "Folder creation works because metadata is free; file upload "
                "needs actual storage."
            ) from he
        raise DriveUploadError(
            f"Drive upload HTTP error: {he.status_code} {he.reason}. "
            f"Response body: {body[:400]}"
        ) from he

    file_id = response["id"]
    reported_size = int(response.get("size") or 0)
    print(
        f"[drive] upload complete: id={file_id} name={response.get('name')} "
        f"size={reported_size} parents={response.get('parents')}"
    )

    # ── Step 3: verify the file actually has bytes in it ─────────────────
    # Some failure modes leave a metadata-only file behind with size=0.
    if reported_size == 0:
        # Double-check via a fresh get() before we raise, in case the create
        # response just didn't include the size field populated yet.
        try:
            check = service.files().get(
                fileId=file_id,
                fields="id, size, parents, trashed",
                supportsAllDrives=True,
            ).execute()
            reported_size = int(check.get("size") or 0)
        except Exception as ver_err:
            print(f"[drive] verify-size failed: {ver_err}")

    if reported_size == 0:
        raise DriveUploadError(
            f"Drive reports 0 bytes for uploaded file {file_id}. "
            "This usually means the service account's storage quota was "
            "exhausted and Drive stored only the metadata, not the content. "
            "Use a Shared Drive — see the comment at the top of "
            "drive_uploader.py for the full fix."
        )

    if reported_size != local_size:
        print(
            f"[drive] WARNING size mismatch — local={local_size} "
            f"drive={reported_size} (usually fine, Drive may round)"
        )

    # ── Step 4: optional 'anyone-with-link reader' permission ────────────
    try:
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute()
    except Exception as perm_err:
        print(f"[drive] anyone-with-link permission failed (non-fatal): {perm_err}")

    # ── Step 5: optional explicit share with the human user ──────────────
    if share_email:
        try:
            service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": "reader", "emailAddress": share_email},
                sendNotificationEmail=False,
                supportsAllDrives=True,
            ).execute()
            print(f"[drive] shared file with {share_email}")
        except Exception as share_err:
            print(f"[drive] explicit share with {share_email} failed (non-fatal): {share_err}")

    return response.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
