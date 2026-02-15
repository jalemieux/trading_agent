import logging
import uuid
from datetime import datetime, timezone

from src.llm_client import LLMClient
from src.news_service import NewsService
from src.prediction import Prediction, parse_prediction
from src.strategy import Strategy

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a crypto price prediction analyst. Analyze the provided "
    "price history and news to predict the short-term price target. "
    "Respond ONLY with valid JSON in this exact format:\n"
    '{"target_price": <float>, "timeframe_minutes": <int>, '
    '"reasoning": "<brief explanation>"}\n'
    "No other text."
)


class NewsPredictionStrategy(Strategy):
    def __init__(
        self,
        llm_client: LLMClient,
        news_service: NewsService,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._llm_client = llm_client
        self._news_service = news_service

    async def _gather_and_predict(self) -> Prediction | None:
        prices = self._price_buffer.snapshot(self._product_id)
        if not prices:
            return None

        current_price = prices[-1].price

        headlines = await self._news_service.fetch_headlines(
            self._product_id,
            lookback_minutes=self._settings.prediction_interval_minutes,
        )
        logger.info("Got %d headlines, requesting prediction...", len(headlines))

        prompt = self._build_prompt(prices, headlines)

        try:
            raw = await self._llm_client.complete(
                system=SYSTEM_PROMPT,
                user=prompt,
                max_tokens=512,
            )
        except Exception:
            logger.exception("LLM API call failed")
            return None

        prediction = parse_prediction(raw, current_price)
        if prediction:
            await self._log_prediction(prediction, headlines)
        return prediction

    def _build_prompt(self, prices, headlines: list[str]) -> str:
        price_lines = "\n".join(
            f"  {p.timestamp}: ${p.price}" for p in prices
        )
        headline_lines = (
            "\n".join(f"  {h}" for h in headlines)
            if headlines
            else "  No recent news available"
        )
        return (
            f"Product: {prices[0].product_id}\n\n"
            f"Recent price history:\n{price_lines}\n\n"
            f"Current price: ${prices[-1].price}\n\n"
            f"Recent news and sentiment:\n{headline_lines}\n\n"
            "Based on this data, predict the short-term price target."
        )

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
             "llm", now),
        )

        for headline in headlines:
            await self._db.execute(
                """INSERT INTO news_history (id, prediction_id, headline, source, sentiment, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), pred_id, headline, None, None, now),
            )
