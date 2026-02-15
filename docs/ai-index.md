# AI Documentation Index

## Quick Links

- [Component Reference](ai-components.md) — constructor signatures, methods, dependencies, internal state for every class
- [Event & Data Reference](ai-data.md) — event schemas, DB schemas, SQL queries used, state machines
- [Execution Traces](ai-traces.md) — step-by-step execution paths for every flow, with file:line references
- [Troubleshooting](ai-troubleshooting.md) — known failure modes, symptoms, root causes, fixes
- [Extension Guide](ai-extending.md) — how to add strategies, events, components, DB tables

## System Summary

Async event-driven trading bot. Single-process, single-threaded asyncio. Components communicate via typed events on a shared EventBus. SQLite for persistence. Coinbase Advanced Trade API for execution.

Entry point: `src/main.py` → `asyncio.run(main())`

Run: `python -m src.main`
Test: `pytest tests/ -v`

## Dependency Graph (import order)

```
config.py          ← no internal deps
event_bus.py       ← no internal deps
events.py          ← no internal deps
db.py              ← no internal deps
kill_switch.py     ← db, event_bus, events
risk_manager.py    ← config, db, event_bus, events, kill_switch
coinbase_client.py ← no internal deps (wraps coinbase SDK)
order_manager.py   ← coinbase_client, db, event_bus, events, risk_manager
position_tracker.py← db, event_bus, events
market_data.py     ← event_bus, events (wraps coinbase SDK)
main.py            ← all of the above
```

## Event Routing Table

```
EventBus subscriptions (registered in main.py):

OrderRequest   → OrderManager._handle_order_request
OrderFilled    → PositionTracker._handle_order_filled

Not subscribed (published only):
PriceUpdate       — published by MarketData, no consumer yet (strategy layer)
OrderFailed       — published by OrderManager, no consumer yet
RiskViolation     — published by RiskManager, no consumer yet
PositionChanged   — published by PositionTracker, no consumer yet
KillSwitchActivated — published by KillSwitch, no consumer yet
```

## File Map

```
src/
├── __init__.py              empty
├── main.py:91               entry point, component wiring, signal handlers
├── config.py:12             Settings(BaseSettings) — env vars
├── event_bus.py:27          EventBus — subscribe/unsubscribe/publish
├── events.py:63             7 frozen dataclasses
├── db.py:81                 Database — aiosqlite wrapper + schema
├── kill_switch.py:42        KillSwitch — activate/deactivate/initialize
├── risk_manager.py:62       RiskManager — check(order) → bool
├── coinbase_client.py:53    CoinbaseClient — SDK wrapper
├── order_manager.py:138     OrderManager — order lifecycle
├── position_tracker.py:175  PositionTracker — P&L tracking
└── market_data.py:63        MarketData — WebSocket ticker

tests/
├── test_event_bus.py        5 tests
├── test_events.py           8 tests
├── test_db.py               5 tests
├── test_kill_switch.py      5 tests
├── test_risk_manager.py     5 tests
├── test_coinbase_client.py  7 tests
├── test_order_manager.py    5 tests
├── test_position_tracker.py 4 tests
├── test_market_data.py      2 tests
└── test_integration.py      2 tests
                             ── 48 total
```
