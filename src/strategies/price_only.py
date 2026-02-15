import logging

from src.llm_client import LLMClient
from src.prediction import Prediction, parse_prediction
from src.price_buffer import PriceBuffer
from src.strategy import Strategy

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


class PriceOnlyStrategy(Strategy):
    def __init__(self, llm_client: LLMClient, **kwargs) -> None:
        super().__init__(**kwargs)
        self._llm_client = llm_client

    async def _gather_and_predict(self) -> Prediction | None:
        prices = self._price_buffer.snapshot(self._product_id)
        if not prices:
            return None

        current_price = prices[-1].price
        prompt = self._build_prompt(prices)

        try:
            raw = await self._llm_client.complete(
                system=SYSTEM_PROMPT,
                user=prompt,
                max_tokens=512,
            )
        except Exception:
            logger.exception("LLM API call failed")
            return None

        return parse_prediction(raw, current_price)

    def _build_prompt(self, prices) -> str:
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
