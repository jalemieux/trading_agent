# Architecture

Reference: [Design Document](plans/2026-02-14-coinbase-trading-bot-design.md)

## Component Diagram

```
                         Event Bus (asyncio pub/sub)
    ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
    │          │          │          │          │          │          │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼─────┐ ┌──▼──────┐
│Market │ │Order  │ │Risk   │ │Pos.   │ │Kill   │ │Strategy │ │Portfol. │
│Data   │ │Mgr    │ │Mgr    │ │Track  │ │Switch │ │(select) │ │Tracker  │
└───┬───┘ └───┬───┘ └───────┘ └───┬───┘ └───────┘ └────┬────┘ └────┬────┘
                                                        │           │
                                         ┌──────────────┤           │
                                         │              │           │
                                  ┌──────▼───────┐ ┌───▼──────────┐│
                                  │ PriceOnly    │ │ News         ││
                                  │ Strategy     │ │ Strategy     ││
                                  └──────┬───────┘ └───┬──────────┘│
                                         │             │           │
                                    ┌────▼──┐    ┌────▼──┬───▼───┐│
                                    │Price  │    │Price  │Claude ││
                                    │Only   │    │Buffer │Predict││
                                    │Predict│    │       │+ News ││
                                    └───────┘    └───────┴───────┘│
    │         │                    │               │
    └─────────┴────────────────────┴───────────────┘
              │
     ┌────────▼────────┐       ┌──────────┐       ┌──────────────┐
     │ Coinbase Client  │       │  SQLite   │◄──────│ Next.js UI   │
     │ (SDK wrapper)    │       │    DB     │       │ (read-only)  │
     └──────────────────┘       └──────────┘       └──────────────┘
```

## Components

| Component | File | Responsibility | Subscribes To | Publishes |
|-----------|------|----------------|---------------|-----------|
| EventBus | `event_bus.py` | Async pub/sub, routes events by type | -- | -- |
| MarketData | `market_data.py` | WebSocket ticker -> price events | -- | `PriceUpdate` |
| OrderManager | `order_manager.py` | Places orders via CoinbaseClient, tracks fills | `OrderRequest` | `OrderFilled`, `OrderFailed` |
| RiskManager | `risk_manager.py` | Validates orders against limits | Called by OrderManager | `RiskViolation`, `KillSwitchActivated` |
| PositionTracker | `position_tracker.py` | Manages positions, computes P&L, writes daily summary | `OrderFilled` | `PositionChanged` |
| KillSwitch | `kill_switch.py` | Emergency stop, persisted to DB | -- | `KillSwitchActivated` |
| CoinbaseClient | `coinbase_client.py` | Wraps coinbase-advanced-py SDK (REST + WebSocket) | -- | -- |
| Database | `db.py` | SQLite schema, connection management | -- | -- |
| Config | `config.py` | Pydantic settings loaded from `.env` | -- | -- |
| PriceBuffer | `price_buffer.py` | In-memory rolling buffer of recent prices | `PriceUpdate` | -- |
| ClaudePredictor | `claude_predictor.py` | Calls Claude API with price + news context to predict BTC targets | -- | -- |
| NewsService | `news_service.py` | Fetches crypto news/sentiment via Grok API (xAI) | -- | -- |
| NewsPredictionStrategy | `strategy_news_prediction.py` | Orchestrates prediction cycle: gathers prices + news, calls ClaudePredictor, emits OrderRequests | `PriceUpdate` | `OrderRequest` |
| PriceOnlyStrategy | `strategy_price_only.py` | Orchestrates prediction cycle: uses price history only (no news), calls ClaudePriceOnlyPredictor, emits OrderRequests | `PriceUpdate` | `OrderRequest` |
| ClaudePriceOnlyPredictor | `claude_price_only_predictor.py` | Calls Claude API with price history only (no news) to predict BTC targets | -- | -- |
| PortfolioTracker | `portfolio_tracker.py` | Periodic snapshots of portfolio value, P&L, and positions | -- | -- |
| Smoke Test | `scripts/smoke_test.py` | Interactive live plumbing validation — buy/sell/hold lifecycle | -- | -- |
| Dashboard UI | `ui/` | Next.js TypeScript dashboard — reads SQLite DB read-only, 6 pages | -- | -- |

## Event Flow

### Order Lifecycle

```
Strategy/Manual
      │
      ▼
 OrderRequest
      │
      ▼
 OrderManager ──► RiskManager.validate()
      │                │
      │           ┌────┴─────┐
      │           │          │
      │        APPROVED   REJECTED
      │           │          │
      │           ▼          ▼
      │    CoinbaseClient  RiskViolation
      │           │        (+ KillSwitchActivated
      │           ▼          if daily loss exceeded)
      │      OrderFilled
      │        or OrderFailed
      │           │
      ▼           ▼
 PositionTracker
      │
      ▼
 PositionChanged
```

### Event Types

| Event | Dataclass | Key Fields |
|-------|-----------|------------|
| `PriceUpdate` | `events.py` | `product_id`, `price`, `timestamp` |
| `OrderRequest` | `events.py` | `product_id`, `side`, `order_type`, `quote_size`/`base_size`, `limit_price` |
| `OrderFilled` | `events.py` | `order_id`, `filled_price`, `filled_qty`, `fee`, `coinbase_order_id` |
| `OrderFailed` | `events.py` | `order_id`, `reason` |
| `RiskViolation` | `events.py` | `order_id`, `reason` |
| `PositionChanged` | `events.py` | `position_id`, `product_id`, `side`, `quantity`, `entry_price`, `status` |
| `KillSwitchActivated` | `events.py` | `reason` |

## Data Model (SQLite)

### positions

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| product_id | TEXT | e.g., BTC-USD |
| side | TEXT | LONG / SHORT |
| entry_price | REAL | Average entry |
| quantity | REAL | Amount held |
| status | TEXT | OPEN / CLOSED |
| realized_pnl | REAL | Realized P&L |
| opened_at | TIMESTAMP | UTC |
| closed_at | TIMESTAMP | Nullable |

### orders

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| position_id | TEXT FK | -> positions.id |
| product_id | TEXT | e.g., BTC-USD |
| side | TEXT | BUY / SELL |
| type | TEXT | MARKET / LIMIT |
| price | REAL | Requested price |
| quantity | REAL | Requested quantity |
| status | TEXT | PENDING / FILLED / CANCELLED / FAILED |
| coinbase_id | TEXT | Coinbase order ID |
| filled_price | REAL | Actual fill price |
| filled_qty | REAL | Actual fill quantity |
| fee | REAL | Fee charged |
| created_at | TIMESTAMP | UTC |
| filled_at | TIMESTAMP | Nullable |

### daily_summary

| Column | Type | Description |
|--------|------|-------------|
| date | DATE PK | Trading date |
| total_pnl | REAL | Realized P&L for the day |
| num_trades | INTEGER | Trade count |
| fees_paid | REAL | Total fees |
| halted | BOOLEAN | Kill switch activated |

### kill_switch

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Always 1 (singleton) |
| active | BOOLEAN | Current state |
| reason | TEXT | Why it was activated |
| activated_at | TIMESTAMP | When activated |

### price_history

| Column | Type | Description |
|--------|------|-------------|
| product_id | TEXT | e.g., BTC-USD |
| price | REAL | Tick price |
| timestamp | TEXT | ISO 8601 UTC |

Indexed: `(product_id, timestamp)`

### predictions

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| product_id | TEXT | e.g., BTC-USD |
| action | TEXT | BUY / SELL / HOLD |
| predicted_price | REAL | Target price |
| current_price | REAL | Price at prediction time |
| confidence | REAL | Abs % difference |
| reasoning | TEXT | Model reasoning |
| model | TEXT | Model name |
| timestamp | TEXT | ISO 8601 UTC |

### news_history

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| prediction_id | TEXT FK | -> predictions.id |
| headline | TEXT | News headline |
| source | TEXT | Source (nullable) |
| sentiment | TEXT | Sentiment (nullable) |
| timestamp | TEXT | ISO 8601 UTC |

### portfolio_snapshots

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| timestamp | TEXT | ISO 8601 UTC |
| total_value_usd | REAL | Total portfolio value (from Coinbase account balances) |
| realized_pnl_cumulative | REAL | Cumulative realized P&L |
| unrealized_pnl | REAL | Unrealized P&L |

## Risk Pipeline

```
OrderRequest arrives
    │
    ├─ 1. Kill switch active?
    │   └─ YES ──► BLOCK (RiskViolation)
    │
    ├─ 2. Daily P&L loss > MAX_DAILY_LOSS_USD?
    │   └─ YES ──► ACTIVATE kill switch + BLOCK
    │
    ├─ 3. Order size > MAX_ORDER_SIZE_USD? (BUY only)
    │   └─ YES ──► BLOCK (RiskViolation)
    │
    └─ All checks pass ──► APPROVED (forward to CoinbaseClient)
```

### Configurable Limits

| Setting | Env Variable | Default | Description |
|---------|-------------|---------|-------------|
| Max order size | `MAX_ORDER_SIZE_USD` | $100 | Per-order dollar limit |
| Daily loss limit | `MAX_DAILY_LOSS_USD` | $500 | Triggers kill switch |
| Kill switch | Manual via DB | off | Blocks all new orders |

## Changelog

- **2026-02-14** -- Initial architecture: EventBus, MarketData, OrderManager, RiskManager, PositionTracker, KillSwitch, Database, Config. 48 tests.
- **2026-02-14** -- Added interactive smoke test script (`scripts/smoke_test.py`) for live plumbing validation.
- **2026-02-14** -- Added PriceBuffer, NewsService (Grok API), ClaudePredictor (Anthropic API), and ClaudePredictionStrategy. 69 tests.
- **2026-02-15** -- Added PriceOnlyStrategy and ClaudePriceOnlyPredictor for price-only predictions (no news). Renamed ClaudePredictionStrategy to NewsPredictionStrategy. Added `strategy` config field to switch between `price_only` and `news`. 82 tests.
- **2026-02-15** -- Added `coinbase_key_file` and `product_id` config fields. CoinbaseClient and MarketData support key file auth. MarketData resolves product IDs by base currency. OrderManager polls for fill details (5 attempts). Fixed risk pipeline check order in docs.
- **2026-02-15** -- Added 4 new DB tables (price_history, predictions, news_history, portfolio_snapshots), PortfolioTracker component, price tick persistence in MarketData, prediction/news logging, and Next.js dashboard UI with 6 pages.
- **2026-02-15** -- PortfolioTracker now sources total_value_usd from Coinbase account balances via get_accounts() instead of computing from local positions. Removed dead columns position_value_usd and num_open_positions from portfolio_snapshots schema and TS types. 89 tests.
