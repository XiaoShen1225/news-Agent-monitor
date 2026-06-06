"""FetcherAgent: fetch website content and compute change hashes — sync + async."""

import asyncio
import logging
import re
from hashlib import sha256

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings

from .base_agent import BaseAgent

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
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

MAX_RETRIES = 3


class FetcherAgent(BaseAgent):
    def __init__(self, config: dict):
        super().__init__("Fetcher", config)
        self.timeout = httpx.Timeout(connect=15.0, read=30.0, write=15.0, pool=5.0)
        self._browser_timeout_ms = 30_000
        self._client = None
        self._playwright = None
        self._browser = None
        self._browser_context_count = 0
        self._max_contexts_before_restart = 20

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=HEADERS,
                follow_redirects=True,
                trust_env=False,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return self._client

    async def aclose(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        await self._close_browser()

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

        logger.info(
            "[Fetcher] Fetched %d bytes, hash: %s", len(html), content_hash[:12]
        )

        return {
            "url": url,
            "html": html,
            "text": text,
            "content_hash": content_hash,
            "status_code": 200,
        }

    async def _fetch_static(self, url: str) -> str:
        """Fetch URL via shared httpx client with retry on connection errors."""
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                client = self._get_client()
                response = await client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.ConnectError:
                import sys

                last_error = sys.exc_info()[1]
                logger.warning(
                    "[Fetcher] ConnectError for %s (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    MAX_RETRIES,
                    last_error,
                )
                if attempt < MAX_RETRIES - 1:
                    delay = 2**attempt
                    logger.info("[Fetcher] Retrying %s in %ds...", url, delay)
                    await asyncio.sleep(delay)
                    # Reset client on retry to force fresh connections
                    await self.aclose()
            except Exception:
                logger.exception("[Fetcher] Fetch failed for %s", url)
                raise

        raise last_error or RuntimeError(f"All {MAX_RETRIES} attempts failed for {url}")

    async def _ensure_browser(self):
        """Lazily launch and cache Playwright browser. Reuses across requests."""
        if self._browser is not None:
            # Periodically restart to prevent memory leaks from many contexts
            if self._browser_context_count >= self._max_contexts_before_restart:
                await self._close_browser()
            else:
                return self._browser

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
        except Exception as e:
            logger.warning("[Fetcher] Browser launch failed: %s", e)
            logger.warning(
                "[Fetcher] Falling back to static fetch for browser-required sites."
            )
            await self._close_browser()
            return None
        self._browser_context_count = 0
        logger.info("[Fetcher] Browser launched (reusable)")
        return self._browser

    async def fetch_article_with_browser(
        self, url: str, timeout_ms: int = 15000
    ) -> str:
        """Fetch a single article page via Playwright. No progressive scroll."""
        browser = await self._ensure_browser()
        if browser is None:
            return ""
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="zh-CN",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )
        self._browser_context_count += 1
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(1500)
            html = await page.content()
            return html
        except Exception as e:
            logger.warning("[Fetcher] Browser article fetch failed for %s: %s", url, e)
            return ""
        finally:
            await context.close()

    async def _close_browser(self):
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._browser_context_count = 0

    async def _fetch_with_browser(self, url: str) -> str:
        browser = await self._ensure_browser()
        if browser is None:
            logger.warning(
                "[Fetcher] Playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
            logger.warning("[Fetcher] Falling back to static fetch.")
            return await self._fetch_static(url)

        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="zh-CN",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )
        self._browser_context_count += 1
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        try:
            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self._browser_timeout_ms
                )
            except Exception:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self._browser_timeout_ms
                )

            await page.wait_for_timeout(2000)

            for _ in range(6):
                await page.evaluate(
                    "window.scrollBy(0, document.body.scrollHeight / 6)"
                )
                await page.wait_for_timeout(1500)

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(3000)

            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(500)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

            html = await page.content()
            return html
        except Exception:
            logger.warning(
                "[Fetcher] Browser interaction failed for %s, falling back to static fetch",
                url,
            )
            return await self._fetch_static(url)
        finally:
            try:
                await context.close()
            except Exception:
                pass  # browser already torn down, ignore cleanup error

    # ── utilities (shared) ──────────────────────────────────────────

    def _clean_html(self, html: str) -> str:
        text = SCRIPT_STYLE_PATTERN.sub(" ", html)
        soup = BeautifulSoup(text, "lxml")
        body = soup.get_text(separator=" ")
        return WHITESPACE_PATTERN.sub(" ", body).strip()

    def _hash_text(self, text: str) -> str:
        return sha256(text.encode("utf-8")).hexdigest()
