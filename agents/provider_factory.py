"""Provider factory — creates LangChain BaseChatModel from config."""

import logging
import os

logger = logging.getLogger(__name__)


def _resolve_key(value: str) -> str:
    """Resolve ${ENV_VAR} placeholders in config values."""
    if not value:
        return ""
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def create_provider(config: dict):
    """Create a LangChain BaseChatModel from the global config dict.

    Config structure:
        llm:
          provider: "zhipu" | "openai" | "claude" | "local"
          model: "deepseek-chat"
          temperature: 0.1
          max_tokens: 4096
          max_retries: 3
          providers:
            zhipu: {api_key, base_url, model}
            openai: {api_key, base_url, model}
            claude: {api_key, model}
            local: {base_url, api_key, model}
    """
    llm_cfg = config.get("llm", {}) or {}
    provider_name = llm_cfg.get("provider", "openai").lower()

    provider_cfgs = llm_cfg.get("providers", {}) or {}
    specific = provider_cfgs.get(provider_name, {})

    # Resolve model (provider-specific overrides top-level)
    model = specific.get("model") or llm_cfg.get("model", "deepseek-chat")
    temperature = llm_cfg.get("temperature", 0.1)
    max_tokens = llm_cfg.get("max_tokens", 4096)
    max_retries = llm_cfg.get("max_retries", 3)

    # Resolve api_key and base_url
    api_key = _resolve_key(specific.get("api_key") or llm_cfg.get("api_key") or "")
    if not api_key:
        api_key = os.environ.get("ZHIPU_API_KEY", "")
    base_url = specific.get("base_url") or llm_cfg.get("base_url") or None

    logger.info("Creating LangChain provider: %s (model=%s)", provider_name, model)

    if provider_name == "claude":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )

    else:
        from langchain_openai import ChatOpenAI

        kwargs = dict(
            model=model,
            api_key=api_key or "not-needed",  # ChatOpenAI requires non-empty api_key
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        if base_url:
            kwargs["base_url"] = base_url

        return ChatOpenAI(**kwargs)
