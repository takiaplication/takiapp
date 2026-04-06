"""
Classify a frame image as 'dm' (Instagram DM conversation screen) or 'meme'.

Primary:  GPT-4o-mini vision — sends a tiny JPEG thumbnail to the API and asks
          "is this an Instagram DM screen or other content?".  Accurate, fast,
          ~$0.0001 per frame (low-detail mode).  Requires an OpenAI API key in
          the app_settings table or OPENAI_API_KEY env var.

Fallback: Heuristic colour analysis — used when no API key is configured or if
          the API call fails for any reason.
"""

import asyncio
import base64
import os
import cv2
import numpy as np
from typing import Literal

FrameType = Literal["dm", "meme", "app_ad"]


# ── API key helper ────────────────────────────────────────────────────────────

async def _get_api_key() -> str:
    """Resolve OpenAI key: DB first, then OPENAI_API_KEY env var."""
    try:
        from database import get_db  # noqa: PLC0415
        db = await get_db()
        try:
            row = await (await db.execute(
                "SELECT openai_api_key FROM app_settings WHERE id=1"
            )).fetchone()
            if row and row["openai_api_key"]:
                return row["openai_api_key"]
        finally:
            await db.close()
    except Exception:
        pass
    return os.getenv("OPENAI_API_KEY", "")


# ── Heuristic fallback ────────────────────────────────────────────────────────

_BLUE_LOWER        = np.array([185, 100,  10], dtype=np.uint8)  # Instagram sent-bubble
_BLUE_UPPER        = np.array([255, 200, 120], dtype=np.uint8)
_DARK_BUB_LOWER    = np.array([ 22,  22,  22], dtype=np.uint8)  # dark-mode received #262626
_DARK_BUB_UPPER    = np.array([ 65,  65,  65], dtype=np.uint8)
_LIGHT_BUB_LOWER   = np.array([220, 220, 220], dtype=np.uint8)  # light-mode received #EFEFEF
_LIGHT_BUB_UPPER   = np.array([248, 248, 248], dtype=np.uint8)


def _heuristic(image_path: str) -> FrameType:
    """Multi-layer heuristic — no external API needed."""
    img = cv2.imread(image_path)
    if img is None:
        return "meme"

    h, w = img.shape[:2]
    cs = max(h // 20, 10)

    # 1. Corner background brightness
    corners = np.vstack([
        img[:cs, :cs].reshape(-1, 3),
        img[:cs, w - cs:].reshape(-1, 3),
        img[h - cs:, :cs].reshape(-1, 3),
        img[h - cs:, w - cs:].reshape(-1, 3),
    ])
    bg_brightness = float(corners.mean())
    is_dark  = bg_brightness < 50
    is_light = bg_brightness > 200

    # App-ad frames (Plug AI, Aura AI, Taki …) have colourful gradient backgrounds
    # (purple, blue, pink) — neither dark nor light.  Detect by high colour saturation
    # in the corner pixels.  Plain meme backgrounds are usually unsaturated.
    if not (is_dark or is_light):
        hsv         = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        corner_hsv  = np.vstack([
            hsv[:cs, :cs].reshape(-1, 3),
            hsv[:cs, w - cs:].reshape(-1, 3),
            hsv[h - cs:, :cs].reshape(-1, 3),
            hsv[h - cs:, w - cs:].reshape(-1, 3),
        ])
        avg_sat = float(corner_hsv[:, 1].mean())   # saturation channel, 0–255
        if avg_sat > 80:   # purple/blue gradients score 120–200; plain photos < 60
            return "app_ad"
        return "meme"

    total_px = h * w

    # 2. Instagram blue sent-bubble
    if float(np.count_nonzero(cv2.inRange(img, _BLUE_LOWER, _BLUE_UPPER))) / total_px >= 0.002:
        return "dm"

    # 3. Receiver bubble colour in centre area
    if is_dark:
        centre = cv2.inRange(img, _DARK_BUB_LOWER, _DARK_BUB_UPPER)[cs: h - cs, cs: w - cs]
        if float(np.count_nonzero(centre)) / max((h - 2*cs) * (w - 2*cs), 1) >= 0.03:
            return "dm"
    else:
        if float(np.count_nonzero(cv2.inRange(img, _LIGHT_BUB_LOWER, _LIGHT_BUB_UPPER))) / total_px >= 0.04:
            return "dm"

    # 4. Background pixel dominance (≥40 % of image is pure bg colour)
    if is_dark:
        if int(np.sum(img.max(axis=2) < 18)) / total_px >= 0.40:
            return "dm"
    else:
        if int(np.sum(img.min(axis=2) > 235)) / total_px >= 0.40:
            return "dm"

    # 5. Bubble-column layout: bright/dark content concentrated in centre columns
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, tmask = cv2.threshold(
        gray,
        180 if is_dark else 75,
        255,
        cv2.THRESH_BINARY if is_dark else cv2.THRESH_BINARY_INV,
    )
    total_text = float(np.count_nonzero(tmask))
    if total_text >= 50:
        cx0, cx1 = int(w * 0.05), int(w * 0.95)
        if float(np.count_nonzero(tmask[:, cx0:cx1])) / total_text > 0.85:
            return "dm"

    return "meme"


# Sync alias — kept for any code that still calls classify_frame synchronously
def classify_frame(image_path: str) -> FrameType:
    return _heuristic(image_path)


# ── Primary: GPT-4o-mini vision ───────────────────────────────────────────────

_VISION_PROMPT = (
    "Look at this image carefully.\n\n"
    "Classify it as one of THREE types:\n\n"
    "1. dm — A plain Instagram (or similar) Direct Message conversation screen.\n"
    "   Signs: chat bubbles on a plain BLACK or WHITE background, contact name at top, "
    "   message input bar at bottom. No app branding, no coloured gradient background.\n\n"
    "2. app_ad — A screen from an AI chat assistant or DM helper app being shown in use.\n"
    "   STRONG signs (any one of these is enough):\n"
    "   - Colourful gradient background (purple, blue, pink, teal — NOT plain black or white)\n"
    "   - App name or brand at the top centre: e.g. 'Plug AI', 'Aura AI', 'Taki', 'Rizz AI', "
    "     'ChatGPT', or any other branded app name displayed as a title\n"
    "   - DM chat messages shown inside a dark ROUNDED RECTANGLE BOX (not full-screen)\n"
    "   - 'tap to copy' text visible below the chat area\n"
    "   - A large coloured pill or bar at the bottom with an AI-suggested reply or pickup line\n"
    "   - Navigation buttons (back arrow, lightning bolt, plus sign) in rounded square boxes "
    "     at the top corners of a colourful screen\n"
    "   Also counts as app_ad: App Store or Play Store download pages for any app.\n\n"
    "3. meme — Everything else: meme images, photos, video clips, text graphics, "
    "   reaction footage, face-to-camera clips, or any content that is not a DM or app screen.\n\n"
    "Reply with ONLY one word:  dm   OR   app_ad   OR   meme"
)


async def classify_frame_ai(image_path: str) -> FrameType:
    """
    Classify via GPT-4o-mini vision.  Falls back to the heuristic if
    no API key is configured or if the API call fails.
    """
    api_key = await _get_api_key()

    if not api_key:
        # No key — use heuristic in a thread (it's CPU-bound)
        return await asyncio.to_thread(_heuristic, image_path)

    # Resize to ≤512 px on the longest side before encoding (low-detail mode)
    img = cv2.imread(image_path)
    if img is None:
        return "meme"

    h, w = img.shape[:2]
    scale = min(512 / w, 768 / h, 1.0)
    small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))))
    _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
    b64 = base64.b64encode(buf.tobytes()).decode()

    def _call() -> FrameType:
        from openai import OpenAI  # noqa: PLC0415
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=5,
            temperature=0,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "low",
                        },
                    },
                    {"type": "text", "text": _VISION_PROMPT},
                ],
            }],
        )
        answer = resp.choices[0].message.content.strip().lower()
        if answer.startswith("dm"):
            return "dm"
        if "app_ad" in answer or answer.startswith("app"):
            return "app_ad"
        return "meme"

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        # Any API error → fall back to heuristic
        return await asyncio.to_thread(_heuristic, image_path)
