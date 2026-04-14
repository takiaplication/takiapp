import asyncio
import base64
import os
import random
import shutil
import tempfile
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Playwright, Browser
from jinja2 import Environment, FileSystemLoader

from config import TEMPLATES_DIR, FONTS_DIR
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
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--allow-file-access-from-files",
                "--disable-web-security",
                "--font-render-hinting=medium",
                "--disable-lcd-text",
                "--force-color-profile=srgb",
            ],
        )

        # Verify font files exist at startup
        woff2 = FONTS_DIR / "SF-Pro-Text-Regular.woff2"
        otf = FONTS_DIR / "SF-Pro-Text-Regular.otf"
        if woff2.exists():
            print(f"[DMRenderer] SF Pro Text WOFF2 ready ({woff2.stat().st_size} bytes)")
        elif otf.exists():
            print(f"[DMRenderer] SF Pro Text OTF ready ({otf.stat().st_size} bytes)")
        else:
            print(f"[DMRenderer] WARNING: No SF Pro font found in {FONTS_DIR}")

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

        # No base64 injection — too memory-heavy for Railway (causes OOM).
        # Instead, copy the font file to the temp dir next to the HTML.
        # Chromium loads it via file:// with the relative URL in the CSS.

        tmpdir = tempfile.mkdtemp(prefix="dm_render_")
        try:
            # Copy font file next to HTML so the relative URL resolves.
            # Prefer WOFF2 (smaller, matches template CSS), fall back to OTF.
            font_src = FONTS_DIR / "SF-Pro-Text-Regular.woff2"
            if font_src.exists():
                shutil.copy(font_src, tmpdir)
            else:
                # Copy OTF and also create the woff2 filename as a copy
                # so the CSS url("SF-Pro-Text-Regular.woff2") still resolves
                otf_src = FONTS_DIR / "SF-Pro-Text-Regular.otf"
                if otf_src.exists():
                    shutil.copy(otf_src, Path(tmpdir) / "SF-Pro-Text-Regular.woff2")

            html_path = Path(tmpdir) / "slide.html"
            html_path.write_text(html, encoding="utf-8")

            context = await self._browser.new_context(
                viewport={"width": 1080, "height": 1920},
                device_scale_factor=1,
            )
            try:
                page = await context.new_page()
                await page.goto(f"file://{html_path}", wait_until="load")

                # Wait for the font to be fully decoded and applied, then
                # force a layout reflow so Chromium re-rasterises all text.
                await page.evaluate("""
                    async () => {
                        await document.fonts.ready;
                        document.body.offsetHeight;
                    }
                """)

                png_bytes = await page.screenshot(type="png")
                return png_bytes
            finally:
                await context.close()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def get_font_debug_info(self) -> dict:
        """Return diagnostic info about font loading — used by /test-font-debug."""
        font_woff2 = FONTS_DIR / "SF-Pro-Text-Regular.woff2"
        font_otf = FONTS_DIR / "SF-Pro-Text-Regular.otf"

        info = {
            "fonts_dir": str(FONTS_DIR),
            "fonts_dir_exists": FONTS_DIR.exists(),
            "woff2_path": str(font_woff2),
            "woff2_exists": font_woff2.exists(),
            "woff2_size": font_woff2.stat().st_size if font_woff2.exists() else 0,
            "otf_exists": font_otf.exists(),
            "fonts_dir_contents": sorted(
                f.name for f in FONTS_DIR.iterdir()
            ) if FONTS_DIR.exists() else [],
        }

        # Test font loading in Playwright using the same file:// approach
        if self._browser:
            tmpdir = tempfile.mkdtemp(prefix="dm_debug_")
            try:
                # Copy font to temp dir
                if font_woff2.exists():
                    shutil.copy(font_woff2, tmpdir)

                test_html = """<!DOCTYPE html>
                <html><head><style>
                @font-face {
                    font-family: "SF Pro Text";
                    src: url("SF-Pro-Text-Regular.woff2") format("woff2");
                    font-weight: 400;
                    font-style: normal;
                    font-display: block;
                }
                body { font-family: 'SF Pro Text', sans-serif; font-size: 48px; }
                </style></head>
                <body><p id="test">ABCabc123</p></body></html>"""

                html_path = Path(tmpdir) / "debug.html"
                html_path.write_text(test_html, encoding="utf-8")

                context = await self._browser.new_context(
                    viewport={"width": 800, "height": 600},
                )
                try:
                    page = await context.new_page()
                    await page.goto(f"file://{html_path}", wait_until="load")
                    await page.evaluate("document.fonts.ready")

                    font_status = await page.evaluate("""
                        () => {
                            const fonts = [...document.fonts].map(f => ({
                                family: f.family,
                                weight: f.weight,
                                style: f.style,
                                status: f.status,
                            }));
                            const el = document.getElementById('test');
                            const computed = window.getComputedStyle(el).fontFamily;
                            return {
                                registeredFonts: fonts,
                                computedFontFamily: computed,
                                fontsSize: document.fonts.size,
                            };
                        }
                    """)
                    info["playwright_font_status"] = font_status
                finally:
                    await context.close()
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        return info


# Singleton instance used by the app
renderer = DMRenderer()
