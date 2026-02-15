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
