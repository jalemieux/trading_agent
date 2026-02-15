from unittest.mock import AsyncMock, MagicMock

import pytest

from src.claude_price_only_predictor import ClaudePriceOnlyPredictor
from src.events import PriceUpdate
from src.prediction import Prediction


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.complete = AsyncMock(
        return_value=(
            '{"target_price": 105000.0, "timeframe_minutes": 60, '
            '"reasoning": "Strong upward momentum in price action"}'
        )
    )
    return client


@pytest.fixture
def prices():
    return [
        PriceUpdate(product_id="BTC-USD", price=100000.0, timestamp="2026-02-15T10:00:00Z"),
        PriceUpdate(product_id="BTC-USD", price=100500.0, timestamp="2026-02-15T10:01:00Z"),
        PriceUpdate(product_id="BTC-USD", price=101000.0, timestamp="2026-02-15T10:02:00Z"),
    ]


async def test_predict_returns_prediction(mock_llm_client, prices):
    predictor = ClaudePriceOnlyPredictor(client=mock_llm_client)

    result = await predictor.predict(prices)

    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    assert result.timeframe_minutes == 60
    assert result.reasoning == "Strong upward momentum in price action"
    assert result.current_price == 101000.0


async def test_predict_calls_client_complete(mock_llm_client, prices):
    predictor = ClaudePriceOnlyPredictor(client=mock_llm_client)

    await predictor.predict(prices)

    mock_llm_client.complete.assert_called_once()
    call_kwargs = mock_llm_client.complete.call_args.kwargs
    assert "100000.0" in call_kwargs["user"]
    assert "101000.0" in call_kwargs["user"]
    assert "news" not in call_kwargs["user"].lower()
    assert "headline" not in call_kwargs["user"].lower()
    assert "news" not in call_kwargs["system"].lower()


async def test_predict_empty_prices(mock_llm_client):
    predictor = ClaudePriceOnlyPredictor(client=mock_llm_client)
    result = await predictor.predict([])
    assert result is None


async def test_predict_api_error(mock_llm_client, prices):
    mock_llm_client.complete = AsyncMock(side_effect=Exception("API error"))
    predictor = ClaudePriceOnlyPredictor(client=mock_llm_client)

    result = await predictor.predict(prices)
    assert result is None


async def test_predict_malformed_json(mock_llm_client, prices):
    mock_llm_client.complete = AsyncMock(return_value="not json")
    predictor = ClaudePriceOnlyPredictor(client=mock_llm_client)

    result = await predictor.predict(prices)
    assert result is None
