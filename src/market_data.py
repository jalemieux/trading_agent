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
