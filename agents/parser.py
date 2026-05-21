"""ParserAgent: multi-strategy news link extraction + DOM-section-based tagging."""

import logging
import re
from collections import Counter
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString

from .base_agent import BaseAgent
from .site_profiles import BAIDU_NEWS, SiteProfile, get_profile

logger = logging.getLogger(__name__)

SEARCH_LINK_PATTERN = re.compile(r"baidu\.com/s\?wd=")
CHINESE_ONLY = re.compile(r"[^\u4e00-\u9fff]")

# Fallback defaults (used when no site profile is provided)
_DEFAULT_SECTION_MAP = BAIDU_NEWS.section_map
_DEFAULT_NOISE = [re.compile(p) for p in BAIDU_NEWS.noise_patterns]
_DEFAULT_UI_LABELS = BAIDU_NEWS.ui_labels

SECTION_PATTERNS = [
    re.compile(r"^[A-Za-z\s]+$"),
    re.compile(r"^.{1,3}$"),
]

# Common junk patterns applied across all sites
_UNIVERSAL_NOISE = [
    re.compile(r"^加载中"), re.compile(r"^\d+$"),
    re.compile(r"^登录"), re.compile(r"^注册"),
    re.compile(r"^关于我们"), re.compile(r"^广告"),
]


class ParserAgent(BaseAgent):
    def __init__(self, config: dict):
        super().__init__("Parser", config)
        self.min_title_len = 6
        self.max_title_len = 200

    def run(
        self, html: str, site_name: str = "default", page_url: str = "",
        profile: Optional[SiteProfile] = None,
    ) -> dict:
        profile_obj = profile or get_profile(site_name)

        self.min_title_len = profile_obj.min_title_len
        self.max_title_len = profile_obj.max_title_len

        logger.info(
            "[Parser] Extracting news from %s (%d bytes, strategy=%s)",
            site_name, len(html), profile_obj.strategy,
        )

        soup = BeautifulSoup(html, "lxml")

        if profile_obj.strategy == "css_selector":
            raw_links = self._extract_css(soup, page_url, profile_obj)
        else:
            raw_links = self._extract_section_walk(soup, page_url, profile_obj)

        # Deduplicate by title
        seen_titles = set()
        unique_links = []
        for link in raw_links:
            key = link["title"].strip()
            if key and key not in seen_titles:
                seen_titles.add(key)
                unique_links.append(link)

        items = [
            {"title": lnk["title"], "url": lnk["url"], "tag": lnk["tag"]}
            for lnk in unique_links
        ]

        tag_counts = Counter(item["tag"] for item in items)
        top_tags = ", ".join(f"{t}:{c}" for t, c in tag_counts.most_common(8))

        logger.info("[Parser] %d items extracted. Tags: %s", len(items), top_tags)
        return {"items": items, "extraction_confidence": 1.0, "raw_response": ""}

    # ── validation ──────────────────────────────────────────────────

    def _is_valid_link(self, text: str, href: str,
                       ui_labels: set, noise_patterns: list,
                       search_pattern=None) -> bool:
        if not text or len(text) < self.min_title_len or len(text) > self.max_title_len:
            return False
        if href.startswith("javascript:") or href == "#":
            return False
        if search_pattern and search_pattern.search(href):
            return False
        if text in ui_labels:
            return False
        if any(p.search(text) for p in noise_patterns):
            return False
        if any(p.search(text) for p in _UNIVERSAL_NOISE):
            return False
        if any(p.search(text) for p in SECTION_PATTERNS):
            return False
        return True

    # ── strategy: section_walk ──────────────────────────────────────

    def _extract_section_walk(self, soup: BeautifulSoup, page_url: str,
                               profile: SiteProfile) -> list:
        section_map = profile.section_map or _DEFAULT_SECTION_MAP
        ui_labels = profile.ui_labels or _DEFAULT_UI_LABELS
        noise_patterns = [re.compile(p) for p in profile.noise_patterns] if profile.noise_patterns else _DEFAULT_NOISE
        max_section_len = profile.section_max_len

        links = []
        current_tag = "要闻"

        for element in soup.descendants:
            if isinstance(element, NavigableString):
                text = element.get_text(strip=True)
                if 2 <= len(text) <= max_section_len and text not in ui_labels:
                    parent = element.parent
                    if parent and parent.name == "a":
                        p_href = parent.get("href", "").strip()
                        p_text = parent.get_text(strip=True)
                        if self._is_valid_link(p_text, p_href, ui_labels, noise_patterns):
                            continue
                    tag = self._match_section(text, section_map)
                    if tag:
                        current_tag = tag
            elif hasattr(element, "name") and element.name == "a":
                href = element.get("href", "").strip()
                if not href:
                    continue
                text = element.get_text(strip=True)

                if not self._is_valid_link(text, href, ui_labels, noise_patterns, SEARCH_LINK_PATTERN):
                    continue

                full_url = urljoin(page_url, href) if page_url else href
                links.append({"title": text, "url": full_url, "tag": current_tag})

        return links

    def _match_section(self, text: str, section_map: dict):
        best_tag = None
        best_len = 0
        for candidate in (text, CHINESE_ONLY.sub("", text)):
            if not candidate or len(candidate) < 2:
                continue
            for key, tag in section_map.items():
                if key in candidate and len(key) > best_len:
                    best_tag = tag
                    best_len = len(key)
        return best_tag

    # ── strategy: css_selector ──────────────────────────────────────

    def _extract_css(self, soup: BeautifulSoup, page_url: str,
                      profile: SiteProfile) -> list:
        noise_patterns = [re.compile(p) for p in profile.noise_patterns]
        links = []
        tag = profile.fixed_tag

        try:
            containers = soup.select(profile.article_selector)
        except Exception:
            containers = []

        if not containers:
            # Fallback: extract all <a> tags with reasonable text
            containers = [soup]

        seen_texts = set()
        for container in containers:
            for a_tag in container.find_all("a"):
                href = a_tag.get(profile.link_attr, "").strip()
                if not href:
                    continue
                text = a_tag.get_text(strip=True)

                if not self._is_valid_link(text, href, set(), noise_patterns):
                    continue

                full_url = urljoin(page_url, href) if page_url else href

                if profile.tag_from == "selector" and profile.tag_selector:
                    tag_el = a_tag.select_one(profile.tag_selector)
                    if tag_el:
                        tag = tag_el.get_text(strip=True)

                if text not in seen_texts:
                    seen_texts.add(text)
                    links.append({"title": text, "url": full_url, "tag": tag})

        return links
