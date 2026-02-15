# Coinbase-Sourced Portfolio Value Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make PortfolioTracker fetch real account balances from Coinbase API instead of computing from local DB, and clean up dead code/columns.

**Architecture:** Inject `CoinbaseClient` + `product_id` into PortfolioTracker. On each snapshot, call `get_accounts()` to get real balances for the traded pair's currencies, convert base currency to USD using local price data. Remove dead columns `position_value_usd` and `num_open_positions` from schema, types, and tests.

**Tech Stack:** Python 3.12, asyncio, aiosqlite, coinbase-advanced-py SDK, Next.js/TypeScript dashboard

**Design doc:** `docs/plans/2026-02-15-coinbase-portfolio-source-design.md`

---

### Task 1: Update DB Schema — Remove Dead Columns

**Files:**
- Modify: `src/db.py:82-91`

**Step 1: Edit the schema**

In `src/db.py`, replace the `portfolio_snapshots` table definition:

```python
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    total_value_usd REAL NOT NULL,
    realized_pnl_cumulative REAL NOT NULL,
    unrealized_pnl REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portfolio_time ON portfolio_snapshots(timestamp);
```

Removed columns: `position_value_usd`, `num_open_positions`.

**Step 2: Run existing tests to confirm they fail**

Run: `pytest tests/test_portfolio_tracker.py -v`
Expected: FAIL (tests reference removed columns)

**Step 3: Commit schema change**

```bash
git add src/db.py
git commit -m "refactor: remove dead columns from portfolio_snapshots schema"
```

---

### Task 2: Rewrite PortfolioTracker to Use Coinbase API

**Files:**
- Modify: `src/portfolio_tracker.py` (full rewrite)

**Step 1: Write the failing tests**

Replace `tests/test_portfolio_tracker.py` entirely:

```python
import pytest
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
    """Create a mock CoinbaseClient with get_accounts() returning given accounts."""
    mock = MagicMock()
    mock.get_accounts.return_value = {"accounts": accounts}
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_portfolio_tracker.py -v`
Expected: FAIL — PortfolioTracker constructor doesn't accept `coinbase` or `product_id` yet

**Step 3: Rewrite PortfolioTracker implementation**

Replace `src/portfolio_tracker.py` entirely:

```python
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from src.coinbase_client import CoinbaseClient
from src.db import Database
from src.event_bus import EventBus

logger = logging.getLogger(__name__)


class PortfolioTracker:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        coinbase: CoinbaseClient,
        product_id: str,
        interval_seconds: int = 300,
    ) -> None:
        self._db = db
        self._bus = bus
        self._coinbase = coinbase
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None

        # Extract base/quote currencies from product_id (e.g. "SOL-USDC" -> "SOL", "USDC")
        parts = product_id.split("-")
        self._base_currency = parts[0]
        self._quote_currency = parts[1]
        self._product_id = product_id

    async def start(self) -> None:
        self._task = asyncio.create_task(self._snapshot_loop())
        logger.info("PortfolioTracker started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PortfolioTracker stopped")

    async def _snapshot_loop(self) -> None:
        while True:
            try:
                await self.take_snapshot()
            except Exception:
                logger.exception("Portfolio snapshot failed")
            await asyncio.sleep(self._interval)

    async def take_snapshot(self) -> None:
        # Fetch real balances from Coinbase (sync call -> run in executor)
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, self._coinbase.get_accounts)
        except Exception:
            logger.exception("Failed to fetch Coinbase accounts, skipping snapshot")
            return

        accounts = result.get("accounts", [])

        # Find base and quote currency balances
        base_balance = 0.0
        quote_balance = 0.0
        for account in accounts:
            currency = account.get("currency", "")
            balance = float(account.get("available_balance", {}).get("value", "0"))
            if currency == self._base_currency:
                base_balance = balance
            elif currency == self._quote_currency:
                quote_balance = balance

        # Convert base currency to USD using latest price
        base_value = 0.0
        if base_balance > 0:
            price_row = await self._db.execute_fetchone(
                "SELECT price FROM price_history WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1",
                (self._product_id,),
            )
            if price_row:
                base_value = base_balance * price_row[0]

        total_value = base_value + quote_balance

        # Local PnL calculations (unchanged)
        positions = await self._db.execute_fetchall(
            "SELECT entry_price, quantity FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (self._product_id,),
        )

        unrealized_pnl = 0.0
        if positions:
            price_row = await self._db.execute_fetchone(
                "SELECT price FROM price_history WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1",
                (self._product_id,),
            )
            if price_row:
                current_price = price_row[0]
                for entry_price, quantity in positions:
                    unrealized_pnl += (current_price - entry_price) * quantity

        pnl_row = await self._db.execute_fetchone(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE status = 'CLOSED'"
        )
        realized_pnl_cumulative = pnl_row[0] if pnl_row else 0.0

        # Write snapshot
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO portfolio_snapshots
               (id, timestamp, total_value_usd, realized_pnl_cumulative, unrealized_pnl)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), now, total_value, realized_pnl_cumulative, unrealized_pnl),
        )
        logger.info("Portfolio snapshot: value=$%.2f, unrealized=$%.2f, realized=$%.2f",
                     total_value, unrealized_pnl, realized_pnl_cumulative)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_portfolio_tracker.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/portfolio_tracker.py tests/test_portfolio_tracker.py
git commit -m "feat: source portfolio value from Coinbase API

PortfolioTracker now calls get_accounts() for real balances instead of
computing from local positions. Keeps local PnL for analytics."
```

---

### Task 3: Update main.py Wiring

**Files:**
- Modify: `src/main.py:59`

**Step 1: Update PortfolioTracker construction**

Change line 59 from:

```python
    portfolio_tracker = PortfolioTracker(db=db, bus=bus, interval_seconds=settings.prediction_interval_minutes * 60)
```

To:

```python
    portfolio_tracker = PortfolioTracker(
        db=db,
        bus=bus,
        coinbase=coinbase,
        product_id=settings.product_id,
        interval_seconds=settings.prediction_interval_minutes * 60,
    )
```

**Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "wire: pass coinbase client and product_id to PortfolioTracker"
```

---

### Task 4: Clean Up Dashboard Types

**Files:**
- Modify: `ui/src/lib/types.ts:65-73`

**Step 1: Remove dead fields from PortfolioSnapshot type**

Replace:

```typescript
export interface PortfolioSnapshot {
  id: string;
  timestamp: string;
  total_value_usd: number;
  position_value_usd: number;
  realized_pnl_cumulative: number;
  unrealized_pnl: number;
  num_open_positions: number;
}
```

With:

```typescript
export interface PortfolioSnapshot {
  id: string;
  timestamp: string;
  total_value_usd: number;
  realized_pnl_cumulative: number;
  unrealized_pnl: number;
}
```

**Step 2: Check for TypeScript compile errors**

Run: `cd ui && npx tsc --noEmit`
Expected: No errors (dashboard pages only use `total_value_usd` and `realized_pnl_cumulative`)

**Step 3: Commit**

```bash
git add ui/src/lib/types.ts
git commit -m "refactor: remove dead fields from PortfolioSnapshot type"
```

---

### Task 5: Update Documentation

**Files:**
- Modify: `docs/architecture.md` (portfolio_snapshots table)
- Modify: AI docs if they reference the old columns

**Step 1: Update architecture.md portfolio_snapshots table**

Find the `portfolio_snapshots` table section and update to match the new schema (remove `position_value_usd` and `num_open_positions` rows). Add a changelog entry noting the change.

**Step 2: Update AI docs**

Check `docs/ai-components.md`, `docs/ai-data.md` for references to `position_value_usd` or `num_open_positions` and update them.

**Step 3: Commit**

```bash
git add docs/
git commit -m "docs: update portfolio_snapshots schema in architecture docs"
```

---

### Task 6: Final Verification

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 2: Run TypeScript check**

Run: `cd ui && npx tsc --noEmit`
Expected: No errors

**Step 3: Verify no remaining references to dead columns**

Search for `position_value_usd` and `num_open_positions` in `src/`, `tests/`, and `ui/src/`. Should only appear in `docs/plans/` (historical plan docs are fine).
