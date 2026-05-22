"""ParserAgent: multi-strategy news link extraction + DOM-section-based tagging."""

import asyncio
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import yaml
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

_PROMPT_PATH = Path("prompts/extraction.yaml")
_LLM_PROMPT_CACHE: Optional[dict] = None


def _get_llm_prompts() -> dict:
    global _LLM_PROMPT_CACHE
    if _LLM_PROMPT_CACHE is None:
        if _PROMPT_PATH.exists():
            with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
                _LLM_PROMPT_CACHE = yaml.safe_load(f) or {}
        else:
            _LLM_PROMPT_CACHE = {}
    return _LLM_PROMPT_CACHE


class ParserAgent(BaseAgent):
    def __init__(self, config: dict):
        super().__init__("Parser", config)
        self.min_title_len = 6
        self.max_title_len = 200

    def run(
        self, html: str, site_name: str = "default", page_url: str = "",
        profile: Optional[SiteProfile] = None,
    ) -> dict:
        """Sync entry point. Delegates to run_async for LLM strategy."""
        profile_obj = profile or get_profile(site_name)

        if profile_obj.strategy == "llm":
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(self.run_async(html, site_name, page_url, profile_obj))
            raise RuntimeError("Parser.run() with LLM strategy in async context — use run_async()")

        return self._run_sync_impl(html, site_name, page_url, profile_obj)

    def _run_sync_impl(
        self, html: str, site_name: str, page_url: str, profile_obj: SiteProfile,
    ) -> dict:
        """Synchronous HTML parsing for section_walk / css_selector strategies."""
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

        return self._build_result(raw_links)

    # ── async LLM extraction ──────────────────────────────────────────

    async def run_async(
        self, html: str, site_name: str = "default", page_url: str = "",
        profile: Optional[SiteProfile] = None,
    ) -> dict:
        """Async entry point for parsing (required for LLM strategy)."""
        profile_obj = profile or get_profile(site_name)

        if profile_obj.strategy != "llm":
            return self._run_sync_impl(html, site_name, page_url, profile_obj)

        self.min_title_len = profile_obj.min_title_len
        self.max_title_len = profile_obj.max_title_len

        logger.info(
            "[Parser] LLM extraction for %s (%d bytes)",
            site_name, len(html),
        )

        soup = BeautifulSoup(html, "lxml")
        raw_links = await self._extract_llm_async(soup, page_url, profile_obj, site_name)
        return self._build_result(raw_links)

    def _extract_candidates(self, soup: BeautifulSoup, page_url: str,
                            profile_obj: SiteProfile) -> list[dict]:
        """Extract all <a> tag candidates from the page for LLM classification."""
        candidates = []
        seen = set()

        for a_tag in soup.find_all("a"):
            href = (a_tag.get("href") or "").strip()
            if not href or href.startswith("javascript:") or href == "#":
                continue
            text = a_tag.get_text(strip=True)
            if not text or len(text) < self.min_title_len or len(text) > self.max_title_len:
                continue
            # Pre-filter obvious noise
            if any(p.search(text) for p in _UNIVERSAL_NOISE):
                continue
            if any(p.search(text) for p in SECTION_PATTERNS):
                continue
            if text in seen:
                continue
            seen.add(text)
            full_url = urljoin(page_url, href) if page_url else href
            candidates.append({"title": text, "url": full_url})

        return candidates

    async def _extract_llm_async(self, soup: BeautifulSoup, page_url: str,
                                  profile_obj: SiteProfile, site_name: str) -> list:
        """Extract news items via LLM: pre-filter candidates, send to LLM, parse result."""
        candidates = self._extract_candidates(soup, page_url, profile_obj)

        if not candidates:
            logger.warning("[Parser] No candidate links found for LLM extraction.")
            return []

        # Build numbered candidate list for LLM prompt
        lines = []
        for i, c in enumerate(candidates, 1):
            url_short = c["url"][:80]
            lines.append(f"{i}. {c['title']} | {url_short}")
        candidate_text = "\n".join(lines)

        tag_candidates = profile_obj.llm_tag_candidates or [
            "国内", "国际", "财经", "科技", "体育", "娱乐", "社会", "军事", "教育", "健康", "其他"
        ]
        tag_list = "、".join(tag_candidates)

        prompts = _get_llm_prompts()
        llm_cfg = prompts.get("llm_extraction", {})
        system_prompt = llm_cfg.get("system", "You are a news link classifier.")
        user_template = llm_cfg.get("user_template",
            "Site: {site_name}\nTags: {tag_candidates}\nLinks:\n{candidates}\nReturn JSON array.")

        user_prompt = user_template.format(
            site_name=site_name,
            tag_candidates=tag_list,
            candidates=candidate_text,
        )

        logger.info("[Parser] Sending %d candidates to LLM for classification.", len(candidates))
        response = await self.call_llm_async(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=1500,
        )

        # Parse LLM response
        try:
            selections = self.parse_json_response(response)
        except ValueError as e:
            logger.warning("[Parser] LLM extraction parse failed: %s", e)
            return []

        if not isinstance(selections, list):
            logger.warning("[Parser] LLM returned non-list response: %s", type(selections))
            return []

        # Map indices back to candidates
        result = []
        for sel in selections:
            if not isinstance(sel, dict):
                continue
            idx = sel.get("index", -1) - 1  # 1-based to 0-based
            if 0 <= idx < len(candidates):
                result.append({
                    "title": candidates[idx]["title"],
                    "url": candidates[idx]["url"],
                    "tag": sel.get("tag", "其他"),
                })

        logger.info("[Parser] LLM classified %d/%d candidates as news.", len(result), len(candidates))
        return result

    # ── shared ────────────────────────────────────────────────────────

    def _build_result(self, raw_links: list) -> dict:
        """Deduplicate by title and build standard result dict."""
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
