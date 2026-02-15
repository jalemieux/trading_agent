# tests/test_market_data.py
import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from src.db import Database
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


async def test_on_message_persists_price_to_db(mock_ws_client):
    db = Database(":memory:")
    await db.initialize()
    bus = EventBus()
    md = MarketData(bus=bus, db=db, api_key="test", api_secret="test")
    md._loop = asyncio.get_running_loop()

    msg = json.dumps({
        "channel": "ticker",
        "timestamp": "2026-01-01T00:00:00Z",
        "events": [{"tickers": [{"product_id": "BTC-USD", "price": "50000.00"}]}],
    })
    await md._on_message(msg)

    rows = await db.execute_fetchall("SELECT product_id, price, timestamp FROM price_history")
    assert len(rows) == 1
    assert rows[0][0] == "BTC-USD"
    assert rows[0][1] == 50000.0
    await db.close()
