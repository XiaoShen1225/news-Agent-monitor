"""Tests for ParserAgent: link extraction, section matching, noise filtering."""

import pytest
from agents.parser import ParserAgent, UI_LABELS, SECTION_MAP


@pytest.fixture
def agent():
    config = {"llm": {"api_key": "test", "model": "glm-4-flash"}}
    return ParserAgent(config)


class TestFiltering:
    def test_valid_link_short_title(self, agent):
        assert not agent._is_valid_link("短", "https://example.com/news")

    def test_valid_link_javascript(self, agent):
        assert not agent._is_valid_link("Valid Title Here", "javascript:void(0)")

    def test_valid_link_hash(self, agent):
        assert not agent._is_valid_link("Valid Title Here", "#")

    def test_valid_link_baidu_search(self, agent):
        assert not agent._is_valid_link(
            "Search Result", "https://baidu.com/s?wd=test"
        )

    def test_valid_link_ui_label(self, agent):
        assert not agent._is_valid_link("首页", "https://example.com")

    def test_valid_link_noise_baidu(self, agent):
        assert not agent._is_valid_link("百度一下你就知道", "https://example.com")

    def test_valid_link_noise_icp(self, agent):
        assert not agent._is_valid_link("京ICP备123456号", "https://example.com")

    def test_valid_link_good(self, agent):
        assert agent._is_valid_link(
            "中国科技取得重大突破", "https://news.example.com/tech/1"
        )

    def test_valid_link_too_long(self, agent):
        assert not agent._is_valid_link("X" * 201, "https://example.com")


class TestSectionMatching:
    def test_match_known_keyword(self, agent):
        assert agent._match_section("国内新闻") == "国内"

    def test_match_longer_keyword_wins(self, agent):
        # "中国军情" (4 chars) > "中国" would match if present; "国内" not in it
        assert agent._match_section("中国军情") == "军事"

    def test_match_mixed_chinese_english(self, agent):
        assert agent._match_section("国内China") == "国内"

    def test_no_match(self, agent):
        assert agent._match_section("不知道") is None

    def test_short_text_ignored(self, agent):
        assert agent._match_section("中") is None


class TestDomExtraction:
    HTML = """<!DOCTYPE html>
<html><body>
<div>
    <h3>国内</h3>
    <a href="https://news.example.com/1">中国经济增长持续向好势头明显各项指标超预期</a>
    <a href="https://news.example.com/2">春节出行人数创历史新高</a>
</div>
<div>
    <h3>科技</h3>
    <a href="https://news.example.com/3">AI大模型技术取得突破性进展引发行业变革</a>
    <a href="https://news.example.com/4">量子计算实现新里程碑</a>
</div>
<div>
    <h3>娱乐</h3>
    <a href="https://news.example.com/5">春节档电影票房突破百亿</a>
    <a href="https://news.example.com/6">知名导演新作官宣引期待</a>
</div>
</body></html>"""

    def test_extracts_links_with_tags(self, agent):
        result = agent.run(self.HTML, site_name="test", page_url="https://news.example.com")
        items = result["items"]
        assert len(items) >= 4

        tags = {item["tag"] for item in items}
        assert "国内" in tags
        assert "科技" in tags
        assert "娱乐" in tags

    def test_extraction_confidence(self, agent):
        result = agent.run(self.HTML, site_name="test")
        assert result["extraction_confidence"] == 1.0

    def test_deduplication(self, agent):
        dup_html = """<div>
            <a href="/a">同一标题出现两次</a>
            <a href="/b">同一标题出现两次</a>
        </div>"""
        result = agent.run(dup_html, site_name="test")
        assert len(result["items"]) == 1


class TestSectionMap:
    def test_section_map_coverage(self):
        # Verify key categories map correctly
        assert SECTION_MAP["热点"] == "要闻"
        assert SECTION_MAP["国内"] == "国内"
        assert SECTION_MAP["国际"] == "国际"
        assert SECTION_MAP["科技"] == "科技"
        assert SECTION_MAP["财经"] == "财经"
        assert SECTION_MAP["娱乐"] == "娱乐"
        assert SECTION_MAP["体育"] == "体育"
        assert SECTION_MAP["军事"] == "军事"
        assert SECTION_MAP["NBA"] == "体育"
        assert SECTION_MAP["明星"] == "娱乐"
        assert SECTION_MAP["中国军情"] == "军事"


class TestUiLabels:
    def test_common_labels_blocked(self):
        for label in ["首页", "登录", "注册", "帮助", "更多", "返回"]:
            assert label in UI_LABELS
