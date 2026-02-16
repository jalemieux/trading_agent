# Balance Pre-flight Check Design

**Date:** 2026-02-16
**Status:** Approved

## Problem

The bot places BUY orders without checking available USDC balance. When `trade_size_usd` exceeds the account's USDC, Coinbase rejects with `INSUFFICIENT_FUND`. This wastes API calls and produces failed orders with no actionable logging.

## Root Cause

`RiskManager.check()` validates policy limits (max order size, daily loss) but not account feasibility. `OrderManager` sends the order directly to Coinbase, relying on the exchange to reject.

## Design

### Approach: Cached Balance from PortfolioTracker

PortfolioTracker already fetches balances from Coinbase every ~2 min. Expose the latest quote balance as instance state. OrderManager reads it before placing buy orders.

```
PortfolioTracker                    OrderManager
┌──────────────┐                   ┌──────────────┐
│ take_snapshot │──updates──►      │ _handle_order │
│ quote_balance ◄──────────────────│   reads       │
└──────────────┘                   └──────────────┘
```

### Changes

**1. PortfolioTracker** — expose cached balance:
- Add `self._quote_balance = 0.0` in `__init__`
- Update it in `take_snapshot()` (already computes it)
- Add `@property quote_balance` getter

**2. OrderManager** — pre-flight check before buy:
- Accept `portfolio_tracker` in constructor
- Before placing buy, check `portfolio_tracker.quote_balance`
- If balance < $1.00 minimum → reject, log, publish OrderFailed
- If balance < quote_size → size down to available, log adjustment
- Pass adjusted size to `_place_market_order` (OrderRequest is frozen)

**3. main.py** — wire dependency:
- Pass `portfolio_tracker` to OrderManager constructor

**4. Tests** — three scenarios:
- Sufficient balance → order unchanged
- Partial balance → sized down
- Below minimum → rejected

### Why Not Other Approaches

- **Live API call per order:** Adds 200-500ms latency, rate limit risk, blocks event loop
- **EventBus balance event:** More moving parts for same result — PortfolioTracker already has the data

### Trade-offs

- Balance can be up to 2 min stale (acceptable — this is a safety net, not a real-time ledger)
- Minimum threshold ($1.00) prevents dust orders that aren't worth the fees
