import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class NewsService:
    def __init__(self, api_key: str, model: str = "grok-3-mini-fast") -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )

    async def fetch_headlines(self, product_id: str, lookback_minutes: int = 5) -> list[str]:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a crypto news analyst. Return the 5 most important "
                            f"news headlines from the last {lookback_minutes} minutes "
                            "about the requested asset. Include sentiment (bullish/bearish/neutral) "
                            "for each. One headline per line, numbered. Be concise. "
                            "If there is no news from this period, say 'No recent news.'"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"What are the news headlines from the last {lookback_minutes} minutes for {product_id}?",
                    },
                ],
            )
            raw = response.choices[0].message.content or ""
            return [line.strip() for line in raw.strip().splitlines() if line.strip()]
        except Exception:
            logger.exception("Failed to fetch headlines for %s", product_id)
            return []
