# publish_note_play/playwright_utils.py
"""playwright_utils.py (async版)"""

import asyncio
from typing import Optional, List
from playwright.async_api import Page, Locator

class PlaywrightUtils:
    """Playwright共通ユーティリティ（async）"""

    @staticmethod
    async def wait_doc_ready(page: Page, timeout: int = 30000):
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout)
            await page.wait_for_load_state("load", timeout=timeout)
            await asyncio.sleep(0.5)
        except Exception:
            pass

    @staticmethod
    async def safe_click(page: Page, element: Locator, description: str = "") -> bool:
        try:
            await element.scroll_into_view_if_needed(timeout=5000)
            await asyncio.sleep(0.2)
            await element.click(timeout=5000)
            if description:
                print(f"  ✓ {description}をクリック")
            await asyncio.sleep(0.2)
            return True
        except Exception as e:
            if description:
                print(f"  ✗ {description}のクリック失敗: {e}")
            return False

    @staticmethod
    async def find_element_with_retry(page: Page, selectors: List[str], timeout: int = 15000) -> Optional[Locator]:
        for sel in selectors:
            try:
                locator = page.locator(f"xpath={sel}") if sel.startswith("//") else page.locator(sel)
                await locator.wait_for(state="attached", timeout=timeout)
                await asyncio.sleep(0.2)
                return locator
            except Exception:
                continue
        return None

    @staticmethod
    async def find_clickable_with_retry(page: Page, selectors: List[str], timeout: int = 15000) -> Optional[Locator]:
        for sel in selectors:
            try:
                locator = page.locator(f"xpath={sel}") if sel.startswith("//") else page.locator(sel)
                await locator.wait_for(state="visible", timeout=timeout)
                await asyncio.sleep(0.2)
                return locator
            except Exception:
                continue
        return None
