from dataclasses import dataclass

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
