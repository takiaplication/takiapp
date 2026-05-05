"""
Translation via OpenAI GPT-4o-mini.
Falls back to returning the original text if no API key is configured.
The API key is read from the OPENAI_API_KEY environment variable.
"""

import asyncio
import os
import re
from typing import Optional


# ───────────────────────────────────────────────────────────────────────────
# Post-processing rules — applied AFTER GPT output, in order.
# Belt-and-braces: GPT is instructed to follow these rules in the prompt,
# but regex enforcement guarantees they hold even when the model slips.
# ───────────────────────────────────────────────────────────────────────────

# Forbidden vocative slang words. They must never appear in the output.
# We replace them with empty string and clean up resulting double spaces /
# stray punctuation. \b ensures we don't touch words that contain "bro" or
# "man" as a substring (e.g. "Bromine", "manier", "gewoon", "human").
_FORBIDDEN_WORDS = re.compile(
    r"\b(bro|broer|brooo+|man|manno*|mano|mannnn+|mannn+|broer|brrr+o+)\b",
    flags=re.IGNORECASE,
)

# Compliment phrases that all collapse to the canonical "je bent smooth".
# Order matters: longer/more specific patterns first so they win over short
# ones. \b on both sides keeps it word-bounded.
_COMPLIMENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bamai\s+je\s+bent\s+(echt\s+)?goed\b", re.IGNORECASE),  "je bent smooth"),
    (re.compile(r"\bdat\s+doe\s+je\s+(echt\s+)?goed\b",   re.IGNORECASE),  "je bent smooth"),
    (re.compile(r"\bje\s+doet\s+dat\s+(echt\s+)?goed\b",  re.IGNORECASE),  "je bent smooth"),
    (re.compile(r"\bkei\s+goed\b",                        re.IGNORECASE),  "je bent smooth"),
    (re.compile(r"\bzwaar\s+goed\b",                      re.IGNORECASE),  "je bent smooth"),
    (re.compile(r"\bje\s+bent\s+(echt\s+)?goed\b",        re.IGNORECASE),  "je bent smooth"),
    (re.compile(r"\bsmooth\b",                            re.IGNORECASE),  "je bent smooth"),
]


def _clean_post_translation(text: str) -> str:
    """
    Post-process GPT output:
      1. Collapse compliment phrases to canonical 'je bent smooth'.
      2. Strip forbidden vocatives ('bro', 'man', and friends).
      3. Tidy whitespace and stray punctuation left after removals.
    Idempotent — running it twice yields the same result.
    """
    if not text:
        return text

    # 1. Compliments → 'je bent smooth' (do this BEFORE forbidden-word strip,
    #    otherwise "je bent smooth" survives but a previous "je bent goed bro"
    #    would lose 'bro' and become "je bent goed" — which we then wouldn't
    #    rewrite to smooth. Order: rewrite first, then strip.)
    out = text
    for pattern, replacement in _COMPLIMENT_PATTERNS:
        out = pattern.sub(replacement, out)

    # Some patterns can chain. Examples:
    #   - 'je bent goed' → 'je bent smooth', then the 'smooth' pattern fires
    #     again on the new 'smooth' and prepends another 'je bent ' →
    #     'je bent je bent smooth'.
    #   - 'zwaar goed' → 'je bent smooth' inside 'je bent zwaar goed' →
    #     'je bent je bent smooth'.
    # Collapse any run of one-or-more 'je bent' prefixes back to a single one.
    out = re.sub(r"(?:\bje\s+bent\s+){2,}smooth\b", "je bent smooth", out, flags=re.IGNORECASE)

    # Same for adjacent duplicates separated by punctuation/whitespace, e.g.
    # 'kei goed, smooth' → 'je bent smooth, je bent smooth' → 'je bent smooth'.
    out = re.sub(
        r"\bje\s+bent\s+smooth(?:[\s,;.!?-]+je\s+bent\s+smooth)+\b",
        "je bent smooth",
        out,
        flags=re.IGNORECASE,
    )

    # 2. Strip forbidden vocatives.
    out = _FORBIDDEN_WORDS.sub("", out)

    # 3. Tidy: collapse whitespace, fix stray punctuation like ", ," or " ,".
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r",\s*,+", ",", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([!?.,;:])", r"\1", out)
    return out.strip(" ,")


async def _get_api_key() -> str:
    """Read OpenAI key from OPENAI_API_KEY environment variable."""
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
                        "(zoals 'goonen', 'raggen', 'ngl', 'lowkey', 'slay', 'vro', "
                        "'ewa', 'wallah', 'joh', 'haha', 'lmao', 'wtf', schuttingtaal), "
                        "dan gebruik je in de vertaling het EQUIVALENT in Nederlandse straattaal. "
                        "Denk aan: 'ff', 'gwn', 'sws', 'ngl', 'ewa', 'vro', "
                        "'joh', 'mn', 'kl', 'lekker puh', 'da's zwaar', 'boeie', 'hoezo', "
                        "'fk dat', 'chill', 'klinkt goed', 'da's fire', 'respecteer'. "
                        "\n\n"
                        "VERBODEN WOORDEN — gebruik deze NOOIT in de vertaling: "
                        "'bro', 'man', 'mano', 'broer' als aanspreekvorm. "
                        "Zelfs als ze in de brontekst staan, vertaal je ze naar iets anders "
                        "of laat je ze gewoon weg. "
                        "\n\n"
                        "COMPLIMENT-REGEL: alle vormen van 'dat doe je goed', "
                        "'amai je bent goed', 'kei goed', 'je bent goed', 'smooth', "
                        "'je bent zwaar goed' worden ALTIJD vertaald als de exacte zin "
                        "'je bent smooth' (geen variaties). "
                        "\n\n"
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

    raw = await asyncio.to_thread(_call)
    return _clean_post_translation(raw)


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
                        "als 'gooning' 'raggen' is, dan overal 'raggen'. "
                        "Match de rauwe toon EXACT — maak het NOOIT netter dan het origineel. "
                        "Schuttingtaal blijft schuttingtaal. Bewaar alle emojis. "
                        "\n\n"
                        "VERBODEN WOORDEN — gebruik deze NOOIT in de vertaling: "
                        "'bro', 'man', 'mano', 'broer' als aanspreekvorm. "
                        "Zelfs als ze in de brontekst staan, vertaal je ze naar iets anders "
                        "of laat je ze gewoon weg. "
                        "\n\n"
                        "COMPLIMENT-REGEL: alle vormen van 'dat doe je goed', "
                        "'amai je bent goed', 'kei goed', 'je bent goed', 'smooth', "
                        "'je bent zwaar goed' worden ALTIJD vertaald als de exacte zin "
                        "'je bent smooth' (geen variaties). "
                        "\n\n"
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
        # Key by (slide, index) for O(1) lookup. Apply the post-processing
        # safety net so any 'bro'/'man'/non-canonical compliment that GPT
        # slipped through is normalised before it reaches the renderer.
        result_map = {
            (item["slide"], item["index"]): _clean_post_translation(item["text"])
            for item in results
        }
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
