# src/market_data.py
from __future__ import annotations

import asyncio
import json
import logging

from coinbase.websocket import WSClient

from src.event_bus import EventBus
from src.events import PriceUpdate

logger = logging.getLogger(__name__)


class MarketData:
    def __init__(self, bus: EventBus, api_key: str = "", api_secret: str = "", key_file: str = "", product_ids: list[str] | None = None, db: Database | None = None) -> None:
        self._bus = bus
        self._db = db
        self._loop: asyncio.AbstractEventLoop | None = None
        self._product_ids = set(product_ids or [])
        ws_kwargs: dict = {"on_message": lambda msg: self._schedule_on_message(msg)}
        if key_file:
            ws_kwargs["key_file"] = key_file
        else:
            ws_kwargs["api_key"] = api_key
            ws_kwargs["api_secret"] = api_secret
        self._ws = WSClient(**ws_kwargs)

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
                raw_product_id = ticker.get("product_id")
                price_str = ticker.get("price")
                if raw_product_id and price_str:
                    # Coinbase may return a different product ID than subscribed
                    # (e.g. SOL-USD instead of SOL-USDC). Map to the subscribed ID.
                    product_id = self._resolve_product_id(raw_product_id)
                    await self._bus.publish(
                        PriceUpdate(
                            product_id=product_id,
                            price=float(price_str),
                            timestamp=timestamp,
                        )
                    )
                    if self._db:
                        await self._db.execute(
                            "INSERT INTO price_history (product_id, price, timestamp) VALUES (?, ?, ?)",
                            (product_id, float(price_str), timestamp),
                        )

    def _resolve_product_id(self, raw_id: str) -> str:
        if raw_id in self._product_ids:
            return raw_id
        # Match by base currency (e.g. SOL-USD → SOL-USDC)
        raw_base = raw_id.split("-")[0]
        for pid in self._product_ids:
            if pid.split("-")[0] == raw_base:
                return pid
        return raw_id

    async def start(self, product_ids: list[str]) -> None:
        self._loop = asyncio.get_running_loop()
        self._product_ids = set(product_ids)
        self._ws.open()
        self._ws.ticker(product_ids=product_ids)
        logger.info("Subscribed to ticker for %s", product_ids)

    async def stop(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass
        logger.info("WebSocket closed")
