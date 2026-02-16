import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.db import Database
from src.event_bus import EventBus
from src.portfolio_tracker import PortfolioTracker


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


def _mock_coinbase(accounts: list[dict]) -> MagicMock:
    """Create a mock CoinbaseClient with get_accounts() returning SDK-style objects."""
    mock = MagicMock()
    account_objects = [
        SimpleNamespace(
            currency=a["currency"],
            available_balance=a["available_balance"],  # SDK stores as raw dict
        )
        for a in accounts
    ]
    mock.get_accounts.return_value = SimpleNamespace(accounts=account_objects)
    return mock


async def test_snapshot_fetches_coinbase_balances(db: Database):
    """total_value_usd = base_balance * price + quote_balance."""
    bus = EventBus()
    coinbase = _mock_coinbase([
        {"currency": "SOL", "available_balance": {"value": "3.5", "currency": "SOL"}},
        {"currency": "USDC", "available_balance": {"value": "100.00", "currency": "USDC"}},
        {"currency": "BTC", "available_balance": {"value": "0.1", "currency": "BTC"}},  # not traded
    ])

    tracker = PortfolioTracker(
        db=db, bus=bus, coinbase=coinbase, product_id="SOL-USDC",
    )

    # Insert price so tracker can convert SOL to USD
    await db.execute(
        "INSERT INTO price_history (product_id, price, timestamp) VALUES (?, ?, ?)",
        ("SOL-USDC", 80.0, "2026-01-01T00:01:00Z"),
    )

    await tracker.take_snapshot()

    coinbase.get_accounts.assert_called_once()
    rows = await db.execute_fetchall(
        "SELECT total_value_usd, realized_pnl_cumulative, unrealized_pnl FROM portfolio_snapshots"
    )
    assert len(rows) == 1
    # total = 3.5 * 80.0 + 100.0 = 380.0
    assert rows[0][0] == pytest.approx(380.0, abs=0.01)


async def test_snapshot_keeps_local_pnl(db: Database):
    """unrealized_pnl and realized_pnl still come from local positions."""
    bus = EventBus()
    coinbase = _mock_coinbase([
        {"currency": "SOL", "available_balance": {"value": "0.001", "currency": "SOL"}},
        {"currency": "USDC", "available_balance": {"value": "50.0", "currency": "USDC"}},
    ])

    tracker = PortfolioTracker(
        db=db, bus=bus, coinbase=coinbase, product_id="SOL-USDC",
    )

    # Price for conversion
    await db.execute(
        "INSERT INTO price_history (product_id, price, timestamp) VALUES (?, ?, ?)",
        ("SOL-USDC", 90.0, "2026-01-01T00:01:00Z"),
    )

    # Open position for unrealized PnL
    await db.execute(
        """INSERT INTO positions (id, product_id, side, entry_price, quantity, status, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("pos-1", "SOL-USDC", "LONG", 80.0, 1.0, "OPEN", "2026-01-01T00:00:00Z"),
    )

    # Closed position for realized PnL
    await db.execute(
        """INSERT INTO positions (id, product_id, side, entry_price, quantity, status, realized_pnl, opened_at, closed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("pos-2", "SOL-USDC", "LONG", 70.0, 0.0, "CLOSED", 10.0, "2025-12-31T00:00:00Z", "2025-12-31T01:00:00Z"),
    )

    await tracker.take_snapshot()

    rows = await db.execute_fetchall(
        "SELECT total_value_usd, realized_pnl_cumulative, unrealized_pnl FROM portfolio_snapshots"
    )
    assert len(rows) == 1
    # unrealized = (90.0 - 80.0) * 1.0 = 10.0
    assert rows[0][2] == pytest.approx(10.0, abs=0.01)
    # realized = 10.0
    assert rows[0][1] == pytest.approx(10.0, abs=0.01)


async def test_snapshot_skips_on_api_error(db: Database):
    """If get_accounts() fails, snapshot is skipped (no row written)."""
    bus = EventBus()
    coinbase = MagicMock()
    coinbase.get_accounts.side_effect = Exception("API timeout")

    tracker = PortfolioTracker(
        db=db, bus=bus, coinbase=coinbase, product_id="SOL-USDC",
    )

    await tracker.take_snapshot()

    rows = await db.execute_fetchall("SELECT * FROM portfolio_snapshots")
    assert len(rows) == 0


async def test_quote_balance_property_updated_by_snapshot(db: Database):
    """quote_balance property reflects latest USDC balance after snapshot."""
    bus = EventBus()
    coinbase = _mock_coinbase([
        {"currency": "SOL", "available_balance": {"value": "1.0", "currency": "SOL"}},
        {"currency": "USDC", "available_balance": {"value": "42.50", "currency": "USDC"}},
    ])

    tracker = PortfolioTracker(
        db=db, bus=bus, coinbase=coinbase, product_id="SOL-USDC",
    )

    assert tracker.quote_balance == 0.0  # before any snapshot

    await db.execute(
        "INSERT INTO price_history (product_id, price, timestamp) VALUES (?, ?, ?)",
        ("SOL-USDC", 80.0, "2026-01-01T00:01:00Z"),
    )
    await tracker.take_snapshot()

    assert tracker.quote_balance == pytest.approx(42.50, abs=0.01)


async def test_snapshot_with_zero_base_balance(db: Database):
    """When base currency balance is 0, total_value = quote balance only."""
    bus = EventBus()
    coinbase = _mock_coinbase([
        {"currency": "SOL", "available_balance": {"value": "0.0", "currency": "SOL"}},
        {"currency": "USDC", "available_balance": {"value": "200.0", "currency": "USDC"}},
    ])

    tracker = PortfolioTracker(
        db=db, bus=bus, coinbase=coinbase, product_id="SOL-USDC",
    )

    await tracker.take_snapshot()

    rows = await db.execute_fetchall(
        "SELECT total_value_usd FROM portfolio_snapshots"
    )
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(200.0, abs=0.01)
