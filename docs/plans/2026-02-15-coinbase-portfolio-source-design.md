# Design: Coinbase-Sourced Portfolio Value

**Date**: 2026-02-15
**Status**: Approved

## Problem

PortfolioTracker computes `total_value_usd` from local DB tables (positions + price_history). This is not the source of truth — Coinbase is. The local calculation can drift from actual account balances due to missed fills, manual trades, deposits, etc.

## Decision

**Option A: PortfolioTracker calls Coinbase directly.**

Inject `CoinbaseClient` into `PortfolioTracker`. On each snapshot cycle, call `get_accounts()` to fetch real balances for bot-traded currencies. Keep local PnL calculations for performance analytics.

## Scope

- Bot-traded assets only (base + quote currency from `product_id`, e.g., SOL + USDC)
- Keep `unrealized_pnl` and `realized_pnl_cumulative` from local positions DB
- Remove dead columns: `position_value_usd`, `num_open_positions`

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  PortfolioTracker                        │
│                                                         │
│  take_snapshot()                                        │
│    │                                                    │
│    ├── CoinbaseClient.get_accounts()                    │
│    │     → filter to traded currencies (SOL, USDC)      │
│    │     → base_balance × current_price + quote_balance │
│    │     → total_value_usd (Coinbase source of truth)   │
│    │                                                    │
│    ├── Local positions DB (unchanged)                   │
│    │     → unrealized_pnl                               │
│    │     → realized_pnl_cumulative                      │
│    │                                                    │
│    └── Write snapshot to portfolio_snapshots             │
└─────────────────────────────────────────────────────────┘
```

## Changes

### `PortfolioTracker.__init__`

Add `coinbase: CoinbaseClient` and `product_id: str` params. Extract base/quote currencies from product_id (e.g., `SOL-USDC` → `SOL`, `USDC`).

### `PortfolioTracker.take_snapshot`

Replace local position-value calculation with:

1. Call `coinbase.get_accounts()` (sync — run in executor)
2. Filter to base + quote currencies
3. Base currency: `balance × latest_price` (from local `price_history`)
4. Quote currency: `balance` directly (USD-equivalent)
5. `total_value_usd = base_value + quote_value`
6. Keep `unrealized_pnl` and `realized_pnl_cumulative` from local positions

### `portfolio_snapshots` table

Remove columns:
- `position_value_usd` — dead (was locally-computed, not used by dashboard)
- `num_open_positions` — dead (not used by dashboard)

### `src/main.py`

Pass `coinbase` and `product_id` to PortfolioTracker constructor.

### Dashboard (`ui/src/lib/types.ts`)

Remove `position_value_usd` and `num_open_positions` from `PortfolioSnapshot` type.

### Tests

Rewrite `test_portfolio_tracker.py` to mock `CoinbaseClient.get_accounts()`.

## Error Handling

If `get_accounts()` fails, log error and skip snapshot. No fallback to local calculation — a gap in snapshots is better than inaccurate data.

## Price Conversion

Use latest price from local `price_history` (populated by WebSocket ticker). Avoids extra API call; price is fresh (updated every tick).
