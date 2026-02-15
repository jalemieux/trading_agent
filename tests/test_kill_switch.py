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
