from unittest.mock import MagicMock, AsyncMock

import pytest

from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFailed, OrderFilled, OrderRequest
from src.kill_switch import KillSwitch
from src.order_manager import OrderManager
from src.risk_manager import RiskManager


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
async def kill_switch(db, bus):
    ks = KillSwitch(db=db, bus=bus)
    await ks.initialize()
    return ks


@pytest.fixture
def settings():
    return Settings(max_order_size_usd=1000.0, max_daily_loss_usd=5000.0)


@pytest.fixture
def risk_manager(db, bus, kill_switch, settings):
    return RiskManager(db=db, bus=bus, kill_switch=kill_switch, settings=settings)


@pytest.fixture
def mock_coinbase():
    mock = MagicMock()
    return mock


@pytest.fixture
async def order_manager(db, bus, risk_manager, mock_coinbase):
    om = OrderManager(db=db, bus=bus, risk_manager=risk_manager, coinbase=mock_coinbase)
    om.register(bus)
    return om


async def test_market_buy_success(order_manager, bus, mock_coinbase):
    filled_events = []

    async def handler(event: OrderFilled):
        filled_events.append(event)

    bus.subscribe(OrderFilled, handler)

    mock_coinbase.market_buy.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-123"},
    }
    mock_coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-123",
            "status": "FILLED",
            "filled_size": "0.002",
            "average_filled_price": "50000",
            "total_fees": "0.20",
        }
    }

    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=100.0
    )
    await bus.publish(order)

    assert len(filled_events) == 1
    assert filled_events[0].coinbase_order_id == "cb-123"
    assert filled_events[0].filled_price == 50000.0


async def test_market_sell_success(order_manager, bus, mock_coinbase):
    filled_events = []

    async def handler(event: OrderFilled):
        filled_events.append(event)

    bus.subscribe(OrderFilled, handler)

    mock_coinbase.market_sell.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-456"},
    }
    mock_coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-456",
            "status": "FILLED",
            "filled_size": "1.0",
            "average_filled_price": "3000",
            "total_fees": "0.60",
        }
    }

    order = OrderRequest(
        product_id="ETH-USD", side="SELL", order_type="MARKET", base_size=1.0
    )
    await bus.publish(order)

    assert len(filled_events) == 1
    assert filled_events[0].side == "SELL"


async def test_order_fails_at_coinbase(order_manager, bus, mock_coinbase):
    failed_events = []

    async def handler(event: OrderFailed):
        failed_events.append(event)

    bus.subscribe(OrderFailed, handler)

    mock_coinbase.market_buy.return_value = {
        "success": False,
        "error_response": {"error": "INSUFFICIENT_FUND"},
    }

    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=50.0
    )
    await bus.publish(order)

    assert len(failed_events) == 1
    assert "INSUFFICIENT_FUND" in failed_events[0].reason


async def test_order_persisted_to_db(order_manager, bus, mock_coinbase, db):
    mock_coinbase.market_buy.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-789"},
    }
    mock_coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-789",
            "status": "FILLED",
            "filled_size": "0.001",
            "average_filled_price": "50000",
            "total_fees": "0.10",
        }
    }

    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=50.0
    )
    await bus.publish(order)

    rows = await db.execute_fetchall("SELECT * FROM orders WHERE coinbase_id = ?", ("cb-789",))
    assert len(rows) == 1


async def test_risk_rejected_order_not_placed(order_manager, bus, mock_coinbase, kill_switch):
    await kill_switch.activate("test")

    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=50.0
    )
    await bus.publish(order)

    mock_coinbase.market_buy.assert_not_called()
    mock_coinbase.market_sell.assert_not_called()
