"""Base agent with Zhipu AI (glm-4-flash) LLM integration — sync + async."""

import asyncio
import json
import logging
import re
from typing import Optional

import httpx
from openai import AsyncOpenAI, OpenAI

logger = logging.getLogger(__name__)


def _make_http_client() -> httpx.AsyncClient:
    """Create an httpx client with safe defaults for LLM API calls."""
    return httpx.AsyncClient(
        timeout=30.0,
        trust_env=False,
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )


class BaseAgent:
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.llm_config = config.get("llm", {})
        self.max_retries = self.llm_config.get("max_retries", 3)
        self._client: Optional[OpenAI] = None
        self._async_client: Optional[AsyncOpenAI] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._last_tokens = 0

    def get_last_tokens(self) -> int:
        """Return total_tokens from the most recent LLM call, or 0 if none."""
        return self._last_tokens

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.llm_config.get("api_key", ""),
                base_url=self.llm_config.get(
                    "base_url", "https://open.bigmodel.cn/api/paas/v4/"
                ),
            )
        return self._client

    @property
    def async_client(self) -> AsyncOpenAI:
        if self._async_client is None:
            self._http_client = _make_http_client()
            self._async_client = AsyncOpenAI(
                api_key=self.llm_config.get("api_key", ""),
                base_url=self.llm_config.get(
                    "base_url", "https://open.bigmodel.cn/api/paas/v4/"
                ),
                http_client=self._http_client,
            )
        return self._async_client

    async def aclose(self):
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
            self._async_client = None

    # ── sync LLM (wraps async) ──────────────────────────────────────

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

    # ── async LLM ───────────────────────────────────────────────────

    async def call_llm_async(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        max_tokens: int = None,
        fallback: str = ...,
    ) -> str:
        if temperature is None:
            temperature = self.llm_config.get("temperature", 0.1)
        if max_tokens is None:
            max_tokens = self.llm_config.get("max_tokens", 2048)
        model = self.llm_config.get("model", "glm-4-flash")

        for attempt in range(self.max_retries):
            try:
                logger.info(
                    "[%s] LLM call attempt %d/%d",
                    self.name,
                    attempt + 1,
                    self.max_retries,
                )
                response = await self.async_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=30.0,
                )
                content = response.choices[0].message.content
                total_tokens = response.usage.total_tokens if response.usage else 0
                self._last_tokens = total_tokens
                logger.info(
                    "[%s] LLM call successful, tokens: %d",
                    self.name,
                    total_tokens,
                )
                return content

            except Exception as e:
                logger.warning(
                    "[%s] LLM call failed (attempt %d): %s", self.name, attempt + 1, e
                )
                if attempt < self.max_retries - 1:
                    wait = 2**attempt
                    logger.info("[%s] Retrying in %ds...", self.name, wait)
                    await asyncio.sleep(wait)
                    # Reset http client on connection errors to force fresh connections
                    if "onnection" in type(e).__name__ or "onnection" in str(e):
                        await self.aclose()

        if fallback is not ...:
            logger.warning(
                "[%s] LLM call failed after %d attempts, returning fallback.",
                self.name,
                self.max_retries,
            )
            return fallback
        raise RuntimeError(
            f"[{self.name}] LLM call failed after {self.max_retries} attempts"
        )

    # ── JSON parsing ────────────────────────────────────────────────

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
