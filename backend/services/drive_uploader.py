"""
Google Drive uploader — supports both OAuth user credentials and service
account credentials.

================================================================
RECOMMENDED: OAuth user credentials (works with free Gmail)
================================================================
Set these three Railway env vars:

  GOOGLE_OAUTH_CLIENT_SECRET_JSON   JSON contents of the OAuth client
                                    (Desktop app) downloaded from Google
                                    Cloud Console → APIs & Services →
                                    Credentials.

  GOOGLE_OAUTH_REFRESH_TOKEN        Long-lived refresh token obtained by
                                    running
                                    `scripts/generate_drive_refresh_token.py`
                                    once on your laptop.

  GOOGLE_DRIVE_FOLDER_ID            ID of the Drive folder where daily
                                    sub-folders should be created. Can be
                                    a regular "My Drive" folder now —
                                    because uploads are done as YOU, not
                                    a service account, so they count
                                    against your own 15 GB quota.

Why: a service account has 0 GB of personal Drive storage. When it tries
to upload a file to a user's "My Drive" folder, Google creates the file
metadata but rejects the bytes with 'storageQuotaExceeded' — an empty
folder appears in your Drive and no video. OAuth sidesteps the problem
by acting as the user instead.

================================================================
FALLBACK: Service account credentials (requires Shared Drive)
================================================================
If GOOGLE_OAUTH_* are not set, the uploader falls back to:

  GOOGLE_SERVICE_ACCOUNT_JSON       JSON contents of a service account
                                    key.

This only works when GOOGLE_DRIVE_FOLDER_ID lives inside a **Shared
Drive** (Team Drive) and the service account is a member with
'Content manager' role. Shared Drives have their own storage pool
independent of the service account, so the 0 GB quota isn't an issue.

If neither OAuth nor service account credentials are configured the
upload is silently skipped and None is returned so the rest of the
export pipeline still works.
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


# ───────────────────────────────────────────────────────────────────────────
# Public API
# ───────────────────────────────────────────────────────────────────────────

async def upload_to_drive(mp4_path: Path, filename: str) -> Optional[str]:
    """
    Async wrapper — runs the blocking Google API calls in a thread.

    Returns:
      - None if Drive is not configured (missing env vars) → silent skip
      - the shareable Drive URL on success

    Raises:
      - DriveUploadError on any real failure.
    """
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    share_email = os.environ.get("GOOGLE_DRIVE_USER_EMAIL", "").strip() or None

    oauth_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_JSON", "").strip()
    oauth_refresh = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN", "").strip()
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    has_oauth = bool(oauth_secret and oauth_refresh)
    has_sa = bool(sa_json)

    if not folder_id or (not has_oauth and not has_sa):
        return None  # Drive not configured — skip silently

    if not mp4_path.exists():
        raise DriveUploadError(f"Local file not found: {mp4_path}")

    try:
        return await asyncio.to_thread(
            _upload_sync,
            mp4_path,
            filename,
            folder_id,
            share_email,
            oauth_secret if has_oauth else None,
            oauth_refresh if has_oauth else None,
            sa_json if has_sa else None,
        )
    except DriveUploadError:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise DriveUploadError(f"Drive upload failed: {exc}") from exc


# ───────────────────────────────────────────────────────────────────────────
# Credential helpers
# ───────────────────────────────────────────────────────────────────────────

def _build_oauth_credentials(client_secret_json: str, refresh_token: str):
    """
    Construct user OAuth credentials from the stored client secret JSON +
    refresh token. Access tokens are refreshed automatically when stale.
    """
    from google.oauth2.credentials import Credentials  # type: ignore
    from google.auth.transport.requests import Request  # type: ignore

    info = json.loads(client_secret_json)
    # Desktop-app client JSON nests under "installed"; web-app under "web".
    body = info.get("installed") or info.get("web") or info
    client_id = body["client_id"]
    client_secret = body["client_secret"]
    token_uri = body.get("token_uri", "https://oauth2.googleapis.com/token")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    # Force-refresh so subsequent calls don't race on it.
    creds.refresh(Request())
    return creds


def _build_sa_credentials(sa_json: str):
    from google.oauth2 import service_account  # type: ignore

    info = json.loads(sa_json)
    return service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive"],
    )


# ───────────────────────────────────────────────────────────────────────────
# Sync upload
# ───────────────────────────────────────────────────────────────────────────

def _upload_sync(
    mp4_path: Path,
    filename: str,
    parent_folder_id: str,
    share_email: Optional[str],
    oauth_secret: Optional[str],
    oauth_refresh: Optional[str],
    sa_json: Optional[str],
) -> str:
    from googleapiclient.discovery import build        # type: ignore
    from googleapiclient.errors import HttpError       # type: ignore
    from googleapiclient.http import MediaFileUpload   # type: ignore

    # Prefer OAuth (user credentials) over SA because it's the only way
    # writes to a personal 'My Drive' folder actually store bytes.
    if oauth_secret and oauth_refresh:
        credentials = _build_oauth_credentials(oauth_secret, oauth_refresh)
        auth_label = "oauth-user"
    else:
        credentials = _build_sa_credentials(sa_json or "")
        auth_label = (
            f"service-account ({json.loads(sa_json or '{}').get('client_email', '?')})"
        )

    service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    local_size = mp4_path.stat().st_size
    print(
        f"[drive] uploading '{filename}' "
        f"({local_size / (1024 * 1024):.1f} MB) "
        f"auth={auth_label} → parent_folder_id={parent_folder_id}"
    )

    # ── Verify parent folder is reachable + writable ──────────────────────
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
                f"No write access to folder {parent.get('name')!r} "
                f"({parent_folder_id}). Check credentials and folder sharing."
            )
    except HttpError as he:
        raise DriveUploadError(
            f"Cannot access GOOGLE_DRIVE_FOLDER_ID={parent_folder_id}. "
            f"Error: {he}"
        ) from he

    # ── Find or create the daily folder ──────────────────────────────────
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

    # ── Resumable upload ─────────────────────────────────────────────────
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
        if "storageQuotaExceeded" in body or "storage quota" in body.lower():
            if auth_label.startswith("service-account"):
                raise DriveUploadError(
                    "storageQuotaExceeded — the service account has 0 GB of "
                    "personal Drive storage. Set GOOGLE_OAUTH_CLIENT_SECRET_JSON "
                    "+ GOOGLE_OAUTH_REFRESH_TOKEN to upload as a real user, or "
                    "move GOOGLE_DRIVE_FOLDER_ID into a Shared Drive with the "
                    "service account as Content manager."
                ) from he
            raise DriveUploadError(
                "storageQuotaExceeded — your own Drive is full. Free up space "
                "in https://drive.google.com or buy more Google One storage."
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

    if reported_size == 0:
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
            f"Drive reports 0 bytes for uploaded file {file_id}. Likely a "
            "silent quota failure."
        )

    if reported_size != local_size:
        print(
            f"[drive] WARNING size mismatch — local={local_size} "
            f"drive={reported_size}"
        )

    # ── Optional: anyone-with-link reader ────────────────────────────────
    try:
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute()
    except Exception as perm_err:
        print(f"[drive] anyone-with-link permission failed (non-fatal): {perm_err}")

    # ── Optional: explicit share with the human user ─────────────────────
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
            print(f"[drive] explicit share failed (non-fatal): {share_err}")

    return response.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
