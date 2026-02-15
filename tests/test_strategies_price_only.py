from unittest.mock import AsyncMock, MagicMock

import pytest

from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.prediction import Prediction
from src.price_buffer import PriceBuffer
from src.strategies.price_only import PriceOnlyStrategy


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def price_buffer():
    buf = PriceBuffer(max_size=50)
    for i in range(5):
        buf.add(PriceUpdate(
            product_id="BTC-USD",
            price=100000.0 + i * 100,
            timestamp=f"2026-02-15T10:0{i}:00Z",
        ))
    return buf


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
def settings():
    s = MagicMock()
    s.trade_threshold_pct = 1.0
    s.trade_size_usd = 50.0
    s.prediction_interval_minutes = 5
    return s


@pytest.fixture
def strategy(bus, price_buffer, mock_llm_client, settings):
    return PriceOnlyStrategy(
        bus=bus,
        price_buffer=price_buffer,
        llm_client=mock_llm_client,
        settings=settings,
        product_id="BTC-USD",
    )


async def test_gather_and_predict_calls_llm(strategy, mock_llm_client):
    result = await strategy._gather_and_predict()

    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    mock_llm_client.complete.assert_called_once()

    # Verify prompt contains price data but no news
    call_kwargs = mock_llm_client.complete.call_args.kwargs
    assert "100000.0" in call_kwargs["user"]
    assert "news" not in call_kwargs["user"].lower()
    assert "headline" not in call_kwargs["user"].lower()


async def test_gather_and_predict_api_error(strategy, mock_llm_client):
    mock_llm_client.complete = AsyncMock(side_effect=Exception("API error"))

    result = await strategy._gather_and_predict()
    assert result is None


async def test_gather_and_predict_malformed_json(strategy, mock_llm_client):
    mock_llm_client.complete = AsyncMock(return_value="not json")

    result = await strategy._gather_and_predict()
    assert result is None


async def test_gather_and_predict_no_prices(bus, mock_llm_client, settings):
    empty_buf = PriceBuffer()
    strat = PriceOnlyStrategy(
        bus=bus, price_buffer=empty_buf, llm_client=mock_llm_client,
        settings=settings, product_id="BTC-USD",
    )

    result = await strat._gather_and_predict()
    assert result is None
    mock_llm_client.complete.assert_not_called()


async def test_full_cycle_bullish_buy(strategy, bus, mock_llm_client):
    """End-to-end: LLM returns bullish → BUY order emitted."""
    mock_llm_client.complete = AsyncMock(
        return_value='{"target_price": 105420.0, "timeframe_minutes": 60, "reasoning": "Bullish"}'
    )

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strategy._run_prediction_cycle()

    assert len(orders) == 1
    assert orders[0].side == "BUY"


async def test_no_news_service_dependency(strategy):
    """PriceOnlyStrategy should have no news_service attribute."""
    assert not hasattr(strategy, "_news_service")
