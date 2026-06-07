"""fetch_article tool — fetch webpage + AI summarization + image extraction."""

import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
WHITESPACE_RE = re.compile(r"\s+")

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _extract_images(soup: BeautifulSoup, base_url: str, limit: int = 10) -> list[str]:
    """Find image URLs with minimal filtering. Searches entire page first;
    only narrows to content area when that yields fewer irrelevant results.
    Returns up to ``limit`` unique absolute URLs.
    """
    # Collect candidates from the whole page
    urls: list[str] = []
    seen: set[str] = set()
    all_imgs = soup.find_all("img")
    logger.info("_extract_images: %d imgs in full page", len(all_imgs))
    for img in all_imgs:
        raw = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-original")
            or img.get("data-lazy-src")
            or ""
        ).strip()
        if not raw or raw.startswith("data:"):
            continue
        full = urljoin(base_url, raw)
        if full not in seen:
            seen.add(full)
            urls.append(full)
            if len(urls) >= limit:
                break
    # Diagnostic: show first 3 for debugging
    for i, u in enumerate(urls[:3]):
        logger.info("_extract_images: [%d] %s", i, u[:150])
    return urls


def make_fetch_article_tool(agent):
    @tool
    async def fetch_article(url: str, title: str = "") -> str:
        """抓取指定URL的网页正文，用AI生成中文摘要，并提取正文区域图片。

        返回格式：摘要 + [配图1] URL + [配图2] URL ...（最多10张候选）。
        请从候选配图中选最相关的一张展示给用户。
        需要网络请求，耗时较长（10-15秒）。
        """
        if not url:
            return "[参数错误] 未提供 url 参数。"
        if not (url.startswith("http://") or url.startswith("https://")):
            return "[参数错误] URL必须以 http:// 或 https:// 开头。"

        # Check cache first — but if image_url is missing, re-fetch to extract it
        for store in (agent.news_store, agent.paper_store):
            if not store:
                continue
            try:
                cached = store.get_item_summary(url)
            except Exception:
                continue
            if cached and "[配图]" in cached:
                return cached
            if cached:
                try:
                    img = store.get_item_image(url)
                except Exception:
                    img = None
                if img:
                    cached += f"\n[配图] {img}"
                    return cached
                logger.info(
                    "fetch_article: cache hit for %s but no image, re-fetching",
                    url[:80],
                )

        try:
            # Try Playwright browser first (bypasses anti-bot measures)
            html = ""
            if agent._coordinator and agent._coordinator.fetcher:
                try:
                    html = await agent._coordinator.fetcher.fetch_article_with_browser(
                        url
                    )
                except Exception:
                    pass

            # Fall back to httpx if browser fetch failed or returned empty
            if not html:
                logger.info(
                    "fetch_article: browser fetch failed/empty for %s, trying httpx",
                    url[:80],
                )
                client = agent._get_fetch_client()
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
                logger.info(
                    "fetch_article: httpx got %d bytes for %s", len(html), url[:80]
                )

            text = SCRIPT_STYLE_RE.sub(" ", html)
            soup = BeautifulSoup(text, "lxml")

            # Extract image URLs (minimal filtering, Agent picks the best one)
            img_urls = _extract_images(soup, url)
            if img_urls:
                for store in (agent.news_store, agent.paper_store):
                    if store:
                        try:
                            store.update_item_image(url, img_urls[0])
                        except Exception:
                            pass

            body = soup.get_text(separator=" ")
            body = WHITESPACE_RE.sub(" ", body).strip()

            if len(body) > 6000:
                body = body[:6000] + "…[内容已截断]"

            if len(body) < 100:
                return f"文章内容过短（{len(body)} 字符），可能为动态加载页面，无法提取正文。"

            if "验证" in body[:200] and ("拖动" in body[:200] or "拼图" in body[:200]):
                return "[反爬拦截] 网站要求验证码验证，请稍后重试或更换来源。"

            title_hint = f"标题：「{title}」\n" if title else ""
            prompt = (
                f"{title_hint}请用 3-5 句中文摘要以下文章的核心内容，"
                f"突出关键信息和观点。\n\n{body}"
            )

            result = await agent.model.ainvoke([{"role": "user", "content": prompt}])
            summary = result.content or "(摘要生成失败)"

            # Cache the summary
            for store in (agent.news_store, agent.paper_store):
                if store:
                    try:
                        store.update_item_summary(url, summary)
                    except Exception:
                        pass

            if img_urls:
                img_lines = "\n".join(
                    f"[配图{i + 1}] {u}" for i, u in enumerate(img_urls)
                )
                return f"{summary}\n\n{img_lines}"
            return summary
        except httpx.HTTPStatusError as e:
            return (
                f"[抓取错误] HTTP {e.response.status_code} — 网页可能不存在或需要登录。"
            )
        except httpx.ConnectError:
            return (
                "[抓取错误] 网络连接失败，目标网站可能被屏蔽（如 GFW），或网络不稳定。"
            )
        except Exception as e:
            return f"[抓取错误] {type(e).__name__}: {e}"

    return fetch_article
