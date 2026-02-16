# Balance Pre-flight Check Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent failed BUY orders by checking available USDC balance before sending to Coinbase, sizing down when needed.

**Architecture:** PortfolioTracker exposes cached `quote_balance` property (already fetched every ~2 min). OrderManager reads it before placing buys. If balance < order size, size down. If balance < $1.00 minimum, reject.

**Tech Stack:** Python 3.12, asyncio, pytest, existing EventBus/events pattern

---

### Task 1: Expose quote_balance on PortfolioTracker

**Files:**
- Modify: `src/portfolio_tracker.py:21,80-81`
- Test: `tests/test_portfolio_tracker.py`

**Step 1: Write the failing test**

Add to `tests/test_portfolio_tracker.py`:

```python
async def test_quote_balance_property_updated_by_snapshot(db: Database):
    """quote_balance property reflects latest USDC balance after snapshot."""
    bus = EventBus()
    coinbase = _mock_coinbase([
        {"currency": "SOL", "available_balance": {"value": "1.0", "currency": "SOL"}},
        {"currency": "USDC", "available_balance": {"value": "42.50", "currency": "USDC"}},
    ])

    tracker = PortfolioTracker(
        db=db, bus=bus, coinbase=coinbase, product_id="SOL-USDC",
    )

    assert tracker.quote_balance == 0.0  # before any snapshot

    await db.execute(
        "INSERT INTO price_history (product_id, price, timestamp) VALUES (?, ?, ?)",
        ("SOL-USDC", 80.0, "2026-01-01T00:01:00Z"),
    )
    await tracker.take_snapshot()

    assert tracker.quote_balance == pytest.approx(42.50, abs=0.01)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_portfolio_tracker.py::test_quote_balance_property_updated_by_snapshot -v`
Expected: FAIL — `AttributeError: 'PortfolioTracker' object has no attribute 'quote_balance'`

**Step 3: Write minimal implementation**

In `src/portfolio_tracker.py`:

1. In `__init__`, add `self._quote_balance = 0.0` after `self._product_id = product_id` (after line 32).

2. In `take_snapshot()`, after `quote_balance` is computed (line 81), add `self._quote_balance = quote_balance`.

3. Add property after `__init__`:

```python
@property
def quote_balance(self) -> float:
    return self._quote_balance
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_portfolio_tracker.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/portfolio_tracker.py tests/test_portfolio_tracker.py
git commit -m "feat: expose quote_balance property on PortfolioTracker"
```

---

### Task 2: Add balance pre-flight check to OrderManager

**Files:**
- Modify: `src/order_manager.py:5,22-27,37-48`
- Test: `tests/test_order_manager.py`

**Step 1: Write the failing tests**

Add to `tests/test_order_manager.py`:

First, update the `order_manager` fixture and add a `mock_portfolio_tracker` fixture:

```python
from src.portfolio_tracker import PortfolioTracker

@pytest.fixture
def mock_portfolio_tracker():
    mock = MagicMock(spec=PortfolioTracker)
    mock.quote_balance = 1000.0  # plenty of balance by default
    return mock

@pytest.fixture
async def order_manager(db, bus, risk_manager, mock_coinbase, mock_portfolio_tracker):
    om = OrderManager(
        db=db, bus=bus, risk_manager=risk_manager,
        coinbase=mock_coinbase, portfolio_tracker=mock_portfolio_tracker,
    )
    om.register(bus)
    return om
```

Then add three new tests:

```python
async def test_buy_rejected_when_balance_below_minimum(
    order_manager, bus, mock_coinbase, mock_portfolio_tracker,
):
    """BUY rejected when USDC balance < $1.00 minimum."""
    mock_portfolio_tracker.quote_balance = 0.50

    failed_events = []
    bus.subscribe(OrderFailed, lambda e: failed_events.append(e))

    order = OrderRequest(
        product_id="SOL-USDC", side="BUY", order_type="MARKET", quote_size=50.0,
    )
    await bus.publish(order)

    mock_coinbase.market_buy.assert_not_called()
    assert len(failed_events) == 1
    assert "Insufficient" in failed_events[0].reason


async def test_buy_sized_down_when_balance_below_order_size(
    order_manager, bus, mock_coinbase, mock_portfolio_tracker,
):
    """BUY sized down to available balance when < quote_size."""
    mock_portfolio_tracker.quote_balance = 25.0

    mock_coinbase.market_buy.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-sized"},
    }
    mock_coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-sized",
            "filled_size": "0.3",
            "average_filled_price": "83.0",
            "total_fees": "0.05",
        }
    }

    order = OrderRequest(
        product_id="SOL-USDC", side="BUY", order_type="MARKET", quote_size=50.0,
    )
    await bus.publish(order)

    mock_coinbase.market_buy.assert_called_once()
    call_kwargs = mock_coinbase.market_buy.call_args
    assert call_kwargs.kwargs["quote_size"] == "25.0" or call_kwargs[1]["quote_size"] == "25.0"


async def test_sell_bypasses_balance_check(
    order_manager, bus, mock_coinbase, mock_portfolio_tracker,
):
    """SELL orders skip balance check entirely."""
    mock_portfolio_tracker.quote_balance = 0.0  # zero USDC

    mock_coinbase.market_sell.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-sell"},
    }
    mock_coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-sell",
            "filled_size": "1.0",
            "average_filled_price": "85.0",
            "total_fees": "0.10",
        }
    }

    order = OrderRequest(
        product_id="SOL-USDC", side="SELL", order_type="MARKET", base_size=1.0,
    )
    await bus.publish(order)

    mock_coinbase.market_sell.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_order_manager.py::test_buy_rejected_when_balance_below_minimum tests/test_order_manager.py::test_buy_sized_down_when_balance_below_order_size tests/test_order_manager.py::test_sell_bypasses_balance_check -v`
Expected: FAIL — `TypeError: OrderManager.__init__() got an unexpected keyword argument 'portfolio_tracker'`

**Step 3: Write minimal implementation**

In `src/order_manager.py`:

1. Add import at top:
```python
from src.portfolio_tracker import PortfolioTracker
```

2. Update `__init__` to accept `portfolio_tracker`:
```python
def __init__(
    self,
    db: Database,
    bus: EventBus,
    risk_manager: RiskManager,
    coinbase: CoinbaseClient,
    portfolio_tracker: PortfolioTracker,
) -> None:
    self._db = db
    self._bus = bus
    self._risk = risk_manager
    self._coinbase = coinbase
    self._portfolio_tracker = portfolio_tracker
```

3. Add balance check in `_handle_order_request`, after risk check passes and before placing order (between lines 43 and 45). Replace the existing order placement block:

```python
    now = datetime.now(timezone.utc).isoformat()

    # Balance pre-flight check (buys only)
    effective_quote_size = order.quote_size
    if order.side == "BUY" and order.quote_size is not None:
        available = self._portfolio_tracker.quote_balance
        if available < 1.0:
            reason = f"Insufficient balance: ${available:.2f} available (minimum $1.00)"
            logger.warning("Order SKIPPED: BUY %s — %s", order.product_id, reason)
            await self._persist_order(order, now, status="FAILED")
            await self._bus.publish(OrderFailed(order_id=order.order_id, reason=reason))
            return
        if available < order.quote_size:
            logger.info(
                "Order sized down: $%.2f → $%.2f (available balance)",
                order.quote_size, available,
            )
            effective_quote_size = available

    # Place order
    try:
        if order.order_type == "MARKET":
            result = self._place_market_order(order, effective_quote_size)
        else:
            result = self._place_limit_order(order)
    except Exception as e:
```

4. Update `_place_market_order` to accept `effective_quote_size`:

```python
def _place_market_order(self, order: OrderRequest, effective_quote_size: float | None = None) -> dict:
    if order.side == "BUY":
        return self._coinbase.market_buy(
            client_order_id=order.order_id,
            product_id=order.product_id,
            quote_size=str(effective_quote_size if effective_quote_size is not None else order.quote_size),
        )
    else:
        return self._coinbase.market_sell(
            client_order_id=order.order_id,
            product_id=order.product_id,
            base_size=str(order.base_size),
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_order_manager.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/order_manager.py tests/test_order_manager.py
git commit -m "feat: pre-flight balance check in OrderManager before buy orders"
```

---

### Task 3: Wire PortfolioTracker into OrderManager in main.py

**Files:**
- Modify: `src/main.py:80`

**Step 1: Update wiring**

In `src/main.py`, move `portfolio_tracker` creation before `order_manager` creation, and pass it:

```python
# Portfolio tracker (must be created before OrderManager)
portfolio_tracker = PortfolioTracker(
    db=db,
    bus=bus,
    coinbase=coinbase,
    product_id=settings.product_id,
    interval_seconds=settings.prediction_interval_minutes * 60,
)

# Order manager
order_manager = OrderManager(
    db=db, bus=bus, risk_manager=risk_manager,
    coinbase=coinbase, portfolio_tracker=portfolio_tracker,
)
order_manager.register(bus)
```

Remove the old `portfolio_tracker` creation block that was after `position_tracker`.

**Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "wire: pass PortfolioTracker to OrderManager in main.py"
```

---

### Task 4: Update documentation

**Files:**
- Modify: `docs/ai-components.md` — update OrderManager constructor docs
- Modify: `docs/ai-traces.md` — update buy flow with balance check step
- Modify: `docs/architecture.md` — add changelog entry

**Step 1: Update docs with new balance check behavior**

**Step 2: Commit**

```bash
git add docs/
git commit -m "docs: document balance pre-flight check in OrderManager"
```
