from __future__ import annotations

import asyncio


VIEWPORT = {"width": 1480, "height": 720}

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

                image = await page.screenshot(type="png", full_page=False)
                return image, None
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
