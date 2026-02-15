# Event & Data Reference

## Events (src/events.py)

All events are `@dataclass(frozen=True)` — immutable after creation.

### PriceUpdate
```
product_id: str     # "BTC-USD"
price: float        # 50123.45
timestamp: str      # ISO 8601 from WebSocket
```
Published by: MarketData._on_message
Consumed by: (none — future strategy layer)

### OrderRequest
```
product_id: str                    # "BTC-USD"
side: str                          # "BUY" or "SELL"
order_type: str                    # "MARKET" or "LIMIT"
quote_size: Optional[float]        # USD amount for market buys
base_size: Optional[float]         # asset amount for sells and limit orders
limit_price: Optional[float]       # required for LIMIT orders
order_id: str = uuid4()            # auto-generated, used as client_order_id
```
Published by: (external — strategy layer)
Consumed by: OrderManager._handle_order_request

Field usage by order type:
- MARKET BUY: quote_size required, base_size=None
- MARKET SELL: base_size required, quote_size=None
- LIMIT BUY/SELL: base_size + limit_price required

### OrderFilled
```
order_id: str              # matches OrderRequest.order_id
product_id: str
side: str                  # "BUY" or "SELL"
filled_price: float        # from Coinbase get_order average_filled_price
filled_qty: float          # from Coinbase get_order filled_size
fee: float                 # from Coinbase get_order total_fees
coinbase_order_id: str     # Coinbase's order ID
```
Published by: OrderManager._handle_order_request
Consumed by: PositionTracker._handle_order_filled

### OrderFailed
```
order_id: str
reason: str     # e.g., "INSUFFICIENT_FUND", exception message
```
Published by: OrderManager._handle_order_request
Consumed by: (none)

### RiskViolation
```
order_id: str
reason: str     # e.g., "Kill switch is active", "Order $200.00 exceeds max..."
```
Published by: RiskManager.check
Consumed by: (none)

### PositionChanged
```
position_id: str
product_id: str
side: str           # always "LONG" currently
quantity: float     # remaining quantity (0.0 if closed)
entry_price: float  # weighted average entry
status: str         # "OPEN" or "CLOSED"
```
Published by: PositionTracker._open_or_add_position, _reduce_or_close_position
Consumed by: (none)

### KillSwitchActivated
```
reason: str     # e.g., "Daily loss $600.00 exceeded limit $500.00"
```
Published by: KillSwitch.activate
Consumed by: (none)

---

## Database Schema (src/db.py SCHEMA)

### positions
```sql
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,              -- UUID from PositionTracker
    product_id TEXT NOT NULL,         -- "BTC-USD"
    side TEXT NOT NULL,               -- always "LONG" currently
    entry_price REAL NOT NULL,        -- weighted average entry price
    quantity REAL NOT NULL,           -- current holding amount
    status TEXT NOT NULL DEFAULT 'OPEN',  -- "OPEN" or "CLOSED"
    realized_pnl REAL DEFAULT 0.0,   -- accumulated realized P&L
    opened_at TEXT NOT NULL,          -- ISO 8601 UTC
    closed_at TEXT                    -- ISO 8601 UTC, NULL while open
);
```
Written by: PositionTracker._open_or_add_position (INSERT/UPDATE), _reduce_or_close_position (UPDATE)
Read by: PositionTracker (SELECT for open position lookup)

### orders
```sql
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,              -- UUID from OrderRequest.order_id
    position_id TEXT,                 -- FK to positions.id, set by PositionTracker
    product_id TEXT NOT NULL,
    side TEXT NOT NULL,               -- "BUY" or "SELL"
    type TEXT NOT NULL,               -- "MARKET" or "LIMIT"
    price REAL,                       -- limit_price for limit orders, NULL for market
    quantity REAL NOT NULL,           -- quote_size or base_size from OrderRequest
    status TEXT NOT NULL DEFAULT 'PENDING',  -- "PENDING", "FILLED", "CANCELLED", "FAILED"
    coinbase_id TEXT,                 -- Coinbase order ID
    filled_price REAL,               -- actual fill price
    filled_qty REAL,                 -- actual fill quantity
    fee REAL,                        -- fee charged
    created_at TEXT NOT NULL,         -- ISO 8601 UTC
    filled_at TEXT,                   -- ISO 8601 UTC
    FOREIGN KEY (position_id) REFERENCES positions(id)  -- NOT ENFORCED (SQLite default)
);
```
Written by: OrderManager._persist_order (INSERT), PositionTracker._upsert_order (INSERT or UPDATE)
Read by: PositionTracker (SELECT SUM(fee) for buy-side fee calculation)

IMPORTANT: Both OrderManager and PositionTracker write to this table.
- OrderManager INSERTs on order placement (before fill)
- PositionTracker UPSERTs on fill (sets position_id, updates fill details)
- PositionTracker._upsert_order handles the case where the order row already exists (UPDATE) or doesn't (INSERT)

### daily_summary
```sql
CREATE TABLE IF NOT EXISTS daily_summary (
    date TEXT PRIMARY KEY,            -- "2026-02-14" (ISO date)
    total_pnl REAL DEFAULT 0.0,      -- accumulated realized P&L for the day
    num_trades INTEGER DEFAULT 0,     -- count of completed round-trips
    fees_paid REAL DEFAULT 0.0,       -- total fees (buy + sell)
    halted INTEGER DEFAULT 0          -- 1 if kill switch activated (NOT CURRENTLY USED)
);
```
Written by: PositionTracker._reduce_or_close_position (INSERT or UPDATE)
Read by: RiskManager.check (SELECT total_pnl for daily loss check)

### kill_switch
```sql
CREATE TABLE IF NOT EXISTS kill_switch (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton constraint
    active INTEGER DEFAULT 0,                -- 0=off, 1=on
    reason TEXT,                              -- why activated
    activated_at TEXT                         -- ISO 8601 UTC
);
-- Seeded on initialize:
INSERT OR IGNORE INTO kill_switch (id, active) VALUES (1, 0);
```
Written by: KillSwitch.activate (UPDATE), KillSwitch.deactivate (UPDATE)
Read by: KillSwitch.initialize (SELECT)

---

## SQL Queries Used (complete list)

### KillSwitch
```sql
-- initialize
SELECT active FROM kill_switch WHERE id = 1
-- activate
UPDATE kill_switch SET active = 1, reason = ?, activated_at = ? WHERE id = 1
-- deactivate
UPDATE kill_switch SET active = 0, reason = NULL, activated_at = NULL WHERE id = 1
```

### RiskManager
```sql
-- check daily P&L
SELECT total_pnl FROM daily_summary WHERE date = ?
```

### OrderManager
```sql
-- persist order
INSERT INTO orders (id, product_id, side, type, price, quantity, status,
    coinbase_id, filled_price, filled_qty, fee, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

### PositionTracker
```sql
-- upsert order (check exists)
SELECT id FROM orders WHERE id = ?
-- upsert order (update existing)
UPDATE orders SET status = 'FILLED', filled_price = ?, filled_qty = ?,
    fee = ?, coinbase_id = ?, filled_at = ? WHERE id = ?
-- upsert order (insert new)
INSERT INTO orders (id, product_id, side, type, quantity, status,
    filled_price, filled_qty, fee, coinbase_id, created_at, filled_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
-- find open position
SELECT id, entry_price, quantity FROM positions WHERE product_id = ? AND status = 'OPEN'
-- update position (average in)
UPDATE positions SET entry_price = ?, quantity = ? WHERE id = ?
-- insert new position
INSERT INTO positions (id, product_id, side, entry_price, quantity, status, opened_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
-- link order to position
UPDATE orders SET position_id = ? WHERE id = ?
-- read position after update
SELECT quantity, entry_price FROM positions WHERE id = ?
-- buy fee lookup
SELECT COALESCE(SUM(fee), 0) FROM orders WHERE position_id = ? AND side = 'BUY'
-- close position
UPDATE positions SET status = 'CLOSED', quantity = 0, realized_pnl = ?, closed_at = ? WHERE id = ?
-- partial close
UPDATE positions SET quantity = ?, realized_pnl = COALESCE(realized_pnl, 0) + ? WHERE id = ?
-- daily summary check
SELECT total_pnl, num_trades, fees_paid FROM daily_summary WHERE date = ?
-- daily summary update
UPDATE daily_summary SET total_pnl = total_pnl + ?, num_trades = num_trades + 1, fees_paid = fees_paid + ? WHERE date = ?
-- daily summary insert
INSERT INTO daily_summary (date, total_pnl, num_trades, fees_paid) VALUES (?, ?, 1, ?)
-- read entry_price for PositionChanged event
SELECT entry_price FROM positions WHERE id = ?
```

---

## State Machines

### Position Lifecycle
```
                BUY fill
(not exists) ──────────► OPEN
                              │
                    BUY fill  │  SELL fill (partial)
                    (average  │  (reduces qty, accumulates pnl)
                     in)      │
                    ◄─────────┤
                              │
                              │ SELL fill (qty → 0)
                              ▼
                           CLOSED
```

### Order Lifecycle
```
OrderRequest arrives
        │
        ▼
     PENDING ──(Coinbase fail)──► FAILED
        │
        │ (Coinbase success + get_order)
        ▼
      FILLED
```

### Kill Switch
```
     OFF ──(activate)──► ON
      ▲                   │
      └──(deactivate)─────┘

Triggers: manual activate(), or RiskManager detects daily loss exceeded
Persists: survives restart via DB
```
