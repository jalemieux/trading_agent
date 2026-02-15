# Architecture

Reference: [Design Document](plans/2026-02-14-coinbase-trading-bot-design.md)

## Component Diagram

```
                         Event Bus (asyncio pub/sub)
    ┌──────────┬──────────┬──────────┬──────────┬──────────┐
    │          │          │          │          │          │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼─────┐
│Market │ │Order  │ │Risk   │ │Pos.   │ │Kill   │ │Strategy │
│Data   │ │Mgr    │ │Mgr    │ │Track  │ │Switch │ │(future) │
└───┬───┘ └───┬───┘ └───────┘ └───┬───┘ └───────┘ └─────────┘
    │         │                    │
    └─────────┴────────────────────┘
              │
     ┌────────▼────────┐       ┌──────────┐
     │ Coinbase Client  │       │  SQLite   │
     │ (SDK wrapper)    │       │    DB     │
     └──────────────────┘       └──────────┘
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
| Smoke Test | `scripts/smoke_test.py` | Interactive live plumbing validation — buy/sell/hold lifecycle | -- | -- |

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

## Risk Pipeline

```
OrderRequest arrives
    │
    ├─ Kill switch active?
    │   └─ YES ──► BLOCK (RiskViolation)
    │
    ├─ Order size > MAX_ORDER_SIZE_USD?
    │   └─ YES ──► BLOCK (RiskViolation)
    │
    ├─ Daily P&L loss > MAX_DAILY_LOSS_USD?
    │   └─ YES ──► ACTIVATE kill switch + BLOCK
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
