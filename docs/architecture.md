# Architecture

Reference: [Design Document](plans/2026-02-14-coinbase-trading-bot-design.md)

## Component Diagram

```
                         Event Bus (asyncio pub/sub)
    ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
    │          │          │          │          │          │          │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼─────┐ ┌──▼──────┐
│Market │ │Order  │ │Risk   │ │Pos.   │ │Kill   │ │Strategy │ │Portfol. │
│Data   │ │Mgr    │ │Mgr    │ │Track  │ │Switch │ │  ABC    │ │Tracker  │
└───┬───┘ └───┬───┘ └───────┘ └───┬───┘ └───────┘ └────┬────┘ └────┬────┘
                                                        │           │
                                  ┌─────────────────────┤           │
                                  │                     │           │
                           ┌──────▼───────┐  ┌─────────▼──────┐    │
                           │ PriceOnly    │  │ News           │    │
                           │ Strategy     │  │ Strategy       │    │
                           └──────┬───────┘  └───┬────────────┘    │
                                  │              │                  │
    │         │                   │         ┌────▼────┐             │
    └─────────┴───────────────────┤         │ News    │             │
              │                   │         │ Service │             │
     ┌────────▼────────┐     ┌────▼─────────┴─▼───┐                │
     │ Coinbase Client  │     │     LLMClient      │                │
     │ (SDK wrapper)    │     │ ┌──────┐┌────┐┌───┐│                │
     └──────────────────┘     │ │Anthr-││Groq││OAI││                │
                              │ │opic  ││    ││   ││                │
     ┌──────────────┐         │ └──────┘└────┘└───┘│                │
     │ Next.js UI   │         └────────────────────┘                │
     │ (read-only)  │──────►┌──────────┐◄───────────────────────────┘
     └──────────────┘       │  SQLite   │
                            │    DB     │
                            └──────────┘
```

## Components

| Component | File | Responsibility | Subscribes To | Publishes |
|-----------|------|----------------|---------------|-----------|
| EventBus | `event_bus.py` | Async pub/sub, routes events by type | -- | -- |
| MarketData | `market_data.py` | WebSocket ticker -> price events | -- | `PriceUpdate` |
| OrderManager | `order_manager.py` | Places orders via CoinbaseClient, tracks fills, balance pre-flight check | `OrderRequest` | `OrderFilled`, `OrderFailed` |
| RiskManager | `risk_manager.py` | Validates orders against limits | Called by OrderManager | `RiskViolation`, `KillSwitchActivated` |
| PositionTracker | `position_tracker.py` | Manages positions, computes P&L, writes daily summary | `OrderFilled` | `PositionChanged` |
| KillSwitch | `kill_switch.py` | Emergency stop, persisted to DB | -- | `KillSwitchActivated` |
| CoinbaseClient | `coinbase_client.py` | Wraps coinbase-advanced-py SDK (REST + WebSocket) | -- | -- |
| Database | `db.py` | SQLite schema, connection management | -- | -- |
| Config | `config.py` | Pydantic settings loaded from `.env` | -- | -- |
| PriceBuffer | `price_buffer.py` | In-memory rolling buffer of recent prices | `PriceUpdate` | -- |
| Prediction | `prediction.py` | Shared prediction dataclass + `parse_prediction()` helper | -- | -- |
| LLMClient | `llm_client.py` | Transport-level LLM abstraction (Anthropic + Groq + OpenAI-compatible) | -- | -- |
| Strategy ABC | `strategy.py` | Shared strategy logic: timer loop, evaluation, position checks | `PriceUpdate` | `OrderRequest` |
| PriceOnlyStrategy | `strategies/price_only.py` | Price-only prediction: builds prompt from price history, calls LLMClient | `PriceUpdate` | `OrderRequest` |
| NewsPredictionStrategy | `strategies/news.py` | News + price prediction: builds prompt from prices + headlines, calls LLMClient | `PriceUpdate` | `OrderRequest` |
| Registry | `registry.py` | `STRATEGIES` + `LLM_PROVIDERS` dicts for CLI-driven wiring | -- | -- |
| NewsService | `news_service.py` | Fetches crypto news/sentiment via Grok API (xAI) | -- | -- |
| PortfolioTracker | `portfolio_tracker.py` | Periodic snapshots of portfolio value, P&L, and positions | -- | -- |
| RunReporter | `run_reporter.py` | Hourly CSV performance reporting + auto git commit/push | -- | -- |
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
      │    Balance Check   RiskViolation
      │    (BUY only)
      │      │
      │  ┌───┴───────┐
      │  │           │
      │  OK/sized  REJECT (<$1)
      │  down       → OrderFailed
      │  │
      │  ▼
      │    CoinbaseClient
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

## ADR: Decoupled Strategies from LLM Providers

**Date:** 2026-02-15
**Status:** Accepted

**Context:** The original architecture tightly coupled strategies to predictor classes (ClaudePredictor, KimiPredictor, ClaudePriceOnlyPredictor). Each predictor bundled prompt construction, response parsing, and LLM transport. Adding a new LLM provider required a new predictor class per strategy. Adding a new strategy required new predictor classes per provider. This was an M x N scaling problem.

**Decision:** Decouple strategies from LLM providers. Strategies own their prompts and data gathering, calling `LLMClient.complete()` directly for transport. The `Predictor` protocol is removed. A shared `parse_prediction()` helper handles response parsing. A `registry.py` maps strategy and LLM provider names to their classes. CLI args (`--strategy`, `--llm`, `--model`) replace env-var-based selection.

**Consequences:**
- Adding a new strategy = 1 new file in `src/strategies/` + 1 registry entry
- Adding a new LLM provider = 1 new `LLMClient` implementation + 1 registry entry
- Strategies and providers scale independently (M + N, not M x N)
- Old predictor files deleted: `claude_predictor.py`, `kimi_predictor.py`, `claude_price_only_predictor.py`
- Old strategy files deleted: `strategy_news_prediction.py`, `strategy_price_only.py`
- Config simplified: removed `strategy`, `predictor_type`, `prediction_model`, `openrouter_model`, `openrouter_base_url` fields

## Changelog

- **2026-02-14** -- Initial architecture: EventBus, MarketData, OrderManager, RiskManager, PositionTracker, KillSwitch, Database, Config. 48 tests.
- **2026-02-14** -- Added interactive smoke test script (`scripts/smoke_test.py`) for live plumbing validation.
- **2026-02-14** -- Added PriceBuffer, NewsService (Grok API), ClaudePredictor (Anthropic API), and ClaudePredictionStrategy. 69 tests.
- **2026-02-15** -- Added PriceOnlyStrategy and ClaudePriceOnlyPredictor for price-only predictions (no news). Renamed ClaudePredictionStrategy to NewsPredictionStrategy. Added `strategy` config field to switch between `price_only` and `news`. 82 tests.
- **2026-02-15** -- Added `coinbase_key_file` and `product_id` config fields. CoinbaseClient and MarketData support key file auth. MarketData resolves product IDs by base currency. OrderManager polls for fill details (5 attempts). Fixed risk pipeline check order in docs.
- **2026-02-15** -- Added 4 new DB tables (price_history, predictions, news_history, portfolio_snapshots), PortfolioTracker component, price tick persistence in MarketData, prediction/news logging, and Next.js dashboard UI with 6 pages.
- **2026-02-15** -- PortfolioTracker now sources total_value_usd from Coinbase account balances via get_accounts() instead of computing from local positions. Removed dead columns position_value_usd and num_open_positions from portfolio_snapshots schema and TS types. 89 tests.
- **2026-02-15** -- Added LLM client abstraction layer (`LLMClient` protocol with `AnthropicLLMClient` and `OpenAICompatibleLLMClient`), shared `Prediction` dataclass and `Predictor` protocol, `KimiPredictor` for OpenRouter-based predictions, and predictor factory in `main.py`. All predictors now use constructor-injected `LLMClient` instead of raw API keys. Config gains `PREDICTOR_TYPE`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`. 103 tests.
- **2026-02-15** -- Decoupled strategies from LLM providers. Replaced predictor classes with Strategy ABC (`src/strategy.py`) + concrete strategies (`src/strategies/`) that call `LLMClient` directly. Added `registry.py` for strategy/provider lookup, CLI args (`--strategy`, `--llm`, `--model`). Removed `Predictor` protocol, added `parse_prediction()` helper. Deleted old files: `claude_predictor.py`, `kimi_predictor.py`, `claude_price_only_predictor.py`, `strategy_news_prediction.py`, `strategy_price_only.py`. Simplified config (removed `strategy`, `predictor_type`, `prediction_model`, `openrouter_model`, `openrouter_base_url`). 96 tests.
- **2026-02-15** -- Added Groq as LLM provider. New `GroqLLMClient` in `llm_client.py` using `groq` SDK (`AsyncGroq`). Registered in `registry.py` with default model `openai/gpt-oss-120b`. Added `groq>=0.13.0` dependency. Available via `--llm groq`. 108 tests.
- **2026-02-15** -- Added RunReporter component. Appends hourly CSV rows to `runs/performance.csv` with daily P&L, trades, fees, portfolio value, and open positions. Auto-commits and pushes to git via subprocess. Timer-driven async loop (same pattern as PortfolioTracker). 108 tests.
- **2026-02-16** -- Added balance pre-flight check to OrderManager. BUY orders now check PortfolioTracker.quote_balance before placing: rejects if < $1.00, sizes down if < order size. PortfolioTracker exposes cached `quote_balance` property updated on each snapshot. SELL orders bypass check entirely. 112 tests.
