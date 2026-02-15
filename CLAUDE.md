# Coinbase Trading Bot

Async event-driven trading bot for Coinbase Advanced Trade. Python 3.12+, asyncio, SQLite.

## Commands

- Run: `python -m src.main --strategy price_only --llm anthropic --model claude-opus-4-6`
- Test: `pytest tests/ -v`
- Test single: `pytest tests/test_risk_manager.py -v`
- Install: `.venv/bin/pip install -e ".[dev]"`

## AI Documentation

Structured reference for AI systems working on this codebase:

- **[docs/ai-index.md](docs/ai-index.md)** — Start here. System summary, dependency graph, event routing table, file map.
- **[docs/ai-components.md](docs/ai-components.md)** — Every class: constructor signatures, methods, internal state, dependencies, behavior notes.
- **[docs/ai-data.md](docs/ai-data.md)** — Event schemas, DB schemas, complete SQL query list, state machines.
- **[docs/ai-traces.md](docs/ai-traces.md)** — Step-by-step execution paths with file:line references for every flow (buy, sell, risk rejection, errors, startup).
- **[docs/ai-troubleshooting.md](docs/ai-troubleshooting.md)** — Known failure modes, symptoms, root causes, fixes, debugging patterns.
- **[docs/ai-extending.md](docs/ai-extending.md)** — How to add strategies, events, components, DB tables, config, risk checks.

## Architecture

Event-driven graph: independent component nodes communicate via typed events on a shared async EventBus. Single process, single-threaded asyncio.

```
OrderRequest → RiskManager.check() → CoinbaseClient → OrderFilled → PositionTracker → PositionChanged
```

Key files: `src/main.py` (wiring + CLI), `src/event_bus.py` (pub/sub), `src/events.py` (7 event types), `src/strategy.py` (Strategy ABC), `src/registry.py` (strategy + LLM provider registries).

## Conventions

- Components use constructor injection + `register(bus)` for event subscriptions
- Events are frozen dataclasses in `src/events.py`
- Tests use in-memory SQLite (`Database(":memory:")`) and `MagicMock` for Coinbase
- Async tests auto-detected via `asyncio_mode = "auto"` in pyproject.toml
- All DB writes auto-commit per call
- IDs are UUID4 strings, timestamps are ISO 8601 UTC, prices are floats internally / strings to Coinbase API
