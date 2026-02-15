import pytest

from src.db import Database


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


async def test_initialize_creates_tables(db: Database):
    tables = await db.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row[0] for row in tables]
    assert "positions" in table_names
    assert "orders" in table_names
    assert "daily_summary" in table_names
    assert "kill_switch" in table_names


async def test_insert_and_fetch_position(db: Database):
    await db.execute(
        """INSERT INTO positions (id, product_id, side, entry_price, quantity, status, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("pos-1", "BTC-USD", "LONG", 50000.0, 0.002, "OPEN", "2026-01-01T00:00:00Z"),
    )
    rows = await db.execute_fetchall("SELECT * FROM positions WHERE id = ?", ("pos-1",))
    assert len(rows) == 1
    assert rows[0][1] == "BTC-USD"


async def test_insert_and_fetch_order(db: Database):
    await db.execute(
        """INSERT INTO positions (id, product_id, side, entry_price, quantity, status, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("pos-1", "BTC-USD", "LONG", 50000.0, 0.002, "OPEN", "2026-01-01T00:00:00Z"),
    )
    await db.execute(
        """INSERT INTO orders (id, position_id, product_id, side, type, quantity, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ord-1", "pos-1", "BTC-USD", "BUY", "MARKET", 0.002, "PENDING", "2026-01-01T00:00:00Z"),
    )
    rows = await db.execute_fetchall("SELECT * FROM orders WHERE id = ?", ("ord-1",))
    assert len(rows) == 1
    assert rows[0][2] == "BTC-USD"


async def test_kill_switch_default_off(db: Database):
    row = await db.execute_fetchone("SELECT active FROM kill_switch WHERE id = 1")
    assert row[0] == 0


async def test_set_kill_switch(db: Database):
    await db.execute("UPDATE kill_switch SET active = 1, reason = ? WHERE id = 1", ("daily loss",))
    row = await db.execute_fetchone("SELECT active, reason FROM kill_switch WHERE id = 1")
    assert row[0] == 1
    assert row[1] == "daily loss"


async def test_initialize_creates_new_tables(db: Database):
    tables = await db.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row[0] for row in tables]
    assert "price_history" in table_names
    assert "predictions" in table_names
    assert "news_history" in table_names
    assert "portfolio_snapshots" in table_names
