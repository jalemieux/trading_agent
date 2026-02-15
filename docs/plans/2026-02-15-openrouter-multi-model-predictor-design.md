# OpenRouter / Multi-Model Predictor Support

**Date**: 2026-02-15
**Status**: Approved

## Problem

The trading bot's prediction system is hardcoded to use Claude via the Anthropic SDK. We want to support multiple LLM providers (starting with OpenRouter for Kimi 2.5) so predictors can be model-specific while sharing a common transport layer.

## Architecture

```
┌─────────────┐     ┌────────────────────────┐
│   Settings   │     │  .env                  │
│ (.env based) │◄────│  PREDICTOR_TYPE=kimi   │
└──────┬───────┘     │  OPENROUTER_API_KEY=.. │
       │             │  OPENROUTER_MODEL=...  │
       ▼             └────────────────────────┘
  main.py factory
       │
       ├─── predictor_type == "claude" ──► AnthropicLLMClient ──► ClaudePredictor
       │                                                                │
       └─── predictor_type == "kimi" ───► OpenAICompatibleLLMClient ──► KimiPredictor
                                                                        │
                                    ┌───────────────────────────────────┘
                                    ▼
                         Predictor Protocol
                         predict(prices, headlines) → Prediction | None
                                    │
                                    ▼
                        ClaudePredictionStrategy
                        (unchanged, uses constructor injection)
```

### Two-Layer Design

**Layer 1 — LLM Client (transport)**:
- `LLMClient` Protocol with `complete(system, user, max_tokens) → str`
- `AnthropicLLMClient` — wraps `AsyncAnthropic`, talks to `api.anthropic.com`
- `OpenAICompatibleLLMClient` — wraps `AsyncOpenAI`, configurable `base_url` (OpenRouter, xAI, etc.)

**Layer 2 — Predictor (model-specific)**:
- `Predictor` Protocol with `predict(prices, headlines) → Prediction | None`
- `ClaudePredictor` — Claude-optimized prompting, uses `AnthropicLLMClient`
- `KimiPredictor` — Kimi-optimized prompting, uses `OpenAICompatibleLLMClient`

### Key Design Decisions

1. **OpenRouter is transport, not predictor** — predictors are model-specific (prompt tuning), clients are API-specific (SDK differences)
2. **Protocol-based, not ABC** — lightweight typing.Protocol, no inheritance machinery
3. **Constructor injection preserved** — strategy already accepts predictor; factory in main.py selects the right one
4. **Shared Prediction dataclass** — moved to `src/prediction.py`, imported by all predictors
5. **Config stays in .env** — flat pydantic-settings, no YAML for now

## New Files

| File | Purpose |
|------|---------|
| `src/llm_client.py` | `LLMClient` Protocol + `AnthropicLLMClient` + `OpenAICompatibleLLMClient` |
| `src/kimi_predictor.py` | `KimiPredictor` with Kimi-tuned prompting |
| `src/prediction.py` | Shared `Prediction` dataclass + `Predictor` Protocol |

## Modified Files

| File | Change |
|------|--------|
| `src/config.py` | Add `predictor_type`, `openrouter_api_key`, `openrouter_model`, `openrouter_base_url` |
| `src/claude_predictor.py` | Accept `LLMClient` instead of raw `api_key`; import `Prediction` from `prediction.py` |
| `src/strategy_claude_prediction.py` | Type hint predictor as `Predictor` protocol |
| `src/main.py` | Factory logic to create the right predictor based on `predictor_type` |

## Config Additions (.env)

```
PREDICTOR_TYPE=claude          # "claude" or "kimi"
OPENROUTER_API_KEY=            # OpenRouter API key
OPENROUTER_MODEL=moonshotai/kimi-k2
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

## Error Handling

Same pattern as existing — `predict()` returns `None` on any failure (API errors, parse errors). Strategy already handles `None`.

## Data Flow (unchanged)

```
PriceUpdate → PriceBuffer → Strategy._run_prediction_cycle()
    → news_service.fetch_headlines()
    → predictor.predict(prices, headlines)  ← swappable!
    → evaluate() → OrderRequest
```
