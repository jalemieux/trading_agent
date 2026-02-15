import abc
import asyncio
import logging

from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.prediction import Prediction
from src.price_buffer import PriceBuffer

logger = logging.getLogger(__name__)


class Strategy(abc.ABC):
    def __init__(
        self,
        bus: EventBus,
        price_buffer: PriceBuffer,
        settings: Settings,
        product_id: str = "BTC-USD",
        db: Database | None = None,
    ) -> None:
        self._bus = bus
        self._price_buffer = price_buffer
        self._settings = settings
        self._product_id = product_id
        self._db = db
        self._task: asyncio.Task | None = None

    def register(self, bus: EventBus) -> None:
        bus.subscribe(PriceUpdate, self._on_price)

    async def _on_price(self, event: PriceUpdate) -> None:
        self._price_buffer.add(event)
        count = len(self._price_buffer.snapshot(event.product_id))
        if count == 1:
            logger.info("First price tick for %s: $%.2f", event.product_id, event.price)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._prediction_loop())
        logger.info(
            "Strategy started for %s (interval=%dm, threshold=%.1f%%)",
            self._product_id,
            self._settings.prediction_interval_minutes,
            self._settings.trade_threshold_pct,
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Strategy stopped")

    async def _prediction_loop(self) -> None:
        interval = self._settings.prediction_interval_minutes * 60
        logger.info("Waiting 30s for initial price data...")
        await asyncio.sleep(30)
        while True:
            logger.info("Starting prediction cycle...")
            try:
                await self._run_prediction_cycle()
            except Exception:
                logger.exception("Prediction cycle failed")
            logger.info("Prediction cycle complete, next in %d minutes", interval // 60)
            await asyncio.sleep(interval)

    async def _run_prediction_cycle(self) -> None:
        prices = self._price_buffer.snapshot(self._product_id)
        if not prices:
            logger.warning("No price data for %s, skipping prediction", self._product_id)
            return

        prediction = await self._gather_and_predict()
        if prediction is None:
            logger.warning("Prediction returned None, skipping")
            return

        logger.info(
            "Prediction: target=$%.2f (current=$%.2f) in %dm — %s",
            prediction.target_price,
            prediction.current_price,
            prediction.timeframe_minutes,
            prediction.reasoning,
        )

        await self._evaluate(prediction)

    @abc.abstractmethod
    async def _gather_and_predict(self) -> Prediction | None:
        """Gather data, build prompts, call LLM, parse response."""
        ...

    async def _evaluate(self, prediction: Prediction) -> None:
        if prediction.current_price <= 0:
            logger.warning("Invalid current price %.2f, skipping", prediction.current_price)
            return

        diff_pct = (
            (prediction.target_price - prediction.current_price)
            / prediction.current_price
            * 100
        )

        threshold = self._settings.trade_threshold_pct

        if diff_pct > threshold:
            if await self._has_open_position():
                logger.info("Bullish (%.1f%%) but position already open, holding", diff_pct)
                return
            logger.info("Bullish signal (%.1f%%), placing BUY", diff_pct)
            await self._bus.publish(OrderRequest(
                product_id=self._product_id,
                side="BUY",
                order_type="MARKET",
                quote_size=self._settings.trade_size_usd,
            ))

        elif diff_pct < -threshold:
            if not await self._has_open_position():
                logger.info("Bearish (%.1f%%) but no position to sell, holding", diff_pct)
                return
            qty = await self._get_position_quantity()
            if qty <= 0:
                logger.warning("Position quantity is zero, skipping SELL")
                return
            logger.info("Bearish signal (%.1f%%), placing SELL for %.6f", diff_pct, qty)
            await self._bus.publish(OrderRequest(
                product_id=self._product_id,
                side="SELL",
                order_type="MARKET",
                base_size=qty,
            ))

        else:
            logger.info("Neutral (%.1f%%), holding", diff_pct)

    async def _has_open_position(self) -> bool:
        if self._db is None:
            return False
        row = await self._db.execute_fetchone(
            "SELECT id FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (self._product_id,),
        )
        return row is not None

    async def _get_position_quantity(self) -> float:
        if self._db is None:
            return 0.0
        row = await self._db.execute_fetchone(
            "SELECT quantity FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (self._product_id,),
        )
        return float(row[0]) if row else 0.0
