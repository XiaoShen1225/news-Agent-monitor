"""Tests for provider factory — creates LangChain ChatOpenAI/ChatAnthropic."""

from agents.provider_factory import create_provider, _resolve_key


class TestResolveKey:
    def test_plain_value(self):
        assert _resolve_key("my-api-key") == "my-api-key"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "from-env")
        assert _resolve_key("${TEST_API_KEY}") == "from-env"

    def test_missing_env_var(self):
        assert _resolve_key("${MISSING_KEY}") == ""

    def test_empty_value(self):
        assert _resolve_key("") == ""


class TestProviderFactory:
    def test_creates_chat_openai_for_openai(self):
        from langchain_openai import ChatOpenAI

        config = {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "providers": {
                    "openai": {"api_key": "sk-test"},
                },
            }
        }
        provider = create_provider(config)
        assert isinstance(provider, ChatOpenAI)
        assert provider.model_name == "gpt-4o"

    def test_creates_chat_openai_for_zhipu(self):
        from langchain_openai import ChatOpenAI

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
        assert isinstance(provider, ChatOpenAI)
        assert provider.model_name == "glm-4-flash"

    def test_creates_chat_openai_for_local(self):
        from langchain_openai import ChatOpenAI

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
        assert isinstance(provider, ChatOpenAI)
        assert provider.model_name == "llama3"

    def test_default_provider_is_openai(self):
        from langchain_openai import ChatOpenAI

        config = {"llm": {"api_key": "test-key"}}
        provider = create_provider(config)
        assert isinstance(provider, ChatOpenAI)

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
        assert provider.model_name == "gpt-4o-mini"

    def test_base_url_set(self):
        config = {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "providers": {
                    "openai": {
                        "api_key": "sk-test",
                        "base_url": "https://custom.api.com/v1",
                    }
                },
            }
        }
        provider = create_provider(config)
        assert "https://custom.api.com/v1" in str(provider.openai_api_base)

    def test_creates_chat_anthropic_for_claude(self):
        from langchain_anthropic import ChatAnthropic

        config = {
            "llm": {
                "provider": "claude",
                "providers": {
                    "claude": {
                        "api_key": "sk-ant-test",
                        "model": "claude-sonnet-4-6",
                    }
                },
            }
        }
        provider = create_provider(config)
        assert isinstance(provider, ChatAnthropic)
