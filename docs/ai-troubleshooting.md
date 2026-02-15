# Troubleshooting Guide

Known failure modes, symptoms, root causes, and fixes.

---

## Startup Failures

### Bot crashes immediately with ModuleNotFoundError
```
Symptom: ModuleNotFoundError: No module named 'src'
Cause: Package not installed in editable mode
Fix: .venv/bin/pip install -e ".[dev]"
```

### Bot crashes with pydantic ValidationError
```
Symptom: ValidationError on Settings()
Cause: .env file has malformed values (e.g., non-numeric MAX_ORDER_SIZE_USD)
Fix: Check .env against .env.example, ensure all values are correct types
```

### "Kill switch is ACTIVE from previous session" warning
```
Symptom: WARNING log on startup, all orders will be blocked
Cause: kill_switch table has active=1 from a previous run
Fix: sqlite3 trading_bot.db "UPDATE kill_switch SET active=0, reason=NULL WHERE id=1"
Or: programmatically call kill_switch.deactivate()
```

---

## Order Failures

### Orders silently rejected (no Coinbase call)
```
Symptom: OrderRequest published but no OrderFilled/OrderFailed emitted, Coinbase never called
Cause: RiskManager.check() returned False
Debug:
  1. Check kill_switch: SELECT active FROM kill_switch WHERE id=1
  2. Check daily P&L: SELECT total_pnl FROM daily_summary WHERE date='YYYY-MM-DD'
  3. Check order size: Is quote_size > max_order_size_usd?
  4. Subscribe to RiskViolation events to see rejection reasons
```

### OrderFailed with "INSUFFICIENT_FUND"
```
Symptom: OrderFailed event with reason containing "INSUFFICIENT_FUND"
Cause: Coinbase account doesn't have enough funds for the order
Fix: Check account balances via coinbase.get_accounts()
```

### Order placed but OrderFilled has filled_price=0
```
Symptom: OrderFilled event with filled_price=0.0 or filled_qty=0.0
Cause: get_order() returned before fill completed, or response format changed
Root: order_manager.py:60-62 uses .get() with default 0
Debug: Log the raw get_order response
Fix: Add polling/retry for order status before reading fill details
```

### OrderFailed on exception (no order persisted)
```
Symptom: OrderFailed event but no row in orders table
Cause: CoinbaseClient method raised exception (network error, etc.)
Root: order_manager.py:43-46 catches exception and publishes OrderFailed, but _persist_order is not called in this path
Fix: If you need failed orders in DB, add _persist_order call before the return in the exception handler
```

---

## Position/P&L Issues

### Sell without open position (warning logged)
```
Symptom: WARNING "Sell for BTC-USD but no open position found"
Cause: SELL fill received but no OPEN position for that product_id
Possible reasons:
  - Position was already closed by a previous sell
  - SELL order placed manually on Coinbase without corresponding position in DB
  - DB was reset/deleted between buy and sell
Root: position_tracker.py:102-104
```

### P&L calculation seems wrong
```
P&L formula (position_tracker.py:111-120):
  pnl = (sell_price - entry_price) * sell_qty - sell_fee - proportional_buy_fee
  proportional_buy_fee = total_buy_fees_for_position * (sell_qty / position_qty)

Common confusion:
  - Both buy AND sell fees are deducted from P&L
  - Buy fees are allocated proportionally based on what fraction of the position is being sold
  - For full close: 100% of buy fees deducted
  - For partial close: (sell_qty/total_qty)% of buy fees deducted

Debug: Check orders table for fee values:
  SELECT side, fee FROM orders WHERE position_id = '<pos_id>'
```

### daily_summary not updating
```
Symptom: daily_summary table empty or stale
Cause: Only updated on SELL fills that close/reduce a position
Root: position_tracker.py:146-160 — INSERT/UPDATE daily_summary only in _reduce_or_close_position
Note: BUY fills do NOT update daily_summary
```

### Floating point position not closing
```
Symptom: Position stays OPEN with tiny remaining quantity (e.g., 1e-15)
Cause: Floating point arithmetic leaves non-zero remainder
Guard: position_tracker.py:124 uses `remaining <= 1e-10` threshold
Fix: If threshold is too small for your use case, adjust the 1e-10 constant
```

---

## Database Issues

### "database is locked" error
```
Symptom: sqlite3.OperationalError: database is locked
Cause: Multiple processes accessing the same .db file, or long-running transaction
Fix:
  - Ensure only one bot instance runs per DB file
  - Database.execute() auto-commits after each call, so no long transactions
  - Consider WAL mode: PRAGMA journal_mode=WAL
```

### FK constraint not enforced
```
Symptom: orders.position_id references non-existent position but no error
Cause: SQLite FK enforcement is OFF by default
Root: db.py does not run PRAGMA foreign_keys = ON
Fix: Add `await self._conn.execute("PRAGMA foreign_keys = ON")` after connect in Database.initialize()
Note: This is by design currently — the app manages referential integrity
```

### Schema migration (adding columns)
```
Current: No migration system. Schema is CREATE TABLE IF NOT EXISTS.
To add a column:
  1. Add to SCHEMA in db.py (for new DBs)
  2. Write ALTER TABLE migration for existing DBs
  3. Run migration before initialize() or as part of it
Caution: SQLite ALTER TABLE only supports ADD COLUMN, not DROP/RENAME
```

---

## WebSocket Issues

### MarketData not receiving prices
```
Symptom: No PriceUpdate events after start()
Debug checklist:
  1. Was start(product_ids) called? (main.py does NOT call it currently)
  2. Are API keys valid? WSClient will silently fail with bad credentials
  3. Is the event loop running? _schedule_on_message checks self._loop
  4. Check for JSON parse errors in _on_message (silently returns on JSONDecodeError)
```

### "Event loop is not running" on stop()
```
Symptom: WSClientException: Event loop is not running
Cause: Calling stop() when WebSocket was never started, or after event loop closed
Fix: Already handled — market_data.py:58-61 wraps close() in try/except
```

---

## Test Issues

### Tests fail with "no module named src"
```
Fix: .venv/bin/pip install -e ".[dev]"
```

### Async test warnings
```
Symptom: DeprecationWarning about event loop or asyncio_mode
Fix: Ensure pyproject.toml has asyncio_mode = "auto" in [tool.pytest.ini_options]
```

### test_market_data uses sync loop
```
Note: test_market_data.py tests use asyncio.get_event_loop().run_until_complete() from sync functions
This is intentional — it tests _on_message directly without async test infrastructure
If this breaks in future Python versions, convert to async def tests with await
```

---

## Common Debugging Patterns

### Subscribe to events for visibility
```python
# In main.py or a debug script, add event listeners:
async def log_event(event):
    logger.info("EVENT: %s", event)

bus.subscribe(RiskViolation, log_event)
bus.subscribe(OrderFailed, log_event)
bus.subscribe(PositionChanged, log_event)
bus.subscribe(KillSwitchActivated, log_event)
```

### Query DB state
```sql
-- Open positions
SELECT * FROM positions WHERE status = 'OPEN';

-- Today's orders
SELECT * FROM orders WHERE created_at LIKE '2026-02-14%';

-- Kill switch state
SELECT * FROM kill_switch;

-- Daily P&L
SELECT * FROM daily_summary ORDER BY date DESC LIMIT 5;

-- Position with its orders
SELECT p.*, o.side, o.filled_price, o.fee
FROM positions p
JOIN orders o ON o.position_id = p.id
WHERE p.id = '<position_id>';
```

### Manually emit an order for testing
```python
import asyncio
from src.event_bus import EventBus
from src.events import OrderRequest

bus = EventBus()
# ... wire up components ...

await bus.publish(OrderRequest(
    product_id="BTC-USD",
    side="BUY",
    order_type="MARKET",
    quote_size=10.0,
))
```
