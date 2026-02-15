from unittest.mock import MagicMock

import pytest

from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFilled, OrderRequest, PositionChanged
from src.kill_switch import KillSwitch
from src.order_manager import OrderManager
from src.position_tracker import PositionTracker
from src.risk_manager import RiskManager


@pytest.fixture
async def system():
    """Wire up the full system with mocked Coinbase."""
    db = Database(":memory:")
    await db.initialize()

    bus = EventBus()
    settings = Settings(max_order_size_usd=1000.0, max_daily_loss_usd=5000.0)

    kill_switch = KillSwitch(db=db, bus=bus)
    await kill_switch.initialize()

    risk_manager = RiskManager(db=db, bus=bus, kill_switch=kill_switch, settings=settings)

    mock_coinbase = MagicMock()
    order_manager = OrderManager(db=db, bus=bus, risk_manager=risk_manager, coinbase=mock_coinbase)
    order_manager.register(bus)

    position_tracker = PositionTracker(db=db, bus=bus)
    position_tracker.register(bus)

    yield {
        "db": db,
        "bus": bus,
        "kill_switch": kill_switch,
        "coinbase": mock_coinbase,
    }

    await db.close()


async def test_full_buy_sell_cycle(system):
    bus = system["bus"]
    coinbase = system["coinbase"]

    position_events = []

    async def on_position(event: PositionChanged):
        position_events.append(event)

    bus.subscribe(PositionChanged, on_position)

    # Buy
    coinbase.market_buy.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-buy-1"},
    }
    coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-buy-1",
            "status": "FILLED",
            "filled_size": "0.002",
            "average_filled_price": "50000",
            "total_fees": "0.20",
        }
    }

    await bus.publish(
        OrderRequest(product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=100.0)
    )

    assert len(position_events) == 1
    assert position_events[0].status == "OPEN"
    assert position_events[0].quantity == 0.002

    # Sell
    coinbase.market_sell.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-sell-1"},
    }
    coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-sell-1",
            "status": "FILLED",
            "filled_size": "0.002",
            "average_filled_price": "51000",
            "total_fees": "0.20",
        }
    }

    await bus.publish(
        OrderRequest(product_id="BTC-USD", side="SELL", order_type="MARKET", base_size=0.002)
    )

    assert len(position_events) == 2
    assert position_events[1].status == "CLOSED"

    # Verify DB state
    db = system["db"]
    positions = await db.execute_fetchall("SELECT * FROM positions WHERE status = 'CLOSED'")
    assert len(positions) == 1

    orders = await db.execute_fetchall("SELECT * FROM orders")
    assert len(orders) == 2

    today = __import__("datetime").date.today().isoformat()
    summary = await db.execute_fetchone("SELECT total_pnl, num_trades FROM daily_summary WHERE date = ?", (today,))
    assert summary is not None
    assert summary[0] > 0  # profitable trade
    assert summary[1] == 1


async def test_kill_switch_blocks_orders(system):
    bus = system["bus"]
    coinbase = system["coinbase"]
    kill_switch = system["kill_switch"]

    await kill_switch.activate("manual test")

    await bus.publish(
        OrderRequest(product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=50.0)
    )

    coinbase.market_buy.assert_not_called()
