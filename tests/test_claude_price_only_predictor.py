from unittest.mock import AsyncMock, MagicMock

import pytest

from src.claude_predictor import Prediction
from src.events import PriceUpdate


@pytest.fixture
def mock_anthropic_client():
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock()]
    response.content[0].text = (
        '{"target_price": 105000.0, "timeframe_minutes": 60, '
        '"reasoning": "Strong upward momentum in price action"}'
    )
    client.messages.create = AsyncMock(return_value=response)
    return client


@pytest.fixture
def prices():
    return [
        PriceUpdate(product_id="BTC-USD", price=100000.0, timestamp="2026-02-15T10:00:00Z"),
        PriceUpdate(product_id="BTC-USD", price=100500.0, timestamp="2026-02-15T10:01:00Z"),
        PriceUpdate(product_id="BTC-USD", price=101000.0, timestamp="2026-02-15T10:02:00Z"),
    ]


async def test_predict_returns_prediction(mock_anthropic_client, prices):
    from src.claude_price_only_predictor import ClaudePriceOnlyPredictor

    predictor = ClaudePriceOnlyPredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices)

    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    assert result.timeframe_minutes == 60
    assert result.reasoning == "Strong upward momentum in price action"
    assert result.current_price == 101000.0


async def test_predict_prompt_contains_prices_no_news(mock_anthropic_client, prices):
    from src.claude_price_only_predictor import ClaudePriceOnlyPredictor

    predictor = ClaudePriceOnlyPredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    await predictor.predict(prices)

    call_kwargs = mock_anthropic_client.messages.create.call_args
    user_msg = call_kwargs.kwargs["messages"][-1]["content"]
    system_msg = call_kwargs.kwargs["system"]
    assert "100000.0" in user_msg
    assert "101000.0" in user_msg
    assert "news" not in user_msg.lower()
    assert "headline" not in user_msg.lower()
    assert "news" not in system_msg.lower()


async def test_predict_empty_prices():
    from src.claude_price_only_predictor import ClaudePriceOnlyPredictor

    predictor = ClaudePriceOnlyPredictor(api_key="test-key")
    result = await predictor.predict([])
    assert result is None


async def test_predict_api_error(mock_anthropic_client, prices):
    from src.claude_price_only_predictor import ClaudePriceOnlyPredictor

    mock_anthropic_client.messages.create = AsyncMock(side_effect=Exception("API error"))
    predictor = ClaudePriceOnlyPredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices)
    assert result is None


async def test_predict_malformed_json(mock_anthropic_client, prices):
    from src.claude_price_only_predictor import ClaudePriceOnlyPredictor

    mock_anthropic_client.messages.create.return_value.content[0].text = "not json"
    predictor = ClaudePriceOnlyPredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices)
    assert result is None
