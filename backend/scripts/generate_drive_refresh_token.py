#!/usr/bin/env python3
"""
One-shot helper — run this on your laptop to obtain a Google Drive OAuth
refresh token. Paste the output into Railway as GOOGLE_OAUTH_REFRESH_TOKEN.

Usage
-----
1. In Google Cloud Console → APIs & Services → Credentials → Create
   credentials → OAuth client ID → "Desktop app". Download the JSON,
   save it as `client_secret.json` next to this file.

2. Install the two dependencies (if you don't have them):
     pip install google-auth-oauthlib google-auth

3. Run:
     python generate_drive_refresh_token.py

   Your browser opens. Log in with the Gmail account whose Drive you
   want ReelFactory to upload into. Grant the permission.

4. The script prints your refresh_token. Copy it to Railway env vars:

     GOOGLE_OAUTH_CLIENT_SECRET_JSON  = <entire contents of client_secret.json>
     GOOGLE_OAUTH_REFRESH_TOKEN       = <the token this script printed>
     GOOGLE_DRIVE_FOLDER_ID           = <unchanged; your 'content' folder ID>

5. Redeploy. Drive uploads will now run as YOU, against your own 15 GB
   (or bigger) personal Drive quota — no service account storage issue.
"""

import json
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
except ImportError:
    sys.exit(
        "ERROR: `google_auth_oauthlib` is not installed.\n"
        "Run:   pip install google-auth-oauthlib google-auth"
    )

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

HERE = Path(__file__).resolve().parent
CLIENT_SECRET_PATH = HERE / "client_secret.json"


def main() -> int:
    if not CLIENT_SECRET_PATH.exists():
        print(
            f"ERROR: expected OAuth client secret at {CLIENT_SECRET_PATH}.\n"
            "Download it from Google Cloud Console and save it there."
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH), SCOPES
    )
    # `access_type=offline` + `prompt=consent` is what actually triggers a
    # refresh_token in the response. Without them Google returns only an
    # access_token that expires in an hour.
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
    )

    if not creds.refresh_token:
        print(
            "ERROR: Google did not return a refresh token. This usually "
            "happens when you've already granted consent to this client "
            "before. Revoke it at https://myaccount.google.com/permissions "
            "and run this script again."
        )
        return 2

    print("\n" + "=" * 70)
    print("SUCCESS — copy these two values into Railway env vars:")
    print("=" * 70)

    print("\n--- GOOGLE_OAUTH_REFRESH_TOKEN ---")
    print(creds.refresh_token)

    print("\n--- GOOGLE_OAUTH_CLIENT_SECRET_JSON ---")
    print(CLIENT_SECRET_PATH.read_text().strip())

    print("\n(Also make sure GOOGLE_DRIVE_FOLDER_ID is set to your 'content' folder ID.)")
    print(
        "\nDon't lose the refresh token — Google only shows it once per consent. "
        "If it goes stale after 6 months of inactivity, just run this script again."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
