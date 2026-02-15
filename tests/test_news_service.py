from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.news_service import NewsService


@pytest.fixture
def mock_openai_client():
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = (
        "1. Bitcoin surges past $100k on ETF inflows\n"
        "2. Fed signals rate pause, crypto markets rally\n"
        "3. Whale accumulation hits 6-month high"
    )
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


async def test_fetch_headlines(mock_openai_client):
    service = NewsService(api_key="test-key")
    service._client = mock_openai_client

    headlines = await service.fetch_headlines("BTC-USD")

    assert isinstance(headlines, list)
    assert len(headlines) > 0
    assert any("Bitcoin" in h for h in headlines)

    # Verify the API was called
    mock_openai_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_openai_client.chat.completions.create.call_args
    assert "BTC-USD" in str(call_kwargs)


async def test_fetch_headlines_api_error(mock_openai_client):
    mock_openai_client.chat.completions.create = AsyncMock(
        side_effect=Exception("API error")
    )
    service = NewsService(api_key="test-key")
    service._client = mock_openai_client

    headlines = await service.fetch_headlines("BTC-USD")
    assert headlines == []
