"""
Render the Taki app-ad slide using Playwright + Jinja2.

Usage
-----
from services.appad_renderer import render_taki_appad
from services.dm_renderer import renderer          # the app singleton

png_bytes = await render_taki_appad(
    dm_screenshot_bytes=<bytes of a 1080×1920 DM PNG or None>,
    next_message="Stuur dit berichtje 👇",
    renderer_instance=renderer,
)
"""

import base64
import io
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from jinja2 import Environment, FileSystemLoader

from config import TEMPLATES_DIR, STORAGE_DIR

# Logo is stored at storage/taki_logo.png — loaded once at import time.
_LOGO_PATH = STORAGE_DIR / "taki_logo.png"


def _load_logo_data_url() -> str:
    """Return a base64 data-URL for the Taki logo, or '' if not found."""
    for candidate in (
        STORAGE_DIR / "taki_logo.png",
        STORAGE_DIR / "taki_logo.jpg",
        STORAGE_DIR / "taki_logo.svg",
        STORAGE_DIR / "taki_logo.webp",
    ):
        if candidate.exists():
            mime_map = {
                ".png":  "image/png",
                ".jpg":  "image/jpeg",
                ".jpeg": "image/jpeg",
                ".svg":  "image/svg+xml",
                ".webp": "image/webp",
            }
            mime = mime_map.get(candidate.suffix.lower(), "image/png")
            b64 = base64.b64encode(candidate.read_bytes()).decode()
            return f"data:{mime};base64,{b64}"
    return ""


def _crop_to_bubbles(png_bytes: bytes, padding: int = 40) -> bytes:
    """
    Crop a DM screenshot to the bounding box of all non-background content
    (message bubbles, header, status bar) plus *padding* pixels on every side.

    The DM renderer produces a full 1080×1920 PNG; most of the lower half is
    empty background.  This function removes that empty space so the phone
    mockup isn't filled with a large black void.

    Strategy
    --------
    1. Sample the four corners to estimate the background colour.
    2. Build a boolean mask of pixels that differ from the background by > 18
       on any channel.
    3. Take the axis-aligned bounding box of that mask.
    4. Expand by *padding* px and clamp to the image bounds.
    5. Crop and return the result as PNG bytes.

    Returns the original bytes unchanged if the image can't be opened or if
    no non-background pixels are found.
    """
    try:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    except Exception:
        return png_bytes

    arr = np.array(img)
    h, w = arr.shape[:2]
    cs = max(h // 30, 10)

    # Estimate background colour from the four corners
    corner_pixels = np.vstack([
        arr[:cs,    :cs   ].reshape(-1, 3),
        arr[:cs,    w-cs: ].reshape(-1, 3),
        arr[h-cs:,  :cs   ].reshape(-1, 3),
        arr[h-cs:,  w-cs: ].reshape(-1, 3),
    ])
    bg = np.median(corner_pixels, axis=0)          # shape (3,)

    # Mask: any pixel that deviates from background by more than 18 on any channel
    diff = np.abs(arr.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
    mask = diff > 18

    rows = np.where(np.any(mask, axis=1))[0]
    cols = np.where(np.any(mask, axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return png_bytes   # nothing found — return original

    r0 = max(0,   int(rows[0])  - padding)
    r1 = min(h-1, int(rows[-1]) + padding)
    c0 = max(0,   int(cols[0])  - padding)
    c1 = min(w-1, int(cols[-1]) + padding)

    cropped = img.crop((c0, r0, c1 + 1, r1 + 1))
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


async def render_taki_appad(
    dm_screenshot_bytes: Optional[bytes],
    next_message: str,
    renderer_instance,          # DMRenderer singleton — supplies the Playwright browser
) -> bytes:
    """
    Render the Taki-style app-ad frame to a 1080×1920 PNG.

    Parameters
    ----------
    dm_screenshot_bytes : bytes | None
        Raw PNG bytes of the DM slide to embed in the phone frame.
        Pass None to show an empty frame.
    next_message : str
        The text shown in the blue AI-suggestion bubble at the bottom.
    renderer_instance : DMRenderer
        The running Playwright browser wrapper (started in app lifespan).

    Returns
    -------
    bytes  — raw PNG bytes of the rendered 1080×1080 slide.
    """
    # Crop the DM screenshot to the bubble bounding box before embedding.
    # The full 1080×1920 PNG has a large empty area below the messages; removing
    # it means the square mockup frame shows actual content instead of dead space.
    if dm_screenshot_bytes:
        cropped = _crop_to_bubbles(dm_screenshot_bytes, padding=40)
        b64 = base64.b64encode(cropped).decode()
        dm_data_url = f"data:image/png;base64,{b64}"
    else:
        dm_data_url = ""

    # Logo — embedded as base64 so set_content() can reference it without a server
    logo_url = _load_logo_data_url()

    # Render Jinja2 template
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
    )
    template = env.get_template("taki_appad.html")
    html = template.render(
        dm_screenshot_url=dm_data_url,
        next_message=next_message or "Stuur dit berichtje 👇",
        logo_url=logo_url,
    )

    # Use the shared Playwright browser
    context = await renderer_instance._browser.new_context(
        viewport={"width": 1080, "height": 1080},
        device_scale_factor=1,
    )
    try:
        page = await context.new_page()
        await page.set_content(html, wait_until="load")
        await page.wait_for_timeout(80)   # let fonts/layout settle
        return await page.screenshot(type="png")
    finally:
        await context.close()
