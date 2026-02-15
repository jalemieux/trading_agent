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

Run: `python -m src.main --strategy price_only --llm anthropic --model claude-opus-4-6`
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
prediction.py      ← no internal deps
llm_client.py      ← no internal deps (wraps anthropic + groq + openai SDKs)
strategy.py        ← config, db, event_bus, events, prediction, price_buffer
strategies/price_only.py ← llm_client, prediction, price_buffer, strategy
strategies/news.py ← llm_client, news_service, prediction, strategy
registry.py        ← llm_client, strategies/news, strategies/price_only
run_reporter.py    ← db (queries daily_summary, portfolio_snapshots, positions)
main.py            ← all of the above (CLI args select strategy + LLM provider via registry)
```

## Event Routing Table

```
EventBus subscriptions (registered in main.py):

OrderRequest   → OrderManager._handle_order_request
OrderFilled    → PositionTracker._handle_order_filled
PriceUpdate    → Strategy._on_price (base class; PriceOnlyStrategy or NewsPredictionStrategy)

Published by:
OrderRequest      — published by Strategy._evaluate() (BUY/SELL decisions from any strategy)
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
├── main.py:174              entry point, CLI args, component wiring, strategy selection, signal handlers
├── config.py:25             Settings(BaseSettings) — env vars (API keys, trading params)
├── event_bus.py:26          EventBus — subscribe/unsubscribe/publish
├── events.py:63             7 frozen dataclasses
├── db.py:80                 Database — aiosqlite wrapper + schema
├── kill_switch.py:41        KillSwitch — activate/deactivate/initialize
├── risk_manager.py:61       RiskManager — check(order) → bool
├── coinbase_client.py:55    CoinbaseClient — SDK wrapper (key_file or key/secret auth)
├── order_manager.py:155     OrderManager — order lifecycle + fill polling
├── position_tracker.py:174  PositionTracker — P&L tracking
├── market_data.py:79        MarketData — WebSocket ticker + product ID resolution
├── price_buffer.py:25       PriceBuffer — in-memory ring buffer per product
├── news_service.py:41       NewsService — Grok xAI news/sentiment client
├── prediction.py:37         Prediction dataclass + parse_prediction() helper
├── llm_client.py:56         LLMClient protocol + AnthropicLLMClient + GroqLLMClient + OpenAICompatibleLLMClient
├── strategy.py:158          Strategy ABC — shared timer loop, evaluation, position checks
├── registry.py:30           STRATEGIES + LLM_PROVIDERS registries
├── run_reporter.py:145      RunReporter — hourly CSV performance reporting + git push
├── strategies/
│   ├── __init__.py          empty
│   ├── price_only.py:57     PriceOnlyStrategy(Strategy) — price-only prompts + LLMClient
│   └── news.py:115          NewsPredictionStrategy(Strategy) — price+news prompts + LLMClient

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
├── test_prediction.py       2 tests
├── test_llm_client.py       8 tests
├── test_config.py           2 tests
├── test_config_prediction.py 3 tests
├── test_strategy_base.py    tests for Strategy ABC
├── test_strategies_price_only.py  tests for PriceOnlyStrategy
├── test_strategies_news.py  tests for NewsPredictionStrategy
├── test_registry.py         tests for registry
├── test_portfolio_tracker.py  tests for PortfolioTracker
└── test_run_reporter.py     7 tests for RunReporter
                             ── 108 total
```
