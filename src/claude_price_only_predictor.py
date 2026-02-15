import json
import logging
from datetime import datetime, timezone

from src.events import PriceUpdate
from src.llm_client import LLMClient
from src.prediction import Prediction

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a crypto price prediction analyst. Analyze the provided "
    "price history to predict the short-term price target using technical "
    "analysis and price action patterns. "
    "Respond ONLY with valid JSON in this exact format:\n"
    '{"target_price": <float>, "timeframe_minutes": <int>, '
    '"reasoning": "<brief explanation>"}\n'
    "No other text."
)


class ClaudePriceOnlyPredictor:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def predict(self, prices: list[PriceUpdate]) -> Prediction | None:
        if not prices:
            return None

        current_price = prices[-1].price
        prompt = self._build_prompt(prices)

        try:
            raw = await self._client.complete(
                system=SYSTEM_PROMPT,
                user=prompt,
                max_tokens=512,
            )
            data = json.loads(raw)
            return Prediction(
                target_price=float(data["target_price"]),
                timeframe_minutes=int(data["timeframe_minutes"]),
                reasoning=str(data["reasoning"]),
                current_price=current_price,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.exception("Failed to parse prediction response")
            return None
        except Exception:
            logger.exception("Prediction API call failed")
            return None

    def _build_prompt(self, prices: list[PriceUpdate]) -> str:
        price_lines = "\n".join(
            f"  {p.timestamp}: ${p.price}" for p in prices
        )

        return (
            f"Product: {prices[0].product_id}\n\n"
            f"Recent price history:\n{price_lines}\n\n"
            f"Current price: ${prices[-1].price}\n\n"
            "Based on the price action and technical patterns, "
            "predict the short-term price target."
        )
