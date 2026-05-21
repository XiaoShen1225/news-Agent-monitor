"""ParserAgent: structural extraction of news links + DOM-section-based tagging."""

import re
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup, NavigableString

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

SEARCH_LINK_PATTERN = re.compile(r"baidu\.com/s\?wd=")
CHINESE_ONLY = re.compile(r"[^\u4e00-\u9fff]")

# Navigation/UI labels that are NOT news section headers
UI_LABELS = {"首页", "登录", "注册", "帮助", "新闻全文", "新闻标题", "更多", "收起",
             "返回", "用户协议", "隐私策略", "营业执照", "收藏本站", "用户反馈",
             "辅助模式", "扫描二维码", "使用百度前必读", "百度新闻客户端"}

# Known section header keywords → canonical tag name
SECTION_MAP = {
    "热点": "要闻", "要闻": "要闻", "热榜": "热榜",
    "北京": "本地", "上海": "本地", "广东": "本地", "深圳": "本地",
    "本地": "本地",
    "国内": "国内", "国际": "国际", "军事": "军事",
    "财经": "财经", "娱乐": "娱乐", "体育": "体育",
    "科技": "科技", "互联网": "科技", "游戏": "游戏",
    "女人": "女性", "汽车": "汽车", "房产": "房产",
    "教育": "教育", "健康": "健康",
    "视频": "视频", "图片": "图片",
    "推荐": "推荐", "精选": "精选",
    "专题": "专题", "探索": "探索",
    "明星": "娱乐", "NBA": "体育", "中国军情": "军事",
}

NOISE_PATTERNS = [
    re.compile(r"^加载中"), re.compile(r"^正在加载"), re.compile(r"^点击刷新"),
    re.compile(r"^\d+$"), re.compile(r"^HOT WORDS$", re.I),
    re.compile(r"^百度"), re.compile(r"^更多"), re.compile(r"^图文资讯"),
    re.compile(r"^新闻图片"), re.compile(r"^热门点击"),
    re.compile(r"^用户协议"), re.compile(r"^隐私策略"), re.compile(r"^营业执照"),
    re.compile(r"^京ICP"), re.compile(r"^京公网"),
    re.compile(r"辟谣平台$"), re.compile(r"举报中心"),
    re.compile(r"^切换城市"), re.compile(r"^热搜新闻词"),
    re.compile(r"^互联网新闻信息服务许可"), re.compile(r"^互联网宗教信息服务许可证"),
    re.compile(r"^随时随地收看更多新闻"),
    re.compile(r"版下载$"),  # app download links
]

SECTION_PATTERNS = [
    re.compile(r"^[A-Za-z\s]+$"),
    re.compile(r"^.{1,3}$"),
]


class ParserAgent(BaseAgent):
    def __init__(self, config: dict):
        super().__init__("Parser", config)
        self.min_title_len = 6
        self.max_title_len = 200

    def run(self, html: str, site_name: str = "default", page_url: str = "") -> dict:
        logger.info("[Parser] Extracting news links from HTML (%s, %d bytes)", site_name, len(html))

        soup = BeautifulSoup(html, "lxml")

        # Single-pass DOM traversal: track current section, extract links
        raw_links = self._extract_news_links(soup, page_url)

        # Deduplicate by title
        seen_titles = set()
        unique_links = []
        for link in raw_links:
            key = link["title"].strip()
            if key and key not in seen_titles:
                seen_titles.add(key)
                unique_links.append(link)

        # Build items (no time field — not reliably available on listing pages)
        items = []
        for link in unique_links:
            items.append({
                "title": link["title"],
                "url": link["url"],
                "tag": link["tag"],
            })

        # Show tag distribution
        from collections import Counter
        tag_counts = Counter(item["tag"] for item in items)
        top_tags = ", ".join(f"{t}:{c}" for t, c in tag_counts.most_common(8))

        logger.info("[Parser] %d items extracted. Tags: %s", len(items), top_tags)
        return {"items": items, "extraction_confidence": 1.0, "raw_response": ""}

    def _is_valid_link(self, text: str, href: str) -> bool:
        """Check if text+url passes all filters for a news link."""
        if not text or len(text) < self.min_title_len or len(text) > self.max_title_len:
            return False
        if href.startswith("javascript:") or href == "#":
            return False
        if SEARCH_LINK_PATTERN.search(href):
            return False
        if text in UI_LABELS:
            return False
        if any(p.search(text) for p in NOISE_PATTERNS):
            return False
        if any(p.search(text) for p in SECTION_PATTERNS):
            return False
        return True

    def _match_section(self, text: str):
        """Try to match text against SECTION_MAP. Longer key matches win."""
        best_tag = None
        best_len = 0
        for candidate in (text, CHINESE_ONLY.sub("", text)):
            if not candidate or len(candidate) < 2:
                continue
            for key, tag in SECTION_MAP.items():
                if key in candidate and len(key) > best_len:
                    best_tag = tag
                    best_len = len(key)
        return best_tag

    def _extract_news_links(self, soup: BeautifulSoup, page_url: str) -> list:
        """Walk DOM in document order, tracking the current section and extracting links."""
        links = []
        current_tag = "要闻"
        MAX_SECTION_LEN = 6

        for element in soup.descendants:
            if isinstance(element, NavigableString):
                text = element.get_text(strip=True)
                if 2 <= len(text) <= MAX_SECTION_LEN and text not in UI_LABELS:
                    parent = element.parent
                    if parent and parent.name == 'a':
                        p_href = parent.get('href', '').strip()
                        p_text = parent.get_text(strip=True)
                        # News link text should not act as a section marker
                        if self._is_valid_link(p_text, p_href):
                            continue
                    tag = self._match_section(text)
                    if tag:
                        current_tag = tag
            elif hasattr(element, 'name') and element.name == 'a':
                href = element.get('href', '').strip()
                if not href:
                    continue
                text = element.get_text(strip=True)

                if not self._is_valid_link(text, href):
                    continue

                full_url = urljoin(page_url, href) if page_url else href
                links.append({
                    "title": text,
                    "url": full_url,
                    "tag": current_tag,
                })

        return links
