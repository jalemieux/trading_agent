# Smoke Test Script Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an interactive CLI script that validates the full trading bot plumbing against the live Coinbase API — connectivity, market data, buy, hold, sell — with SOL-USDC.

**Architecture:** Single script `scripts/smoke_test.py` that reuses all existing components (EventBus, OrderManager, PositionTracker, RiskManager, etc.) wired identically to `main.py`, but with interactive stage prompts and colored output. Uses a separate `smoke_test.db` to isolate from production.

**Tech Stack:** Python 3.12+, asyncio, existing src modules, ANSI escape codes for color

---

### Task 1: Create scripts directory and smoke test skeleton

**Files:**
- Create: `scripts/smoke_test.py`

**Step 1: Write the script skeleton with helpers and component wiring**

```python
#!/usr/bin/env python3
"""Interactive smoke test for trading bot plumbing."""

import asyncio
import logging
import os
import sys

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.coinbase_client import CoinbaseClient
from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFilled, OrderRequest, PositionChanged
from src.kill_switch import KillSwitch
from src.market_data import MarketData
from src.order_manager import OrderManager
from src.position_tracker import PositionTracker
from src.risk_manager import RiskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("smoke_test")

# --- Constants ---
PRODUCT_ID = "SOL-USDC"
BUY_QUOTE_USD = 1.0  # $1 worth of SOL
SMOKE_DB = "smoke_test.db"

# --- ANSI Colors ---
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓ {msg}{RESET}")


def fail(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}")


def info(msg: str) -> None:
    print(f"  {CYAN}ℹ {msg}{RESET}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠ {msg}{RESET}")


def header(stage: int, title: str) -> None:
    print(f"\n{BOLD}{'='*50}")
    print(f"  Stage {stage}: {title}")
    print(f"{'='*50}{RESET}\n")


def prompt_continue() -> bool:
    """Prompt user to continue or quit. Returns True to continue."""
    try:
        resp = input(f"\n  {YELLOW}[Enter to continue / q to quit]{RESET} ")
        return resp.strip().lower() != "q"
    except (EOFError, KeyboardInterrupt):
        return False


async def run() -> None:
    print(f"\n{BOLD}{CYAN}Coinbase Trading Bot — Smoke Test{RESET}")
    print(f"{CYAN}Product: {PRODUCT_ID} | Trade size: ${BUY_QUOTE_USD}{RESET}\n")

    # Load settings (override DB path and risk limits for safety)
    settings = Settings()
    settings.db_path = SMOKE_DB
    settings.max_order_size_usd = 10.0
    settings.max_daily_loss_usd = 50.0

    # Wire components identically to main.py
    bus = EventBus()
    db = Database(SMOKE_DB)
    await db.initialize()

    kill_switch = KillSwitch(db=db, bus=bus)
    await kill_switch.initialize()
    if kill_switch.is_active:
        warn("Kill switch active from previous run — deactivating")
        await kill_switch.deactivate()

    risk_manager = RiskManager(db=db, bus=bus, kill_switch=kill_switch, settings=settings)

    coinbase = CoinbaseClient(
        api_key=settings.coinbase_api_key,
        api_secret=settings.coinbase_api_secret,
    )

    order_manager = OrderManager(db=db, bus=bus, risk_manager=risk_manager, coinbase=coinbase)
    order_manager.register(bus)

    position_tracker = PositionTracker(db=db, bus=bus)
    position_tracker.register(bus)

    market_data = MarketData(
        bus=bus,
        api_key=settings.coinbase_api_key,
        api_secret=settings.coinbase_api_secret,
    )

    # Collectors for events during each stage
    filled_events: list[OrderFilled] = []
    position_events: list[PositionChanged] = []

    async def collect_filled(e: OrderFilled) -> None:
        filled_events.append(e)

    async def collect_position(e: PositionChanged) -> None:
        position_events.append(e)

    bus.subscribe(OrderFilled, collect_filled)
    bus.subscribe(PositionChanged, collect_position)

    try:
        # --- Stage 1: Connectivity ---
        await stage_connectivity(coinbase)
        if not prompt_continue():
            return

        # --- Stage 2: Market Data ---
        await stage_market_data(market_data, bus)
        if not prompt_continue():
            return

        # --- Stage 3: Buy ---
        filled_events.clear()
        position_events.clear()
        await stage_buy(bus, filled_events, position_events)
        if not prompt_continue():
            return

        # --- Stage 4: Verify Position ---
        await stage_verify_position(db)
        if not prompt_continue():
            return

        # --- Stage 5: Hold ---
        await stage_hold(db)
        if not prompt_continue():
            return

        # --- Stage 6: Sell ---
        filled_events.clear()
        position_events.clear()
        buy_qty = await get_open_position_qty(db)
        await stage_sell(bus, buy_qty, filled_events, position_events)
        if not prompt_continue():
            return

        # --- Stage 7: Summary ---
        await stage_summary(db)

    finally:
        await market_data.stop()
        await db.close()
        print(f"\n{CYAN}Smoke test complete. Database saved to {SMOKE_DB}{RESET}\n")


# --- Placeholder stage functions (implemented in subsequent tasks) ---

async def stage_connectivity(coinbase: CoinbaseClient) -> None:
    pass

async def stage_market_data(market_data: MarketData, bus: EventBus) -> None:
    pass

async def stage_buy(bus: EventBus, filled: list, positions: list) -> None:
    pass

async def stage_verify_position(db: Database) -> None:
    pass

async def stage_hold(db: Database) -> None:
    pass

async def get_open_position_qty(db: Database) -> float:
    return 0.0

async def stage_sell(bus: EventBus, qty: float, filled: list, positions: list) -> None:
    pass

async def stage_summary(db: Database) -> None:
    pass


if __name__ == "__main__":
    asyncio.run(run())
```

**Step 2: Run to verify it loads and exits cleanly**

Run: `python scripts/smoke_test.py` (then press `q` at first prompt)
Expected: Shows header, Stage 1 placeholder runs, prompts to continue, exits on `q`.

**Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "feat: smoke test skeleton with component wiring"
```

---

### Task 2: Implement Stage 1 — Connectivity

**Files:**
- Modify: `scripts/smoke_test.py`

**Step 1: Implement `stage_connectivity`**

Replace the placeholder with:

```python
async def stage_connectivity(coinbase: CoinbaseClient) -> None:
    header(1, "Connectivity")

    # Test 1: Get accounts
    info("Fetching accounts...")
    try:
        accounts_resp = coinbase.get_accounts()
        accounts = accounts_resp.get("accounts", [])
        ok(f"Connected — {len(accounts)} account(s) found")
        for acct in accounts:
            currency = acct.get("currency", "?")
            available = acct.get("available_balance", {}).get("value", "0")
            if float(available) > 0:
                info(f"  {currency}: {available}")
    except Exception as e:
        fail(f"get_accounts() failed: {e}")
        return

    # Test 2: Get product info
    info(f"Fetching product info for {PRODUCT_ID}...")
    try:
        product = coinbase.get_product(PRODUCT_ID)
        price = product.get("price", "?")
        status = product.get("status", "?")
        base_min = product.get("base_min_size", "?")
        quote_min = product.get("quote_min_size", "?")
        ok(f"{PRODUCT_ID} — price: ${price}, status: {status}")
        info(f"  min base: {base_min}, min quote: {quote_min}")
    except Exception as e:
        fail(f"get_product() failed: {e}")
```

**Step 2: Run smoke test, verify Stage 1 shows account info and product info**

Run: `python scripts/smoke_test.py` (then `q` after Stage 1)
Expected: Green checkmarks with account balances and SOL-USDC product info.

**Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "feat: smoke test stage 1 — connectivity check"
```

---

### Task 3: Implement Stage 2 — Market Data

**Files:**
- Modify: `scripts/smoke_test.py`

**Step 1: Implement `stage_market_data`**

Replace the placeholder with:

```python
async def stage_market_data(market_data: MarketData, bus: EventBus) -> None:
    header(2, "Market Data (WebSocket)")

    prices: list[float] = []
    price_event = asyncio.Event()

    async def on_price(event):
        prices.append(event.price)
        info(f"  tick #{len(prices)}: {event.product_id} = ${event.price}")
        if len(prices) >= 3:
            price_event.set()

    bus.subscribe(PriceUpdate, on_price)

    info(f"Subscribing to {PRODUCT_ID} ticker...")
    try:
        await market_data.start([PRODUCT_ID])
        ok("WebSocket opened")
    except Exception as e:
        fail(f"WebSocket failed to open: {e}")
        bus.unsubscribe(PriceUpdate, on_price)
        return

    info("Waiting for 3 price ticks (30s timeout)...")
    try:
        await asyncio.wait_for(price_event.wait(), timeout=30.0)
        ok(f"Received {len(prices)} ticks — market data working")
    except asyncio.TimeoutError:
        warn(f"Only received {len(prices)} ticks in 30s")

    bus.unsubscribe(PriceUpdate, on_price)

    # Stop market data after test
    await market_data.stop()
    ok("WebSocket closed")
```

Also add `PriceUpdate` to the imports at the top (it's already in `src.events`).

**Step 2: Run smoke test through Stage 2**

Run: `python scripts/smoke_test.py` (continue through Stage 1, watch Stage 2 for ticks, then `q`)
Expected: WebSocket opens, 3 price ticks displayed, closes cleanly.

**Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "feat: smoke test stage 2 — market data websocket"
```

---

### Task 4: Implement Stage 3 — Buy

**Files:**
- Modify: `scripts/smoke_test.py`

**Step 1: Implement `stage_buy`**

Replace the placeholder with:

```python
async def stage_buy(
    bus: EventBus,
    filled: list[OrderFilled],
    positions: list[PositionChanged],
) -> None:
    header(3, "Buy")

    info(f"Placing market buy: ${BUY_QUOTE_USD} of {PRODUCT_ID}")
    warn(f"This will spend real money (${BUY_QUOTE_USD})")

    order = OrderRequest(
        product_id=PRODUCT_ID,
        side="BUY",
        order_type="MARKET",
        quote_size=BUY_QUOTE_USD,
    )
    info(f"Order ID: {order.order_id}")

    await bus.publish(order)

    # Wait briefly for event propagation
    await asyncio.sleep(2.0)

    if filled:
        f = filled[0]
        ok(f"Order filled: {f.filled_qty} SOL @ ${f.filled_price:.4f}")
        info(f"  Fee: ${f.fee:.6f}")
        info(f"  Coinbase order ID: {f.coinbase_order_id}")
    else:
        fail("No OrderFilled event received — check logs above for errors")

    if positions:
        p = positions[0]
        ok(f"Position opened: {p.quantity} SOL, entry ${p.entry_price:.4f}, status={p.status}")
    else:
        warn("No PositionChanged event received")
```

**Step 2: Run smoke test through Stage 3**

Run: `python scripts/smoke_test.py` (continue through Stages 1-2, execute buy at Stage 3, then `q`)
Expected: Order placed, filled event with qty/price, position opened.

**Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "feat: smoke test stage 3 — market buy"
```

---

### Task 5: Implement Stages 4 & 5 — Verify Position and Hold

**Files:**
- Modify: `scripts/smoke_test.py`

**Step 1: Implement `stage_verify_position`, `stage_hold`, and `get_open_position_qty`**

Replace the placeholders with:

```python
async def stage_verify_position(db: Database) -> None:
    header(4, "Verify Position")

    row = await db.execute_fetchone(
        "SELECT id, product_id, entry_price, quantity, status FROM positions WHERE product_id = ? AND status = 'OPEN'",
        (PRODUCT_ID,),
    )
    if row:
        pos_id, product, entry, qty, status = row
        ok(f"Open position found in DB")
        info(f"  Position ID: {pos_id}")
        info(f"  Product:     {product}")
        info(f"  Entry price: ${entry:.4f}")
        info(f"  Quantity:    {qty}")
        info(f"  Status:      {status}")
    else:
        fail(f"No open position for {PRODUCT_ID} in DB")

    # Check order record
    orders = await db.execute_fetchall(
        "SELECT id, side, status, filled_price, filled_qty, fee, coinbase_id FROM orders WHERE product_id = ? ORDER BY created_at DESC LIMIT 1",
        (PRODUCT_ID,),
    )
    if orders:
        o = orders[0]
        ok(f"Order record in DB: side={o[1]}, status={o[2]}, filled_price=${o[3]:.4f}, qty={o[4]}, fee=${o[5]:.6f}")
        info(f"  Coinbase ID: {o[6]}")
    else:
        warn("No order record found in DB")


async def stage_hold(db: Database) -> None:
    header(5, "Hold")

    row = await db.execute_fetchone(
        "SELECT entry_price, quantity FROM positions WHERE product_id = ? AND status = 'OPEN'",
        (PRODUCT_ID,),
    )
    if row:
        entry, qty = row
        value = entry * qty
        info(f"Holding {qty} SOL @ ${entry:.4f} (value ≈ ${value:.2f})")
        ok("Position remains open — hold confirmed")
    else:
        fail("No open position to hold")


async def get_open_position_qty(db: Database) -> float:
    row = await db.execute_fetchone(
        "SELECT quantity FROM positions WHERE product_id = ? AND status = 'OPEN'",
        (PRODUCT_ID,),
    )
    return row[0] if row else 0.0
```

**Step 2: Run smoke test through Stages 4-5**

Run: `python scripts/smoke_test.py` (run full buy, verify position, hold, then `q`)
Expected: DB position shown with entry price/qty, hold confirmed.

**Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "feat: smoke test stages 4-5 — verify position and hold"
```

---

### Task 6: Implement Stage 6 — Sell

**Files:**
- Modify: `scripts/smoke_test.py`

**Step 1: Implement `stage_sell`**

Replace the placeholder with:

```python
async def stage_sell(
    bus: EventBus,
    qty: float,
    filled: list[OrderFilled],
    positions: list[PositionChanged],
) -> None:
    header(6, "Sell")

    if qty <= 0:
        fail("No position to sell — skipping")
        return

    info(f"Placing market sell: {qty} SOL of {PRODUCT_ID}")
    warn("This will sell real assets")

    order = OrderRequest(
        product_id=PRODUCT_ID,
        side="SELL",
        order_type="MARKET",
        base_size=qty,
    )
    info(f"Order ID: {order.order_id}")

    await bus.publish(order)

    # Wait for event propagation
    await asyncio.sleep(2.0)

    if filled:
        f = filled[0]
        ok(f"Sell filled: {f.filled_qty} SOL @ ${f.filled_price:.4f}")
        info(f"  Fee: ${f.fee:.6f}")
        info(f"  Coinbase order ID: {f.coinbase_order_id}")
    else:
        fail("No OrderFilled event received for sell — check logs")

    if positions:
        p = positions[-1]
        ok(f"Position status: {p.status} (qty={p.quantity})")
    else:
        warn("No PositionChanged event received")
```

**Step 2: Run full smoke test through Stage 6**

Run: `python scripts/smoke_test.py` (run all stages through sell, then `q`)
Expected: Sell fills, position shows CLOSED.

**Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "feat: smoke test stage 6 — market sell"
```

---

### Task 7: Implement Stage 7 — Summary

**Files:**
- Modify: `scripts/smoke_test.py`

**Step 1: Implement `stage_summary`**

Replace the placeholder with:

```python
async def stage_summary(db: Database) -> None:
    header(7, "Summary")

    # Position final state
    row = await db.execute_fetchone(
        "SELECT entry_price, quantity, status, realized_pnl FROM positions WHERE product_id = ? ORDER BY opened_at DESC LIMIT 1",
        (PRODUCT_ID,),
    )
    if row:
        entry, qty, status, pnl = row
        info(f"Position: {status}")
        info(f"  Entry price:  ${entry:.4f}")
        info(f"  Final qty:    {qty}")
        pnl = pnl or 0.0
        color = GREEN if pnl >= 0 else RED
        print(f"  {color}{BOLD}  Realized P&L: ${pnl:.6f}{RESET}")

    # Daily summary
    from datetime import date
    today = date.today().isoformat()
    daily = await db.execute_fetchone(
        "SELECT total_pnl, num_trades, fees_paid FROM daily_summary WHERE date = ?",
        (today,),
    )
    if daily:
        total_pnl, trades, fees = daily
        info(f"Daily summary ({today}):")
        info(f"  Trades:    {trades}")
        info(f"  Total P&L: ${total_pnl:.6f}")
        info(f"  Fees paid: ${fees:.6f}")
    else:
        info("No daily summary yet (position may not have been closed)")

    # All orders
    orders = await db.execute_fetchall(
        "SELECT side, status, filled_price, filled_qty, fee FROM orders WHERE product_id = ? ORDER BY created_at",
        (PRODUCT_ID,),
    )
    if orders:
        info(f"Orders ({len(orders)} total):")
        for o in orders:
            info(f"  {o[0]} | {o[1]} | price=${o[2]:.4f} | qty={o[3]} | fee=${o[4]:.6f}")

    ok("Smoke test complete — all plumbing validated")
```

**Step 2: Run full end-to-end smoke test**

Run: `python scripts/smoke_test.py` (run all 7 stages)
Expected: Full buy → hold → sell → summary with P&L and fees displayed.

**Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "feat: smoke test stage 7 — summary and P&L report"
```

---

### Task 8: Update documentation

**Files:**
- Modify: `docs/architecture.md` — add smoke test to component table and testing section
- Modify: `README.md` — add smoke test usage instructions

**Step 1: Add smoke test section to architecture.md**

Add to the component table:
```markdown
| Smoke Test | `scripts/smoke_test.py` | Interactive live plumbing validation — buy/sell/hold lifecycle |
```

**Step 2: Add to README.md**

Add under testing section:
```markdown
### Live Smoke Test

Validates the full trading pipeline against the real Coinbase API:

```bash
python scripts/smoke_test.py
```

Walks through 7 stages interactively:
1. **Connectivity** — API keys, account info, product lookup
2. **Market Data** — WebSocket ticker subscription
3. **Buy** — Market buy $1 of SOL-USDC
4. **Verify** — Check position in DB
5. **Hold** — Confirm position stays open
6. **Sell** — Market sell all SOL
7. **Summary** — P&L, fees, final state

Requires `.env` with valid `COINBASE_API_KEY` and `COINBASE_API_SECRET`.
Uses a separate `smoke_test.db` database.
```

**Step 3: Commit**

```bash
git add docs/architecture.md README.md
git commit -m "docs: add smoke test to architecture and README"
```
