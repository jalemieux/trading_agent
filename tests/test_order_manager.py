from unittest.mock import MagicMock, AsyncMock

import pytest

from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFailed, OrderFilled, OrderRequest
from src.kill_switch import KillSwitch
from src.order_manager import OrderManager
from src.portfolio_tracker import PortfolioTracker
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
def mock_portfolio_tracker():
    mock = MagicMock(spec=PortfolioTracker)
    mock.quote_balance = 1000.0  # plenty of balance by default
    return mock


@pytest.fixture
async def order_manager(db, bus, risk_manager, mock_coinbase, mock_portfolio_tracker):
    om = OrderManager(
        db=db, bus=bus, risk_manager=risk_manager,
        coinbase=mock_coinbase, portfolio_tracker=mock_portfolio_tracker,
    )
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


async def test_buy_rejected_when_balance_below_minimum(
    order_manager, bus, mock_coinbase, mock_portfolio_tracker,
):
    """BUY rejected when USDC balance < $1.00 minimum."""
    mock_portfolio_tracker.quote_balance = 0.50

    failed_events = []
    bus.subscribe(OrderFailed, lambda e: failed_events.append(e))

    order = OrderRequest(
        product_id="SOL-USDC", side="BUY", order_type="MARKET", quote_size=50.0,
    )
    await bus.publish(order)

    mock_coinbase.market_buy.assert_not_called()
    assert len(failed_events) == 1
    assert "Insufficient" in failed_events[0].reason


async def test_buy_sized_down_when_balance_below_order_size(
    order_manager, bus, mock_coinbase, mock_portfolio_tracker,
):
    """BUY sized down to available balance when < quote_size."""
    mock_portfolio_tracker.quote_balance = 25.0

    mock_coinbase.market_buy.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-sized"},
    }
    mock_coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-sized",
            "filled_size": "0.3",
            "average_filled_price": "83.0",
            "total_fees": "0.05",
        }
    }

    order = OrderRequest(
        product_id="SOL-USDC", side="BUY", order_type="MARKET", quote_size=50.0,
    )
    await bus.publish(order)

    mock_coinbase.market_buy.assert_called_once()
    call_kwargs = mock_coinbase.market_buy.call_args
    assert call_kwargs.kwargs["quote_size"] == "25.0" or call_kwargs[1]["quote_size"] == "25.0"


async def test_sell_bypasses_balance_check(
    order_manager, bus, mock_coinbase, mock_portfolio_tracker,
):
    """SELL orders skip balance check entirely."""
    mock_portfolio_tracker.quote_balance = 0.0  # zero USDC

    mock_coinbase.market_sell.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-sell"},
    }
    mock_coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-sell",
            "filled_size": "1.0",
            "average_filled_price": "85.0",
            "total_fees": "0.10",
        }
    }

    order = OrderRequest(
        product_id="SOL-USDC", side="SELL", order_type="MARKET", base_size=1.0,
    )
    await bus.publish(order)

    mock_coinbase.market_sell.assert_called_once()
