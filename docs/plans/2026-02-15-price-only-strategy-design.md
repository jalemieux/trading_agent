# Price-Only Strategy Design

**Date:** 2026-02-15
**Status:** Approved

## Summary

Add a `PriceOnlyStrategy` that uses only price history (no news) for predictions, and rename existing `ClaudePredictionStrategy` to `NewsPredictionStrategy`. A config flag switches between the two.

## Architecture

```
Strategy layer (model-agnostic):
  NewsPredictionStrategy  ──→  predictor.predict(prices, headlines)
  PriceOnlyStrategy       ──→  predictor.predict(prices)

Predictor layer (model-specific):
  ClaudePredictor              ← Anthropic API, news+price prompt
  ClaudePriceOnlyPredictor     ← Anthropic API, price-only prompt
```

## New Components

### `src/claude_price_only_predictor.py` — `ClaudePriceOnlyPredictor`

- Constructor: `(api_key: str, model: str)`
- Method: `predict(prices: list[PriceUpdate]) -> Prediction | None`
- System prompt tuned for pure technical/price analysis (no news references)
- Returns same `Prediction` dataclass from `claude_predictor.py`

### `src/strategy_price_only.py` — `PriceOnlyStrategy`

- Constructor: `(bus, price_buffer, predictor, settings, product_id, db)`
- No `news_service` dependency
- Same loop/evaluate/position logic as `NewsPredictionStrategy`
- `_run_prediction_cycle` calls `predictor.predict(prices)` directly

## Renames

| Old | New |
|-----|-----|
| `strategy_claude_prediction.py` | `strategy_news_prediction.py` |
| `ClaudePredictionStrategy` | `NewsPredictionStrategy` |

## Config Changes

`src/config.py` — add:

```python
strategy: str = "price_only"  # "price_only" or "news"
```

## Wiring (`src/main.py`)

Branch on `settings.strategy`:
- `"news"` → `NewsService` + `ClaudePredictor` + `NewsPredictionStrategy`
- `"price_only"` → `ClaudePriceOnlyPredictor` + `PriceOnlyStrategy`

## Testing

- Unit tests for `ClaudePriceOnlyPredictor` (mock Anthropic, verify no news in prompt, parse JSON)
- Unit tests for `PriceOnlyStrategy` (mock predictor, no news_service, evaluate logic)
- Verify main.py wiring for both config values

## What stays the same

- `Prediction` dataclass (reused from `claude_predictor.py`)
- `PriceBuffer`, `EventBus`, all event types
- `ClaudePredictor` and `NewsService` — untouched
