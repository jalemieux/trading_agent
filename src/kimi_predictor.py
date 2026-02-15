import json
import logging
from datetime import datetime, timezone

from src.events import PriceUpdate
from src.llm_client import LLMClient
from src.prediction import Prediction

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a quantitative crypto analyst. Given price history and recent news, "
    "predict the short-term price target.\n"
    "Respond ONLY with valid JSON in this exact format:\n"
    '{"target_price": <float>, "timeframe_minutes": <int>, '
    '"reasoning": "<brief explanation>"}\n'
    "No other text."
)


class KimiPredictor:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def predict(
        self, prices: list[PriceUpdate], headlines: list[str]
    ) -> Prediction | None:
        if not prices:
            return None

        current_price = prices[-1].price
        user_prompt = self._build_prompt(prices, headlines)

        try:
            raw = await self._client.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
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
            logger.exception("Failed to parse Kimi prediction response")
            return None
        except Exception:
            logger.exception("Kimi prediction API call failed")
            return None

    def _build_prompt(
        self, prices: list[PriceUpdate], headlines: list[str]
    ) -> str:
        price_lines = "\n".join(
            f"  {p.timestamp}: ${p.price}" for p in prices
        )
        headline_lines = (
            "\n".join(f"  {h}" for h in headlines)
            if headlines
            else "  No recent news available"
        )

        return (
            f"Asset: {prices[0].product_id}\n\n"
            f"Price history (recent):\n{price_lines}\n\n"
            f"Latest price: ${prices[-1].price}\n\n"
            f"News headlines:\n{headline_lines}\n\n"
            "Predict the price target for the next short-term window."
        )
