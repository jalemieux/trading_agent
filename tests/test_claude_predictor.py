from unittest.mock import AsyncMock, MagicMock

import pytest

from src.claude_predictor import ClaudePredictor, Prediction
from src.events import PriceUpdate


@pytest.fixture
def mock_anthropic_client():
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock()]
    response.content[0].text = (
        '{"target_price": 105000.0, "timeframe_minutes": 60, '
        '"reasoning": "Bullish momentum with strong ETF inflows"}'
    )
    client.messages.create = AsyncMock(return_value=response)
    return client


@pytest.fixture
def prices():
    return [
        PriceUpdate(product_id="BTC-USD", price=100000.0, timestamp="2026-02-14T10:00:00Z"),
        PriceUpdate(product_id="BTC-USD", price=100500.0, timestamp="2026-02-14T10:01:00Z"),
        PriceUpdate(product_id="BTC-USD", price=101000.0, timestamp="2026-02-14T10:02:00Z"),
    ]


@pytest.fixture
def headlines():
    return [
        "1. Bitcoin surges on ETF inflows",
        "2. Fed signals rate pause",
    ]


async def test_predict_returns_prediction(mock_anthropic_client, prices, headlines):
    predictor = ClaudePredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices, headlines)

    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    assert result.timeframe_minutes == 60
    assert result.reasoning == "Bullish momentum with strong ETF inflows"
    assert result.current_price == 101000.0  # last price in list


async def test_predict_prompt_contains_prices_and_headlines(
    mock_anthropic_client, prices, headlines
):
    predictor = ClaudePredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    await predictor.predict(prices, headlines)

    call_kwargs = mock_anthropic_client.messages.create.call_args
    user_msg = call_kwargs.kwargs["messages"][-1]["content"]
    assert "100000.0" in user_msg
    assert "101000.0" in user_msg
    assert "ETF inflows" in user_msg


async def test_predict_api_error(mock_anthropic_client, prices, headlines):
    mock_anthropic_client.messages.create = AsyncMock(
        side_effect=Exception("API error")
    )
    predictor = ClaudePredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices, headlines)
    assert result is None


async def test_predict_malformed_json(mock_anthropic_client, prices, headlines):
    mock_anthropic_client.messages.create.return_value.content[0].text = "not json"
    predictor = ClaudePredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices, headlines)
    assert result is None
