from unittest.mock import AsyncMock, MagicMock

import pytest

from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.prediction import Prediction
from src.price_buffer import PriceBuffer
from src.strategy import Strategy


class StubStrategy(Strategy):
    """Minimal concrete strategy for testing the base class."""

    def __init__(self, prediction_result, **kwargs):
        super().__init__(**kwargs)
        self._prediction_result = prediction_result

    async def _gather_and_predict(self) -> Prediction | None:
        return self._prediction_result


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
def settings():
    s = MagicMock()
    s.trade_threshold_pct = 1.0
    s.trade_size_usd = 50.0
    s.prediction_interval_minutes = 5
    return s


def _make_strategy(bus, price_buffer, settings, prediction, db=None):
    return StubStrategy(
        prediction_result=prediction,
        bus=bus,
        price_buffer=price_buffer,
        settings=settings,
        product_id="BTC-USD",
        db=db,
    )


async def test_on_price_feeds_buffer(bus, settings):
    buf = PriceBuffer()
    strat = _make_strategy(bus, buf, settings, prediction=None)
    strat.register(bus)

    await bus.publish(PriceUpdate(product_id="BTC-USD", price=99000.0, timestamp="t1"))
    assert len(buf.snapshot("BTC-USD")) == 1


async def test_bullish_emits_buy(bus, price_buffer, settings):
    prediction = Prediction(
        target_price=105420.0, timeframe_minutes=60,
        reasoning="Bullish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    )
    strat = _make_strategy(bus, price_buffer, settings, prediction)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()

    assert len(orders) == 1
    assert orders[0].side == "BUY"
    assert orders[0].quote_size == 50.0


async def test_bearish_emits_sell(bus, price_buffer, settings):
    prediction = Prediction(
        target_price=95380.0, timeframe_minutes=60,
        reasoning="Bearish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    )
    strat = _make_strategy(bus, price_buffer, settings, prediction)
    strat._has_open_position = AsyncMock(return_value=True)
    strat._get_position_quantity = AsyncMock(return_value=0.001)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()

    assert len(orders) == 1
    assert orders[0].side == "SELL"
    assert orders[0].base_size == 0.001


async def test_neutral_no_order(bus, price_buffer, settings):
    prediction = Prediction(
        target_price=100902.0, timeframe_minutes=60,
        reasoning="Sideways", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    )
    strat = _make_strategy(bus, price_buffer, settings, prediction)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()
    assert len(orders) == 0


async def test_buy_blocked_when_position_open(bus, price_buffer, settings):
    prediction = Prediction(
        target_price=105420.0, timeframe_minutes=60,
        reasoning="Bullish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    )
    strat = _make_strategy(bus, price_buffer, settings, prediction)
    strat._has_open_position = AsyncMock(return_value=True)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()
    assert len(orders) == 0


async def test_sell_blocked_when_no_position(bus, price_buffer, settings):
    prediction = Prediction(
        target_price=95380.0, timeframe_minutes=60,
        reasoning="Bearish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    )
    strat = _make_strategy(bus, price_buffer, settings, prediction)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()
    assert len(orders) == 0


async def test_none_prediction_skips(bus, price_buffer, settings):
    strat = _make_strategy(bus, price_buffer, settings, prediction=None)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()
    assert len(orders) == 0


async def test_no_prices_skips(bus, settings):
    empty_buf = PriceBuffer()
    strat = _make_strategy(bus, empty_buf, settings, prediction=Prediction(
        target_price=105420.0, timeframe_minutes=60,
        reasoning="Bullish", current_price=100400.0,
        timestamp="t",
    ))

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()
    assert len(orders) == 0
