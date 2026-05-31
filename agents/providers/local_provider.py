"""Local provider — OpenAI-compatible local models (ollama, vLLM, etc.)."""

import asyncio
import logging

import httpx
from openai import AsyncOpenAI

from ..llm_provider import ChatResult, LLMProvider, StreamEvent

logger = logging.getLogger(__name__)


class LocalProvider(LLMProvider):
    """LLM provider for local OpenAI-compatible endpoints (ollama, vLLM, LocalAI, etc.)."""

    def __init__(self, config: dict):
        self._cfg = config
        self.model = config.get("model", "qwen2.5:14b")
        self.max_retries = config.get("max_retries", 2)
        self._http_client = httpx.AsyncClient(
            timeout=120.0,
            trust_env=False,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        self._client = AsyncOpenAI(
            api_key=config.get("api_key", "ollama"),
            base_url=config.get("base_url", "http://localhost:11434/v1"),
            http_client=self._http_client,
        )

    async def close(self):
        await self._http_client.aclose()

    def supports_tools(self) -> bool:
        return False  # tool support varies widely; default to no

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
        tools: list[dict] | None = None,
        timeout: float = 120.0,
    ) -> ChatResult:
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                result = ChatResult(
                    content=choice.message.content,
                    total_tokens=response.usage.total_tokens if response.usage else 0,
                    finish_reason=choice.finish_reason,
                )
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2**attempt)
        raise RuntimeError(
            f"LocalProvider failed: {type(last_error).__name__}: {last_error}"
        )

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
        timeout: float = 120.0,
    ):
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            stream=True,
        )
        total_tokens = 0
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield StreamEvent(type="content", content=delta.content)
            if chunk.usage and chunk.usage.total_tokens:
                total_tokens = chunk.usage.total_tokens
        yield StreamEvent(type="done", total_tokens=total_tokens)
