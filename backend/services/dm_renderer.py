import asyncio
import os
import random
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Playwright, Browser, Route, Request
from jinja2 import Environment, FileSystemLoader

from config import TEMPLATES_DIR, BASE_DIR
from schemas.render import DMConversation, DMMessage


def _make_jitter(theme: str = "dark") -> dict:
    """
    Generate subtle per-render randomisation values.

    All deltas are small enough to be invisible to the human eye but large
    enough to produce unique pixel fingerprints that defeat template detection.
    """
    r = random.Random()   # fresh RNG — NOT seeded → different every call

    # Background shade: ±3 RGB units off pure black or white
    if theme == "dark":
        base = 0
        shade = f"rgb({base+r.randint(0,3)},{base+r.randint(0,3)},{base+r.randint(0,3)})"
    else:
        base = 255
        shade = f"rgb({base-r.randint(0,3)},{base-r.randint(0,3)},{base-r.randint(0,3)})"

    return {
        "font_size":      48 + r.randint(-1, 1),       # 47–49 px
        "bubble_pad_v":   27 + r.randint(-1, 1),       # 26–28 px
        "bubble_pad_h":   36 + r.randint(-1, 1),       # 35–37 px
        "gap_same":        6 + r.randint(-1, 2),       # 5–8 px
        "gap_diff":       24 + r.randint(-2, 4),       # 22–28 px
        "msg_padding_x":  42 + r.randint(-2, 2),       # 40–44 px
        "bg_color":       shade,
        "line_height":    round(1.35 + r.uniform(-0.03, 0.03), 3),   # 1.32–1.38
    }


class ProcessedMessage:
    def __init__(self, msg: DMMessage, position: str, same_as_prev: bool):
        self.text = msg.text
        self.is_sender = msg.is_sender
        self.show_timestamp = msg.show_timestamp
        self.timestamp_text = msg.timestamp_text
        self.read_receipt = msg.read_receipt
        self.emoji_reaction = msg.emoji_reaction
        self.story_image_base64 = msg.story_image_base64
        self.story_reply_label = msg.story_reply_label
        self.position = position  # solo, first, middle, last
        self.same_as_prev = same_as_prev


def preprocess_messages(messages: list[DMMessage]) -> list[ProcessedMessage]:
    """Assign bubble position (solo/first/middle/last) based on consecutive sender grouping."""
    if not messages:
        return []

    processed = []
    n = len(messages)

    for i, msg in enumerate(messages):
        prev_same = i > 0 and messages[i - 1].is_sender == msg.is_sender
        next_same = i < n - 1 and messages[i + 1].is_sender == msg.is_sender

        if not prev_same and not next_same:
            position = "solo"
        elif not prev_same and next_same:
            position = "first"
        elif prev_same and next_same:
            position = "middle"
        else:
            position = "last"

        processed.append(ProcessedMessage(msg, position, same_as_prev=prev_same))

    return processed


class DMRenderer:
    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=False,
        )

    async def start(self):
        self._playwright = await async_playwright().start()
        chromium_path = os.environ.get(
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium"
        )
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            executable_path=chromium_path,
        )

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def render_slide(
        self,
        conversation: DMConversation,
        jitter: Optional[dict] = None,
    ) -> bytes:
        """Render a DM conversation to a 1080x1920 PNG.

        *jitter* carries subtle per-render randomisation values so no two
        exported slides are pixel-identical.  If None a fresh set is generated.
        """
        processed = preprocess_messages(conversation.messages)
        if jitter is None:
            jitter = _make_jitter(conversation.theme)

        template = self._jinja_env.get_template("dm_screen.html")
        html = template.render(
            theme=conversation.theme,
            processed_messages=processed,
            show_typing=conversation.show_typing,
            jitter=jitter,
        )

        # Fonts are served via page.route() — no <base href> needed.
        fonts_dir = BASE_DIR / "fonts"
        print(f"[DMRenderer] fonts_dir={fonts_dir} exists={fonts_dir.exists()}")
        for f in fonts_dir.glob("*.otf") if fonts_dir.exists() else []:
            print(f"[DMRenderer]   found font: {f.name}")

        context = await self._browser.new_context(
            viewport={"width": 1080, "height": 1920},
            device_scale_factor=1,
        )
        try:
            page = await context.new_page()

            # Intercept font requests and serve directly from disk.
            # This bypasses Chromium's file:// security restrictions on about:blank.
            async def serve_font(route: Route, request: Request) -> None:
                url = request.url
                filename = url.split("/")[-1].split("?")[0]
                font_path = fonts_dir / filename
                print(f"[DMRenderer] font request: {url} → {font_path} exists={font_path.exists()}")
                if font_path.exists():
                    await route.fulfill(
                        body=font_path.read_bytes(),
                        content_type="font/otf",
                        headers={"Access-Control-Allow-Origin": "*"},
                    )
                else:
                    await route.abort()

            await page.route("http://dm-assets/fonts/**", serve_font)
            await page.set_content(html, wait_until="load")
            # Small delay to let fonts settle
            await page.wait_for_timeout(100)
            png_bytes = await page.screenshot(type="png")
            return png_bytes
        finally:
            await context.close()


# Singleton instance used by the app
renderer = DMRenderer()
