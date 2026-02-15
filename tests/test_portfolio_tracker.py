import pytest
from unittest.mock import AsyncMock

from src.db import Database
from src.event_bus import EventBus
from src.portfolio_tracker import PortfolioTracker


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


async def test_snapshot_with_open_position(db: Database):
    bus = EventBus()
    tracker = PortfolioTracker(db=db, bus=bus)

    # Insert a price so tracker can compute value
    await db.execute(
        "INSERT INTO price_history (product_id, price, timestamp) VALUES (?, ?, ?)",
        ("BTC-USD", 51000.0, "2026-01-01T00:01:00Z"),
    )

    # Insert an open position
    await db.execute(
        """INSERT INTO positions (id, product_id, side, entry_price, quantity, status, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("pos-1", "BTC-USD", "LONG", 50000.0, 0.001, "OPEN", "2026-01-01T00:00:00Z"),
    )

    # Insert a closed position with realized P&L
    await db.execute(
        """INSERT INTO positions (id, product_id, side, entry_price, quantity, status, realized_pnl, opened_at, closed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("pos-2", "BTC-USD", "LONG", 49000.0, 0.0, "CLOSED", 5.0, "2025-12-31T00:00:00Z", "2025-12-31T01:00:00Z"),
    )

    await tracker.take_snapshot()

    rows = await db.execute_fetchall("SELECT total_value_usd, position_value_usd, unrealized_pnl, realized_pnl_cumulative, num_open_positions FROM portfolio_snapshots")
    assert len(rows) == 1
    # position_value = 0.001 * 51000 = 51.0
    assert rows[0][1] == pytest.approx(51.0, abs=0.01)
    # unrealized = (51000 - 50000) * 0.001 = 1.0
    assert rows[0][2] == pytest.approx(1.0, abs=0.01)
    # cumulative realized = 5.0
    assert rows[0][3] == pytest.approx(5.0, abs=0.01)
    assert rows[0][4] == 1


async def test_snapshot_with_no_positions(db: Database):
    bus = EventBus()
    tracker = PortfolioTracker(db=db, bus=bus)

    await tracker.take_snapshot()

    rows = await db.execute_fetchall("SELECT total_value_usd, position_value_usd, unrealized_pnl, num_open_positions FROM portfolio_snapshots")
    assert len(rows) == 1
    assert rows[0][0] == 0.0
    assert rows[0][1] == 0.0
    assert rows[0][2] == 0.0
    assert rows[0][3] == 0
