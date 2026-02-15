# Coinbase Trading Bot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build async trading plumbing that lets an agent buy, hold, and sell any Coinbase pair, with risk controls and SQLite persistence.

**Architecture:** Modular graph — independent nodes connected via an async event bus. Each node subscribes to/publishes typed events. The event bus is a simple asyncio pub/sub. All I/O goes through an SDK wrapper.

**Tech Stack:** Python 3.12+, coinbase-advanced-py, aiosqlite, pydantic, pytest + pytest-asyncio

**Design doc:** `docs/plans/2026-02-14-coinbase-trading-bot-design.md`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py`
- Create: `src/config.py`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.backends"

[project]
name = "coinbase-trading-bot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "coinbase-advanced-py>=1.8.0",
    "aiosqlite>=0.20.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 2: Create .gitignore**

```
__pycache__/
*.pyc
.env
*.db
.venv/
dist/
*.egg-info/
.pytest_cache/
```

**Step 3: Create .env.example**

```
COINBASE_API_KEY=organizations/YOUR_ORG_ID/apiKeys/YOUR_KEY_ID
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\nYOUR_KEY\n-----END EC PRIVATE KEY-----\n"
MAX_ORDER_SIZE_USD=100
MAX_DAILY_LOSS_USD=500
DB_PATH=trading_bot.db
```

**Step 4: Create src/__init__.py and tests/__init__.py**

Both empty files.

**Step 5: Create src/config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    max_order_size_usd: float = 100.0
    max_daily_loss_usd: float = 500.0
    db_path: str = "trading_bot.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

**Step 6: Install dependencies**

Run: `.venv/bin/pip install -e ".[dev]"`

**Step 7: Commit**

```bash
git add pyproject.toml .gitignore .env.example src/__init__.py src/config.py tests/__init__.py
git commit -m "feat: project scaffolding with config and dependencies"
```

---

### Task 2: Event Bus

**Files:**
- Create: `src/event_bus.py`
- Create: `tests/test_event_bus.py`

**Step 1: Write the failing tests**

```python
# tests/test_event_bus.py
import asyncio
from dataclasses import dataclass

import pytest

from src.event_bus import EventBus


@dataclass
class FakeEvent:
    value: int


@dataclass
class OtherEvent:
    name: str


async def test_subscribe_and_publish():
    bus = EventBus()
    received = []

    async def handler(event: FakeEvent):
        received.append(event)

    bus.subscribe(FakeEvent, handler)
    await bus.publish(FakeEvent(value=42))

    assert len(received) == 1
    assert received[0].value == 42


async def test_multiple_subscribers():
    bus = EventBus()
    received_a = []
    received_b = []

    async def handler_a(event: FakeEvent):
        received_a.append(event)

    async def handler_b(event: FakeEvent):
        received_b.append(event)

    bus.subscribe(FakeEvent, handler_a)
    bus.subscribe(FakeEvent, handler_b)
    await bus.publish(FakeEvent(value=1))

    assert len(received_a) == 1
    assert len(received_b) == 1


async def test_publish_only_reaches_matching_subscribers():
    bus = EventBus()
    fake_received = []
    other_received = []

    async def fake_handler(event: FakeEvent):
        fake_received.append(event)

    async def other_handler(event: OtherEvent):
        other_received.append(event)

    bus.subscribe(FakeEvent, fake_handler)
    bus.subscribe(OtherEvent, other_handler)
    await bus.publish(FakeEvent(value=99))

    assert len(fake_received) == 1
    assert len(other_received) == 0


async def test_publish_with_no_subscribers():
    bus = EventBus()
    await bus.publish(FakeEvent(value=1))  # Should not raise


async def test_unsubscribe():
    bus = EventBus()
    received = []

    async def handler(event: FakeEvent):
        received.append(event)

    bus.subscribe(FakeEvent, handler)
    bus.unsubscribe(FakeEvent, handler)
    await bus.publish(FakeEvent(value=1))

    assert len(received) == 0
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_event_bus.py -v`
Expected: FAIL — cannot import `EventBus`

**Step 3: Write minimal implementation**

```python
# src/event_bus.py
import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

Handler = Callable[[Any], Coroutine[Any, Any, None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Handler) -> None:
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: Handler) -> None:
        self._subscribers[event_type].remove(handler)

    async def publish(self, event: Any) -> None:
        event_type = type(event)
        for handler in self._subscribers.get(event_type, []):
            try:
                await handler(event)
            except Exception:
                logger.exception("Handler %s failed for event %s", handler, event)
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_event_bus.py -v`
Expected: All 5 PASS

**Step 5: Commit**

```bash
git add src/event_bus.py tests/test_event_bus.py
git commit -m "feat: async event bus with pub/sub"
```

---

### Task 3: Event Definitions

**Files:**
- Create: `src/events.py`
- Create: `tests/test_events.py`

**Step 1: Write the failing tests**

```python
# tests/test_events.py
from src.events import (
    KillSwitchActivated,
    OrderFailed,
    OrderFilled,
    OrderRequest,
    PositionChanged,
    PriceUpdate,
    RiskViolation,
)


def test_price_update_creation():
    e = PriceUpdate(product_id="BTC-USD", price=50000.0, timestamp="2026-01-01T00:00:00Z")
    assert e.product_id == "BTC-USD"
    assert e.price == 50000.0


def test_order_request_market_buy():
    e = OrderRequest(
        product_id="BTC-USD",
        side="BUY",
        order_type="MARKET",
        quote_size=100.0,
    )
    assert e.side == "BUY"
    assert e.base_size is None


def test_order_request_limit_sell():
    e = OrderRequest(
        product_id="ETH-USD",
        side="SELL",
        order_type="LIMIT",
        base_size=1.5,
        limit_price=3000.0,
    )
    assert e.order_type == "LIMIT"
    assert e.limit_price == 3000.0


def test_order_filled():
    e = OrderFilled(
        order_id="abc-123",
        product_id="BTC-USD",
        side="BUY",
        filled_price=50000.0,
        filled_qty=0.002,
        fee=0.20,
        coinbase_order_id="cb-456",
    )
    assert e.filled_price == 50000.0


def test_order_failed():
    e = OrderFailed(order_id="abc-123", reason="insufficient funds")
    assert e.reason == "insufficient funds"


def test_risk_violation():
    e = RiskViolation(order_id="abc-123", reason="exceeds max order size")
    assert "max order size" in e.reason


def test_position_changed():
    e = PositionChanged(
        position_id="pos-1",
        product_id="BTC-USD",
        side="LONG",
        quantity=0.002,
        entry_price=50000.0,
        status="OPEN",
    )
    assert e.status == "OPEN"


def test_kill_switch_activated():
    e = KillSwitchActivated(reason="daily loss exceeded")
    assert e.reason == "daily loss exceeded"
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_events.py -v`
Expected: FAIL — cannot import events

**Step 3: Write minimal implementation**

```python
# src/events.py
from dataclasses import dataclass, field
from typing import Optional
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class PriceUpdate:
    product_id: str
    price: float
    timestamp: str


@dataclass(frozen=True)
class OrderRequest:
    product_id: str
    side: str  # BUY or SELL
    order_type: str  # MARKET or LIMIT
    quote_size: Optional[float] = None  # USD amount (market buys)
    base_size: Optional[float] = None  # Asset amount (sells, limit orders)
    limit_price: Optional[float] = None
    order_id: str = field(default_factory=_new_id)


@dataclass(frozen=True)
class OrderFilled:
    order_id: str
    product_id: str
    side: str
    filled_price: float
    filled_qty: float
    fee: float
    coinbase_order_id: str


@dataclass(frozen=True)
class OrderFailed:
    order_id: str
    reason: str


@dataclass(frozen=True)
class RiskViolation:
    order_id: str
    reason: str


@dataclass(frozen=True)
class PositionChanged:
    position_id: str
    product_id: str
    side: str
    quantity: float
    entry_price: float
    status: str  # OPEN or CLOSED


@dataclass(frozen=True)
class KillSwitchActivated:
    reason: str
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_events.py -v`
Expected: All 8 PASS

**Step 5: Commit**

```bash
git add src/events.py tests/test_events.py
git commit -m "feat: event dataclasses for trading pipeline"
```

---

### Task 4: Database Layer

**Files:**
- Create: `src/db.py`
- Create: `tests/test_db.py`

**Step 1: Write the failing tests**

```python
# tests/test_db.py
import pytest

from src.db import Database


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


async def test_initialize_creates_tables(db: Database):
    tables = await db.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row[0] for row in tables]
    assert "positions" in table_names
    assert "orders" in table_names
    assert "daily_summary" in table_names
    assert "kill_switch" in table_names


async def test_insert_and_fetch_position(db: Database):
    await db.execute(
        """INSERT INTO positions (id, product_id, side, entry_price, quantity, status, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("pos-1", "BTC-USD", "LONG", 50000.0, 0.002, "OPEN", "2026-01-01T00:00:00Z"),
    )
    rows = await db.execute_fetchall("SELECT * FROM positions WHERE id = ?", ("pos-1",))
    assert len(rows) == 1
    assert rows[0][1] == "BTC-USD"


async def test_insert_and_fetch_order(db: Database):
    await db.execute(
        """INSERT INTO positions (id, product_id, side, entry_price, quantity, status, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("pos-1", "BTC-USD", "LONG", 50000.0, 0.002, "OPEN", "2026-01-01T00:00:00Z"),
    )
    await db.execute(
        """INSERT INTO orders (id, position_id, product_id, side, type, quantity, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ord-1", "pos-1", "BTC-USD", "BUY", "MARKET", 0.002, "PENDING", "2026-01-01T00:00:00Z"),
    )
    rows = await db.execute_fetchall("SELECT * FROM orders WHERE id = ?", ("ord-1",))
    assert len(rows) == 1
    assert rows[0][2] == "BTC-USD"


async def test_kill_switch_default_off(db: Database):
    row = await db.execute_fetchone("SELECT active FROM kill_switch WHERE id = 1")
    assert row[0] == 0


async def test_set_kill_switch(db: Database):
    await db.execute("UPDATE kill_switch SET active = 1, reason = ? WHERE id = 1", ("daily loss",))
    row = await db.execute_fetchone("SELECT active, reason FROM kill_switch WHERE id = 1")
    assert row[0] == 1
    assert row[1] == "daily loss"
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: FAIL — cannot import `Database`

**Step 3: Write minimal implementation**

```python
# src/db.py
import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    quantity REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    realized_pnl REAL DEFAULT 0.0,
    opened_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    position_id TEXT,
    product_id TEXT NOT NULL,
    side TEXT NOT NULL,
    type TEXT NOT NULL,
    price REAL,
    quantity REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    coinbase_id TEXT,
    filled_price REAL,
    filled_qty REAL,
    fee REAL,
    created_at TEXT NOT NULL,
    filled_at TEXT,
    FOREIGN KEY (position_id) REFERENCES positions(id)
);

CREATE TABLE IF NOT EXISTS daily_summary (
    date TEXT PRIMARY KEY,
    total_pnl REAL DEFAULT 0.0,
    num_trades INTEGER DEFAULT 0,
    fees_paid REAL DEFAULT 0.0,
    halted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kill_switch (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active INTEGER DEFAULT 0,
    reason TEXT,
    activated_at TEXT
);

INSERT OR IGNORE INTO kill_switch (id, active) VALUES (1, 0);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def execute(self, sql: str, params: tuple = ()) -> None:
        assert self._conn is not None
        await self._conn.execute(sql, params)
        await self._conn.commit()

    async def execute_fetchall(self, sql: str, params: tuple = ()) -> list:
        assert self._conn is not None
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchall()

    async def execute_fetchone(self, sql: str, params: tuple = ()):
        assert self._conn is not None
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchone()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: All 5 PASS

**Step 5: Commit**

```bash
git add src/db.py tests/test_db.py
git commit -m "feat: SQLite database layer with schema"
```

---

### Task 5: Kill Switch

**Files:**
- Create: `src/kill_switch.py`
- Create: `tests/test_kill_switch.py`

**Step 1: Write the failing tests**

```python
# tests/test_kill_switch.py
import pytest

from src.db import Database
from src.event_bus import EventBus
from src.events import KillSwitchActivated
from src.kill_switch import KillSwitch


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
async def bus():
    return EventBus()


@pytest.fixture
async def kill_switch(db, bus):
    ks = KillSwitch(db=db, bus=bus)
    await ks.initialize()
    return ks


async def test_default_inactive(kill_switch):
    assert not kill_switch.is_active


async def test_activate(kill_switch, bus):
    received = []

    async def handler(event: KillSwitchActivated):
        received.append(event)

    bus.subscribe(KillSwitchActivated, handler)
    await kill_switch.activate("test reason")

    assert kill_switch.is_active
    assert len(received) == 1
    assert received[0].reason == "test reason"


async def test_activate_persists_to_db(kill_switch, db):
    await kill_switch.activate("persisted")
    row = await db.execute_fetchone("SELECT active, reason FROM kill_switch WHERE id = 1")
    assert row[0] == 1
    assert row[1] == "persisted"


async def test_deactivate(kill_switch):
    await kill_switch.activate("test")
    await kill_switch.deactivate()
    assert not kill_switch.is_active


async def test_loads_state_from_db(db, bus):
    await db.execute("UPDATE kill_switch SET active = 1, reason = 'from db' WHERE id = 1")
    ks = KillSwitch(db=db, bus=bus)
    await ks.initialize()
    assert ks.is_active
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kill_switch.py -v`
Expected: FAIL — cannot import `KillSwitch`

**Step 3: Write minimal implementation**

```python
# src/kill_switch.py
import logging
from datetime import datetime, timezone

from src.db import Database
from src.event_bus import EventBus
from src.events import KillSwitchActivated

logger = logging.getLogger(__name__)


class KillSwitch:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def initialize(self) -> None:
        row = await self._db.execute_fetchone("SELECT active FROM kill_switch WHERE id = 1")
        if row:
            self._active = bool(row[0])

    async def activate(self, reason: str) -> None:
        self._active = True
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE kill_switch SET active = 1, reason = ?, activated_at = ? WHERE id = 1",
            (reason, now),
        )
        logger.warning("KILL SWITCH ACTIVATED: %s", reason)
        await self._bus.publish(KillSwitchActivated(reason=reason))

    async def deactivate(self) -> None:
        self._active = False
        await self._db.execute(
            "UPDATE kill_switch SET active = 0, reason = NULL, activated_at = NULL WHERE id = 1"
        )
        logger.info("Kill switch deactivated")
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kill_switch.py -v`
Expected: All 5 PASS

**Step 5: Commit**

```bash
git add src/kill_switch.py tests/test_kill_switch.py
git commit -m "feat: kill switch with DB persistence"
```

---

### Task 6: Risk Manager

**Files:**
- Create: `src/risk_manager.py`
- Create: `tests/test_risk_manager.py`

**Step 1: Write the failing tests**

```python
# tests/test_risk_manager.py
import pytest

from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderRequest, RiskViolation
from src.kill_switch import KillSwitch
from src.risk_manager import RiskManager


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
async def bus():
    return EventBus()


@pytest.fixture
async def kill_switch(db, bus):
    ks = KillSwitch(db=db, bus=bus)
    await ks.initialize()
    return ks


@pytest.fixture
def settings():
    return Settings(
        max_order_size_usd=100.0,
        max_daily_loss_usd=500.0,
    )


@pytest.fixture
async def risk_manager(db, bus, kill_switch, settings):
    rm = RiskManager(db=db, bus=bus, kill_switch=kill_switch, settings=settings)
    return rm


async def test_approve_valid_order(risk_manager):
    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=50.0
    )
    result = await risk_manager.check(order)
    assert result is True


async def test_reject_order_exceeding_max_size(risk_manager, bus):
    violations = []

    async def handler(event: RiskViolation):
        violations.append(event)

    bus.subscribe(RiskViolation, handler)

    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=200.0
    )
    result = await risk_manager.check(order)

    assert result is False
    assert len(violations) == 1
    assert "max order size" in violations[0].reason


async def test_reject_when_kill_switch_active(risk_manager, kill_switch, bus):
    violations = []

    async def handler(event: RiskViolation):
        violations.append(event)

    bus.subscribe(RiskViolation, handler)

    await kill_switch.activate("test")
    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=10.0
    )
    result = await risk_manager.check(order)

    assert result is False
    assert "kill switch" in violations[0].reason.lower()


async def test_activate_kill_switch_on_daily_loss(risk_manager, db, kill_switch):
    today = __import__("datetime").date.today().isoformat()
    await db.execute(
        "INSERT INTO daily_summary (date, total_pnl) VALUES (?, ?)",
        (today, -600.0),
    )
    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=10.0
    )
    result = await risk_manager.check(order)

    assert result is False
    assert kill_switch.is_active


async def test_approve_sell_order_regardless_of_size(risk_manager):
    """Sells close positions — don't block them by quote size."""
    order = OrderRequest(
        product_id="BTC-USD", side="SELL", order_type="MARKET", base_size=5.0
    )
    result = await risk_manager.check(order)
    assert result is True
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_risk_manager.py -v`
Expected: FAIL — cannot import `RiskManager`

**Step 3: Write minimal implementation**

```python
# src/risk_manager.py
import logging
from datetime import date

from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderRequest, RiskViolation
from src.kill_switch import KillSwitch

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        kill_switch: KillSwitch,
        settings: Settings,
    ) -> None:
        self._db = db
        self._bus = bus
        self._kill_switch = kill_switch
        self._settings = settings

    async def check(self, order: OrderRequest) -> bool:
        # 1. Kill switch
        if self._kill_switch.is_active:
            await self._bus.publish(
                RiskViolation(order_id=order.order_id, reason="Kill switch is active")
            )
            return False

        # 2. Check daily P&L
        today = date.today().isoformat()
        row = await self._db.execute_fetchone(
            "SELECT total_pnl FROM daily_summary WHERE date = ?", (today,)
        )
        if row and row[0] <= -self._settings.max_daily_loss_usd:
            await self._kill_switch.activate(
                f"Daily loss ${abs(row[0]):.2f} exceeded limit ${self._settings.max_daily_loss_usd:.2f}"
            )
            await self._bus.publish(
                RiskViolation(order_id=order.order_id, reason="Daily loss limit exceeded")
            )
            return False

        # 3. Max order size (only for buys — sells close positions)
        if order.side == "BUY" and order.quote_size is not None:
            if order.quote_size > self._settings.max_order_size_usd:
                await self._bus.publish(
                    RiskViolation(
                        order_id=order.order_id,
                        reason=f"Order ${order.quote_size:.2f} exceeds max order size ${self._settings.max_order_size_usd:.2f}",
                    )
                )
                return False

        return True
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_risk_manager.py -v`
Expected: All 5 PASS

**Step 5: Commit**

```bash
git add src/risk_manager.py tests/test_risk_manager.py
git commit -m "feat: risk manager with order size and daily loss checks"
```

---

### Task 7: Coinbase Client Wrapper

**Files:**
- Create: `src/coinbase_client.py`
- Create: `tests/test_coinbase_client.py`

This wraps the SDK so the rest of our code never touches `coinbase-advanced-py` directly. All methods are async-compatible and return simple dicts/dataclasses.

**Step 1: Write the failing tests**

```python
# tests/test_coinbase_client.py
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

import pytest

from src.coinbase_client import CoinbaseClient


@pytest.fixture
def mock_rest_client():
    with patch("src.coinbase_client.RESTClient") as MockREST:
        mock = MockREST.return_value
        yield mock


@pytest.fixture
def client(mock_rest_client):
    return CoinbaseClient(api_key="test-key", api_secret="test-secret")


def test_market_buy(client, mock_rest_client):
    mock_rest_client.market_order_buy.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-order-1"},
    }
    result = client.market_buy(
        client_order_id="my-order-1",
        product_id="BTC-USD",
        quote_size="100",
    )
    assert result["success"] is True
    mock_rest_client.market_order_buy.assert_called_once_with(
        client_order_id="my-order-1",
        product_id="BTC-USD",
        quote_size="100",
    )


def test_market_sell(client, mock_rest_client):
    mock_rest_client.market_order_sell.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-order-2"},
    }
    result = client.market_sell(
        client_order_id="my-order-2",
        product_id="BTC-USD",
        base_size="0.002",
    )
    assert result["success"] is True
    mock_rest_client.market_order_sell.assert_called_once_with(
        client_order_id="my-order-2",
        product_id="BTC-USD",
        base_size="0.002",
    )


def test_limit_buy(client, mock_rest_client):
    mock_rest_client.limit_order_gtc.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-order-3"},
    }
    result = client.limit_order(
        client_order_id="my-order-3",
        product_id="BTC-USD",
        side="BUY",
        base_size="0.002",
        limit_price="48000",
    )
    assert result["success"] is True


def test_cancel_orders(client, mock_rest_client):
    mock_rest_client.cancel_orders.return_value = {"results": [{"success": True}]}
    result = client.cancel_orders(["cb-order-1"])
    mock_rest_client.cancel_orders.assert_called_once_with(order_ids=["cb-order-1"])


def test_get_order(client, mock_rest_client):
    mock_rest_client.get_order.return_value = {
        "order": {"order_id": "cb-order-1", "status": "FILLED"}
    }
    result = client.get_order("cb-order-1")
    assert result["order"]["status"] == "FILLED"


def test_get_accounts(client, mock_rest_client):
    mock_rest_client.get_accounts.return_value = {"accounts": []}
    result = client.get_accounts()
    assert result["accounts"] == []


def test_get_product(client, mock_rest_client):
    mock_rest_client.get_product.return_value = {
        "product_id": "BTC-USD",
        "price": "50000.00",
    }
    result = client.get_product("BTC-USD")
    assert result["price"] == "50000.00"
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_coinbase_client.py -v`
Expected: FAIL — cannot import `CoinbaseClient`

**Step 3: Write minimal implementation**

```python
# src/coinbase_client.py
import logging

from coinbase.rest import RESTClient

logger = logging.getLogger(__name__)


class CoinbaseClient:
    def __init__(self, api_key: str, api_secret: str) -> None:
        self._client = RESTClient(api_key=api_key, api_secret=api_secret)

    def market_buy(self, client_order_id: str, product_id: str, quote_size: str) -> dict:
        return self._client.market_order_buy(
            client_order_id=client_order_id,
            product_id=product_id,
            quote_size=quote_size,
        )

    def market_sell(self, client_order_id: str, product_id: str, base_size: str) -> dict:
        return self._client.market_order_sell(
            client_order_id=client_order_id,
            product_id=product_id,
            base_size=base_size,
        )

    def limit_order(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        base_size: str,
        limit_price: str,
    ) -> dict:
        return self._client.limit_order_gtc(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            base_size=base_size,
            limit_price=limit_price,
        )

    def cancel_orders(self, order_ids: list[str]) -> dict:
        return self._client.cancel_orders(order_ids=order_ids)

    def get_order(self, order_id: str) -> dict:
        return self._client.get_order(order_id)

    def get_accounts(self) -> dict:
        return self._client.get_accounts()

    def get_product(self, product_id: str) -> dict:
        return self._client.get_product(product_id)
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_coinbase_client.py -v`
Expected: All 7 PASS

**Step 5: Commit**

```bash
git add src/coinbase_client.py tests/test_coinbase_client.py
git commit -m "feat: Coinbase SDK wrapper with order and account methods"
```

---

### Task 8: Order Manager

**Files:**
- Create: `src/order_manager.py`
- Create: `tests/test_order_manager.py`

The OrderManager listens for `OrderRequest` events, runs them through the RiskManager, places them via CoinbaseClient, and emits `OrderFilled`/`OrderFailed`.

**Step 1: Write the failing tests**

```python
# tests/test_order_manager.py
from unittest.mock import MagicMock, AsyncMock

import pytest

from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFailed, OrderFilled, OrderRequest
from src.kill_switch import KillSwitch
from src.order_manager import OrderManager
from src.risk_manager import RiskManager


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
async def kill_switch(db, bus):
    ks = KillSwitch(db=db, bus=bus)
    await ks.initialize()
    return ks


@pytest.fixture
def settings():
    return Settings(max_order_size_usd=1000.0, max_daily_loss_usd=5000.0)


@pytest.fixture
def risk_manager(db, bus, kill_switch, settings):
    return RiskManager(db=db, bus=bus, kill_switch=kill_switch, settings=settings)


@pytest.fixture
def mock_coinbase():
    mock = MagicMock()
    return mock


@pytest.fixture
async def order_manager(db, bus, risk_manager, mock_coinbase):
    om = OrderManager(db=db, bus=bus, risk_manager=risk_manager, coinbase=mock_coinbase)
    om.register(bus)
    return om


async def test_market_buy_success(order_manager, bus, mock_coinbase):
    filled_events = []

    async def handler(event: OrderFilled):
        filled_events.append(event)

    bus.subscribe(OrderFilled, handler)

    mock_coinbase.market_buy.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-123"},
    }
    mock_coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-123",
            "status": "FILLED",
            "filled_size": "0.002",
            "average_filled_price": "50000",
            "total_fees": "0.20",
        }
    }

    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=100.0
    )
    await bus.publish(order)

    assert len(filled_events) == 1
    assert filled_events[0].coinbase_order_id == "cb-123"
    assert filled_events[0].filled_price == 50000.0


async def test_market_sell_success(order_manager, bus, mock_coinbase):
    filled_events = []

    async def handler(event: OrderFilled):
        filled_events.append(event)

    bus.subscribe(OrderFilled, handler)

    mock_coinbase.market_sell.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-456"},
    }
    mock_coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-456",
            "status": "FILLED",
            "filled_size": "1.0",
            "average_filled_price": "3000",
            "total_fees": "0.60",
        }
    }

    order = OrderRequest(
        product_id="ETH-USD", side="SELL", order_type="MARKET", base_size=1.0
    )
    await bus.publish(order)

    assert len(filled_events) == 1
    assert filled_events[0].side == "SELL"


async def test_order_fails_at_coinbase(order_manager, bus, mock_coinbase):
    failed_events = []

    async def handler(event: OrderFailed):
        failed_events.append(event)

    bus.subscribe(OrderFailed, handler)

    mock_coinbase.market_buy.return_value = {
        "success": False,
        "error_response": {"error": "INSUFFICIENT_FUND"},
    }

    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=50.0
    )
    await bus.publish(order)

    assert len(failed_events) == 1
    assert "INSUFFICIENT_FUND" in failed_events[0].reason


async def test_order_persisted_to_db(order_manager, bus, mock_coinbase, db):
    mock_coinbase.market_buy.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-789"},
    }
    mock_coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-789",
            "status": "FILLED",
            "filled_size": "0.001",
            "average_filled_price": "50000",
            "total_fees": "0.10",
        }
    }

    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=50.0
    )
    await bus.publish(order)

    rows = await db.execute_fetchall("SELECT * FROM orders WHERE coinbase_id = ?", ("cb-789",))
    assert len(rows) == 1


async def test_risk_rejected_order_not_placed(order_manager, bus, mock_coinbase, kill_switch):
    await kill_switch.activate("test")

    order = OrderRequest(
        product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=50.0
    )
    await bus.publish(order)

    mock_coinbase.market_buy.assert_not_called()
    mock_coinbase.market_sell.assert_not_called()
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_order_manager.py -v`
Expected: FAIL — cannot import `OrderManager`

**Step 3: Write minimal implementation**

```python
# src/order_manager.py
import logging
from datetime import datetime, timezone

from src.coinbase_client import CoinbaseClient
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFailed, OrderFilled, OrderRequest
from src.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        risk_manager: RiskManager,
        coinbase: CoinbaseClient,
    ) -> None:
        self._db = db
        self._bus = bus
        self._risk = risk_manager
        self._coinbase = coinbase

    def register(self, bus: EventBus) -> None:
        bus.subscribe(OrderRequest, self._handle_order_request)

    async def _handle_order_request(self, order: OrderRequest) -> None:
        # Risk check
        approved = await self._risk.check(order)
        if not approved:
            return

        now = datetime.now(timezone.utc).isoformat()

        # Place order
        try:
            if order.order_type == "MARKET":
                result = self._place_market_order(order)
            else:
                result = self._place_limit_order(order)
        except Exception as e:
            logger.exception("Failed to place order")
            await self._bus.publish(OrderFailed(order_id=order.order_id, reason=str(e)))
            return

        if not result.get("success"):
            error = result.get("error_response", {})
            reason = str(error.get("error", "Unknown error"))
            await self._persist_order(order, now, status="FAILED")
            await self._bus.publish(OrderFailed(order_id=order.order_id, reason=reason))
            return

        cb_order_id = result["success_response"]["order_id"]

        # Poll for fill details
        order_details = self._coinbase.get_order(cb_order_id)
        details = order_details.get("order", {})
        filled_price = float(details.get("average_filled_price", 0))
        filled_qty = float(details.get("filled_size", 0))
        fee = float(details.get("total_fees", 0))

        # Persist
        await self._persist_order(
            order, now,
            coinbase_id=cb_order_id,
            filled_price=filled_price,
            filled_qty=filled_qty,
            fee=fee,
            status="FILLED",
        )

        await self._bus.publish(
            OrderFilled(
                order_id=order.order_id,
                product_id=order.product_id,
                side=order.side,
                filled_price=filled_price,
                filled_qty=filled_qty,
                fee=fee,
                coinbase_order_id=cb_order_id,
            )
        )

    def _place_market_order(self, order: OrderRequest) -> dict:
        if order.side == "BUY":
            return self._coinbase.market_buy(
                client_order_id=order.order_id,
                product_id=order.product_id,
                quote_size=str(order.quote_size),
            )
        else:
            return self._coinbase.market_sell(
                client_order_id=order.order_id,
                product_id=order.product_id,
                base_size=str(order.base_size),
            )

    def _place_limit_order(self, order: OrderRequest) -> dict:
        return self._coinbase.limit_order(
            client_order_id=order.order_id,
            product_id=order.product_id,
            side=order.side,
            base_size=str(order.base_size),
            limit_price=str(order.limit_price),
        )

    async def _persist_order(
        self,
        order: OrderRequest,
        created_at: str,
        coinbase_id: str | None = None,
        filled_price: float | None = None,
        filled_qty: float | None = None,
        fee: float | None = None,
        status: str = "PENDING",
    ) -> None:
        await self._db.execute(
            """INSERT INTO orders (id, product_id, side, type, price, quantity, status,
               coinbase_id, filled_price, filled_qty, fee, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order.order_id,
                order.product_id,
                order.side,
                order.order_type,
                order.limit_price,
                order.quote_size or order.base_size,
                status,
                coinbase_id,
                filled_price,
                filled_qty,
                fee,
                created_at,
            ),
        )
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_order_manager.py -v`
Expected: All 5 PASS

**Step 5: Commit**

```bash
git add src/order_manager.py tests/test_order_manager.py
git commit -m "feat: order manager with risk checks and Coinbase execution"
```

---

### Task 9: Position Tracker

**Files:**
- Create: `src/position_tracker.py`
- Create: `tests/test_position_tracker.py`

Listens for `OrderFilled`, opens/updates positions, tracks P&L, updates daily summary.

**Step 1: Write the failing tests**

```python
# tests/test_position_tracker.py
import pytest

from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFilled, PositionChanged
from src.position_tracker import PositionTracker


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
async def tracker(db, bus):
    t = PositionTracker(db=db, bus=bus)
    t.register(bus)
    return t


async def test_buy_opens_new_position(tracker, bus, db):
    changed = []

    async def handler(event: PositionChanged):
        changed.append(event)

    bus.subscribe(PositionChanged, handler)

    await bus.publish(
        OrderFilled(
            order_id="ord-1",
            product_id="BTC-USD",
            side="BUY",
            filled_price=50000.0,
            filled_qty=0.002,
            fee=0.20,
            coinbase_order_id="cb-1",
        )
    )

    assert len(changed) == 1
    assert changed[0].status == "OPEN"
    assert changed[0].quantity == 0.002

    rows = await db.execute_fetchall("SELECT * FROM positions WHERE status = 'OPEN'")
    assert len(rows) == 1


async def test_sell_closes_position(tracker, bus, db):
    # Open a position first
    await bus.publish(
        OrderFilled(
            order_id="ord-1",
            product_id="BTC-USD",
            side="BUY",
            filled_price=50000.0,
            filled_qty=0.002,
            fee=0.20,
            coinbase_order_id="cb-1",
        )
    )

    changed = []

    async def handler(event: PositionChanged):
        changed.append(event)

    bus.subscribe(PositionChanged, handler)

    # Sell to close
    await bus.publish(
        OrderFilled(
            order_id="ord-2",
            product_id="BTC-USD",
            side="SELL",
            filled_price=51000.0,
            filled_qty=0.002,
            fee=0.20,
            coinbase_order_id="cb-2",
        )
    )

    assert len(changed) == 1
    assert changed[0].status == "CLOSED"

    rows = await db.execute_fetchall("SELECT * FROM positions WHERE status = 'CLOSED'")
    assert len(rows) == 1

    # Check realized P&L: (51000 - 50000) * 0.002 - fees
    pos = rows[0]
    realized_pnl = pos[6]  # realized_pnl column
    assert realized_pnl == pytest.approx(2.0 - 0.40, abs=0.01)


async def test_sell_updates_daily_summary(tracker, bus, db):
    await bus.publish(
        OrderFilled(
            order_id="ord-1", product_id="BTC-USD", side="BUY",
            filled_price=50000.0, filled_qty=0.002, fee=0.20, coinbase_order_id="cb-1",
        )
    )
    await bus.publish(
        OrderFilled(
            order_id="ord-2", product_id="BTC-USD", side="SELL",
            filled_price=51000.0, filled_qty=0.002, fee=0.20, coinbase_order_id="cb-2",
        )
    )

    today = __import__("datetime").date.today().isoformat()
    row = await db.execute_fetchone("SELECT total_pnl, num_trades, fees_paid FROM daily_summary WHERE date = ?", (today,))
    assert row is not None
    assert row[0] > 0  # profit
    assert row[1] == 1  # one round-trip trade
    assert row[2] == pytest.approx(0.40, abs=0.01)


async def test_partial_sell_reduces_position(tracker, bus, db):
    await bus.publish(
        OrderFilled(
            order_id="ord-1", product_id="BTC-USD", side="BUY",
            filled_price=50000.0, filled_qty=0.004, fee=0.40, coinbase_order_id="cb-1",
        )
    )

    changed = []

    async def handler(event: PositionChanged):
        changed.append(event)

    bus.subscribe(PositionChanged, handler)

    await bus.publish(
        OrderFilled(
            order_id="ord-2", product_id="BTC-USD", side="SELL",
            filled_price=51000.0, filled_qty=0.002, fee=0.20, coinbase_order_id="cb-2",
        )
    )

    assert len(changed) == 1
    assert changed[0].status == "OPEN"
    assert changed[0].quantity == pytest.approx(0.002, abs=0.0001)
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_position_tracker.py -v`
Expected: FAIL — cannot import `PositionTracker`

**Step 3: Write minimal implementation**

```python
# src/position_tracker.py
import logging
import uuid
from datetime import date, datetime, timezone

from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFilled, PositionChanged

logger = logging.getLogger(__name__)


class PositionTracker:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus

    def register(self, bus: EventBus) -> None:
        bus.subscribe(OrderFilled, self._handle_order_filled)

    async def _handle_order_filled(self, event: OrderFilled) -> None:
        if event.side == "BUY":
            await self._open_or_add_position(event)
        else:
            await self._reduce_or_close_position(event)

    async def _open_or_add_position(self, event: OrderFilled) -> None:
        # Check for existing open position in this product
        row = await self._db.execute_fetchone(
            "SELECT id, entry_price, quantity FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (event.product_id,),
        )

        now = datetime.now(timezone.utc).isoformat()

        if row:
            # Average into existing position
            pos_id, old_price, old_qty = row
            new_qty = old_qty + event.filled_qty
            new_price = ((old_price * old_qty) + (event.filled_price * event.filled_qty)) / new_qty
            await self._db.execute(
                "UPDATE positions SET entry_price = ?, quantity = ? WHERE id = ?",
                (new_price, new_qty, pos_id),
            )
        else:
            pos_id = str(uuid.uuid4())
            await self._db.execute(
                """INSERT INTO positions (id, product_id, side, entry_price, quantity, status, opened_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (pos_id, event.product_id, "LONG", event.filled_price, event.filled_qty, "OPEN", now),
            )

        # Link order to position
        await self._db.execute(
            "UPDATE orders SET position_id = ? WHERE id = ?", (pos_id, event.order_id)
        )

        pos = await self._db.execute_fetchone(
            "SELECT quantity, entry_price FROM positions WHERE id = ?", (pos_id,)
        )
        await self._bus.publish(
            PositionChanged(
                position_id=pos_id,
                product_id=event.product_id,
                side="LONG",
                quantity=pos[0],
                entry_price=pos[1],
                status="OPEN",
            )
        )

    async def _reduce_or_close_position(self, event: OrderFilled) -> None:
        row = await self._db.execute_fetchone(
            "SELECT id, entry_price, quantity FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (event.product_id,),
        )
        if not row:
            logger.warning("Sell for %s but no open position found", event.product_id)
            return

        pos_id, entry_price, current_qty = row
        sell_qty = min(event.filled_qty, current_qty)
        remaining = current_qty - sell_qty

        # Calculate realized P&L
        pnl = (event.filled_price - entry_price) * sell_qty - event.fee
        # Include buy-side fee proportionally
        buy_fee_row = await self._db.execute_fetchone(
            "SELECT COALESCE(SUM(fee), 0) FROM orders WHERE position_id = ? AND side = 'BUY'",
            (pos_id,),
        )
        buy_fee_total = buy_fee_row[0] if buy_fee_row else 0
        # Proportion of buy fee attributable to this sell
        buy_fee_portion = buy_fee_total * (sell_qty / current_qty) if current_qty > 0 else 0
        pnl -= buy_fee_portion

        now = datetime.now(timezone.utc).isoformat()

        if remaining <= 1e-10:
            # Fully closed
            await self._db.execute(
                "UPDATE positions SET status = 'CLOSED', quantity = 0, realized_pnl = ?, closed_at = ? WHERE id = ?",
                (pnl, now, pos_id),
            )
            status = "CLOSED"
            remaining = 0.0
        else:
            # Partially closed
            await self._db.execute(
                "UPDATE positions SET quantity = ?, realized_pnl = COALESCE(realized_pnl, 0) + ? WHERE id = ?",
                (remaining, pnl, pos_id),
            )
            status = "OPEN"

        # Link order
        await self._db.execute(
            "UPDATE orders SET position_id = ? WHERE id = ?", (pos_id, event.order_id)
        )

        # Update daily summary
        today = date.today().isoformat()
        existing = await self._db.execute_fetchone(
            "SELECT total_pnl, num_trades, fees_paid FROM daily_summary WHERE date = ?", (today,)
        )
        total_fee = event.fee + buy_fee_portion
        if existing:
            await self._db.execute(
                "UPDATE daily_summary SET total_pnl = total_pnl + ?, num_trades = num_trades + 1, fees_paid = fees_paid + ? WHERE date = ?",
                (pnl, total_fee, today),
            )
        else:
            await self._db.execute(
                "INSERT INTO daily_summary (date, total_pnl, num_trades, fees_paid) VALUES (?, ?, 1, ?)",
                (today, pnl, total_fee),
            )

        pos = await self._db.execute_fetchone(
            "SELECT entry_price FROM positions WHERE id = ?", (pos_id,)
        )
        await self._bus.publish(
            PositionChanged(
                position_id=pos_id,
                product_id=event.product_id,
                side="LONG",
                quantity=remaining,
                entry_price=pos[0] if pos else entry_price,
                status=status,
            )
        )
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_position_tracker.py -v`
Expected: All 4 PASS

**Step 5: Commit**

```bash
git add src/position_tracker.py tests/test_position_tracker.py
git commit -m "feat: position tracker with P&L and daily summary"
```

---

### Task 10: Market Data (WebSocket)

**Files:**
- Create: `src/market_data.py`
- Create: `tests/test_market_data.py`

Subscribes to Coinbase WebSocket ticker channel, parses messages, publishes `PriceUpdate` events.

**Step 1: Write the failing tests**

```python
# tests/test_market_data.py
import json
from unittest.mock import MagicMock, patch

import pytest

from src.event_bus import EventBus
from src.events import PriceUpdate
from src.market_data import MarketData


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_ws_client():
    with patch("src.market_data.WSClient") as MockWS:
        mock = MockWS.return_value
        yield mock


@pytest.fixture
def market_data(bus, mock_ws_client):
    return MarketData(bus=bus, api_key="test", api_secret="test")


def test_parse_ticker_message(market_data, bus):
    received = []

    async def handler(event: PriceUpdate):
        received.append(event)

    bus.subscribe(PriceUpdate, handler)

    # Simulate a ticker message from WebSocket
    msg = json.dumps({
        "channel": "ticker",
        "events": [
            {
                "type": "update",
                "tickers": [
                    {
                        "product_id": "BTC-USD",
                        "price": "50123.45",
                    }
                ],
            }
        ],
        "timestamp": "2026-01-01T00:00:00Z",
    })

    import asyncio
    asyncio.get_event_loop().run_until_complete(market_data._on_message(msg))

    assert len(received) == 1
    assert received[0].product_id == "BTC-USD"
    assert received[0].price == 50123.45


def test_ignore_non_ticker_messages(market_data, bus):
    received = []

    async def handler(event: PriceUpdate):
        received.append(event)

    bus.subscribe(PriceUpdate, handler)

    msg = json.dumps({"channel": "heartbeats", "events": []})

    import asyncio
    asyncio.get_event_loop().run_until_complete(market_data._on_message(msg))

    assert len(received) == 0
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_market_data.py -v`
Expected: FAIL — cannot import `MarketData`

**Step 3: Write minimal implementation**

```python
# src/market_data.py
import asyncio
import json
import logging

from coinbase.websocket import WSClient

from src.event_bus import EventBus
from src.events import PriceUpdate

logger = logging.getLogger(__name__)


class MarketData:
    def __init__(self, bus: EventBus, api_key: str, api_secret: str) -> None:
        self._bus = bus
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = WSClient(
            api_key=api_key,
            api_secret=api_secret,
            on_message=lambda msg: self._schedule_on_message(msg),
        )

    def _schedule_on_message(self, msg: str) -> None:
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._on_message(msg), self._loop)

    async def _on_message(self, msg: str) -> None:
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            return

        if data.get("channel") != "ticker":
            return

        timestamp = data.get("timestamp", "")
        for event in data.get("events", []):
            for ticker in event.get("tickers", []):
                product_id = ticker.get("product_id")
                price_str = ticker.get("price")
                if product_id and price_str:
                    await self._bus.publish(
                        PriceUpdate(
                            product_id=product_id,
                            price=float(price_str),
                            timestamp=timestamp,
                        )
                    )

    async def start(self, product_ids: list[str]) -> None:
        self._loop = asyncio.get_running_loop()
        self._ws.open()
        self._ws.ticker(product_ids=product_ids)
        logger.info("Subscribed to ticker for %s", product_ids)

    async def stop(self) -> None:
        self._ws.close()
        logger.info("WebSocket closed")
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_market_data.py -v`
Expected: All 2 PASS

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: market data WebSocket with ticker parsing"
```

---

### Task 11: Main Entry Point

**Files:**
- Create: `src/main.py`

This wires everything together: creates the event bus, initializes all nodes, starts the event loop.

**Step 1: Write main.py**

```python
# src/main.py
import asyncio
import logging
import signal

from src.coinbase_client import CoinbaseClient
from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.kill_switch import KillSwitch
from src.market_data import MarketData
from src.order_manager import OrderManager
from src.position_tracker import PositionTracker
from src.risk_manager import RiskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    bus = EventBus()

    # Database
    db = Database(settings.db_path)
    await db.initialize()
    logger.info("Database initialized at %s", settings.db_path)

    # Kill switch
    kill_switch = KillSwitch(db=db, bus=bus)
    await kill_switch.initialize()
    if kill_switch.is_active:
        logger.warning("Kill switch is ACTIVE from previous session")

    # Risk manager
    risk_manager = RiskManager(db=db, bus=bus, kill_switch=kill_switch, settings=settings)

    # Coinbase client
    coinbase = CoinbaseClient(
        api_key=settings.coinbase_api_key,
        api_secret=settings.coinbase_api_secret,
    )

    # Order manager
    order_manager = OrderManager(db=db, bus=bus, risk_manager=risk_manager, coinbase=coinbase)
    order_manager.register(bus)

    # Position tracker
    position_tracker = PositionTracker(db=db, bus=bus)
    position_tracker.register(bus)

    # Market data
    market_data = MarketData(
        bus=bus,
        api_key=settings.coinbase_api_key,
        api_secret=settings.coinbase_api_secret,
    )

    logger.info("All components initialized. Starting market data...")
    logger.info("Risk limits: max_order=$%.2f, max_daily_loss=$%.2f",
                settings.max_order_size_usd, settings.max_daily_loss_usd)

    # Graceful shutdown
    stop_event = asyncio.Event()

    def shutdown():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    # Start WebSocket (provide product IDs via env or default)
    # For now, start without subscribing to any products
    # Products will be subscribed when a strategy is attached

    logger.info("Bot running. Waiting for strategy to emit OrderRequest events...")
    await stop_event.wait()

    # Cleanup
    await market_data.stop()
    await db.close()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Commit**

```bash
git add src/main.py
git commit -m "feat: main entry point wiring all components"
```

---

### Task 12: Integration Test

**Files:**
- Create: `tests/test_integration.py`

End-to-end test: OrderRequest flows through risk → order manager → position tracker with all real components (mocked Coinbase only).

**Step 1: Write the integration test**

```python
# tests/test_integration.py
from unittest.mock import MagicMock

import pytest

from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFilled, OrderRequest, PositionChanged
from src.kill_switch import KillSwitch
from src.order_manager import OrderManager
from src.position_tracker import PositionTracker
from src.risk_manager import RiskManager


@pytest.fixture
async def system():
    """Wire up the full system with mocked Coinbase."""
    db = Database(":memory:")
    await db.initialize()

    bus = EventBus()
    settings = Settings(max_order_size_usd=1000.0, max_daily_loss_usd=5000.0)

    kill_switch = KillSwitch(db=db, bus=bus)
    await kill_switch.initialize()

    risk_manager = RiskManager(db=db, bus=bus, kill_switch=kill_switch, settings=settings)

    mock_coinbase = MagicMock()
    order_manager = OrderManager(db=db, bus=bus, risk_manager=risk_manager, coinbase=mock_coinbase)
    order_manager.register(bus)

    position_tracker = PositionTracker(db=db, bus=bus)
    position_tracker.register(bus)

    yield {
        "db": db,
        "bus": bus,
        "kill_switch": kill_switch,
        "coinbase": mock_coinbase,
    }

    await db.close()


async def test_full_buy_sell_cycle(system):
    bus = system["bus"]
    coinbase = system["coinbase"]

    position_events = []

    async def on_position(event: PositionChanged):
        position_events.append(event)

    bus.subscribe(PositionChanged, on_position)

    # Buy
    coinbase.market_buy.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-buy-1"},
    }
    coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-buy-1",
            "status": "FILLED",
            "filled_size": "0.002",
            "average_filled_price": "50000",
            "total_fees": "0.20",
        }
    }

    await bus.publish(
        OrderRequest(product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=100.0)
    )

    assert len(position_events) == 1
    assert position_events[0].status == "OPEN"
    assert position_events[0].quantity == 0.002

    # Sell
    coinbase.market_sell.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-sell-1"},
    }
    coinbase.get_order.return_value = {
        "order": {
            "order_id": "cb-sell-1",
            "status": "FILLED",
            "filled_size": "0.002",
            "average_filled_price": "51000",
            "total_fees": "0.20",
        }
    }

    await bus.publish(
        OrderRequest(product_id="BTC-USD", side="SELL", order_type="MARKET", base_size=0.002)
    )

    assert len(position_events) == 2
    assert position_events[1].status == "CLOSED"

    # Verify DB state
    db = system["db"]
    positions = await db.execute_fetchall("SELECT * FROM positions WHERE status = 'CLOSED'")
    assert len(positions) == 1

    orders = await db.execute_fetchall("SELECT * FROM orders")
    assert len(orders) == 2

    today = __import__("datetime").date.today().isoformat()
    summary = await db.execute_fetchone("SELECT total_pnl, num_trades FROM daily_summary WHERE date = ?", (today,))
    assert summary is not None
    assert summary[0] > 0  # profitable trade
    assert summary[1] == 1


async def test_kill_switch_blocks_orders(system):
    bus = system["bus"]
    coinbase = system["coinbase"]
    kill_switch = system["kill_switch"]

    await kill_switch.activate("manual test")

    await bus.publish(
        OrderRequest(product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=50.0)
    )

    coinbase.market_buy.assert_not_called()
```

**Step 2: Run integration tests**

Run: `.venv/bin/pytest tests/test_integration.py -v`
Expected: All 2 PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: integration tests for full buy/sell cycle"
```

---

### Task 13: Documentation

**Files:**
- Create: `README.md`
- Create: `docs/architecture.md`

**Step 1: Write README.md**

Write a README covering: what the bot does, setup instructions (API keys, .env), how to run, how to run tests, architecture overview (link to docs/architecture.md), risk controls.

**Step 2: Write docs/architecture.md**

Document: component diagram, event flow, data model, risk pipeline. Reference the design doc.

**Step 3: Commit**

```bash
git add README.md docs/architecture.md
git commit -m "docs: README and architecture documentation"
```

---

### Task 14: Run Full Test Suite

**Step 1: Run all tests**

Run: `.venv/bin/pytest tests/ -v --tb=short`
Expected: All tests pass (approximately 26 tests across 7 test files)

**Step 2: Fix any failures discovered**

If any tests fail, fix them and commit.

---

## Dependency Graph

```
Task 1 (scaffolding)
  └─→ Task 2 (event bus)
       └─→ Task 3 (events)
            ├─→ Task 4 (database)
            │    ├─→ Task 5 (kill switch)
            │    │    └─→ Task 6 (risk manager)
            │    │         └─→ Task 8 (order manager)
            │    │              └─→ Task 9 (position tracker)
            │    │                   └─→ Task 12 (integration test)
            │    │                        └─→ Task 14 (full test suite)
            │    └─→ Task 9
            └─→ Task 7 (coinbase client)
                 └─→ Task 8
  └─→ Task 10 (market data) — independent, can be built in parallel
  └─→ Task 11 (main entry point) — after tasks 5-10
  └─→ Task 13 (docs) — after task 12
```
