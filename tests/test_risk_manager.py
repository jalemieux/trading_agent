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
