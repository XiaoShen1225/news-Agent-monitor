"""Abstract LLM Provider interface and result types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator


@dataclass
class ChatResult:
    """Normalized chat completion result across providers."""

    content: str | None = None
    tool_calls: list = field(
        default_factory=list
    )  # [{"id":..., "function": {"name":..., "arguments":...}}]
    total_tokens: int = 0
    finish_reason: str | None = None


@dataclass
class StreamEvent:
    """Single event yielded by chat_stream()."""

    type: str  # "content" | "done"
    content: str = ""
    total_tokens: int = 0


class LLMProvider(ABC):
    """Abstract LLM provider — all implementations normalize to this interface.

    Internal tool format is OpenAI-compatible:
        {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}

    Providers that use a different native format (e.g. Anthropic) must convert
    internally so callers can always pass/expect OpenAI-format tools.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
        tools: list[dict] | None = None,
        timeout: float = 30.0,
    ) -> ChatResult:
        """Send a chat completion request. Returns normalized ChatResult."""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
        timeout: float = 60.0,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream chat completion tokens. Yields StreamEvent objects."""
        ...

    @abstractmethod
    def supports_tools(self) -> bool:
        """Whether this provider supports function/tool calling."""
        ...

    def count_tokens(self, text: str) -> int:
        """Estimate token count for a string. Override for accurate counting."""
        import re

        chinese = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", text))
        english = len(re.findall(r"[a-zA-Z]+", text))
        other = len(text) - chinese - english
        return int(chinese * 1.2 + english * 1.3 + other * 0.3)
