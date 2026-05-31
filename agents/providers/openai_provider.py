"""OpenAI provider — native OpenAI SDK, no conversion needed."""

import asyncio
import logging

import httpx
from openai import AsyncOpenAI

from ..llm_provider import ChatResult, LLMProvider, StreamEvent

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """LLM provider for OpenAI (GPT-4o, etc.) via native OpenAI SDK."""

    def __init__(self, config: dict):
        self._cfg = config
        self.model = config.get("model", "gpt-4o")
        self.max_retries = config.get("max_retries", 3)
        self._http_client = httpx.AsyncClient(
            timeout=60.0,
            trust_env=False,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        self._client = AsyncOpenAI(
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url", "https://api.openai.com/v1"),
            http_client=self._http_client,
        )

    async def close(self):
        await self._http_client.aclose()

    def supports_tools(self) -> bool:
        return True

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
        tools: list[dict] | None = None,
        timeout: float = 30.0,
    ) -> ChatResult:
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        if tools:
            kwargs["tools"] = tools

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                msg = choice.message
                result = ChatResult(
                    content=msg.content,
                    total_tokens=response.usage.total_tokens if response.usage else 0,
                    finish_reason=choice.finish_reason,
                )
                if msg.tool_calls:
                    result.tool_calls = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2**attempt)
        raise RuntimeError(
            f"OpenAIProvider failed: {type(last_error).__name__}: {last_error}"
        )

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
        timeout: float = 60.0,
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
