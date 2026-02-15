import json
import logging
from datetime import datetime, timezone

from anthropic import AsyncAnthropic

from src.claude_predictor import Prediction
from src.events import PriceUpdate

logger = logging.getLogger(__name__)


class ClaudePriceOnlyPredictor:
    def __init__(self, api_key: str, model: str = "claude-opus-4-6") -> None:
        self._model = model
        self._client = AsyncAnthropic(api_key=api_key)

    async def predict(self, prices: list[PriceUpdate]) -> Prediction | None:
        if not prices:
            return None

        current_price = prices[-1].price
        prompt = self._build_prompt(prices)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You are a crypto price prediction analyst. Analyze the provided "
                    "price history to predict the short-term price target using technical "
                    "analysis and price action patterns. "
                    "Respond ONLY with valid JSON in this exact format:\n"
                    '{"target_price": <float>, "timeframe_minutes": <int>, '
                    '"reasoning": "<brief explanation>"}\n'
                    "No other text."
                ),
            )
            raw = response.content[0].text
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
