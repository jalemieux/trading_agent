from unittest.mock import AsyncMock, MagicMock

import pytest

from src.claude_predictor import Prediction
from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.price_buffer import PriceBuffer
from src.strategy_price_only import PriceOnlyStrategy


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
def predictor():
    return MagicMock()


@pytest.fixture
def settings():
    s = MagicMock()
    s.trade_threshold_pct = 1.0
    s.trade_size_usd = 50.0
    s.prediction_interval_minutes = 5
    return s


@pytest.fixture
def strategy(bus, price_buffer, predictor, settings):
    return PriceOnlyStrategy(
        bus=bus,
        price_buffer=price_buffer,
        predictor=predictor,
        settings=settings,
        product_id="BTC-USD",
    )


async def test_on_price_feeds_buffer(bus, predictor, settings):
    buf = PriceBuffer()
    strat = PriceOnlyStrategy(
        bus=bus, price_buffer=buf, predictor=predictor,
        settings=settings, product_id="BTC-USD",
    )
    strat.register(bus)

    await bus.publish(PriceUpdate(product_id="BTC-USD", price=99000.0, timestamp="t1"))

    assert len(buf.snapshot("BTC-USD")) == 1


async def test_bullish_prediction_emits_buy(strategy, bus, predictor):
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=105420.0, timeframe_minutes=60,
        reasoning="Bullish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    ))

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 1
    assert orders[0].side == "BUY"
    assert orders[0].quote_size == 50.0
    assert orders[0].product_id == "BTC-USD"


async def test_bearish_prediction_emits_sell(strategy, bus, predictor):
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=95380.0, timeframe_minutes=60,
        reasoning="Bearish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    ))
    strategy._has_open_position = AsyncMock(return_value=True)
    strategy._get_position_quantity = AsyncMock(return_value=0.001)

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 1
    assert orders[0].side == "SELL"
    assert orders[0].base_size == 0.001


async def test_neutral_prediction_no_order(strategy, bus, predictor):
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=100902.0, timeframe_minutes=60,
        reasoning="Sideways", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    ))

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 0


async def test_no_prices_skips_prediction(bus, predictor, settings):
    empty_buf = PriceBuffer()
    strat = PriceOnlyStrategy(
        bus=bus, price_buffer=empty_buf, predictor=predictor,
        settings=settings, product_id="BTC-USD",
    )

    predictor.predict = AsyncMock()

    await strat._run_prediction_cycle()

    predictor.predict.assert_not_called()


async def test_prediction_failure_no_order(strategy, bus, predictor):
    predictor.predict = AsyncMock(return_value=None)

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 0


async def test_no_news_service_dependency(strategy):
    """PriceOnlyStrategy should have no news_service attribute."""
    assert not hasattr(strategy, "_news_service")
