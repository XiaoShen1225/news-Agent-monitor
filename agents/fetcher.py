"""FetcherAgent: fetch website content and compute change hashes."""

import re
import logging
import httpx
from bs4 import BeautifulSoup
from typing import Optional

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

SCRIPT_STYLE_PATTERN = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")


class FetcherAgent(BaseAgent):
    def __init__(self, config: dict):
        super().__init__("Fetcher", config)
        self.timeout = 30
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        self._browser = None

    def run(self, url: str, use_browser: bool = False) -> dict:
        """Fetch a URL and return HTML with metadata.

        Args:
            url: Target URL to fetch.
            use_browser: If True, renders the page with Playwright (for JS-heavy sites).
        """
        logger.info("[Fetcher] Fetching: %s (browser=%s)", url, use_browser)

        if use_browser:
            html = self._fetch_with_browser(url)
        else:
            html = self._fetch_static(url)

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

    def _fetch_static(self, url: str) -> str:
        with httpx.Client(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text

    def _fetch_with_browser(self, url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[Fetcher] Playwright not installed. Run: pip install playwright && playwright install chromium")
            logger.warning("[Fetcher] Falling back to static fetch.")
            return self._fetch_static(url)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ])
            context = browser.new_context(
                user_agent=self.headers["User-Agent"],
                locale="zh-CN",
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            page = context.new_page()
            # Evade headless detection
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            except Exception:
                page.goto(url, timeout=self.timeout * 1000)

            # Wait for initial dynamic content
            page.wait_for_timeout(2000)

            # Scroll down in steps to trigger lazy loading (more steps = more sections)
            for scroll_step in range(6):
                page.evaluate("window.scrollBy(0, document.body.scrollHeight / 6)")
                page.wait_for_timeout(1500)

            # One full scroll to bottom to trigger final lazy blocks
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(3000)

            # Scroll back to top (some pages load more content on reverse scroll too)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)

            html = page.content()
            browser.close()
            return html

    def _clean_html(self, html: str) -> str:
        """Strip scripts, styles, and extra whitespace from HTML for hashing."""
        text = SCRIPT_STYLE_PATTERN.sub(" ", html)
        soup = BeautifulSoup(text, "lxml")
        body = soup.get_text(separator=" ")
        return WHITESPACE_PATTERN.sub(" ", body).strip()

    def _hash_text(self, text: str) -> str:
        from hashlib import sha256
        return sha256(text.encode("utf-8")).hexdigest()
