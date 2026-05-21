"""FetcherAgent: fetch website content and compute change hashes — sync + async."""

import asyncio
import logging
import re
from hashlib import sha256

import httpx
from bs4 import BeautifulSoup

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

SCRIPT_STYLE_PATTERN = re.compile(
    r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
WHITESPACE_PATTERN = re.compile(r"\s+")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class FetcherAgent(BaseAgent):
    def __init__(self, config: dict):
        super().__init__("Fetcher", config)
        self.timeout = 30

    # ── sync (wraps async) ──────────────────────────────────────────

    def run(self, url: str, use_browser: bool = False) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(url, use_browser))
        raise RuntimeError("Fetcher.run() in async context — use run_async()")

    # ── async ───────────────────────────────────────────────────────

    async def run_async(self, url: str, use_browser: bool = False) -> dict:
        logger.info("[Fetcher] Fetching: %s (browser=%s)", url, use_browser)

        if use_browser:
            html = await self._fetch_with_browser(url)
        else:
            html = await self._fetch_static(url)

        text = self._clean_html(html)
        content_hash = self._hash_text(text)

        logger.info("[Fetcher] Fetched %d bytes, hash: %s", len(html), content_hash[:12])

        return {
            "url": url,
            "html": html,
            "text": text,
            "content_hash": content_hash,
            "status_code": 200,
        }

    async def _fetch_static(self, url: str) -> str:
        async with httpx.AsyncClient(
            timeout=self.timeout, headers=HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    async def _fetch_with_browser(self, url: str) -> str:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning(
                "[Fetcher] Playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
            logger.warning("[Fetcher] Falling back to static fetch.")
            return await self._fetch_static(url)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="zh-CN",
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            )
            page = await context.new_page()
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            except Exception:
                await page.goto(url, timeout=self.timeout * 1000)

            await page.wait_for_timeout(2000)

            for _ in range(6):
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight / 6)")
                await page.wait_for_timeout(1500)

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(3000)

            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(500)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

            html = await page.content()
            await browser.close()
            return html

    # ── utilities (shared) ──────────────────────────────────────────

    def _clean_html(self, html: str) -> str:
        text = SCRIPT_STYLE_PATTERN.sub(" ", html)
        soup = BeautifulSoup(text, "lxml")
        body = soup.get_text(separator=" ")
        return WHITESPACE_PATTERN.sub(" ", body).strip()

    def _hash_text(self, text: str) -> str:
        return sha256(text.encode("utf-8")).hexdigest()
