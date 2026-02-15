# Component Reference

Every class, its constructor, public methods, internal state, and exact dependencies.

---

## EventBus — `src/event_bus.py`

```
class EventBus:
    __init__()
    subscribe(event_type: type, handler: Callable[[Any], Coroutine]) → None
    unsubscribe(event_type: type, handler) → None
    publish(event: Any) → None  # async, awaits each handler sequentially
```

Internal state:
- `_subscribers: dict[type, list[Handler]]` — defaultdict(list), keyed by event class

Behavior:
- publish() dispatches to handlers matching `type(event)` exactly (no inheritance)
- Handler exceptions are caught and logged, do not propagate
- Handlers run sequentially (not concurrent) in subscription order
- unsubscribe() raises ValueError if handler not found

Dependencies: none

---

## Settings — `src/config.py`

```
class Settings(BaseSettings):
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    max_order_size_usd: float = 100.0
    max_daily_loss_usd: float = 500.0
    db_path: str = "trading_bot.db"
    strategy: str = "price_only"  # "price_only" or "news"
    anthropic_api_key: str = ""
    grok_api_key: str = ""
    prediction_interval_minutes: int = 5
    prediction_model: str = "claude-opus-4-6"
    grok_model: str = "grok-3-mini-fast"
    trade_threshold_pct: float = 1.0
    trade_size_usd: float = 50.0
```

Loads from `.env` file via pydantic-settings. Env var names are UPPER_SNAKE_CASE versions of field names.

Dependencies: pydantic-settings

---

## Database — `src/db.py`

```
class Database:
    __init__(db_path: str)
    initialize() → None        # async, creates tables, seeds kill_switch row
    execute(sql, params=()) → None          # async, auto-commits
    execute_fetchall(sql, params=()) → list # async
    execute_fetchone(sql, params=())        # async, returns tuple|None
    close() → None                          # async
```

Internal state:
- `_db_path: str`
- `_conn: aiosqlite.Connection | None`

Schema: defined in module-level `SCHEMA` string. 4 tables + 1 seed INSERT. See ai-data.md for full schema.

Behavior:
- initialize() runs executescript(SCHEMA) then commit
- execute() runs single statement + commit (auto-commit per call)
- Uses assert for connection checks (stripped with python -O)
- `:memory:` path creates in-memory DB (used in tests)
- FK enforcement is OFF by default (SQLite default, no PRAGMA foreign_keys = ON)

Dependencies: aiosqlite

---

## KillSwitch — `src/kill_switch.py`

```
class KillSwitch:
    __init__(db: Database, bus: EventBus)
    is_active: bool             # property
    initialize() → None        # async, loads state from DB
    activate(reason: str) → None   # async, sets DB, publishes KillSwitchActivated
    deactivate() → None            # async, clears DB
```

Internal state:
- `_active: bool` — in-memory cache of DB state
- `_db`, `_bus`

Behavior:
- initialize() reads `kill_switch` row, sets `_active` from DB
- activate() sets `_active=True`, writes DB, publishes event
- deactivate() sets `_active=False`, clears reason/activated_at in DB
- State survives restarts (persisted in kill_switch table, loaded on initialize)

Dependencies: Database, EventBus

---

## RiskManager — `src/risk_manager.py`

```
class RiskManager:
    __init__(db: Database, bus: EventBus, kill_switch: KillSwitch, settings: Settings)
    check(order: OrderRequest) → bool  # async, True=approved, False=rejected
```

Internal state: references to db, bus, kill_switch, settings

Check pipeline (order matters):
1. `kill_switch.is_active` → reject, publish RiskViolation
2. `daily_summary.total_pnl <= -max_daily_loss_usd` → activate kill switch, reject, publish RiskViolation
3. `order.side == "BUY" and order.quote_size > max_order_size_usd` → reject, publish RiskViolation
4. All checks pass → return True

SELL orders skip check #3 (always allowed for size — they close positions).

Dependencies: Database, EventBus, KillSwitch, Settings

---

## CoinbaseClient — `src/coinbase_client.py`

```
class CoinbaseClient:
    __init__(api_key: str, api_secret: str)
    market_buy(client_order_id, product_id, quote_size) → dict
    market_sell(client_order_id, product_id, base_size) → dict
    limit_order(client_order_id, product_id, side, base_size, limit_price) → dict
    cancel_orders(order_ids: list[str]) → dict
    get_order(order_id: str) → dict
    get_accounts() → dict
    get_product(product_id: str) → dict
```

Internal state: `_client: RESTClient` from coinbase.rest

Behavior:
- Thin wrapper, each method delegates directly to SDK
- All params are strings (SDK requirement for sizes/prices)
- Methods are synchronous (SDK is sync)
- Returns raw SDK response dicts

SDK method mapping:
- market_buy → _client.market_order_buy
- market_sell → _client.market_order_sell
- limit_order → _client.limit_order_gtc
- cancel_orders → _client.cancel_orders
- get_order → _client.get_order
- get_accounts → _client.get_accounts
- get_product → _client.get_product

Response shapes:
- Success: `{"success": True, "success_response": {"order_id": "..."}}`
- Failure: `{"success": False, "error_response": {"error": "INSUFFICIENT_FUND"}}`
- get_order: `{"order": {"order_id": "...", "status": "FILLED", "filled_size": "0.002", "average_filled_price": "50000", "total_fees": "0.20"}}`

Dependencies: coinbase-advanced-py (coinbase.rest.RESTClient)

---

## OrderManager — `src/order_manager.py`

```
class OrderManager:
    __init__(db: Database, bus: EventBus, risk_manager: RiskManager, coinbase: CoinbaseClient)
    register(bus: EventBus) → None  # subscribes to OrderRequest
```

Internal state: _db, _bus, _risk, _coinbase

Subscribes to: OrderRequest
Publishes: OrderFilled, OrderFailed

Private methods:
- `_handle_order_request(order: OrderRequest)` — main handler
- `_place_market_order(order) → dict` — routes BUY to market_buy, SELL to market_sell
- `_place_limit_order(order) → dict` — calls limit_order
- `_persist_order(order, created_at, coinbase_id=None, filled_price=None, filled_qty=None, fee=None, status="PENDING")` — INSERT INTO orders

Flow (see ai-traces.md for detailed trace):
1. risk.check(order) → if False, return (RiskViolation already published by RiskManager)
2. Place order via CoinbaseClient (sync call)
3. If exception → publish OrderFailed
4. If result.success == False → persist as FAILED, publish OrderFailed
5. If success → get_order for fill details → persist as FILLED → publish OrderFilled

Dependencies: Database, EventBus, RiskManager, CoinbaseClient

---

## PositionTracker — `src/position_tracker.py`

```
class PositionTracker:
    __init__(db: Database, bus: EventBus)
    register(bus: EventBus) → None  # subscribes to OrderFilled
```

Subscribes to: OrderFilled
Publishes: PositionChanged

Private methods:
- `_handle_order_filled(event: OrderFilled)` — routes to buy/sell handlers
- `_upsert_order(event: OrderFilled)` — ensures order row exists in DB for fee lookups
- `_open_or_add_position(event: OrderFilled)` — creates or averages into position
- `_reduce_or_close_position(event: OrderFilled)` — reduces/closes position, calculates P&L

P&L calculation:
```
pnl = (sell_price - entry_price) * sell_qty - sell_fee - proportional_buy_fee
proportional_buy_fee = total_buy_fees * (sell_qty / position_qty)
```

Position fully closed when `remaining <= 1e-10` (floating point guard).

Dependencies: Database, EventBus

---

## MarketData — `src/market_data.py`

```
class MarketData:
    __init__(bus: EventBus, api_key: str, api_secret: str)
    start(product_ids: list[str]) → None  # async, opens WS, subscribes to ticker
    stop() → None                         # async, closes WS (safe if never started)
```

Internal state:
- `_bus: EventBus`
- `_loop: AbstractEventLoop | None` — set on start(), used for thread bridging
- `_ws: WSClient` — Coinbase WebSocket client

Publishes: PriceUpdate

Thread bridging:
- WSClient callback runs in a separate thread
- `_schedule_on_message` bridges to asyncio loop via `run_coroutine_threadsafe`
- `_on_message` is async, runs on the event loop

Message parsing:
- Only processes `channel == "ticker"` messages
- Extracts `events[].tickers[].{product_id, price}` from JSON
- Publishes PriceUpdate for each ticker entry

Dependencies: EventBus, coinbase-advanced-py (coinbase.websocket.WSClient)

---

## main() — `src/main.py`

Initialization order:
1. Settings()
2. EventBus()
3. Database(settings.db_path) → await initialize()
4. KillSwitch(db, bus) → await initialize()
5. RiskManager(db, bus, kill_switch, settings)
6. CoinbaseClient(settings.coinbase_api_key, settings.coinbase_api_secret)
7. OrderManager(db, bus, risk_manager, coinbase) → register(bus)
8. PositionTracker(db, bus) → register(bus)
9. MarketData(bus, settings.coinbase_api_key, settings.coinbase_api_secret)

Shutdown:
- SIGINT/SIGTERM → sets asyncio.Event
- await market_data.stop()
- await db.close()

Note: MarketData.start() is NOT called in main(). Products must be subscribed explicitly (strategy layer responsibility).

---

## PriceBuffer — `src/price_buffer.py`

```
class PriceBuffer:
    __init__(max_size: int = 50)
    add(update: PriceUpdate) → None
    snapshot(product_id: str) → list[PriceUpdate]
    latest(product_id: str) → PriceUpdate | None
```

Internal state:
- `_max_size: int`
- `_buffers: dict[str, deque[PriceUpdate]]`

Behavior:
- Ring buffer per product_id, FIFO eviction at max_size
- snapshot() returns a list copy of the deque for that product
- latest() returns the most recent PriceUpdate or None if empty
- add() appends to the deque, evicting oldest if at capacity

Dependencies: events

---

## NewsService — `src/news_service.py`

```
class NewsService:
    __init__(api_key: str, model: str = "grok-3-mini-fast")
    fetch_headlines(product_id: str) → list[str]  # async
```

Internal state:
- `_model: str`
- `_client: AsyncOpenAI`

Behavior:
- Calls Grok xAI API (via OpenAI-compatible SDK) for crypto news headlines
- Returns list of headline strings relevant to the given product
- Returns empty list on any error (network, API, parsing)

Dependencies: openai SDK

---

## ClaudePredictor — `src/claude_predictor.py`

```
@dataclass
class Prediction:
    target_price: float
    timeframe_minutes: int
    reasoning: str
    current_price: float
    timestamp: str

class ClaudePredictor:
    __init__(api_key: str, model: str = "claude-opus-4-6")
    predict(prices: list[PriceUpdate], headlines: list[str]) → Prediction | None  # async
```

Internal state:
- `_model: str`
- `_client: AsyncAnthropic`

Behavior:
- Sends price history + headlines to Claude API as a structured prompt
- Parses JSON response into a Prediction dataclass
- Returns None on any failure (API error, malformed response, parsing error)

Dependencies: anthropic SDK, events

---

## NewsPredictionStrategy — `src/strategy_news_prediction.py`

```
class NewsPredictionStrategy:
    __init__(bus, price_buffer, news_service, predictor, settings, product_id="BTC-USD", db=None)
    register(bus) → None
    start() → None  # async, starts timer loop
    stop() → None   # async, cancels timer
```

Subscribes to: PriceUpdate
Publishes: OrderRequest

Internal state:
- `_bus: EventBus`
- `_price_buffer: PriceBuffer`
- `_news_service: NewsService`
- `_predictor: ClaudePredictor`
- `_settings: Settings`
- `_product_id: str`
- `_db: Database | None`
- `_task: asyncio.Task | None`

Behavior:
- register() subscribes to PriceUpdate, delegates to _on_price which feeds the PriceBuffer
- start() launches an asyncio task that runs a prediction loop on a timer
- Timer fires every `prediction_interval_minutes` minutes
- Each cycle: snapshot prices → fetch headlines → predict → evaluate prediction vs current price
- If predicted price differs from current by more than `trade_threshold_pct`, emits OrderRequest (BUY if higher, SELL if lower)
- stop() cancels the timer task
- Selected when `strategy = "news"` in config

Dependencies: PriceBuffer, NewsService, ClaudePredictor, EventBus, Database, Settings

---

## PriceOnlyStrategy — `src/strategy_price_only.py`

```
class PriceOnlyStrategy:
    __init__(bus, price_buffer, predictor, settings, product_id="BTC-USD", db=None)
    register(bus) → None
    start() → None  # async, starts timer loop
    stop() → None   # async, cancels timer
```

Subscribes to: PriceUpdate
Publishes: OrderRequest

Internal state:
- `_bus: EventBus`
- `_price_buffer: PriceBuffer`
- `_predictor: ClaudePriceOnlyPredictor`
- `_settings: Settings`
- `_product_id: str`
- `_db: Database | None`
- `_task: asyncio.Task | None`

Behavior:
- Same loop/evaluate/position pattern as NewsPredictionStrategy but without news
- register() subscribes to PriceUpdate, delegates to _on_price which feeds the PriceBuffer
- start() launches an asyncio task that runs a prediction loop (30s initial delay, then timer)
- Each cycle: snapshot prices → predict (price-only) → evaluate prediction vs current price
- If predicted price differs from current by more than `trade_threshold_pct`, emits OrderRequest
- No news_service dependency
- Selected when `strategy = "price_only"` in config (default)

Dependencies: PriceBuffer, ClaudePriceOnlyPredictor, EventBus, Database, Settings

---

## ClaudePriceOnlyPredictor — `src/claude_price_only_predictor.py`

```
class ClaudePriceOnlyPredictor:
    __init__(api_key: str, model: str = "claude-opus-4-6")
    predict(prices: list[PriceUpdate]) → Prediction | None  # async
```

Internal state:
- `_model: str`
- `_client: AsyncAnthropic`

Behavior:
- Sends price history only (no news) to Claude API as a structured prompt
- System prompt focuses on technical analysis and price action patterns
- Parses JSON response into a Prediction dataclass (reuses from claude_predictor)
- Returns None on any failure (API error, malformed response, empty prices)

Dependencies: anthropic SDK, events, claude_predictor (Prediction dataclass)
