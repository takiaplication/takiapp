"""
Translation via OpenAI GPT-4o-mini.
Falls back to returning the original text if no API key is configured.
The API key is loaded at call-time from the app_settings table so the user
can update it without restarting the server.
"""

import asyncio
import os
from typing import Optional


async def _get_api_key() -> str:
    """Resolve the OpenAI API key: DB first, then OPENAI_API_KEY env var."""
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


async def translate_text(
    text: str,
    target_lang: str = "nl",
) -> str:
    """
    Translate *text* to *target_lang* using GPT-4o-mini.
    Preserves casual DM tone, slang, abbreviations, and emojis.
    Returns the original text unchanged if no API key is available.
    """
    if not text.strip():
        return text

    api_key = await _get_api_key()
    if not api_key:
        return text  # no key → pass-through

    lang_names = {
        "nl": "Dutch", "en": "English", "fr": "French", "de": "German",
        "es": "Spanish", "pt": "Portuguese", "it": "Italian",
        "ru": "Russian", "ar": "Arabic", "zh-cn": "Chinese (Simplified)",
        "ja": "Japanese", "ko": "Korean",
    }
    lang_name = lang_names.get(target_lang, target_lang)

    def _call() -> str:
        from openai import OpenAI  # noqa: PLC0415
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Je bent een vertaler voor Instagram DM-gesprekken van jongeren. "
                        f"Vertaal de tekst naar {lang_name}. "
                        "\n\n"
                        "BELANGRIJKSTE REGEL: Match de toon EXACT. "
                        "Als de brontekst straattaal, jeugdslang of rauwe taal bevat "
                        "(zoals 'goonen', 'raggen', 'bro', 'ngl', 'lowkey', 'slay', 'vro', 'mano', "
                        "'ewa', 'wallah', 'joh', 'haha', 'lmao', 'wtf', schuttingtaal), "
                        "dan gebruik je in de vertaling het EQUIVALENT in Nederlandse straattaal. "
                        "Denk aan: 'ff', 'gwn', 'bro', 'sws', 'ngl', 'ewa', 'mano', 'vro', "
                        "'joh', 'mn', 'kl', 'lekker puh', 'da's zwaar', 'boeie', 'hoezo', "
                        "'fk dat', 'chill', 'klinkt goed', 'da's fire', 'respecteer'. "
                        "Maak de taal NOOIT netter of formeler dan het origineel. "
                        "Laat schuttingtaal staan als schuttingtaal. "
                        "Bewaar alle emojis exact. "
                        "Geef ALLEEN de vertaalde tekst terug — geen uitleg, geen aanhalingstekens."
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=500,
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()

    return await asyncio.to_thread(_call)


async def batch_translate_conversation(
    messages: list[dict],
    target_lang: str = "nl",
) -> list[dict]:
    """
    Translate an ENTIRE conversation in one GPT call for consistency.

    Input:  [{"slide": int, "index": int, "sender": str, "text": str, ...}, ...]
    Output: same list with "text" replaced by a consistent Dutch translation.

    Using slide + index as the two-level key guarantees that the same phrase
    always maps to the same Dutch slang word across all slides.
    Extra fields (msg_id, slide_id, etc.) are preserved unchanged.
    Falls back to returning the originals unchanged if no API key is configured.
    """
    import json as _json

    api_key = await _get_api_key()
    if not api_key or not messages:
        return messages

    lang_names = {
        "nl": "Dutch", "en": "English", "fr": "French", "de": "German",
        "es": "Spanish", "pt": "Portuguese", "it": "Italian",
        "ru": "Russian", "ar": "Arabic", "zh-cn": "Chinese (Simplified)",
        "ja": "Japanese", "ko": "Korean",
    }
    lang_name = lang_names.get(target_lang, target_lang)

    # Build the payload GPT will see — only the fields it needs
    gpt_input = _json.dumps(
        [
            {"slide": m["slide"], "index": m["index"],
             "sender": m["sender"], "text": m["text"]}
            for m in messages
        ],
        ensure_ascii=False,
    )

    def _call() -> str:
        from openai import OpenAI  # noqa: PLC0415
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=4096,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Je krijgt een volledig Instagram DM-gesprek. "
                        f"Vertaal elk bericht naar CONSISTENT {lang_name} straatjeugdtaal. "
                        "Gebruik EXACT dezelfde slang-keuze door het hele gesprek: "
                        "als 'bro' één keer 'bro' is, dan altijd 'bro'. "
                        "Als 'gooning' 'raggen' is, dan overal 'raggen'. "
                        "Match de rauwe toon EXACT — maak het NOOIT netter dan het origineel. "
                        "Schuttingtaal blijft schuttingtaal. Bewaar alle emojis. "
                        "Geef ALLEEN een JSON-array terug met dezelfde slide- en index-waarden:\n"
                        '[{"slide": 1, "index": 0, "text": "..."}, ...]'
                    ),
                },
                {"role": "user", "content": gpt_input},
            ],
        )
        return resp.choices[0].message.content.strip()

    try:
        raw = await asyncio.to_thread(_call)
        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        results = _json.loads(raw.strip())
        # Key by (slide, index) for O(1) lookup
        result_map = {(item["slide"], item["index"]): item["text"] for item in results}
        out = []
        for m in messages:
            key = (m["slide"], m["index"])
            out.append({**m, "text": result_map.get(key, m["text"])})
        return out
    except Exception:
        return messages   # any parse failure → return originals unchanged


async def detect_language(text: str) -> Optional[str]:
    """Best-effort language detection."""
    if not text.strip():
        return None
    try:
        def _detect() -> Optional[str]:
            from langdetect import detect  # noqa: PLC0415
            return detect(text)
        return await asyncio.to_thread(_detect)
    except Exception:
        return None
