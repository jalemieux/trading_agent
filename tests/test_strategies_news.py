from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db import Database
from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.prediction import Prediction
from src.price_buffer import PriceBuffer
from src.strategies.news import NewsPredictionStrategy


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def price_buffer():
    buf = PriceBuffer(max_size=50)
    buf.add(PriceUpdate(product_id="BTC-USD", price=50000.0, timestamp="2026-01-01T00:00:00Z"))
    return buf


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.complete = AsyncMock(
        return_value=(
            '{"target_price": 55000.0, "timeframe_minutes": 60, '
            '"reasoning": "Bullish momentum with strong ETF inflows"}'
        )
    )
    return client


@pytest.fixture
def news_service():
    service = MagicMock()
    service.fetch_headlines = AsyncMock(return_value=["Bitcoin surges on ETF inflows"])
    return service


@pytest.fixture
def settings():
    s = MagicMock()
    s.trade_threshold_pct = 1.0
    s.trade_size_usd = 50.0
    s.prediction_interval_minutes = 5
    return s


@pytest.fixture
def strategy(bus, price_buffer, mock_llm_client, news_service, settings):
    return NewsPredictionStrategy(
        bus=bus,
        price_buffer=price_buffer,
        llm_client=mock_llm_client,
        news_service=news_service,
        settings=settings,
        product_id="BTC-USD",
    )


async def test_gather_and_predict_calls_llm_with_news(strategy, mock_llm_client, news_service):
    result = await strategy._gather_and_predict()

    assert isinstance(result, Prediction)
    assert result.target_price == 55000.0
    mock_llm_client.complete.assert_called_once()
    news_service.fetch_headlines.assert_called_once()

    # Prompt should include news headlines
    call_kwargs = mock_llm_client.complete.call_args.kwargs
    assert "ETF inflows" in call_kwargs["user"]


async def test_gather_and_predict_api_error(strategy, mock_llm_client):
    mock_llm_client.complete = AsyncMock(side_effect=Exception("API error"))

    result = await strategy._gather_and_predict()
    assert result is None


async def test_gather_and_predict_no_prices(bus, mock_llm_client, news_service, settings):
    empty_buf = PriceBuffer()
    strat = NewsPredictionStrategy(
        bus=bus, price_buffer=empty_buf, llm_client=mock_llm_client,
        news_service=news_service, settings=settings, product_id="BTC-USD",
    )

    result = await strat._gather_and_predict()
    assert result is None
    mock_llm_client.complete.assert_not_called()


async def test_prediction_logging():
    """Predictions and news headlines are logged to the database."""
    db = Database(":memory:")
    await db.initialize()
    bus = EventBus()
    price_buffer = PriceBuffer()
    price_buffer.add(PriceUpdate(product_id="BTC-USD", price=50000.0, timestamp="2026-01-01T00:00:00Z"))

    mock_llm = MagicMock()
    mock_llm.complete = AsyncMock(
        return_value='{"target_price": 50100.0, "timeframe_minutes": 5, "reasoning": "bullish momentum"}'
    )

    mock_news = MagicMock()
    mock_news.fetch_headlines = AsyncMock(return_value=["BTC surges - bullish", "Fed holds rates - neutral"])

    settings = MagicMock()
    settings.trade_threshold_pct = 0.1
    settings.trade_size_usd = 50.0
    settings.prediction_interval_minutes = 5

    strategy = NewsPredictionStrategy(
        bus=bus, price_buffer=price_buffer, llm_client=mock_llm,
        news_service=mock_news, settings=settings, product_id="BTC-USD", db=db,
    )

    await strategy._run_prediction_cycle()

    # Check prediction was logged
    rows = await db.execute_fetchall(
        "SELECT product_id, action, predicted_price, current_price, reasoning FROM predictions"
    )
    assert len(rows) == 1
    assert rows[0][0] == "BTC-USD"
    assert rows[0][2] == 50100.0

    # Check news was logged
    news_rows = await db.execute_fetchall("SELECT headline FROM news_history")
    assert len(news_rows) == 2

    await db.close()
