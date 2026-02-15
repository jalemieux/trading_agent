# Extension Guide

How to add new capabilities to the trading bot.

---

## Adding a Strategy (most common extension)

A strategy subscribes to PriceUpdate events and publishes OrderRequest events.

### Files to create
- `src/strategy_<name>.py`
- `tests/test_strategy_<name>.py`

### Template
```python
# src/strategy_example.py
from src.event_bus import EventBus
from src.events import PriceUpdate, OrderRequest

class ExampleStrategy:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def register(self, bus: EventBus) -> None:
        bus.subscribe(PriceUpdate, self._on_price)

    async def _on_price(self, event: PriceUpdate) -> None:
        # Your logic here
        if should_buy(event):
            await self._bus.publish(OrderRequest(
                product_id=event.product_id,
                side="BUY",
                order_type="MARKET",
                quote_size=50.0,
            ))
```

### Wire into main.py
```python
# After position_tracker.register(bus):
strategy = ExampleStrategy(bus=bus)
strategy.register(bus)

# Start market data for the products you want:
await market_data.start(product_ids=["BTC-USD"])
```

### Test pattern
```python
async def test_strategy_emits_order():
    bus = EventBus()
    strategy = ExampleStrategy(bus=bus)
    strategy.register(bus)

    orders = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await bus.publish(PriceUpdate(product_id="BTC-USD", price=50000.0, timestamp="..."))
    assert len(orders) == 1
```

---

## Adding a New Event Type

### 1. Define in src/events.py
```python
@dataclass(frozen=True)
class NewEvent:
    field1: str
    field2: float
```

### 2. Add test in tests/test_events.py
```python
def test_new_event():
    e = NewEvent(field1="x", field2=1.0)
    assert e.field1 == "x"
```

### 3. Subscribe in consuming component
```python
bus.subscribe(NewEvent, self._handle_new_event)
```

### 4. Update docs
- Add to ai-data.md Event section
- Add to ai-index.md Event Routing Table
- Add trace to ai-traces.md if it's a new flow

---

## Adding a New Component

Follow the existing pattern: constructor injection, register() method, event-based communication.

### Pattern
```python
class NewComponent:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus

    def register(self, bus: EventBus) -> None:
        bus.subscribe(SomeEvent, self._handler)

    async def _handler(self, event: SomeEvent) -> None:
        # process event
        await self._bus.publish(OutputEvent(...))
```

### Wire into main.py
```python
new_component = NewComponent(db=db, bus=bus)
new_component.register(bus)
```

### Test pattern
```python
@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()

@pytest.fixture
def bus():
    return EventBus()

async def test_new_component(db, bus):
    comp = NewComponent(db=db, bus=bus)
    comp.register(bus)
    # publish input event, assert output event or DB state
```

---

## Adding a New DB Table

### 1. Add to SCHEMA in src/db.py
```python
SCHEMA = """
... existing tables ...

CREATE TABLE IF NOT EXISTS new_table (
    id TEXT PRIMARY KEY,
    ...
);
"""
```

### 2. For existing databases
Write a migration or ALTER TABLE. SQLite only supports ADD COLUMN.

### 3. Add test in tests/test_db.py
```python
async def test_new_table_created(db: Database):
    tables = await db.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    assert "new_table" in [row[0] for row in tables]
```

### 4. Update docs
- Add schema to ai-data.md
- Add SQL queries to ai-data.md

---

## Adding a New Configuration Setting

### 1. Add field to Settings in src/config.py
```python
class Settings(BaseSettings):
    ... existing fields ...
    new_setting: str = "default_value"
```

### 2. Add to .env.example
```
NEW_SETTING=default_value
```

### 3. Pass to component that needs it
```python
# In main.py or wherever the component is created
component = NewComponent(settings=settings)
# Or pass the specific value:
component = NewComponent(new_setting=settings.new_setting)
```

---

## Adding a New Risk Check

### 1. Add check to RiskManager.check() in src/risk_manager.py
```python
async def check(self, order: OrderRequest) -> bool:
    ... existing checks ...

    # New check (add BEFORE the "return True" at the end)
    if some_condition:
        await self._bus.publish(
            RiskViolation(order_id=order.order_id, reason="Descriptive reason")
        )
        return False

    return True
```

Order of checks matters — put critical checks (kill switch) first.

### 2. Add test in tests/test_risk_manager.py
```python
async def test_new_risk_check(risk_manager, bus):
    violations = []
    async def handler(event: RiskViolation):
        violations.append(event)
    bus.subscribe(RiskViolation, handler)

    order = OrderRequest(...)
    result = await risk_manager.check(order)
    assert result is False
    assert "reason" in violations[0].reason
```

---

## Adding WebSocket Channels

MarketData currently only handles the `ticker` channel. To add more:

### 1. Subscribe in start()
```python
async def start(self, product_ids: list[str]) -> None:
    self._loop = asyncio.get_running_loop()
    self._ws.open()
    self._ws.ticker(product_ids=product_ids)
    self._ws.level2(product_ids=product_ids)  # add new channel
```

### 2. Handle in _on_message()
```python
async def _on_message(self, msg: str) -> None:
    data = json.loads(msg)
    channel = data.get("channel")

    if channel == "ticker":
        # existing handling
    elif channel == "level2":
        # new handling
```

---

## Conventions

- All components take dependencies via constructor (dependency injection)
- Components register event subscriptions via register(bus) method
- Events are frozen dataclasses defined in src/events.py
- Tests use in-memory SQLite (Database(":memory:"))
- Tests use MagicMock for CoinbaseClient
- Async tests need no special decorators (asyncio_mode = "auto" in pyproject.toml)
- IDs are UUID4 strings
- Timestamps are ISO 8601 UTC strings
- Prices/quantities are floats internally, strings when sent to Coinbase API
- All DB writes auto-commit (Database.execute does commit after each call)
