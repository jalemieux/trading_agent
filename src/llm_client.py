import logging
from typing import Protocol, runtime_checkable

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


@runtime_checkable
class LLMClient(Protocol):
    """Transport-level LLM API client."""

    async def complete(self, system: str, user: str, max_tokens: int = 512) -> str: ...


class AnthropicLLMClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, system: str, user: str, max_tokens: int = 512) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text


class OpenAICompatibleLLMClient:
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def complete(self, system: str, user: str, max_tokens: int = 512) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        if not response.choices:
            logger.warning("OpenAI-compatible API returned no choices: %s", response)
            return ""
        content = response.choices[0].message.content or ""
        if not content:
            logger.warning(
                "OpenAI-compatible API returned empty content (finish_reason=%s, model=%s)",
                response.choices[0].finish_reason, response.model,
            )
        return content
