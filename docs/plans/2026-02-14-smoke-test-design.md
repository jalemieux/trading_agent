# Smoke Test Script Design

## Purpose

Interactive CLI script (`scripts/smoke_test.py`) that validates the full trading bot plumbing against the live Coinbase API. Walks through staged checks — connectivity, market data, buy, hold, sell — with user confirmation at each step.

## Architecture

Reuses all existing components wired through the real EventBus:

```
smoke_test.py
  │
  load .env → Settings
  │
  ├── Database (smoke_test.db)
  ├── EventBus
  ├── CoinbaseClient (real API)
  ├── KillSwitch
  ├── RiskManager
  ├── OrderManager (subscribed to OrderRequest)
  └── PositionTracker (subscribed to OrderFilled)
```

Orders flow through the same event-driven path a strategy would use: publish `OrderRequest` → `OrderManager` validates via `RiskManager` → places order via `CoinbaseClient` → publishes `OrderFilled` → `PositionTracker` updates position.

## Stages

| # | Stage | Actions | Validates |
|---|-------|---------|-----------|
| 1 | Connectivity | `get_accounts()`, `get_product("SOL-USDC")` | API keys, product exists |
| 2 | Market Data | Subscribe ticker WebSocket, show 3-5 live prices | WebSocket, price parsing |
| 3 | Buy | Market buy ~$1 USD SOL via `OrderRequest` event | Order placement, fill tracking, position opened |
| 4 | Verify Position | Query DB for open position | Position tracker, DB persistence |
| 5 | Hold | Display position state, pause | Position remains open |
| 6 | Sell | Market sell all SOL via `OrderRequest` event | Sell execution, position close, P&L calc |
| 7 | Summary | Show realized P&L, fees, final balances | End-to-end lifecycle |

## Safety Controls

- Hardcoded $1 trade size
- `MAX_ORDER_SIZE_USD=10` safety cap
- Separate `smoke_test.db` database
- User confirmation (`Enter/q`) before each stage
- Graceful error handling — fail and offer to continue or quit

## Design Decisions

- **Real EventBus flow**: validates actual wiring, not just API calls
- **Market orders only**: simplest path for smoke testing
- **Single pair (SOL-USDC)**: configurable via constant
- **ANSI colored output**: green/red/yellow for pass/fail/info, no extra deps
- **Each stage is a function**: independently testable, skippable

## Out of Scope

- Strategy logic
- Limit orders
- Concurrent orders
- Coinbase state cleanup
