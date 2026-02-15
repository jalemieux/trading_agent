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
    coinbase_key_file: str = ""
    max_order_size_usd: float = 100.0
    max_daily_loss_usd: float = 500.0
    db_path: str = "trading_bot.db"
    anthropic_api_key: str = ""
    grok_api_key: str = ""
    openrouter_api_key: str = ""
    prediction_interval_minutes: int = 5
    grok_model: str = "grok-3-mini-fast"
    trade_threshold_pct: float = 1.0
    trade_size_usd: float = 50.0
    product_id: str = "BTC-USD"
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
    __init__(api_key: str = "", api_secret: str = "", key_file: str = "")
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
- If `key_file` is provided, creates `RESTClient(key_file=key_file)` (JSON key file auth)
- Otherwise creates `RESTClient(api_key=api_key, api_secret=api_secret)` (inline key auth)
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

Module-level helper:
- `_get(obj, key, default=None)` — gets value from dict (`.get()`) or object (`getattr()`). Used throughout OrderManager to handle both dict and object attribute access from SDK responses.

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
5. If success → poll get_order up to 5 times (1s delay between) for fill details → persist as FILLED → publish OrderFilled

Fill polling: Market orders may not settle immediately. The handler polls `get_order()` up to 5 times with 1-second delays, checking `filled_size > 0` before extracting fill details.

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
    __init__(bus: EventBus, api_key: str = "", api_secret: str = "", key_file: str = "", product_ids: list[str] | None = None)
    start(product_ids: list[str]) → None  # async, opens WS, subscribes to ticker
    stop() → None                         # async, closes WS (safe if never started)
```

Internal state:
- `_bus: EventBus`
- `_loop: AbstractEventLoop | None` — set on start(), used for thread bridging
- `_product_ids: set[str]` — subscribed product IDs, used for product ID resolution
- `_ws: WSClient` — Coinbase WebSocket client

Publishes: PriceUpdate

Constructor auth:
- If `key_file` is provided, creates `WSClient(key_file=key_file, ...)`
- Otherwise creates `WSClient(api_key=api_key, api_secret=api_secret, ...)`

Thread bridging:
- WSClient callback runs in a separate thread
- `_schedule_on_message` bridges to asyncio loop via `run_coroutine_threadsafe`
- `_on_message` is async, runs on the event loop

Message parsing:
- Only processes `channel == "ticker"` messages
- Extracts `events[].tickers[].{product_id, price}` from JSON
- Runs product_id through `_resolve_product_id()` before publishing
- Publishes PriceUpdate for each ticker entry

Product ID resolution (`_resolve_product_id`):
- If raw ID is in `_product_ids`, return as-is
- Otherwise, match by base currency (e.g., Coinbase returns "SOL-USD" but subscribed to "SOL-USDC" → maps to "SOL-USDC")
- Falls back to raw ID if no match found

Dependencies: EventBus, coinbase-advanced-py (coinbase.websocket.WSClient)

---

## main() — `src/main.py`

CLI args (via argparse):
- `--strategy`: `price_only` (default) or `news` — selects from `STRATEGIES` registry
- `--llm`: `anthropic` (default) or `openrouter` — selects from `LLM_PROVIDERS` registry
- `--model`: LLM model ID (default from provider config)

Initialization order:
1. parse_args() — CLI flags
2. Settings() — env vars
3. EventBus()
4. Database(settings.db_path) → await initialize()
5. KillSwitch(db, bus) → await initialize()
6. RiskManager(db, bus, kill_switch, settings)
7. CoinbaseClient(key, secret, key_file)
8. OrderManager(db, bus, risk_manager, coinbase) → register(bus)
9. PositionTracker(db, bus) → register(bus)
10. PortfolioTracker(db, bus, coinbase, product_id, interval)
11. MarketData(bus, key, secret, key_file, db)
12. LLM client from registry: `LLM_PROVIDERS[args.llm]["class"](**provider_kwargs)`
13. PriceBuffer(max_size=50)
14. Strategy from registry: `STRATEGIES[args.strategy]["class"](**strategy_kwargs)`
    - News strategy additionally gets NewsService injected
15. strategy.register(bus) — subscribes to PriceUpdate
16. await market_data.start(product_ids=[settings.product_id])
17. await strategy.start() — launches prediction loop
18. await portfolio_tracker.start()

Shutdown:
- SIGINT/SIGTERM → sets asyncio.Event
- await portfolio_tracker.stop()
- await strategy.stop()
- await market_data.stop()
- await db.close()

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

## Prediction — `src/prediction.py`

```
@dataclass
class Prediction:
    target_price: float
    timeframe_minutes: int
    reasoning: str
    current_price: float
    timestamp: str

def parse_prediction(raw: str, current_price: float) → Prediction | None
```

Shared data model for predictions. `parse_prediction()` strips markdown code fences, parses JSON, and returns a `Prediction` or `None` on failure.

Dependencies: none

---

## LLMClient Protocol — `src/llm_client.py`

```
@runtime_checkable
class LLMClient(Protocol):
    async def complete(self, system: str, user: str, max_tokens: int = 512) → str: ...

class AnthropicLLMClient:
    __init__(api_key: str, model: str)
    complete(system, user, max_tokens=512) → str  # async

class OpenAICompatibleLLMClient:
    __init__(api_key: str, model: str, base_url: str)
    complete(system, user, max_tokens=512) → str  # async
```

Transport-level LLM abstraction. `AnthropicLLMClient` wraps the Anthropic Messages API. `OpenAICompatibleLLMClient` wraps any OpenAI-compatible API (e.g., OpenRouter).

Behavior:
- AnthropicLLMClient: sends system param + user message to Anthropic, returns `response.content[0].text`
- OpenAICompatibleLLMClient: sends system + user as chat messages, returns `response.choices[0].message.content` (empty string if None)

Dependencies: anthropic SDK, openai SDK

---

## Strategy ABC — `src/strategy.py`

```
class Strategy(abc.ABC):
    __init__(bus: EventBus, price_buffer: PriceBuffer, settings: Settings,
             product_id: str = "BTC-USD", db: Database | None = None)
    register(bus: EventBus) → None
    start() → None   # async, starts timer loop
    stop() → None    # async, cancels timer
    _gather_and_predict() → Prediction | None  # async, abstract
    _evaluate(prediction: Prediction) → None   # async
    _has_open_position() → bool                # async
    _get_position_quantity() → float           # async
```

Subscribes to: PriceUpdate
Publishes: OrderRequest

Internal state:
- `_bus: EventBus`
- `_price_buffer: PriceBuffer`
- `_settings: Settings`
- `_product_id: str`
- `_db: Database | None`
- `_task: asyncio.Task | None`

Behavior:
- register() subscribes to PriceUpdate, delegates to _on_price which feeds the PriceBuffer
- start() launches an asyncio task running _prediction_loop (30s initial delay, then timer)
- _prediction_loop fires every `prediction_interval_minutes` minutes, calls _run_prediction_cycle
- _run_prediction_cycle: snapshot prices → _gather_and_predict() → _evaluate()
- _evaluate: computes diff_pct, checks position state, emits BUY/SELL OrderRequest if threshold exceeded
- _has_open_position and _get_position_quantity query the DB for open positions
- Concrete strategies only need to implement _gather_and_predict()

Dependencies: config, db, event_bus, events, prediction, price_buffer

---

## PriceOnlyStrategy — `src/strategies/price_only.py`

```
class PriceOnlyStrategy(Strategy):
    __init__(llm_client: LLMClient, **kwargs)
    _gather_and_predict() → Prediction | None  # async
    _build_prompt(prices) → str
```

Internal state:
- `_llm_client: LLMClient`
- Inherits all state from Strategy ABC

Behavior:
- Overrides _gather_and_predict(): snapshots prices, builds a technical-analysis prompt, calls LLMClient.complete(), parses response via parse_prediction()
- System prompt focuses on price action and technical patterns
- No news_service dependency
- Selected via `--strategy price_only` (default)

Dependencies: llm_client, prediction, price_buffer, strategy

---

## NewsPredictionStrategy — `src/strategies/news.py`

```
class NewsPredictionStrategy(Strategy):
    __init__(llm_client: LLMClient, news_service: NewsService, **kwargs)
    _gather_and_predict() → Prediction | None  # async
    _build_prompt(prices, headlines: list[str]) → str
    _log_prediction(prediction: Prediction, headlines: list[str]) → None  # async
```

Internal state:
- `_llm_client: LLMClient`
- `_news_service: NewsService`
- Inherits all state from Strategy ABC

Behavior:
- Overrides _gather_and_predict(): snapshots prices, fetches headlines via NewsService, builds prompt with both, calls LLMClient.complete(), parses via parse_prediction()
- Logs predictions and headlines to DB (predictions + news_history tables)
- Selected via `--strategy news`

Dependencies: llm_client, news_service, prediction, strategy

---

## Registry — `src/registry.py`

```
STRATEGIES = {
    "price_only": {"class": PriceOnlyStrategy, "description": "..."},
    "news": {"class": NewsPredictionStrategy, "description": "..."},
}

LLM_PROVIDERS = {
    "anthropic": {"class": AnthropicLLMClient, "default_model": "claude-opus-4-6", "key_env": "ANTHROPIC_API_KEY", ...},
    "openrouter": {"class": OpenAICompatibleLLMClient, "default_model": "moonshotai/kimi-k2", "key_env": "OPENROUTER_API_KEY", "base_url": "...", ...},
}
```

Lookup dicts used by `main.py` to wire strategy + LLM provider from CLI args. Adding a new strategy or LLM provider is a single dict entry.

Dependencies: llm_client, strategies/news, strategies/price_only
