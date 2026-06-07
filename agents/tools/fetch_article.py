"""fetch_article tool — fetch webpage + AI summarization + image extraction."""

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import tool

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

# Minimum width/height for an img to be considered a content image (skip icons)
MIN_IMG_SIZE = 120
ICON_PATTERNS = [
    "icon",
    "logo",
    "avatar",
    "homenav",
    "qr_code",
    "qr-code",
    "button",
    "placeholder",
    "pixel",
    "track",
    "favicon",
    "apple-touch-icon",
    "code110x110",
    "banner_",
    "wechat",
    "weibo",
    "share",
    "qrcode",
    "erweima",
    "code_",
    "mini_",
    "thumb_",
    "default_",
    "prd/",
]
# Parent tags that indicate a UI/decoration image, not article content
SKIP_PARENTS = {"nav", "header", "footer", "aside", "noscript", "template"}


def _is_icon_url(url: str) -> bool:
    """Check if a URL looks like an icon/decoration, not article content.

    Patterns without '/' match only the filename (last path segment).
    Patterns with '/' match anywhere in the URL.
    """
    lower = url.lower()
    # Split URL: check only the filename portion for non-path patterns
    path = lower.split("?")[0]  # strip query string
    filename = path.rsplit("/", 1)[-1] if "/" in path else path
    for p in ICON_PATTERNS:
        if "/" in p:
            if p in lower:
                return True
        else:
            if p in filename:
                return True
    return False


def _extract_image(soup: BeautifulSoup, base_url: str) -> tuple[str, str]:
    """Extract (image_url, alt_text) from a page."""
    # 1. og:image / twitter:image — check both property and name attributes
    og_img = None
    for attr in ("property", "name"):
        for tag_name in ("og:image", "twitter:image"):
            og = soup.find("meta", {attr: tag_name})
            if og and og.get("content"):
                full_url = urljoin(base_url, og["content"].strip())
                if not _is_icon_url(full_url):
                    og_img = full_url
                    break
        if og_img:
            break
    if og_img:
        alt = ""
        og_alt = soup.find("meta", property="og:image:alt") or soup.find(
            "meta", attrs={"name": "og:image:alt"}
        )
        if og_alt and og_alt.get("content"):
            alt = og_alt["content"].strip()
        return og_img, alt

    # 2. Scan <img> in content area, prefer <figure> children, skip UI
    content_area = (
        soup.find("article")
        or soup.find("main")
        or soup.find("div", class_=re.compile(r"content|article|post|detail|body"))
    )
    search_in = content_area if content_area else soup

    candidates = []  # (score, src, alt) — higher score = better
    for img in search_in.find_all("img"):
        src = (img.get("src") or "").strip()
        # Fallback for lazy-loaded images: data-src, data-original, data-lazy-src
        if not src or src.startswith("data:") or _is_icon_url(src):
            for attr in ("data-src", "data-original", "data-lazy-src"):
                alt_src = (img.get(attr) or "").strip()
                if (
                    alt_src
                    and not alt_src.startswith("data:")
                    and not _is_icon_url(alt_src)
                ):
                    src = alt_src
                    break
        if not src or src.startswith("data:") or _is_icon_url(src):
            continue
        # Skip UI images by parent tag
        parent = img.parent
        if parent and parent.name in SKIP_PARENTS:
            continue
        # Skip if ancestor has share/sidebar/tool class
        skip = False
        for a in img.parents:
            cls = (a.get("class") or []) if hasattr(a, "get") else []
            cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
            if any(
                k in cls_str.lower()
                for k in ("share", "sidebar", "toolbar", "recommend", "related")
            ):
                skip = True
                break
        if skip:
            continue

        w = _parse_dim(img.get("width"))
        h = _parse_dim(img.get("height"))
        if w is not None and w < MIN_IMG_SIZE:
            continue
        if h is not None and h < MIN_IMG_SIZE:
            continue

        score = (w or 0) * (h or 0)
        # Bonus for <figure>/<picture> children (strong content signal)
        if parent and parent.name in ("figure", "picture"):
            score += 100000
        alt = (img.get("alt") or "").strip()
        # Boost images with descriptive alt text
        if len(alt) > 5:
            score += 50000
        candidates.append((score, src, alt))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        _, src, alt = candidates[0]
        return urljoin(base_url, src), alt

    return "", ""


def _parse_dim(val) -> int | None:
    if val is None:
        return None
    try:
        return int(str(val).strip("px "))
    except (ValueError, TypeError):
        return None


def make_fetch_article_tool(agent):
    @tool
    async def fetch_article(url: str, title: str = "") -> str:
        """抓取指定URL的网页正文，用AI生成中文摘要，并自动提取文章配图（若有）。

        返回格式：摘要 + [配图] URL。若返回中包含 [配图]，请在回复中展示该图片链接。
        需要网络请求，耗时较长（10-15秒）。
        使用场景：用户想看某篇文章的具体内容，且 get_item 缓存为空时使用。
        优先用 get_item 查缓存，确认无缓存后再用此工具。
        """
        if not url:
            return "[参数错误] 未提供 url 参数。"
        if not (url.startswith("http://") or url.startswith("https://")):
            return "[参数错误] URL必须以 http:// 或 https:// 开头。"

        # Check cache first
        for store in (agent.news_store, agent.paper_store):
            if store:
                cached = store.get_item_summary(url)
                if cached:
                    img = store.get_item_image(url)
                    if img:
                        cached += f"\n[配图] {img}"
                    return cached

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
                client = agent._get_fetch_client()
                response = await client.get(url)
                response.raise_for_status()
                html = response.text

            text = SCRIPT_STYLE_RE.sub(" ", html)
            soup = BeautifulSoup(text, "lxml")

            # Extract image
            img_url, img_alt = _extract_image(soup, url)
            if img_url:
                for store in (agent.news_store, agent.paper_store):
                    if store:
                        try:
                            store.update_item_image(url, img_url)
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
            img_hint = ""
            if img_alt:
                img_hint = f"（文章配图描述：{img_alt}）"
            prompt = (
                f"{title_hint}请用 3-5 句中文摘要以下文章的核心内容，"
                f"突出关键信息和观点。{img_hint}\n\n{body}"
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

            img_line = f"\n[配图] {img_url}" if img_url else ""
            return summary + img_line
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
