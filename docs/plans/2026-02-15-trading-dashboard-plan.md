# Trading Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 4 new DB tables for historical data persistence + a Next.js TypeScript dashboard to monitor the trading bot.

**Architecture:** Python bot gains new tables (price_history, predictions, news_history, portfolio_snapshots) and writes to them from existing components + a new PortfolioTracker. A separate Next.js app in `ui/` reads the SQLite DB read-only via better-sqlite3 and serves a dark-themed dashboard with 6 pages.

**Tech Stack:** Python 3.12 (aiosqlite), Next.js 14+ (App Router), TypeScript, Tailwind CSS, Recharts, better-sqlite3

---

## Part 1: Python Backend — New Tables & Data Persistence

### Task 1: Add new tables to DB schema

**Files:**
- Modify: `src/db.py:3-50` (SCHEMA string)
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
async def test_initialize_creates_new_tables(db: Database):
    tables = await db.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row[0] for row in tables]
    assert "price_history" in table_names
    assert "predictions" in table_names
    assert "news_history" in table_names
    assert "portfolio_snapshots" in table_names
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_initialize_creates_new_tables -v`
Expected: FAIL — tables don't exist yet

**Step 3: Add tables to SCHEMA in `src/db.py`**

Append these after the existing `kill_switch` table in the SCHEMA string (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS price_history (
    product_id TEXT NOT NULL,
    price REAL NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_history_product_time ON price_history(product_id, timestamp);

CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    action TEXT NOT NULL,
    predicted_price REAL,
    current_price REAL NOT NULL,
    confidence REAL,
    reasoning TEXT,
    model TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_predictions_time ON predictions(timestamp);

CREATE TABLE IF NOT EXISTS news_history (
    id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL,
    headline TEXT NOT NULL,
    source TEXT,
    sentiment TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
);
CREATE INDEX IF NOT EXISTS idx_news_prediction ON news_history(prediction_id);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    total_value_usd REAL NOT NULL,
    position_value_usd REAL NOT NULL,
    realized_pnl_cumulative REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    num_open_positions INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portfolio_time ON portfolio_snapshots(timestamp);
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/db.py tests/test_db.py
git commit -m "feat: add price_history, predictions, news_history, portfolio_snapshots tables"
```

---

### Task 2: Persist price ticks from MarketData

**Files:**
- Modify: `src/market_data.py` (add db param, write on each tick)
- Modify: `src/main.py:61-66` (pass db to MarketData)
- Test: `tests/test_market_data.py`

**Step 1: Write the failing test**

Add to `tests/test_market_data.py`:

```python
async def test_on_message_persists_price_to_db():
    db = Database(":memory:")
    await db.initialize()
    bus = EventBus()
    md = MarketData(bus=bus, db=db, product_ids=["BTC-USD"])
    md._loop = asyncio.get_running_loop()

    msg = json.dumps({
        "channel": "ticker",
        "timestamp": "2026-01-01T00:00:00Z",
        "events": [{"tickers": [{"product_id": "BTC-USD", "price": "50000.00"}]}],
    })
    await md._on_message(msg)

    rows = await db.execute_fetchall("SELECT product_id, price, timestamp FROM price_history")
    assert len(rows) == 1
    assert rows[0][0] == "BTC-USD"
    assert rows[0][1] == 50000.0
    await db.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_market_data.py::test_on_message_persists_price_to_db -v`
Expected: FAIL — MarketData doesn't accept `db` param

**Step 3: Modify MarketData to accept and use db**

In `src/market_data.py`:

1. Add `db` parameter to `__init__` (default `None`):
```python
def __init__(self, bus: EventBus, api_key: str = "", api_secret: str = "", key_file: str = "", product_ids: list[str] | None = None, db: "Database | None" = None) -> None:
    self._db = db
    # ... rest unchanged
```

2. Add import at top: `from __future__ import annotations`

3. At the end of `_on_message`, after `await self._bus.publish(...)`, add:
```python
if self._db:
    await self._db.execute(
        "INSERT INTO price_history (product_id, price, timestamp) VALUES (?, ?, ?)",
        (product_id, float(price_str), timestamp),
    )
```

4. In `src/main.py:61`, pass `db=db` to MarketData constructor.

**Step 4: Run tests**

Run: `pytest tests/test_market_data.py -v`
Expected: ALL PASS (existing tests still pass since db defaults to None)

**Step 5: Commit**

```bash
git add src/market_data.py src/main.py tests/test_market_data.py
git commit -m "feat: persist price ticks to price_history table"
```

---

### Task 3: Log predictions and news from ClaudePredictionStrategy

**Files:**
- Modify: `src/strategy_claude_prediction.py:76-101` (_run_prediction_cycle)
- Test: `tests/test_strategy_claude_prediction.py`

**Step 1: Write the failing test**

Add to `tests/test_strategy_claude_prediction.py`:

```python
async def test_prediction_cycle_logs_prediction_and_news():
    db = Database(":memory:")
    await db.initialize()
    bus = EventBus()
    price_buffer = PriceBuffer()
    price_buffer.add(PriceUpdate(product_id="BTC-USD", price=50000.0, timestamp="2026-01-01T00:00:00Z"))

    mock_news = AsyncMock()
    mock_news.fetch_headlines = AsyncMock(return_value=["1. BTC surges - bullish", "2. Fed holds rates - neutral"])

    mock_predictor = AsyncMock()
    mock_predictor.predict = AsyncMock(return_value=Prediction(
        target_price=50100.0,
        timeframe_minutes=5,
        reasoning="bullish momentum",
        current_price=50000.0,
        timestamp="2026-01-01T00:00:00Z",
    ))

    settings = Settings(trade_threshold_pct=0.1, trade_size_usd=50.0, product_id="BTC-USD",
                        prediction_interval_minutes=5, prediction_model="test-model")

    strategy = ClaudePredictionStrategy(
        bus=bus, price_buffer=price_buffer, news_service=mock_news,
        predictor=mock_predictor, settings=settings, product_id="BTC-USD", db=db,
    )

    await strategy._run_prediction_cycle()

    # Check prediction was logged
    rows = await db.execute_fetchall("SELECT product_id, action, predicted_price, current_price, reasoning, model FROM predictions")
    assert len(rows) == 1
    assert rows[0][0] == "BTC-USD"
    assert rows[0][2] == 50100.0  # predicted_price
    assert rows[0][5] == "test-model"  # model

    # Check news was logged
    news_rows = await db.execute_fetchall("SELECT headline FROM news_history")
    assert len(news_rows) == 2

    await db.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy_claude_prediction.py::test_prediction_cycle_logs_prediction_and_news -v`
Expected: FAIL — no prediction logging code yet

**Step 3: Modify `_run_prediction_cycle` in `src/strategy_claude_prediction.py`**

1. Add imports at top:
```python
import uuid
from datetime import datetime, timezone
```

2. After `await self._evaluate(prediction)` (line 101), add a call to a new method `_log_prediction`:

```python
await self._log_prediction(prediction, headlines)
```

3. Add the `_log_prediction` method:

```python
async def _log_prediction(self, prediction: Prediction, headlines: list[str]) -> None:
    if self._db is None:
        return

    diff_pct = (
        (prediction.target_price - prediction.current_price)
        / prediction.current_price * 100
    ) if prediction.current_price > 0 else 0

    threshold = self._settings.trade_threshold_pct
    if diff_pct > threshold:
        action = "BUY"
    elif diff_pct < -threshold:
        action = "SELL"
    else:
        action = "HOLD"

    pred_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    await self._db.execute(
        """INSERT INTO predictions (id, product_id, action, predicted_price, current_price,
           confidence, reasoning, model, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pred_id, self._product_id, action, prediction.target_price,
         prediction.current_price, abs(diff_pct), prediction.reasoning,
         self._settings.prediction_model, now),
    )

    for headline in headlines:
        await self._db.execute(
            """INSERT INTO news_history (id, prediction_id, headline, source, sentiment, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), pred_id, headline, None, None, now),
        )
```

**Step 4: Run tests**

Run: `pytest tests/test_strategy_claude_prediction.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/strategy_claude_prediction.py tests/test_strategy_claude_prediction.py
git commit -m "feat: log predictions and news headlines to database"
```

---

### Task 4: Add PortfolioTracker component

**Files:**
- Create: `src/portfolio_tracker.py`
- Modify: `src/main.py` (wire PortfolioTracker into startup)
- Test: `tests/test_portfolio_tracker.py`

**Step 1: Write the failing test**

Create `tests/test_portfolio_tracker.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_portfolio_tracker.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Create `src/portfolio_tracker.py`**

```python
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from src.db import Database
from src.event_bus import EventBus

logger = logging.getLogger(__name__)


class PortfolioTracker:
    def __init__(self, db: Database, bus: EventBus, interval_seconds: int = 300) -> None:
        self._db = db
        self._bus = bus
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None

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
        # Get all open positions
        positions = await self._db.execute_fetchall(
            "SELECT product_id, entry_price, quantity FROM positions WHERE status = 'OPEN'"
        )

        position_value = 0.0
        unrealized_pnl = 0.0
        num_open = len(positions)

        for product_id, entry_price, quantity in positions:
            # Get latest price for this product
            price_row = await self._db.execute_fetchone(
                "SELECT price FROM price_history WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1",
                (product_id,),
            )
            if price_row:
                current_price = price_row[0]
                position_value += current_price * quantity
                unrealized_pnl += (current_price - entry_price) * quantity
            else:
                # Use entry price if no price history available
                position_value += entry_price * quantity

        # Cumulative realized P&L from all closed positions
        pnl_row = await self._db.execute_fetchone(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE status = 'CLOSED'"
        )
        realized_pnl_cumulative = pnl_row[0] if pnl_row else 0.0

        total_value = position_value + realized_pnl_cumulative

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO portfolio_snapshots
               (id, timestamp, total_value_usd, position_value_usd, realized_pnl_cumulative, unrealized_pnl, num_open_positions)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), now, total_value, position_value, realized_pnl_cumulative, unrealized_pnl, num_open),
        )
        logger.info("Portfolio snapshot: value=$%.2f, unrealized=$%.2f, realized=$%.2f",
                     total_value, unrealized_pnl, realized_pnl_cumulative)
```

**Step 4: Run tests**

Run: `pytest tests/test_portfolio_tracker.py -v`
Expected: ALL PASS

**Step 5: Wire into main.py**

In `src/main.py`, add import and instantiation after position_tracker:

```python
from src.portfolio_tracker import PortfolioTracker
```

After `position_tracker.register(bus)` (line 58), add:

```python
portfolio_tracker = PortfolioTracker(db=db, bus=bus, interval_seconds=settings.prediction_interval_minutes * 60)
```

After `await strategy.start()` (line 106), add:

```python
await portfolio_tracker.start()
```

Before `await db.close()` (line 115), add:

```python
await portfolio_tracker.stop()
```

**Step 6: Run all tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add src/portfolio_tracker.py src/main.py tests/test_portfolio_tracker.py
git commit -m "feat: add PortfolioTracker for periodic portfolio snapshots"
```

---

## Part 2: Next.js Dashboard

### Task 5: Scaffold Next.js project

**Files:**
- Create: `ui/` directory with Next.js project

**Step 1: Initialize the project**

```bash
cd /Users/jac/Dev/src/coinbase_trading_bot
npx create-next-app@latest ui --typescript --tailwind --eslint --app --src-dir --no-import-alias --use-npm
```

**Step 2: Install dependencies**

```bash
cd ui && npm install better-sqlite3 recharts && npm install -D @types/better-sqlite3
```

**Step 3: Verify it builds**

```bash
cd ui && npm run build
```
Expected: Build succeeds

**Step 4: Commit**

```bash
git add ui/
git commit -m "feat: scaffold Next.js dashboard project"
```

---

### Task 6: Database connection layer

**Files:**
- Create: `ui/src/lib/db.ts`
- Create: `ui/src/lib/types.ts`

**Step 1: Create types file `ui/src/lib/types.ts`**

```typescript
export interface Position {
  id: string;
  product_id: string;
  side: string;
  entry_price: number;
  quantity: number;
  status: string;
  realized_pnl: number;
  opened_at: string;
  closed_at: string | null;
}

export interface Order {
  id: string;
  position_id: string | null;
  product_id: string;
  side: string;
  type: string;
  price: number | null;
  quantity: number;
  status: string;
  coinbase_id: string | null;
  filled_price: number | null;
  filled_qty: number | null;
  fee: number | null;
  created_at: string;
  filled_at: string | null;
}

export interface PricePoint {
  product_id: string;
  price: number;
  timestamp: string;
}

export interface PredictionRecord {
  id: string;
  product_id: string;
  action: string;
  predicted_price: number | null;
  current_price: number;
  confidence: number | null;
  reasoning: string | null;
  model: string;
  timestamp: string;
}

export interface NewsRecord {
  id: string;
  prediction_id: string;
  headline: string;
  source: string | null;
  sentiment: string | null;
  timestamp: string;
}

export interface DailySummary {
  date: string;
  total_pnl: number;
  num_trades: number;
  fees_paid: number;
  halted: number;
}

export interface PortfolioSnapshot {
  id: string;
  timestamp: string;
  total_value_usd: number;
  position_value_usd: number;
  realized_pnl_cumulative: number;
  unrealized_pnl: number;
  num_open_positions: number;
}

export interface KillSwitchStatus {
  active: boolean;
  reason: string | null;
  activated_at: string | null;
}
```

**Step 2: Create db connection `ui/src/lib/db.ts`**

```typescript
import Database from "better-sqlite3";
import path from "path";

let db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (!db) {
    const dbPath = process.env.DB_PATH || path.resolve(__dirname, "../../../../trading_bot.db");
    db = new Database(dbPath, { readonly: true });
    db.pragma("journal_mode = WAL");
  }
  return db;
}
```

**Step 3: Create `ui/.env.local`**

```
DB_PATH=../trading_bot.db
```

**Step 4: Commit**

```bash
git add ui/src/lib/
git commit -m "feat: add database types and connection layer"
```

---

### Task 7: API routes

**Files:**
- Create: `ui/src/app/api/positions/route.ts`
- Create: `ui/src/app/api/orders/route.ts`
- Create: `ui/src/app/api/prices/route.ts`
- Create: `ui/src/app/api/predictions/route.ts`
- Create: `ui/src/app/api/summary/route.ts`
- Create: `ui/src/app/api/portfolio/route.ts`

**Step 1: Create all API routes**

Each route follows the same pattern — read-only query, return JSON. Example for positions:

`ui/src/app/api/positions/route.ts`:
```typescript
import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";
import type { Position } from "@/lib/types";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const status = searchParams.get("status"); // "OPEN", "CLOSED", or null for all

  const db = getDb();
  let rows;
  if (status) {
    rows = db.prepare("SELECT * FROM positions WHERE status = ? ORDER BY opened_at DESC").all(status);
  } else {
    rows = db.prepare("SELECT * FROM positions ORDER BY opened_at DESC").all();
  }
  return NextResponse.json(rows as Position[]);
}
```

`ui/src/app/api/orders/route.ts`:
```typescript
import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const limit = parseInt(searchParams.get("limit") || "100");

  const db = getDb();
  const rows = db.prepare("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?").all(limit);
  return NextResponse.json(rows);
}
```

`ui/src/app/api/prices/route.ts`:
```typescript
import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const product = searchParams.get("product_id") || "BTC-USD";
  const hours = parseInt(searchParams.get("hours") || "24");

  const db = getDb();
  const rows = db.prepare(
    "SELECT * FROM price_history WHERE product_id = ? AND timestamp >= datetime('now', ?) ORDER BY timestamp ASC"
  ).all(product, `-${hours} hours`);
  return NextResponse.json(rows);
}
```

`ui/src/app/api/predictions/route.ts`:
```typescript
import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const limit = parseInt(searchParams.get("limit") || "50");

  const db = getDb();
  const predictions = db.prepare("SELECT * FROM predictions ORDER BY timestamp DESC LIMIT ?").all(limit);

  // Attach news to each prediction
  const stmt = db.prepare("SELECT * FROM news_history WHERE prediction_id = ?");
  const result = (predictions as any[]).map((p) => ({
    ...p,
    news: stmt.all(p.id),
  }));

  return NextResponse.json(result);
}
```

`ui/src/app/api/summary/route.ts`:
```typescript
import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET() {
  const db = getDb();

  const killSwitch = db.prepare("SELECT active, reason, activated_at FROM kill_switch WHERE id = 1").get();
  const todaySummary = db.prepare("SELECT * FROM daily_summary WHERE date = date('now')").get();
  const openPositions = db.prepare("SELECT * FROM positions WHERE status = 'OPEN'").all();
  const latestPrice = db.prepare("SELECT price, timestamp FROM price_history ORDER BY timestamp DESC LIMIT 1").get();

  return NextResponse.json({
    kill_switch: killSwitch,
    daily_summary: todaySummary || { date: new Date().toISOString().slice(0, 10), total_pnl: 0, num_trades: 0, fees_paid: 0, halted: 0 },
    open_positions: openPositions,
    latest_price: latestPrice,
  });
}
```

`ui/src/app/api/portfolio/route.ts`:
```typescript
import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const hours = parseInt(searchParams.get("hours") || "168"); // default 7 days

  const db = getDb();
  const rows = db.prepare(
    "SELECT * FROM portfolio_snapshots WHERE timestamp >= datetime('now', ?) ORDER BY timestamp ASC"
  ).all(`-${hours} hours`);
  return NextResponse.json(rows);
}
```

**Step 2: Verify build**

Run: `cd ui && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add ui/src/app/api/
git commit -m "feat: add API routes for positions, orders, prices, predictions, summary, portfolio"
```

---

### Task 8: Shared layout and navigation

**Files:**
- Modify: `ui/src/app/layout.tsx`
- Modify: `ui/src/app/globals.css`
- Create: `ui/src/components/nav.tsx`

**Step 1: Create navigation component `ui/src/components/nav.tsx`**

```typescript
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Overview" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/positions", label: "Positions" },
  { href: "/orders", label: "Orders" },
  { href: "/prices", label: "Prices" },
  { href: "/predictions", label: "Predictions" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-zinc-800 bg-zinc-950 px-6 py-3">
      <div className="flex items-center gap-8">
        <span className="text-lg font-semibold text-zinc-100">Trading Bot</span>
        <div className="flex gap-1">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`rounded px-3 py-1.5 text-sm transition-colors ${
                pathname === link.href
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
              }`}
            >
              {link.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
```

**Step 2: Update layout `ui/src/app/layout.tsx`**

```typescript
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/nav";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Trading Bot Dashboard",
  description: "Monitor your Coinbase trading bot",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-zinc-950 text-zinc-100 min-h-screen`}>
        <Nav />
        <main className="p-6">{children}</main>
      </body>
    </html>
  );
}
```

**Step 3: Trim globals.css to just Tailwind directives**

Replace `ui/src/app/globals.css` with:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

**Step 4: Commit**

```bash
git add ui/src/components/nav.tsx ui/src/app/layout.tsx ui/src/app/globals.css
git commit -m "feat: add dark theme layout and navigation"
```

---

### Task 9: Overview page

**Files:**
- Modify: `ui/src/app/page.tsx`

**Step 1: Build the overview page**

`ui/src/app/page.tsx`:
```typescript
"use client";

import { useEffect, useState } from "react";

interface SummaryData {
  kill_switch: { active: number; reason: string | null; activated_at: string | null };
  daily_summary: { date: string; total_pnl: number; num_trades: number; fees_paid: number };
  open_positions: Array<{
    id: string; product_id: string; entry_price: number; quantity: number; status: string;
  }>;
  latest_price: { price: number; timestamp: string } | null;
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="text-sm text-zinc-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {sub && <p className="mt-1 text-xs text-zinc-500">{sub}</p>}
    </div>
  );
}

export default function OverviewPage() {
  const [data, setData] = useState<SummaryData | null>(null);

  useEffect(() => {
    const load = () => fetch("/api/summary").then((r) => r.json()).then(setData);
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  if (!data) return <p className="text-zinc-500">Loading...</p>;

  const pos = data.open_positions[0];
  const price = data.latest_price?.price ?? 0;
  const unrealizedPnl = pos ? (price - pos.entry_price) * pos.quantity : 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Overview</h1>

      {data.kill_switch.active ? (
        <div className="rounded-lg border border-red-800 bg-red-950 p-4 text-red-300">
          Kill switch ACTIVE: {data.kill_switch.reason}
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Current Price" value={price ? `$${price.toLocaleString()}` : "—"} sub={data.latest_price?.timestamp} />
        <StatCard label="Daily P&L" value={`$${data.daily_summary.total_pnl.toFixed(2)}`} sub={`${data.daily_summary.num_trades} trades`} />
        <StatCard label="Fees Today" value={`$${data.daily_summary.fees_paid.toFixed(2)}`} />
        <StatCard
          label="Unrealized P&L"
          value={pos ? `$${unrealizedPnl.toFixed(2)}` : "—"}
          sub={pos ? `${pos.quantity.toFixed(6)} @ $${pos.entry_price.toFixed(2)}` : "No open position"}
        />
      </div>

      {pos && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <h2 className="mb-2 text-lg font-semibold">Open Position</h2>
          <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
            <div><span className="text-zinc-400">Product:</span> {pos.product_id}</div>
            <div><span className="text-zinc-400">Entry:</span> ${pos.entry_price.toFixed(2)}</div>
            <div><span className="text-zinc-400">Qty:</span> {pos.quantity.toFixed(6)}</div>
            <div><span className="text-zinc-400">Value:</span> ${(pos.quantity * price).toFixed(2)}</div>
          </div>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd ui && npm run build`

**Step 3: Commit**

```bash
git add ui/src/app/page.tsx
git commit -m "feat: add overview page with live polling"
```

---

### Task 10: Portfolio page

**Files:**
- Create: `ui/src/app/portfolio/page.tsx`

**Step 1: Build the portfolio page with equity curve**

`ui/src/app/portfolio/page.tsx`:
```typescript
"use client";

import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { PortfolioSnapshot } from "@/lib/types";

const ranges = [
  { label: "1D", hours: 24 },
  { label: "1W", hours: 168 },
  { label: "1M", hours: 720 },
  { label: "ALL", hours: 8760 },
];

export default function PortfolioPage() {
  const [data, setData] = useState<PortfolioSnapshot[]>([]);
  const [hours, setHours] = useState(168);

  useEffect(() => {
    fetch(`/api/portfolio?hours=${hours}`).then((r) => r.json()).then(setData);
  }, [hours]);

  const latest = data[data.length - 1];
  const first = data[0];
  const change = latest && first ? latest.total_value_usd - first.total_value_usd : 0;
  const changePct = first && first.total_value_usd !== 0 ? (change / first.total_value_usd) * 100 : 0;

  // Drawdown calculation
  let peak = 0;
  let maxDrawdown = 0;
  for (const snap of data) {
    if (snap.total_value_usd > peak) peak = snap.total_value_usd;
    const dd = peak > 0 ? ((peak - snap.total_value_usd) / peak) * 100 : 0;
    if (dd > maxDrawdown) maxDrawdown = dd;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Portfolio</h1>

      <div className="flex gap-2">
        {ranges.map((r) => (
          <button
            key={r.label}
            onClick={() => setHours(r.hours)}
            className={`rounded px-3 py-1 text-sm ${hours === r.hours ? "bg-zinc-700 text-zinc-100" : "bg-zinc-900 text-zinc-400"}`}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-sm text-zinc-400">Total Value</p>
          <p className="mt-1 text-2xl font-semibold">${latest?.total_value_usd.toFixed(2) ?? "—"}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-sm text-zinc-400">Change</p>
          <p className={`mt-1 text-2xl font-semibold ${change >= 0 ? "text-green-400" : "text-red-400"}`}>
            {change >= 0 ? "+" : ""}${change.toFixed(2)} ({changePct.toFixed(1)}%)
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-sm text-zinc-400">Realized P&L</p>
          <p className="mt-1 text-2xl font-semibold">${latest?.realized_pnl_cumulative.toFixed(2) ?? "—"}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-sm text-zinc-400">Max Drawdown</p>
          <p className="mt-1 text-2xl font-semibold text-red-400">-{maxDrawdown.toFixed(1)}%</p>
        </div>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4" style={{ height: 400 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="timestamp"
              stroke="#71717a"
              tickFormatter={(t) => new Date(t).toLocaleDateString()}
            />
            <YAxis stroke="#71717a" tickFormatter={(v) => `$${v}`} />
            <Tooltip
              contentStyle={{ backgroundColor: "#18181b", border: "1px solid #3f3f46" }}
              labelFormatter={(t) => new Date(t).toLocaleString()}
              formatter={(v: number) => [`$${v.toFixed(2)}`, "Value"]}
            />
            <Line type="monotone" dataKey="total_value_usd" stroke="#22c55e" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add ui/src/app/portfolio/
git commit -m "feat: add portfolio page with equity curve"
```

---

### Task 11: Positions page

**Files:**
- Create: `ui/src/app/positions/page.tsx`

**Step 1: Build positions table page**

`ui/src/app/positions/page.tsx`:
```typescript
"use client";

import { useEffect, useState } from "react";
import type { Position } from "@/lib/types";

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [filter, setFilter] = useState<string>("");

  useEffect(() => {
    const url = filter ? `/api/positions?status=${filter}` : "/api/positions";
    fetch(url).then((r) => r.json()).then(setPositions);
  }, [filter]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Positions</h1>
        <div className="flex gap-2">
          {["", "OPEN", "CLOSED"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded px-3 py-1 text-sm ${filter === f ? "bg-zinc-700 text-zinc-100" : "bg-zinc-900 text-zinc-400"}`}
            >
              {f || "All"}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full text-sm">
          <thead className="border-b border-zinc-800 bg-zinc-900">
            <tr>
              <th className="px-4 py-2 text-left text-zinc-400">Product</th>
              <th className="px-4 py-2 text-left text-zinc-400">Status</th>
              <th className="px-4 py-2 text-right text-zinc-400">Entry Price</th>
              <th className="px-4 py-2 text-right text-zinc-400">Quantity</th>
              <th className="px-4 py-2 text-right text-zinc-400">Realized P&L</th>
              <th className="px-4 py-2 text-left text-zinc-400">Opened</th>
              <th className="px-4 py-2 text-left text-zinc-400">Closed</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                <td className="px-4 py-2">{p.product_id}</td>
                <td className="px-4 py-2">
                  <span className={`rounded px-2 py-0.5 text-xs ${p.status === "OPEN" ? "bg-green-950 text-green-400" : "bg-zinc-800 text-zinc-400"}`}>
                    {p.status}
                  </span>
                </td>
                <td className="px-4 py-2 text-right">${p.entry_price.toFixed(2)}</td>
                <td className="px-4 py-2 text-right">{p.quantity.toFixed(6)}</td>
                <td className={`px-4 py-2 text-right ${p.realized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                  ${p.realized_pnl.toFixed(2)}
                </td>
                <td className="px-4 py-2 text-zinc-400">{new Date(p.opened_at).toLocaleString()}</td>
                <td className="px-4 py-2 text-zinc-400">{p.closed_at ? new Date(p.closed_at).toLocaleString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add ui/src/app/positions/
git commit -m "feat: add positions page with filterable table"
```

---

### Task 12: Orders page

**Files:**
- Create: `ui/src/app/orders/page.tsx`

**Step 1: Build orders log page**

`ui/src/app/orders/page.tsx`:
```typescript
"use client";

import { useEffect, useState } from "react";
import type { Order } from "@/lib/types";

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);

  useEffect(() => {
    fetch("/api/orders?limit=200").then((r) => r.json()).then(setOrders);
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Orders</h1>

      <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full text-sm">
          <thead className="border-b border-zinc-800 bg-zinc-900">
            <tr>
              <th className="px-4 py-2 text-left text-zinc-400">Time</th>
              <th className="px-4 py-2 text-left text-zinc-400">Product</th>
              <th className="px-4 py-2 text-left text-zinc-400">Side</th>
              <th className="px-4 py-2 text-left text-zinc-400">Type</th>
              <th className="px-4 py-2 text-left text-zinc-400">Status</th>
              <th className="px-4 py-2 text-right text-zinc-400">Qty</th>
              <th className="px-4 py-2 text-right text-zinc-400">Fill Price</th>
              <th className="px-4 py-2 text-right text-zinc-400">Fee</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                <td className="px-4 py-2 text-zinc-400">{new Date(o.created_at).toLocaleString()}</td>
                <td className="px-4 py-2">{o.product_id}</td>
                <td className={`px-4 py-2 ${o.side === "BUY" ? "text-green-400" : "text-red-400"}`}>{o.side}</td>
                <td className="px-4 py-2">{o.type}</td>
                <td className="px-4 py-2">
                  <span className={`rounded px-2 py-0.5 text-xs ${
                    o.status === "FILLED" ? "bg-green-950 text-green-400" :
                    o.status === "FAILED" ? "bg-red-950 text-red-400" :
                    "bg-yellow-950 text-yellow-400"
                  }`}>{o.status}</span>
                </td>
                <td className="px-4 py-2 text-right">{o.filled_qty?.toFixed(6) ?? "—"}</td>
                <td className="px-4 py-2 text-right">{o.filled_price ? `$${o.filled_price.toFixed(2)}` : "—"}</td>
                <td className="px-4 py-2 text-right">{o.fee ? `$${o.fee.toFixed(4)}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add ui/src/app/orders/
git commit -m "feat: add orders page"
```

---

### Task 13: Price chart page

**Files:**
- Create: `ui/src/app/prices/page.tsx`

**Step 1: Build price chart page with trade markers**

`ui/src/app/prices/page.tsx`:
```typescript
"use client";

import { useEffect, useState } from "react";
import {
  ComposedChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Scatter,
} from "recharts";
import type { Order, PricePoint } from "@/lib/types";

const ranges = [
  { label: "1H", hours: 1 },
  { label: "6H", hours: 6 },
  { label: "1D", hours: 24 },
  { label: "1W", hours: 168 },
];

interface ChartPoint {
  timestamp: string;
  price: number;
  buy?: number;
  sell?: number;
}

export default function PricesPage() {
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [hours, setHours] = useState(24);

  useEffect(() => {
    fetch(`/api/prices?hours=${hours}`).then((r) => r.json()).then(setPrices);
    fetch("/api/orders?limit=500").then((r) => r.json()).then(setOrders);
  }, [hours]);

  // Merge prices with trade markers
  const filledOrders = orders.filter((o) => o.status === "FILLED" && o.filled_price);
  const chartData: ChartPoint[] = prices.map((p) => ({ timestamp: p.timestamp, price: p.price }));

  // Overlay trades on nearest price point
  for (const order of filledOrders) {
    const entry: ChartPoint = {
      timestamp: order.filled_at || order.created_at,
      price: order.filled_price!,
    };
    if (order.side === "BUY") entry.buy = order.filled_price!;
    else entry.sell = order.filled_price!;
    chartData.push(entry);
  }

  chartData.sort((a, b) => a.timestamp.localeCompare(b.timestamp));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Price Chart</h1>

      <div className="flex gap-2">
        {ranges.map((r) => (
          <button
            key={r.label}
            onClick={() => setHours(r.hours)}
            className={`rounded px-3 py-1 text-sm ${hours === r.hours ? "bg-zinc-700 text-zinc-100" : "bg-zinc-900 text-zinc-400"}`}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4" style={{ height: 500 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="timestamp"
              stroke="#71717a"
              tickFormatter={(t) => new Date(t).toLocaleTimeString()}
            />
            <YAxis stroke="#71717a" domain={["auto", "auto"]} tickFormatter={(v) => `$${v.toLocaleString()}`} />
            <Tooltip
              contentStyle={{ backgroundColor: "#18181b", border: "1px solid #3f3f46" }}
              labelFormatter={(t) => new Date(t).toLocaleString()}
              formatter={(v: number, name: string) => [`$${v.toLocaleString()}`, name]}
            />
            <Line type="monotone" dataKey="price" stroke="#a1a1aa" dot={false} strokeWidth={1.5} />
            <Scatter dataKey="buy" fill="#22c55e" shape="triangle" />
            <Scatter dataKey="sell" fill="#ef4444" shape="diamond" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add ui/src/app/prices/
git commit -m "feat: add price chart page with trade markers"
```

---

### Task 14: Predictions page

**Files:**
- Create: `ui/src/app/predictions/page.tsx`

**Step 1: Build predictions log page**

`ui/src/app/predictions/page.tsx`:
```typescript
"use client";

import { useEffect, useState } from "react";
import type { PredictionRecord, NewsRecord } from "@/lib/types";

interface PredictionWithNews extends PredictionRecord {
  news: NewsRecord[];
}

export default function PredictionsPage() {
  const [predictions, setPredictions] = useState<PredictionWithNews[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetch("/api/predictions?limit=100").then((r) => r.json()).then(setPredictions);
  }, []);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Predictions</h1>

      <div className="space-y-2">
        {predictions.map((p) => (
          <div key={p.id} className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <span className={`rounded px-2 py-0.5 text-sm font-medium ${
                  p.action === "BUY" ? "bg-green-950 text-green-400" :
                  p.action === "SELL" ? "bg-red-950 text-red-400" :
                  "bg-zinc-800 text-zinc-400"
                }`}>{p.action}</span>
                <span className="text-zinc-400">{p.product_id}</span>
                <span className="text-sm text-zinc-500">
                  Current: ${p.current_price.toFixed(2)} → Target: ${p.predicted_price?.toFixed(2) ?? "—"}
                </span>
              </div>
              <div className="flex items-center gap-4 text-sm text-zinc-500">
                <span>{p.model}</span>
                <span>{new Date(p.timestamp).toLocaleString()}</span>
              </div>
            </div>

            {p.reasoning && (
              <p className="mt-2 text-sm text-zinc-300">{p.reasoning}</p>
            )}

            {p.news.length > 0 && (
              <button onClick={() => toggle(p.id)} className="mt-2 text-xs text-zinc-500 hover:text-zinc-300">
                {expanded.has(p.id) ? "Hide" : "Show"} {p.news.length} headlines
              </button>
            )}

            {expanded.has(p.id) && (
              <ul className="mt-2 space-y-1 border-l-2 border-zinc-800 pl-3">
                {p.news.map((n) => (
                  <li key={n.id} className="text-sm text-zinc-400">{n.headline}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add ui/src/app/predictions/
git commit -m "feat: add predictions page with expandable news"
```

---

### Task 15: Final build verification and all-tests pass

**Step 1: Run all Python tests**

```bash
cd /Users/jac/Dev/src/coinbase_trading_bot && pytest tests/ -v
```
Expected: ALL PASS

**Step 2: Build Next.js dashboard**

```bash
cd ui && npm run build
```
Expected: Build succeeds

**Step 3: Final commit with any fixups**

If any adjustments were needed, commit them.

**Step 4: Update documentation**

Update `docs/architecture.md` with new components (PortfolioTracker, 4 new tables, UI).
Update `README.md` with UI setup instructions:

```markdown
## Dashboard UI

```bash
cd ui
npm install
npm run dev     # development at http://localhost:3000
```

Set `DB_PATH` in `ui/.env.local` to point at your `trading_bot.db`.
```

**Step 5: Commit docs**

```bash
git add docs/ README.md
git commit -m "docs: update architecture and README with dashboard UI"
```
