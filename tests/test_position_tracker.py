import pytest

from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFilled, PositionChanged
from src.position_tracker import PositionTracker


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
async def tracker(db, bus):
    t = PositionTracker(db=db, bus=bus)
    t.register(bus)
    return t


async def test_buy_opens_new_position(tracker, bus, db):
    changed = []

    async def handler(event: PositionChanged):
        changed.append(event)

    bus.subscribe(PositionChanged, handler)

    await bus.publish(
        OrderFilled(
            order_id="ord-1",
            product_id="BTC-USD",
            side="BUY",
            filled_price=50000.0,
            filled_qty=0.002,
            fee=0.20,
            coinbase_order_id="cb-1",
        )
    )

    assert len(changed) == 1
    assert changed[0].status == "OPEN"
    assert changed[0].quantity == 0.002

    rows = await db.execute_fetchall("SELECT * FROM positions WHERE status = 'OPEN'")
    assert len(rows) == 1


async def test_sell_closes_position(tracker, bus, db):
    # Open a position first
    await bus.publish(
        OrderFilled(
            order_id="ord-1",
            product_id="BTC-USD",
            side="BUY",
            filled_price=50000.0,
            filled_qty=0.002,
            fee=0.20,
            coinbase_order_id="cb-1",
        )
    )

    changed = []

    async def handler(event: PositionChanged):
        changed.append(event)

    bus.subscribe(PositionChanged, handler)

    # Sell to close
    await bus.publish(
        OrderFilled(
            order_id="ord-2",
            product_id="BTC-USD",
            side="SELL",
            filled_price=51000.0,
            filled_qty=0.002,
            fee=0.20,
            coinbase_order_id="cb-2",
        )
    )

    assert len(changed) == 1
    assert changed[0].status == "CLOSED"

    rows = await db.execute_fetchall("SELECT * FROM positions WHERE status = 'CLOSED'")
    assert len(rows) == 1

    # Check realized P&L: (51000 - 50000) * 0.002 - fees
    pos = rows[0]
    realized_pnl = pos[6]  # realized_pnl column
    assert realized_pnl == pytest.approx(2.0 - 0.40, abs=0.01)


async def test_sell_updates_daily_summary(tracker, bus, db):
    await bus.publish(
        OrderFilled(
            order_id="ord-1", product_id="BTC-USD", side="BUY",
            filled_price=50000.0, filled_qty=0.002, fee=0.20, coinbase_order_id="cb-1",
        )
    )
    await bus.publish(
        OrderFilled(
            order_id="ord-2", product_id="BTC-USD", side="SELL",
            filled_price=51000.0, filled_qty=0.002, fee=0.20, coinbase_order_id="cb-2",
        )
    )

    today = __import__("datetime").date.today().isoformat()
    row = await db.execute_fetchone("SELECT total_pnl, num_trades, fees_paid FROM daily_summary WHERE date = ?", (today,))
    assert row is not None
    assert row[0] > 0  # profit
    assert row[1] == 1  # one round-trip trade
    assert row[2] == pytest.approx(0.40, abs=0.01)


async def test_partial_sell_reduces_position(tracker, bus, db):
    await bus.publish(
        OrderFilled(
            order_id="ord-1", product_id="BTC-USD", side="BUY",
            filled_price=50000.0, filled_qty=0.004, fee=0.40, coinbase_order_id="cb-1",
        )
    )

    changed = []

    async def handler(event: PositionChanged):
        changed.append(event)

    bus.subscribe(PositionChanged, handler)

    await bus.publish(
        OrderFilled(
            order_id="ord-2", product_id="BTC-USD", side="SELL",
            filled_price=51000.0, filled_qty=0.002, fee=0.20, coinbase_order_id="cb-2",
        )
    )

    assert len(changed) == 1
    assert changed[0].status == "OPEN"
    assert changed[0].quantity == pytest.approx(0.002, abs=0.0001)
