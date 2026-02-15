# Coinbase Trading Bot - Design Document

**Date:** 2026-02-14
**Status:** Approved

## Goal

Build trading plumbing that enables an agent to buy, hold, and sell positions on Coinbase for any tradable pair. The bot runs as a long-lived process with real-time market data. A Claude-powered price prediction strategy will be layered on later.

## Architecture: Modular Graph

Components are independent nodes connected via an async event bus. Each node is independently testable and reusable.

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
     ┌────────▼────────┐
     │ Coinbase Client  │
     │ (SDK wrapper)    │
     └──────────────────┘
```

## Components

| Component | Responsibility | Subscribes To | Publishes |
|-----------|---------------|---------------|-----------|
| CoinbaseClient | SDK wrapper for REST + WebSocket | - | Raw API responses |
| MarketData | Real-time prices via WebSocket, candles via REST | - | PriceUpdate |
| OrderManager | Places/cancels orders, tracks order lifecycle | OrderRequest | OrderFilled, OrderFailed |
| RiskManager | Validates trades against limits before execution | OrderRequest | RiskViolation |
| PositionTracker | Tracks open positions, P&L, persists to SQLite | OrderFilled | PositionChanged |
| KillSwitch | Emergency stop - halts all trading | RiskViolation, manual | KillSwitch |
| Strategy (future) | Claude prediction node | PriceUpdate | OrderRequest |

## Trade Flow

```
Strategy emits OrderRequest
    -> RiskManager intercepts, checks limits
        -> If OK: OrderManager places order via CoinbaseClient
            -> Coinbase confirms -> OrderFilled
                -> PositionTracker updates DB + emits PositionChanged
        -> If NOT OK: RiskViolation emitted, order blocked
```

## Data Model (SQLite)

### positions
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| product_id | TEXT | e.g., BTC-USD |
| side | TEXT | LONG/SHORT |
| entry_price | REAL | Average entry price |
| quantity | REAL | Amount held |
| status | TEXT | OPEN/CLOSED |
| realized_pnl | REAL | Realized profit/loss |
| opened_at | TIMESTAMP | UTC |
| closed_at | TIMESTAMP | UTC, nullable |

### orders
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| position_id | TEXT FK | References positions.id |
| product_id | TEXT | e.g., BTC-USD |
| side | TEXT | BUY/SELL |
| type | TEXT | MARKET/LIMIT |
| price | REAL | Requested price (limit orders) |
| quantity | REAL | Requested quantity |
| status | TEXT | PENDING/FILLED/CANCELLED/FAILED |
| coinbase_id | TEXT | Coinbase order ID |
| filled_price | REAL | Actual fill price |
| filled_qty | REAL | Actual fill quantity |
| fee | REAL | Fee charged |
| created_at | TIMESTAMP | UTC |
| filled_at | TIMESTAMP | UTC, nullable |

### daily_summary
| Column | Type | Description |
|--------|------|-------------|
| date | DATE PK | Trading date |
| total_pnl | REAL | Realized P&L for the day |
| num_trades | INTEGER | Number of trades |
| fees_paid | REAL | Total fees |
| halted | BOOLEAN | Whether kill switch activated |

## Risk Management

Order validation pipeline:

```
OrderRequest arrives
    -> Kill switch active? -> YES -> BLOCK
    -> Order size <= MAX_ORDER_SIZE_USD? -> NO -> BLOCK
    -> Daily P&L <= MAX_DAILY_LOSS_USD? -> NO -> ACTIVATE KILL SWITCH
    -> APPROVED -> Forward to OrderManager
```

### Kill Switch Behavior
- Blocks all new orders
- Does NOT auto-close existing positions
- Persists across restarts (stored in DB)
- Toggled via CLI command

### Configurable Limits
- `MAX_ORDER_SIZE_USD` - Max dollar value per order
- `MAX_DAILY_LOSS_USD` - Daily loss threshold for kill switch
- `KILL_SWITCH` - Manual override

## Project Structure

```
coinbase_trading_bot/
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── config.py               # Pydantic settings
│   ├── event_bus.py            # Async pub/sub
│   ├── events.py               # Event dataclasses
│   ├── coinbase_client.py      # SDK wrapper
│   ├── market_data.py          # WebSocket price feeds
│   ├── order_manager.py        # Order placement/tracking
│   ├── risk_manager.py         # Limit validation
│   ├── position_tracker.py     # Position + P&L management
│   ├── kill_switch.py          # Emergency halt
│   └── db.py                   # SQLite setup
├── tests/
├── docs/
├── pyproject.toml
├── .env.example
└── README.md
```

## Tech Stack

- **Python 3.12+** with asyncio
- **coinbase-advanced-py** - Official Coinbase SDK
- **aiosqlite** - Async SQLite
- **pydantic** - Config validation and event schemas
- **pytest + pytest-asyncio** - Testing

## Coinbase API Details

- **REST:** `api.coinbase.com/api/v3/brokerage/*`
- **WebSocket:** Real-time level2, matches, ticker channels
- **Auth:** CDP API Keys (ES256 format, HMAC-SHA256 signatures)
- **Rate Limits:** 30 req/s private, 10 req/s public
- **Fees:** ~0.25% maker / 0.40% taker at entry tier

## Testing Strategy

- Unit tests for each node with mocked event bus and Coinbase client
- Integration tests with real event bus but mocked Coinbase responses
- Critical test scenarios:
  1. Full order flow: request -> risk check -> place -> fill -> position update
  2. Order exceeds max size -> blocked
  3. Daily loss exceeded -> kill switch activates
  4. Kill switch blocks all subsequent orders
  5. Correct P&L calculation on partial fills
  6. WebSocket reconnection on disconnect
