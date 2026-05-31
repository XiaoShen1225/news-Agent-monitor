"""Provider factory — creates LLMProvider from config."""

import logging
import os

from .llm_provider import LLMProvider

logger = logging.getLogger(__name__)


def create_provider(config: dict) -> LLMProvider:
    """Create an LLMProvider instance from the global config dict.

    Config structure:
        llm:
          provider: "zhipu" | "openai" | "claude" | "local"
          model: "glm-4-flash"
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
    provider_name = llm_cfg.get("provider", "zhipu").lower()

    # Merge provider-specific config with top-level defaults
    provider_cfgs = llm_cfg.get("providers", {}) or {}
    specific = provider_cfgs.get(provider_name, {})

    effective = {}
    # Top-level overrides (model, temperature, max_tokens, max_retries)
    for k in ("model", "temperature", "max_tokens", "max_retries"):
        effective[k] = llm_cfg.get(k)

    # Provider-specific settings (api_key, base_url)
    for k in ("api_key", "base_url"):
        val = specific.get(k) or llm_cfg.get(k) or ""
        if val.startswith("${") and val.endswith("}"):
            env_var = val[2:-1]
            val = os.environ.get(env_var, "")
        effective[k] = val

    # Provider-specific model override
    if specific.get("model"):
        effective["model"] = specific["model"]

    # Resolve api_key from env if not set
    if not effective.get("api_key"):
        effective["api_key"] = os.environ.get("ZHIPU_API_KEY", "")

    logger.info(
        "Creating LLM provider: %s (model=%s)", provider_name, effective.get("model")
    )

    if provider_name == "zhipu":
        from .providers.zhipu_provider import ZhipuProvider

        return ZhipuProvider(effective)

    elif provider_name == "openai":
        from .providers.openai_provider import OpenAIProvider

        return OpenAIProvider(effective)

    elif provider_name == "claude":
        from .providers.claude_provider import ClaudeProvider

        return ClaudeProvider(effective)

    elif provider_name == "local":
        from .providers.local_provider import LocalProvider

        return LocalProvider(effective)

    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider_name}'. "
            f"Supported: zhipu, openai, claude, local"
        )
