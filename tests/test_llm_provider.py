"""Tests for LLM Provider abstraction layer."""

import pytest

from agents.llm_provider import ChatResult, StreamEvent
from agents.provider_factory import create_provider


class TestProviderFactory:
    def test_create_zhipu_provider(self):
        config = {
            "llm": {
                "provider": "zhipu",
                "model": "glm-4-flash",
                "max_retries": 2,
                "providers": {
                    "zhipu": {
                        "api_key": "test-key",
                        "base_url": "https://test.api.com/v1",
                    }
                },
            }
        }
        provider = create_provider(config)
        from agents.providers.zhipu_provider import ZhipuProvider

        assert isinstance(provider, ZhipuProvider)
        assert provider.model == "glm-4-flash"

    def test_create_openai_provider(self):
        config = {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "providers": {
                    "openai": {
                        "api_key": "sk-test",
                    }
                },
            }
        }
        provider = create_provider(config)
        from agents.providers.openai_provider import OpenAIProvider

        assert isinstance(provider, OpenAIProvider)

    def test_create_local_provider(self):
        config = {
            "llm": {
                "provider": "local",
                "model": "llama3",
                "providers": {
                    "local": {
                        "base_url": "http://localhost:11434/v1",
                        "api_key": "ollama",
                    }
                },
            }
        }
        provider = create_provider(config)
        from agents.providers.local_provider import LocalProvider

        assert isinstance(provider, LocalProvider)
        assert provider.model == "llama3"

    def test_default_provider_is_zhipu(self):
        config = {
            "llm": {
                "api_key": "test-key",
            }
        }
        provider = create_provider(config)
        from agents.providers.zhipu_provider import ZhipuProvider

        assert isinstance(provider, ZhipuProvider)

    def test_unknown_provider_raises(self):
        config = {
            "llm": {
                "provider": "nonexistent",
                "api_key": "x",
            }
        }
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_provider(config)

    def test_provider_specific_model_overrides_top_level(self):
        config = {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "providers": {
                    "openai": {
                        "api_key": "sk-test",
                        "model": "gpt-4o-mini",
                    }
                },
            }
        }
        provider = create_provider(config)
        assert provider.model == "gpt-4o-mini"

    def test_provider_supports_tools(self):
        config = {
            "llm": {"provider": "local", "providers": {"local": {"api_key": "x"}}}
        }
        provider = create_provider(config)
        assert provider.supports_tools() is False


class TestChatResult:
    def test_default_values(self):
        r = ChatResult()
        assert r.content is None
        assert r.tool_calls == []
        assert r.total_tokens == 0

    def test_with_content(self):
        r = ChatResult(content="hello", total_tokens=10)
        assert r.content == "hello"
        assert r.total_tokens == 10

    def test_with_tool_calls(self):
        tc = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "test", "arguments": "{}"},
            }
        ]
        r = ChatResult(tool_calls=tc)
        assert len(r.tool_calls) == 1
        assert r.tool_calls[0]["id"] == "call_1"


class TestStreamEvent:
    def test_content_event(self):
        e = StreamEvent(type="content", content="你好")
        assert e.type == "content"
        assert e.content == "你好"

    def test_done_event(self):
        e = StreamEvent(type="done", total_tokens=100)
        assert e.type == "done"
        assert e.total_tokens == 100


class TestClaudeToolConversion:
    def test_openai_to_anthropic(self):
        from agents.providers.claude_provider import _tools_openai_to_anthropic

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = _tools_openai_to_anthropic(openai_tools)
        assert len(result) == 1
        assert result[0]["name"] == "get_weather"
        assert result[0]["description"] == "Get weather"
        assert "input_schema" in result[0]

    def test_anthropic_to_openai(self):
        from agents.providers.claude_provider import _tool_calls_anthropic_to_openai

        class MockBlock:
            type = "tool_use"
            id = "toolu_001"
            name = "search"
            input = {"query": "test"}

        result = _tool_calls_anthropic_to_openai([MockBlock()])
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search"
        assert "query" in result[0]["function"]["arguments"]


class TestTokenCounting:
    def test_chinese_text(self):
        from agents.providers.zhipu_provider import ZhipuProvider

        p = ZhipuProvider({"api_key": "test", "model": "glm-4-flash"})
        tokens = p.count_tokens("今天天气很好")
        assert tokens > 0

    def test_english_text(self):
        from agents.providers.zhipu_provider import ZhipuProvider

        p = ZhipuProvider({"api_key": "test", "model": "glm-4-flash"})
        tokens = p.count_tokens("Hello world")
        assert tokens > 0

    def test_empty_string(self):
        from agents.providers.zhipu_provider import ZhipuProvider

        p = ZhipuProvider({"api_key": "test", "model": "glm-4-flash"})
        assert p.count_tokens("") == 0
