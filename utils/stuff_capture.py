from __future__ import annotations

import asyncio
from io import BytesIO

from PIL import Image


VIEWPORT = {"width": 1540, "height": 920}
CAPTURE_CLIP = {"x": 70, "y": 206, "width": 1470, "height": 690}
TOP_PADDING = 12
CAPTURE_BACKGROUND = "#241f1b"
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-gpu",
]

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
                args=CHROMIUM_ARGS,
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
                await _hide_ad_overlays(page)
                await asyncio.sleep(1)

                title = await _read_page_title(page)
                body_text = await _read_body_text(page)
                if _has_blocked_marker(title, body_text):
                    return None, "Dofusbook a bloque la capture automatique."

                await _hide_ad_overlays(page)
                image = await page.screenshot(type="png", clip=CAPTURE_CLIP)
                return _add_top_padding(image), None
            finally:
                await browser.close()
    except Exception as exc:
        return None, _format_capture_error(exc)


async def _read_page_title(page) -> str:
    try:
        return await page.title()
    except Exception:
        return ""


async def _read_body_text(page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=2_000)
    except Exception:
        return ""


def _has_blocked_marker(*values: str) -> bool:
    return any(marker in value for marker in BLOCKED_MARKERS for value in values)


def _format_capture_error(exc: Exception) -> str:
    if type(exc).__name__ == "TimeoutError":
        return "Capture navigateur impossible: Dofusbook n'a pas repondu a temps."
    return f"Capture navigateur impossible: {type(exc).__name__}: {exc}"


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


async def _hide_ad_overlays(page) -> None:
    await page.add_style_tag(
        content="""
            iframe,
            ins.adsbygoogle,
            [id*="google"],
            [id*="ads"],
            [id*="advert"],
            [class*="google"],
            [class*="ads"],
            [class*="advert"],
            [style*="position: fixed"] {
                display: none !important;
                visibility: hidden !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }
        """
    )
    await page.evaluate(
        """
        () => {
            const candidates = [
                ...document.querySelectorAll('iframe, ins.adsbygoogle'),
                ...document.querySelectorAll(
                    '[id*="google"], [id*="ads"], [id*="advert"], ' +
                    '[class*="google"], [class*="ads"], [class*="advert"]'
                ),
            ];

            for (const element of document.querySelectorAll('body *')) {
                const style = window.getComputedStyle(element);
                if (style.position !== 'fixed') continue;

                const box = element.getBoundingClientRect();
                const isFloatingAd = box.width > 120 && box.height > 80;
                if (isFloatingAd) candidates.push(element);
            }

            for (const element of candidates) {
                element.style.setProperty('display', 'none', 'important');
                element.style.setProperty('visibility', 'hidden', 'important');
            }
        }
        """
    )


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
