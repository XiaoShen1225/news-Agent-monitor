"""Base agent with pluggable LLM provider — sync + async."""

import asyncio
import json
import logging
import re

from .provider_factory import create_provider
from .llm_provider import LLMProvider

logger = logging.getLogger(__name__)


class BaseAgent:
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.llm_config = config.get("llm", {})
        self.max_retries = self.llm_config.get("max_retries", 3)
        self._last_tokens = 0
        self._provider: LLMProvider | None = None

    # ── provider (lazy init) ────────────────────────────────────────────

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = create_provider(self.config)
        return self._provider

    def get_last_tokens(self) -> int:
        return self._last_tokens

    async def aclose(self):
        if self._provider is not None:
            await self._provider.close()
            self._provider = None

    # ── sync LLM (wraps async) ──────────────────────────────────────────

    def call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        max_tokens: int = None,
        fallback: str = ...,
    ) -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.call_llm_async(
                    system_prompt, user_prompt, temperature, max_tokens, fallback
                )
            )
        raise RuntimeError(
            "call_llm (sync) called from async context — use call_llm_async instead"
        )

    # ── async LLM ───────────────────────────────────────────────────────

    async def call_llm_async(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        max_tokens: int = None,
        fallback: str = ...,
    ) -> str:
        """Generic async LLM call. Retries handled by provider."""
        if temperature is None:
            temperature = self.llm_config.get("temperature", 0.1)
        if max_tokens is None:
            max_tokens = self.llm_config.get("max_tokens", 2048)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await self.provider.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=30.0,
            )
            self._last_tokens = result.total_tokens
            logger.info(
                "[%s] LLM call successful, tokens: %d", self.name, result.total_tokens
            )
            return result.content

        except Exception as e:
            if fallback is not ...:
                logger.warning(
                    "[%s] LLM call failed, returning fallback: %s", self.name, e
                )
                return fallback
            raise RuntimeError(
                f"[{self.name}] LLM call failed: {type(e).__name__}: {e}"
            )

    # ── async streaming LLM ─────────────────────────────────────────────

    async def call_llm_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        max_tokens: int = None,
    ):
        """Stream LLM response tokens via async generator (no retries)."""
        if temperature is None:
            temperature = self.llm_config.get("temperature", 0.3)
        if max_tokens is None:
            max_tokens = self.llm_config.get("max_tokens", 1024)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        async for event in self.provider.chat_stream(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=60.0,
        ):
            if event.type == "content":
                yield event.content
            elif event.type == "done":
                self._last_tokens = event.total_tokens

    # ── JSON parsing ────────────────────────────────────────────────────

    def parse_json_response(self, response: str) -> list:
        """Extract JSON array from LLM response, with robust error recovery."""
        text = response.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
            text = text.strip()

        # Attempt 1: strict parse
        try:
            result = json.loads(text)
            return result if isinstance(result, list) else [result]
        except json.JSONDecodeError:
            pass

        # Attempt 2: fix trailing commas before ] or }
        fixed = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            result = json.loads(fixed)
            return result if isinstance(result, list) else [result]
        except json.JSONDecodeError:
            pass

        # Attempt 3: find the outermost [...] and try to parse it
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            segment = text[start : end + 1]
            segment = re.sub(r",\s*([}\]])", r"\1", segment)
            try:
                result = json.loads(segment)
                return result if isinstance(result, list) else [result]
            except json.JSONDecodeError:
                pass

        # Attempt 3b: truncated array — close at last complete }
        if start != -1 and end == -1:
            logger.warning(
                "[BaseAgent] JSON array appears truncated. Attempting recovery."
            )
            depth = 0
            last_complete = -1
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        last_complete = i
            if last_complete > start:
                segment = text[start : last_complete + 1] + "]"
                segment = re.sub(r",\s*([}\]])", r"\1", segment)
                try:
                    result = json.loads(segment)
                    return result if isinstance(result, list) else [result]
                except json.JSONDecodeError:
                    pass

        # Attempt 4: single JSON object → wrap in array
        start_obj = text.find("{")
        if start_obj != -1:
            depth = 0
            for i in range(start_obj, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end_obj = i
                        break
            else:
                end_obj = len(text) - 1
            try:
                obj = json.loads(text[start_obj : end_obj + 1])
                return (
                    [obj]
                    if isinstance(obj, dict)
                    else (obj if isinstance(obj, list) else [obj])
                )
            except json.JSONDecodeError:
                pass

        # Attempt 5: regex-extract flat objects
        obj_pattern = re.compile(r"\{[^{}]*\}", re.DOTALL)
        objects = []
        for match in obj_pattern.finditer(text):
            try:
                obj = json.loads(match.group())
                objects.append(obj)
            except json.JSONDecodeError:
                continue
        if objects:
            return objects

        raise ValueError(f"Failed to parse JSON from LLM response: {text[:300]}...")

    def run(self, *args, **kwargs):
        """Override in subclasses."""
        raise NotImplementedError
