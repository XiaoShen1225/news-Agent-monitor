"""fetch_article tool — fetch webpage + AI summarization."""

import re

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


def make_fetch_article_tool(agent):
    @tool
    async def fetch_article(url: str, title: str = "") -> str:
        """抓取指定URL的网页正文并用AI生成中文摘要。需要网络请求，耗时较长（10-15秒）。

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
                    return cached

        try:
            client = agent._get_fetch_client()
            response = await client.get(url)
            response.raise_for_status()

            text = SCRIPT_STYLE_RE.sub(" ", response.text)
            soup = BeautifulSoup(text, "lxml")
            body = soup.get_text(separator=" ")
            body = WHITESPACE_RE.sub(" ", body).strip()

            if len(body) > 6000:
                body = body[:6000] + "…[内容已截断]"

            if len(body) < 100:
                return f"文章内容过短（{len(body)} 字符），可能为动态加载页面，无法提取正文。"

            title_hint = f"标题：「{title}」\n" if title else ""
            prompt = (
                f"{title_hint}请用 3-5 句中文摘要以下文章的核心内容，"
                f"突出关键信息和观点：\n\n{body}"
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
