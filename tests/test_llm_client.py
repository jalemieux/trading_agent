from unittest.mock import AsyncMock, MagicMock

import pytest

from src.llm_client import AnthropicLLMClient, LLMClient, OpenAICompatibleLLMClient


def test_anthropic_client_satisfies_protocol():
    client = AnthropicLLMClient.__new__(AnthropicLLMClient)
    assert isinstance(client, LLMClient)


def test_openai_compatible_client_satisfies_protocol():
    client = OpenAICompatibleLLMClient.__new__(OpenAICompatibleLLMClient)
    assert isinstance(client, LLMClient)


async def test_anthropic_client_complete():
    client = AnthropicLLMClient(api_key="test-key", model="claude-opus-4-6")

    response = MagicMock()
    response.content = [MagicMock()]
    response.content[0].text = "Hello from Claude"
    client._client = MagicMock()
    client._client.messages.create = AsyncMock(return_value=response)

    result = await client.complete(system="Be helpful", user="Hi", max_tokens=100)
    assert result == "Hello from Claude"

    call_kwargs = client._client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-opus-4-6"
    assert call_kwargs["system"] == "Be helpful"
    assert call_kwargs["max_tokens"] == 100


async def test_openai_compatible_client_complete():
    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        model="moonshotai/kimi-k2",
        base_url="https://openrouter.ai/api/v1",
    )

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "Hello from Kimi"
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(return_value=response)

    result = await client.complete(system="Be helpful", user="Hi", max_tokens=100)
    assert result == "Hello from Kimi"

    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "moonshotai/kimi-k2"
    assert call_kwargs["max_tokens"] == 100
    messages = call_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "Be helpful"}
    assert messages[1] == {"role": "user", "content": "Hi"}


async def test_openai_compatible_client_handles_none_content():
    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        model="moonshotai/kimi-k2",
        base_url="https://openrouter.ai/api/v1",
    )

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = None
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(return_value=response)

    result = await client.complete(system="Be helpful", user="Hi")
    assert result == ""
