# Run Reporter Design

**Date**: 2026-02-15
**Status**: Approved

## Goal

Periodically commit trading bot run data to the git repository so performance is visible on GitHub without SSH access. Tracks strategy, LLM provider, model, product_id, and P/L metrics.

## Approach

Append-only CSV file (`runs/performance.csv`), auto-committed and pushed hourly. GitHub renders CSV as a native table.

## Architecture

New `RunReporter` component — a timer-driven node (like `PortfolioTracker`). No EventBus subscription needed.

```
                  ┌─────────────┐
                  │  main.py    │
                  │  (wiring)   │
                  └──────┬──────┘
                         │ constructs with:
                         │  strategy, llm, model, product_id
                         ▼
                  ┌─────────────┐
                  │ RunReporter │──── async loop (hourly)
                  │             │        │
                  │  db ────────┤        ▼
                  │  run_meta   │   1. Query DB for P/L, trades, fees
                  └─────────────┘   2. Append row to runs/performance.csv
                                    3. git add + commit + push
```

## CSV Schema

```
timestamp,strategy,llm_provider,model,product_id,daily_pnl,unrealized_pnl,num_trades,fees_paid,portfolio_value,open_positions
```

## Component: `src/run_reporter.py`

```python
class RunReporter:
    def __init__(self, db, strategy, llm_provider, model, product_id, repo_path):
        ...

    async def start(self):
        """Start the hourly reporting loop."""

    async def _report_loop(self):
        """Every hour: query DB, append CSV, git commit+push."""

    async def _append_csv(self, row: dict):
        """Append row to runs/performance.csv, create with header if missing."""

    async def _git_push(self):
        """git add + commit + push the CSV file."""
```

## Wiring (main.py)

```python
reporter = RunReporter(
    db=db,
    strategy=args.strategy,
    llm_provider=args.llm,
    model=args.model,
    product_id=settings.product_id,
    repo_path=Path(__file__).resolve().parent.parent,
)
await reporter.start()
```

## Data Queries (each hour)

1. `daily_summary` → today's `total_pnl`, `num_trades`, `fees_paid`
2. `portfolio_snapshots` → latest `total_value_usd`, `unrealized_pnl`
3. `positions` → count of open positions

## Edge Cases

- **First run**: Creates `runs/` directory and CSV with header row
- **Git push fails**: Log warning, don't crash the bot. CSV still accumulates locally.
- **No trades yet**: Writes a row with zeros — shows the bot is alive
- **`.gitignore`**: Ensure `runs/` is NOT gitignored

## Testing

- Unit test: mock DB queries, verify CSV output format
- Unit test: verify header creation on first write
- Unit test: verify git failure is handled gracefully (logged, not raised)

## Decisions

- **Format**: CSV (GitHub renders natively, append-only avoids merge conflicts)
- **Frequency**: Hourly
- **Prompt versioning**: Deferred to future iteration
