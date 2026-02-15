import asyncio
import logging
import uuid
from datetime import datetime, timezone

from src.prediction import Prediction, Predictor
from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.news_service import NewsService
from src.price_buffer import PriceBuffer

logger = logging.getLogger(__name__)


class NewsPredictionStrategy:
    def __init__(
        self,
        bus: EventBus,
        price_buffer: PriceBuffer,
        news_service: NewsService,
        predictor: Predictor,
        settings: Settings,
        product_id: str = "BTC-USD",
        db: Database | None = None,
    ) -> None:
        self._bus = bus
        self._price_buffer = price_buffer
        self._news_service = news_service
        self._predictor = predictor
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
            "Claude prediction strategy started for %s (interval=%dm, threshold=%.1f%%)",
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
        logger.info("Claude prediction strategy stopped")

    async def _prediction_loop(self) -> None:
        interval = self._settings.prediction_interval_minutes * 60
        # Wait briefly for initial price data to arrive
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

        logger.info("Fetching news headlines for %s...", self._product_id)
        headlines = await self._news_service.fetch_headlines(
            self._product_id,
            lookback_minutes=self._settings.prediction_interval_minutes,
        )
        logger.info("Got %d headlines, requesting Claude prediction...", len(headlines))
        prediction = await self._predictor.predict(prices, headlines)
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
        await self._log_prediction(prediction, headlines)

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
            # Bullish — buy if no open position
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
            # Bearish — sell if we have a position
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

    async def _log_prediction(self, prediction: Prediction, headlines: list[str]) -> None:
        if self._db is None:
            return

        diff_pct = (
            (prediction.target_price - prediction.current_price)
            / prediction.current_price * 100
        ) if prediction.current_price > 0 else 0

        threshold = self._settings.trade_threshold_pct
        if diff_pct > threshold:
            action = "BUY"
        elif diff_pct < -threshold:
            action = "SELL"
        else:
            action = "HOLD"

        pred_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """INSERT INTO predictions (id, product_id, action, predicted_price, current_price,
               confidence, reasoning, model, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pred_id, self._product_id, action, prediction.target_price,
             prediction.current_price, abs(diff_pct), prediction.reasoning,
             self._settings.prediction_model, now),
        )

        for headline in headlines:
            await self._db.execute(
                """INSERT INTO news_history (id, prediction_id, headline, source, sentiment, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), pred_id, headline, None, None, now),
            )
