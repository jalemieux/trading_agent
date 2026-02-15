import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from anthropic import AsyncAnthropic

from src.events import PriceUpdate

logger = logging.getLogger(__name__)


@dataclass
class Prediction:
    target_price: float
    timeframe_minutes: int
    reasoning: str
    current_price: float
    timestamp: str


class ClaudePredictor:
    def __init__(self, api_key: str, model: str = "claude-opus-4-6") -> None:
        self._model = model
        self._client = AsyncAnthropic(api_key=api_key)

    async def predict(
        self, prices: list[PriceUpdate], headlines: list[str]
    ) -> Prediction | None:
        if not prices:
            return None

        current_price = prices[-1].price
        prompt = self._build_prompt(prices, headlines)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You are a crypto price prediction analyst. Analyze the provided "
                    "price history and news to predict the short-term price target. "
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
            logger.exception("Failed to parse Claude prediction response")
            return None
        except Exception:
            logger.exception("Claude prediction API call failed")
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
            f"Product: {prices[0].product_id}\n\n"
            f"Recent price history:\n{price_lines}\n\n"
            f"Current price: ${prices[-1].price}\n\n"
            f"Recent news and sentiment:\n{headline_lines}\n\n"
            "Based on this data, predict the short-term price target."
        )
