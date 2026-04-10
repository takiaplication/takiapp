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
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from config import TEMPLATES_DIR


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
    bytes  — raw PNG bytes of the rendered 1080×1920 slide.
    """
    # Encode DM screenshot as a base64 data-URL so it works with set_content()
    if dm_screenshot_bytes:
        b64 = base64.b64encode(dm_screenshot_bytes).decode()
        dm_data_url = f"data:image/png;base64,{b64}"
    else:
        dm_data_url = ""

    # Render Jinja2 template
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
    )
    template = env.get_template("taki_appad.html")
    html = template.render(
        dm_screenshot_url=dm_data_url,
        next_message=next_message or "Stuur dit berichtje 👇",
    )

    # Use the shared Playwright browser
    context = await renderer_instance._browser.new_context(
        viewport={"width": 1080, "height": 1920},
        device_scale_factor=1,
    )
    try:
        page = await context.new_page()
        await page.set_content(html, wait_until="load")
        await page.wait_for_timeout(80)   # let fonts/layout settle
        return await page.screenshot(type="png")
    finally:
        await context.close()
