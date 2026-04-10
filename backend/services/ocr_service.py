import asyncio
import base64
import json
import re
from typing import List, Dict, Any, Tuple

# ── GPT-4o Vision OCR (primary) ───────────────────────────────────────────────

_VISION_SYSTEM = """\
Je analyseert een Instagram Direct Message (DM) screenshot.

EXTRAHEER: Alleen de tekst van echte berichtbubbels (de daadwerkelijke conversatie).
AFZENDER: 'self' = rechts-uitgelijnd blauw bubbel (verstuurd), 'other' = links-uitgelijnd grijs/donker bubbel (ontvangen).
TEKST: Geef de originele tekst EXACT terug zoals die in het screenshot staat — GEEN vertaling, GEEN aanpassing.
  - Bewaar alle emojis exact zoals ze zijn.

NEGEER VOLLEDIG (NIET opnemen in output):
  - Header: gebruikersnaam, terugpijl, profielfoto, bel/video-icoontjes
  - Invoerbalk onderaan: "Message...", verzendknop
  - Tijdstempels: "10:42", "Gisteren", "Vandaag", "5 min geleden", datums
  - Leesbevestigingen: "Seen", "Delivered", "Gezien"
  - Statuslabels: "Active now", "Active today"
  - Verhaalantwoord-labels: "Replied to your story", "Reageerde op je verhaal"
    → detecteer die als has_story_reply: true

Geef ALLEEN geldige JSON terug (geen markdown, geen uitleg):
{
  "messages": [
    {"sender": "self", "text": "original text"},
    {"sender": "other", "text": "original text"}
  ],
  "has_story_reply": false
}

Berichten in volgorde van boven naar beneden. Geen berichten gevonden? {"messages": [], "has_story_reply": false}\
"""


async def extract_messages_vision(
    image_path: str,
    api_key: str,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Primary OCR path: one GPT-4o call per frame.

    Does OCR + sender classification + Dutch translation + story-reply detection
    all in a single API call.

    Returns:
        messages        -- [{"sender": "self"|"other", "text": "...dutch..."}]
        has_story_reply -- True if a story-reply layout should be used
    """
    import cv2  # noqa: PLC0415

    img = cv2.imread(image_path)
    if img is None:
        return [], False

    # Encode as JPEG — keep at native resolution so text stays legible
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    b64 = base64.b64encode(buf.tobytes()).decode()

    def _call() -> str:
        from openai import OpenAI  # noqa: PLC0415
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=1200,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _VISION_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": "high",   # needed to read small text
                            },
                        },
                        {"type": "text", "text": "Analyseer dit DM screenshot."},
                    ],
                },
            ],
        )
        return resp.choices[0].message.content.strip()

    try:
        raw = await asyncio.to_thread(_call)
        data = json.loads(raw)
        messages = [
            {"sender": m.get("sender", "other"), "text": m.get("text", "").strip()}
            for m in data.get("messages", [])
            if m.get("text", "").strip()
        ]
        has_story_reply = bool(data.get("has_story_reply", False))
        return messages, has_story_reply
    except Exception:
        return [], False


# ── EasyOCR fallback (used when no API key is configured) ─────────────────────

# EasyOCR reader is loaded lazily to avoid blocking startup
_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr  # noqa: PLC0415
        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _reader


async def ocr_frame(image_path: str) -> List[Dict[str, Any]]:
    """
    EasyOCR fallback — returns raw blocks with coordinates.
    Only called when no OpenAI key is configured.
    """
    def _run() -> List[Dict[str, Any]]:
        reader = _get_reader()
        results = reader.readtext(image_path, detail=1, paragraph=False)
        out = []
        for bbox, text, conf in results:
            if conf < 0.3 or not text.strip():
                continue
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            out.append({
                "text": text.strip(),
                "x": min(xs),
                "y": min(ys),
                "w": max(xs) - min(xs),
                "h": max(ys) - min(ys),
                "confidence": conf,
            })
        return out

    return await asyncio.to_thread(_run)


# ── UI noise filtering ────────────────────────────────────────────────────────

# Exact strings that are Instagram UI chrome, not conversation text
_UI_EXACT: set = {
    "seen", "delivered", "sending", "message...", "message...",
    "message", "send message", "active now", "active today",
    "audio call", "video chat", "view profile", "report",
    "block", "restrict", "mute", "unfollow",
}

# Patterns that indicate story-reply UI labels (not message text)
_STORY_REPLY_RE = re.compile(
    r"(replied to (your|their|his|her) story"
    r"|reacted to (your|their|his|her) story"
    r"|replied to a story)",
    re.IGNORECASE,
)

# Patterns that look like timestamps or "Seen X ago" — short UI snippets
_TIMESTAMP_RE = re.compile(
    r"^("
    r"\d{1,2}:\d{2}(\s*(am|pm))?"
    r"|\d+\s*(min|hr|h|d|w|m|sec)s?\s*(ago)?"
    r"|yesterday|today|just now"
    r"|mon|tue|wed|thu|fri|sat|sun"
    r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
    r")$",
    re.IGNORECASE,
)


def filter_message_blocks(
    text_blocks: List[Dict[str, Any]],
    image_height: int = 1920,
    image_width: int = 1080,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Strip Instagram UI chrome from OCR results so only message-bubble text remains.

    Returns:
        filtered_blocks  -- text blocks from real message bubbles only
        has_story_reply  -- True if a story-reply label was found
                           (caller should auto-create story_reply message type)

    Removes:
      Top 13% of image    -> header (back arrow, username, call icons)
      Bottom 11% of image -> input bar
      Height < 2%         -> timestamps, "Seen", small UI labels
      Exact UI strings    -> Seen / Delivered / Active now / ...
      Timestamp patterns  -> "10:42 am", "5 min ago", "Yesterday" ...
      Story-reply labels  -> "Replied to your story" (sets has_story_reply=True)
      Single-char / punct -> stray OCR noise
    """
    top_cutoff    = image_height * 0.13
    bottom_cutoff = image_height * 0.89
    min_h         = image_height * 0.020

    has_story_reply = False
    filtered = []

    for block in text_blocks:
        text = block["text"].strip()
        tl   = text.lower()

        # Story-reply UI label detection
        if _STORY_REPLY_RE.search(text):
            has_story_reply = True
            continue

        # Position: header or input bar
        if block["y"] < top_cutoff:
            continue
        if block["y"] > bottom_cutoff:
            continue

        # Size: too small to be a message bubble
        if block["h"] < min_h:
            continue

        # Exact UI strings
        if tl in _UI_EXACT:
            continue

        # Timestamp / date patterns
        if _TIMESTAMP_RE.match(text):
            continue

        # Single punctuation / near-empty blocks
        stripped = re.sub(r"[^\w]", "", text)
        if len(stripped) < 2:
            continue

        filtered.append(block)

    return filtered, has_story_reply


def classify_sender(
    text_blocks: List[Dict[str, Any]],
    image_width: int = 1080,
) -> List[Dict[str, Any]]:
    """
    Classify each text block as 'self' (right-aligned) or 'other' (left-aligned).
    Sorts blocks top-to-bottom.
    """
    mid = image_width / 2
    result = []
    for block in text_blocks:
        cx = block["x"] + block["w"] / 2
        result.append({**block, "sender": "self" if cx > mid else "other"})
    result.sort(key=lambda m: m["y"])
    return result
