"""Claude provider — Anthropic SDK with OpenAI↔Anthropic tool format conversion."""

import asyncio
import json
import logging

from ..llm_provider import ChatResult, LLMProvider, StreamEvent

logger = logging.getLogger(__name__)

try:
    from anthropic import AsyncAnthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    AsyncAnthropic = None
    _ANTHROPIC_AVAILABLE = False


def _tools_openai_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI tool format to Anthropic format."""
    result = []
    for t in tools:
        func = t.get("function", {})
        result.append(
            {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            }
        )
    return result


def _tool_calls_anthropic_to_openai(tool_use_blocks: list) -> list[dict]:
    """Convert Anthropic tool_use blocks back to OpenAI tool_calls format."""
    result = []
    for block in tool_use_blocks:
        if block.type == "tool_use":
            result.append(
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input, ensure_ascii=False),
                    },
                }
            )
    return result


class ClaudeProvider(LLMProvider):
    """LLM provider for Anthropic Claude via Anthropic SDK."""

    def __init__(self, config: dict):
        if not _ANTHROPIC_AVAILABLE:
            raise ImportError("Anthropic SDK not installed. Run: pip install anthropic")
        self._cfg = config
        self.model = config.get("model", "claude-sonnet-4-6")
        self.max_retries = config.get("max_retries", 3)
        self._client = AsyncAnthropic(
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url", None),
        )

    async def close(self):
        await self._client.close()

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
        # Anthropic requires system message to be separate, not in messages array
        system_prompt = ""
        converted = []
        for m in messages:
            if m["role"] == "system":
                system_prompt += m.get("content", "") + "\n"
            else:
                converted.append({"role": m["role"], "content": m.get("content", "")})

        kwargs = dict(
            model=self.model,
            messages=converted,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        if system_prompt.strip():
            kwargs["system"] = system_prompt.strip()
        if tools:
            kwargs["tools"] = _tools_openai_to_anthropic(tools)

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await self._client.messages.create(**kwargs)
                content = ""
                tool_calls = []
                total_tokens = (
                    response.usage.input_tokens + response.usage.output_tokens
                    if response.usage
                    else 0
                )

                for block in response.content:
                    if block.type == "text":
                        content += block.text
                    elif block.type == "tool_use":
                        pass  # collected below

                # Collect tool_use blocks
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                if tool_use_blocks:
                    tool_calls = _tool_calls_anthropic_to_openai(tool_use_blocks)

                return ChatResult(
                    content=content if not tool_calls else None,
                    tool_calls=tool_calls,
                    total_tokens=total_tokens,
                    finish_reason=response.stop_reason,
                )

            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2**attempt)
        raise RuntimeError(
            f"ClaudeProvider failed: {type(last_error).__name__}: {last_error}"
        )

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
        timeout: float = 60.0,
    ):
        system_prompt = ""
        converted = []
        for m in messages:
            if m["role"] == "system":
                system_prompt += m.get("content", "") + "\n"
            else:
                converted.append({"role": m["role"], "content": m.get("content", "")})

        kwargs = dict(
            model=self.model,
            messages=converted,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        if system_prompt.strip():
            kwargs["system"] = system_prompt.strip()

        total_tokens = 0
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield StreamEvent(type="content", content=text)
        if hasattr(stream, "final_message") and stream.final_message:
            usage = getattr(stream.final_message, "usage", None)
            if usage:
                total_tokens = usage.input_tokens + usage.output_tokens
        yield StreamEvent(type="done", total_tokens=total_tokens)
