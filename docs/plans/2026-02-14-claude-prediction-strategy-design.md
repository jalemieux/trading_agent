# Claude Prediction Strategy Design

## Summary

A trading strategy that uses Claude (Opus 4.6) to predict BTC price targets based on recent price history and real-time news/sentiment from Grok (xAI). Runs on a configurable timer, auto-trades via the existing EventBus and risk management pipeline.

## Architecture

Approach 3: Strategy + Shared Services. The strategy orchestrates reusable, injectable services. Future strategies can reuse any service independently.

```
PriceUpdate (EventBus)
       │
       ▼
  PriceBuffer.add()          ← in-memory ring buffer
       │
       │   Timer fires every N minutes
       │         │
       ▼         ▼
  PriceBuffer.snapshot()  +  NewsService.fetch_headlines()
       │                          │
       └──────────┬───────────────┘
                  ▼
        ClaudePredictor.predict(prices, headlines)
                  │
                  ▼
          Prediction(target_price, timeframe, reasoning)
                  │
                  ▼
        Strategy compares target vs current price
                  │
          ┌───────┴───────┐
          ▼               ▼
    target > current   target < current
      + threshold        + threshold
          │               │
          ▼               ▼
    OrderRequest(BUY)  OrderRequest(SELL)
```

## Reusability Model

```
                    ┌─────────────────┐
                    │   PriceBuffer   │  ← shared service
                    └────────┬────────┘
                             │
    ┌────────────────────────┼────────────────────────┐
    │                        │                        │
┌───┴──────────────┐  ┌─────┴────────────┐  ┌───────┴──────────┐
│ ClaudePrediction │  │ MomentumStrategy │  │ FutureStrategyC  │
│    Strategy      │  │   (future)       │  │   (future)       │
└───┬──────────────┘  └──────────────────┘  └──────────────────┘
    │
    ├── NewsService      ← shared service
    ├── ClaudePredictor  ← shared service
    └──→ OrderRequest
```

## Components

### New Files

| File | Type | Purpose |
|------|------|---------|
| `src/price_buffer.py` | Service | Accumulates last N price updates in memory |
| `src/news_service.py` | Service | Fetches real-time crypto news/sentiment via Grok API |
| `src/claude_predictor.py` | Service | Calls Claude API, returns structured prediction |
| `src/strategy_claude_prediction.py` | Strategy | Timer loop, gathers data, predicts, trades |

### PriceBuffer

In-memory ring buffer that accumulates PriceUpdate events per product_id.

```python
class PriceBuffer:
    def __init__(self, max_size: int = 50): ...
    def add(self, update: PriceUpdate) -> None: ...
    def snapshot(self, product_id: str) -> list[PriceUpdate]: ...
    def latest(self, product_id: str) -> PriceUpdate | None: ...
```

- Keyed by product_id
- FIFO eviction when max_size reached
- No EventBus dependency — the strategy calls `add()` from its PriceUpdate handler

### NewsService (Grok API)

Fetches real-time news and sentiment from Grok, which has built-in access to X/Twitter data.

```python
class NewsService:
    def __init__(self, api_key: str, model: str = "grok-3-mini-fast"): ...
    async def fetch_headlines(self, product_id: str) -> list[str]: ...
```

- Uses the `openai` SDK pointed at `https://api.x.ai/v1` (Grok is OpenAI-compatible)
- Asks Grok for recent news headlines and sentiment about the given crypto asset
- Returns a list of headline-style strings

### ClaudePredictor

Calls Claude API with price history + headlines, returns a structured prediction.

```python
@dataclass
class Prediction:
    target_price: float
    timeframe_minutes: int
    reasoning: str
    current_price: float
    timestamp: str

class ClaudePredictor:
    def __init__(self, api_key: str, model: str = "claude-opus-4-6"): ...
    async def predict(self, prices: list[PriceUpdate], headlines: list[str]) -> Prediction: ...
```

- Uses the `anthropic` SDK
- Builds a structured prompt with price data and news context
- Parses Claude's response into a Prediction dataclass
- Model configurable via Settings

### ClaudePredictionStrategy

Orchestrates the services on a timer, makes trade decisions.

```python
class ClaudePredictionStrategy:
    def __init__(self, bus, price_buffer, news_service, predictor, settings): ...
    def register(self, bus) -> None: ...       # subscribes to PriceUpdate
    async def start(self) -> None: ...          # starts timer loop
    async def stop(self) -> None: ...           # cancels timer
    async def _on_price(self, event) -> None:   # feeds PriceBuffer
    async def _prediction_loop(self) -> None:   # timer-driven prediction cycle
    async def _evaluate(self, prediction) -> None:  # trade decision logic
```

## Trading Logic

```
price_diff_pct = (target_price - current_price) / current_price * 100

if price_diff_pct > +threshold  →  BUY  (quote_size = trade_size_usd)
if price_diff_pct < -threshold  →  SELL (base_size = open position qty)
else                            →  HOLD (do nothing)
```

Constraints:
- BUY only if no open position (avoid stacking)
- SELL only if there IS an open position
- Risk manager still gates everything (max order size, daily loss, kill switch)

## Config Additions

```python
# Added to Settings class
anthropic_api_key: str = ""
grok_api_key: str = ""
prediction_interval_minutes: int = 5
prediction_model: str = "claude-opus-4-6"
grok_model: str = "grok-3-mini-fast"
trade_threshold_pct: float = 1.0   # min % difference to trigger trade
trade_size_usd: float = 50.0       # USD per trade
```

## New Dependencies

```
anthropic     # Claude API
openai        # Grok API (OpenAI-compatible)
```

## Testing Strategy

| Component | Approach |
|-----------|----------|
| PriceBuffer | Pure unit tests, no mocks |
| NewsService | Mock openai client, verify prompt and response parsing |
| ClaudePredictor | Mock anthropic client, verify prompt construction and response parsing |
| ClaudePredictionStrategy | Mock all three services, verify OrderRequest emission for bullish/bearish/neutral/below-threshold scenarios |
