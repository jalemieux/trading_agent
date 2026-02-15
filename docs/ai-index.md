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
price_buffer.py    ← events
news_service.py    ← no internal deps (wraps openai SDK)
claude_predictor.py← events (wraps anthropic SDK)
claude_price_only_predictor.py ← claude_predictor, events (wraps anthropic SDK)
strategy_news_prediction.py ← price_buffer, news_service, claude_predictor, config, db, event_bus, events
strategy_price_only.py ← price_buffer, claude_price_only_predictor, config, db, event_bus, events
main.py            ← all of the above (conditional imports based on strategy config)
```

## Event Routing Table

```
EventBus subscriptions (registered in main.py):

OrderRequest   → OrderManager._handle_order_request
OrderFilled    → PositionTracker._handle_order_filled
PriceUpdate    → PriceOnlyStrategy._on_price (default) or NewsPredictionStrategy._on_price

Published by:
OrderRequest      — published by PriceOnlyStrategy or NewsPredictionStrategy (BUY/SELL decisions)
PriceUpdate       — published by MarketData

Not subscribed (published only):
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
├── market_data.py:63        MarketData — WebSocket ticker
├── price_buffer.py:25        PriceBuffer — in-memory ring buffer per product
├── news_service.py:39        NewsService — Grok xAI news/sentiment client
├── claude_predictor.py:84    ClaudePredictor — Claude API predictions (news strategy)
├── claude_price_only_predictor.py:68  ClaudePriceOnlyPredictor — Claude API price-only predictions
├── strategy_news_prediction.py:153  NewsPredictionStrategy — timer-based AI strategy (price + news)
└── strategy_price_only.py:148  PriceOnlyStrategy — timer-based AI strategy (price only)

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
├── test_integration.py      2 tests
├── test_price_buffer.py     5 tests
├── test_news_service.py     2 tests
├── test_claude_predictor.py 4 tests
├── test_config_prediction.py 3 tests
├── test_claude_price_only_predictor.py 5 tests
├── test_strategy_news_prediction.py 8 tests
└── test_strategy_price_only.py 7 tests
                             ── 82 total
```
