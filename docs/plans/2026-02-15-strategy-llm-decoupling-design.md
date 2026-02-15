# Strategy / LLM Provider Decoupling Design

**Date:** 2026-02-15
**Goal:** Decouple prediction strategies from LLM providers so any strategy works with any LLM backend, controlled via CLI args.

## Problem

Currently strategies are tightly coupled to specific predictor classes (`ClaudePredictor`, `KimiPredictor`, `ClaudePriceOnlyPredictor`). Each predictor bakes in both prompt logic and LLM transport. This creates a combinatorial explosion — every new strategy needs a matching predictor per LLM provider.

The prompt is fundamentally a function of the strategy (what data to include, what to ask), not the LLM provider (how to send the request). These concerns should be separated.

## Design

### Two-Layer Architecture

```
CLI: --strategy news --llm anthropic --model claude-opus-4-6

Strategy (owns prompts, gathers data)
    │
    └── LLMClient (transport only)
            │
            └── Anthropic / OpenRouter / OpenAI / etc.
```

Strategies call `self._llm_client.complete(system, user)` directly. The predictor layer is eliminated.

### Strategy Base Class — `src/strategy.py`

Abstract base class that holds all shared logic currently duplicated between `NewsPredictionStrategy` and `PriceOnlyStrategy`:

- Timer loop (`start()`, `stop()`, `_prediction_loop()`)
- Event subscription (`register()`, `_on_price()`)
- Evaluation logic (`_evaluate()`, buy/sell/hold decisions)
- Position checks (`_has_open_position()`, `_get_position_quantity()`)

Each concrete strategy implements only:
- `_gather_and_predict() -> Prediction | None` — gathers data, builds prompts, calls LLM, parses response

### Concrete Strategies — `src/strategies/`

**`src/strategies/price_only.py`** — `PriceOnlyStrategy`
- Gathers: price history from PriceBuffer
- System prompt: technical analysis / price action focus
- No external dependencies beyond LLMClient

**`src/strategies/news.py`** — `NewsPredictionStrategy`
- Gathers: price history + headlines from NewsService
- System prompt: includes news/sentiment analysis context
- Additional dependency: `NewsService` (injected)

### Shared Prediction Parsing — `src/prediction.py`

`parse_prediction(raw: str, current_price: float) -> Prediction | None` — shared JSON parsing helper that all strategies use. The `Prediction` dataclass stays. The `Predictor` protocol is removed.

### Registry — `src/registry.py`

```python
STRATEGIES = {
    "price_only": {"class": PriceOnlyStrategy, "description": "Technical analysis from price history only"},
    "news": {"class": NewsPredictionStrategy, "description": "Price history + real-time news sentiment via Grok API"},
}

LLM_PROVIDERS = {
    "anthropic": {"class": AnthropicLLMClient, "default_model": "claude-opus-4-6", "key_env": "ANTHROPIC_API_KEY", "description": "Anthropic Claude API"},
    "openrouter": {"class": OpenAICompatibleLLMClient, "default_model": "moonshotai/kimi-k2", "key_env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "description": "OpenRouter API"},
}
```

CLI `--help` and `main.py` factory are generated from these dicts. Adding a strategy or provider = add one entry.

### CLI Interface — `src/main.py`

```bash
python -m src.main --strategy news --llm anthropic --model claude-opus-4-6
python -m src.main --help
```

- `--strategy` — choices from `STRATEGIES` keys, default `price_only`
- `--llm` — choices from `LLM_PROVIDERS` keys, default `anthropic`
- `--model` — model ID string, default depends on `--llm`

Help strings pulled from registry descriptions.

### Config Changes — `src/config.py`

Remove from Settings (now CLI args): `strategy`, `predictor_type`, `prediction_model`, `openrouter_api_key`, `openrouter_model`, `openrouter_base_url`

Keep in Settings (.env): `coinbase_api_key`, `coinbase_api_secret`, `coinbase_key_file`, `max_order_size_usd`, `max_daily_loss_usd`, `db_path`, `anthropic_api_key`, `grok_api_key`, `openrouter_api_key`, `prediction_interval_minutes`, `grok_model`, `trade_threshold_pct`, `trade_size_usd`, `product_id`

Note: `openrouter_api_key` stays in `.env` (it's a secret), but `openrouter_model` and `openrouter_base_url` move to the registry (they're provider config, not user secrets).

### File Changes

**Created:**
- `src/strategy.py` — Strategy ABC + shared logic
- `src/strategies/__init__.py`
- `src/strategies/price_only.py` — PriceOnlyStrategy
- `src/strategies/news.py` — NewsPredictionStrategy
- `src/registry.py` — STRATEGIES + LLM_PROVIDERS

**Modified:**
- `src/main.py` — argparse CLI, factory from registries
- `src/prediction.py` — add `parse_prediction()` helper, remove `Predictor` protocol
- `src/config.py` — remove strategy/predictor fields
- `.env.example` — remove strategy/predictor lines
- `docs/` — update architecture, ai-components, ai-index

**Deleted:**
- `src/claude_predictor.py`
- `src/kimi_predictor.py`
- `src/claude_price_only_predictor.py`
- `src/strategy_news_prediction.py`
- `src/strategy_price_only.py`
- `tests/test_claude_predictor.py`
- `tests/test_kimi_predictor.py`
- `tests/test_claude_price_only_predictor.py`
- `tests/test_strategy_news_prediction.py`
- `tests/test_strategy_price_only.py`
