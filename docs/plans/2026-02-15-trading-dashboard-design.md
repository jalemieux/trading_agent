# Trading Dashboard Design

## Problem

The bot persists trade/position/P&L data but has no UI to monitor it. Critical data is lost on restart (price ticks, predictions, news). No way to track portfolio evolution over time.

## Solution

Two-part change:

1. **Python side:** Add 4 new DB tables to persist historical data the bot currently discards
2. **UI side:** Next.js + TypeScript dashboard reading SQLite directly (read-only)

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Python Bot (existing)               │
│                                                      │
│  MarketData ──→ PriceBuffer ──→ Strategy ──→ Orders  │
│       │              │              │                 │
│       ▼              ▼              ▼                 │
│  ┌─────────────────────────────────────────────┐     │
│  │           SQLite DB (trading_bot.db)         │     │
│  │                                              │     │
│  │  [positions] [orders] [daily_summary]        │     │
│  │  [kill_switch]                               │     │
│  │  [price_history]       ◄── NEW               │     │
│  │  [predictions]         ◄── NEW               │     │
│  │  [news_history]        ◄── NEW               │     │
│  │  [portfolio_snapshots] ◄── NEW               │     │
│  └──────────────────────┬──────────────────────┘     │
└─────────────────────────┼────────────────────────────┘
                          │ read-only
                          ▼
┌─────────────────────────────────────────────────────┐
│              Next.js Dashboard (ui/)                 │
│                                                      │
│  API Routes (read-only SQLite via better-sqlite3):   │
│  /api/positions   /api/orders    /api/prices         │
│  /api/predictions /api/summary   /api/portfolio      │
│                                                      │
│  Pages:                                              │
│  /             Overview (live P&L, positions, status) │
│  /portfolio    Equity curve + returns                │
│  /positions    Position history table                │
│  /orders       Order log with filters                │
│  /prices       Price chart + trade markers           │
│  /predictions  Prediction decision log + news        │
└─────────────────────────────────────────────────────┘
```

## New Database Tables

### price_history

Stores every WebSocket price tick. Written by MarketData on each PriceUpdate event.

```sql
CREATE TABLE price_history (
    product_id TEXT NOT NULL,
    price REAL NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX idx_price_history_product_time ON price_history(product_id, timestamp);
```

### predictions

Logs each Claude prediction decision. Written by ClaudePredictionStrategy after each evaluation.

```sql
CREATE TABLE predictions (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    action TEXT NOT NULL,          -- BUY, SELL, HOLD
    predicted_price REAL,
    current_price REAL NOT NULL,
    confidence REAL,
    reasoning TEXT,
    model TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX idx_predictions_time ON predictions(timestamp);
```

### news_history

Headlines fetched per prediction cycle. FK to predictions.

```sql
CREATE TABLE news_history (
    id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL,
    headline TEXT NOT NULL,
    source TEXT,
    sentiment TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
);
CREATE INDEX idx_news_prediction ON news_history(prediction_id);
```

### portfolio_snapshots

Periodic portfolio state snapshots (every ~5 min). Written by a new PortfolioTracker component.

```sql
CREATE TABLE portfolio_snapshots (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    total_value_usd REAL NOT NULL,
    position_value_usd REAL NOT NULL,
    realized_pnl_cumulative REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    num_open_positions INTEGER NOT NULL
);
CREATE INDEX idx_portfolio_time ON portfolio_snapshots(timestamp);
```

## Data Flow for New Tables

```
PriceUpdate event
    ├──→ PriceBuffer (existing, in-memory)
    └──→ price_history table (NEW)

ClaudePredictionStrategy._evaluate()
    ├──→ OrderRequest event (existing)
    ├──→ predictions table (NEW)
    └──→ news_history table (NEW)

Every 5 min (PortfolioTracker)
    ├──→ Read open positions from DB
    ├──→ Get current price from latest price_history
    ├──→ Compute total_value, unrealized_pnl
    └──→ INSERT into portfolio_snapshots
```

## Dashboard Pages

| Page | Route | Content |
|------|-------|---------|
| Overview | `/` | Current price, open position with unrealized P&L, daily P&L, trade count, fees, kill switch status, daily loss limit gauge |
| Portfolio | `/portfolio` | Equity curve (total value over time), realized vs unrealized P&L, drawdown, daily/weekly/monthly returns, time range selector |
| Positions | `/positions` | Table of all positions (open/closed), entry/exit price, P&L, duration, sortable/filterable |
| Orders | `/orders` | Full order log with status, fill details, slippage, fees |
| Price Chart | `/prices` | Line chart of price history, time range selector, buy/sell markers overlaid |
| Predictions | `/predictions` | Log of every Claude decision — action, reasoning, confidence, expandable news headlines |

## Tech Stack (UI)

- **Next.js 14+** with App Router, TypeScript
- **better-sqlite3** for read-only DB access in API routes
- **Tailwind CSS** for styling
- **Recharts** for charts (price, equity curve, P&L)
- **Dark theme** throughout
- **Auto-refresh** via polling (5-10s) on overview page

## Data Access Pattern

Bot writes → SQLite ← UI reads (read-only). No concurrent write conflicts. better-sqlite3 uses WAL mode by default, safe for concurrent readers.

## New Python Component

**PortfolioTracker** — subscribes to a timer/price events, periodically snapshots portfolio state into `portfolio_snapshots` table. Follows existing component pattern (constructor injection + `register(bus)`).
