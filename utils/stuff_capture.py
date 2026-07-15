from __future__ import annotations

import asyncio
from io import BytesIO

from PIL import Image


VIEWPORT = {"width": 1540, "height": 830}
CAPTURE_CLIP = {"x": 70, "y": 132, "width": 1470, "height": 690}
TOP_PADDING = 12
CAPTURE_BACKGROUND = "#241f1b"

BLOCKED_MARKERS = (
    "Attention Required",
    "Sorry, you have been blocked",
    "front doesn't work properly without JavaScript",
)

CONSENT_BUTTON_SELECTORS = (
    "button:has-text('Do not consent')",
    "button:has-text('Reject all')",
    "button:has-text('Refuser')",
    "button:has-text('Tout refuser')",
    "button:has-text('Continuer sans accepter')",
    "[role='button']:has-text('Do not consent')",
    "[role='button']:has-text('Refuser')",
)


async def capture_dofusbook_page(url: str) -> tuple[bytes | None, str | None]:
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright
    except ModuleNotFoundError:
        return None, "Capture navigateur indisponible: Playwright n'est pas installe."

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            page = await browser.new_page(
                viewport=VIEWPORT,
                device_scale_factor=1,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            )
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=12_000)
                except PlaywrightError:
                    pass
                await asyncio.sleep(2)
                await _dismiss_consent_dialog(page)
                await asyncio.sleep(1)

                title = await page.title()
                body_text = await page.locator("body").inner_text(timeout=5_000)
                if any(marker in title or marker in body_text for marker in BLOCKED_MARKERS):
                    return None, "Dofusbook a bloque la capture automatique."

                image = await page.screenshot(type="png", clip=CAPTURE_CLIP)
                return _add_top_padding(image), None
            finally:
                await browser.close()
    except Exception as exc:
        return None, f"Capture navigateur impossible: {type(exc).__name__}: {exc}"


async def _dismiss_consent_dialog(page) -> None:
    for selector in CONSENT_BUTTON_SELECTORS:
        try:
            button = page.locator(selector).first
            if await button.count() == 0:
                continue
            if not await button.is_visible(timeout=1_000):
                continue
            await button.click(timeout=3_000)
            return
        except Exception:
            continue


def _add_top_padding(image: bytes) -> bytes:
    with Image.open(BytesIO(image)) as screenshot:
        screenshot = screenshot.convert("RGB")
        canvas = Image.new("RGB", screenshot.size, CAPTURE_BACKGROUND)
        visible = screenshot.crop(
            (0, 0, screenshot.width, screenshot.height - TOP_PADDING)
        )
        canvas.paste(visible, (0, TOP_PADDING))

        output = BytesIO()
        canvas.save(output, format="PNG")
        return output.getvalue()
