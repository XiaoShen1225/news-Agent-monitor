"""Tests for FetcherAgent: HTML cleaning, hash computation, and static fetch."""

import pytest
from agents.fetcher import FetcherAgent, SCRIPT_STYLE_PATTERN, WHITESPACE_PATTERN


@pytest.fixture
def agent():
    config = {"llm": {"api_key": "test", "model": "glm-4-flash"}}
    return FetcherAgent(config)


class TestHtmlCleaning:
    def test_strips_script_tags(self, agent):
        html = "<html><body><p>Hello</p><script>alert('xss')</script></body></html>"
        cleaned = agent._clean_html(html)
        assert "alert" not in cleaned
        assert "Hello" in cleaned

    def test_strips_style_tags(self, agent):
        html = "<html><head><style>.a{color:red}</style></head><body>Content</body></html>"
        cleaned = agent._clean_html(html)
        assert "color" not in cleaned
        assert "Content" in cleaned

    def test_strips_noscript(self, agent):
        html = "<html><body><noscript>JS required</noscript><p>text</p></body></html>"
        cleaned = agent._clean_html(html)
        assert "JS required" not in cleaned
        assert "text" in cleaned

    def test_normalizes_whitespace(self, agent):
        html = "<html><body>   hello    world   </body></html>"
        cleaned = agent._clean_html(html)
        assert "   " not in cleaned

    def test_empty_html(self, agent):
        cleaned = agent._clean_html("<html></html>")
        assert isinstance(cleaned, str)


class TestHashComputation:
    def test_deterministic(self, agent):
        h1 = agent._hash_text("hello world")
        h2 = agent._hash_text("hello world")
        assert h1 == h2

    def test_different_content_different_hash(self, agent):
        h1 = agent._hash_text("hello world")
        h2 = agent._hash_text("hello world!")
        assert h1 != h2

    def test_hash_length(self, agent):
        h = agent._hash_text("test")
        assert len(h) == 64  # SHA256


class TestRegexPatterns:
    def test_script_pattern(self):
        assert SCRIPT_STYLE_PATTERN.search('<script>var x=1;</script>')
        assert SCRIPT_STYLE_PATTERN.search('<style>.a{}</style>')
        assert SCRIPT_STYLE_PATTERN.search('<noscript>text</noscript>')

    def test_whitespace_pattern(self):
        result = WHITESPACE_PATTERN.sub(" ", "a   b\n\nc")
        assert result == "a b c"
