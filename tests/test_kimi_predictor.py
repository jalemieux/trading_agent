from unittest.mock import AsyncMock, MagicMock

import pytest

from src.events import PriceUpdate
from src.kimi_predictor import KimiPredictor
from src.prediction import Prediction, Predictor


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.complete = AsyncMock(
        return_value=(
            '{"target_price": 105000.0, "timeframe_minutes": 60, '
            '"reasoning": "Strong upward momentum detected"}'
        )
    )
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
    return ["1. Bitcoin bullish on ETF news"]


def test_kimi_predictor_satisfies_protocol():
    client = MagicMock()
    predictor = KimiPredictor(client=client)
    assert isinstance(predictor, Predictor)


async def test_predict_returns_prediction(mock_llm_client, prices, headlines):
    predictor = KimiPredictor(client=mock_llm_client)

    result = await predictor.predict(prices, headlines)

    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    assert result.timeframe_minutes == 60
    assert result.current_price == 101000.0


async def test_predict_calls_client_complete(mock_llm_client, prices, headlines):
    predictor = KimiPredictor(client=mock_llm_client)

    await predictor.predict(prices, headlines)

    mock_llm_client.complete.assert_called_once()
    call_kwargs = mock_llm_client.complete.call_args.kwargs
    assert "user" in call_kwargs
    assert "system" in call_kwargs


async def test_predict_api_error(mock_llm_client, prices, headlines):
    mock_llm_client.complete = AsyncMock(side_effect=Exception("API error"))
    predictor = KimiPredictor(client=mock_llm_client)

    result = await predictor.predict(prices, headlines)
    assert result is None


async def test_predict_malformed_json(mock_llm_client, prices, headlines):
    mock_llm_client.complete = AsyncMock(return_value="not json at all")
    predictor = KimiPredictor(client=mock_llm_client)

    result = await predictor.predict(prices, headlines)
    assert result is None


async def test_predict_empty_prices(mock_llm_client, headlines):
    predictor = KimiPredictor(client=mock_llm_client)
    result = await predictor.predict([], headlines)
    assert result is None
