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

    async def fetch_headlines(self, product_id: str) -> list[str]:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a crypto news analyst. Return the 5 most important "
                            "recent news headlines and sentiment about the requested asset. "
                            "One headline per line, numbered. Be concise."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"What are the latest news and sentiment for {product_id}?",
                    },
                ],
            )
            raw = response.choices[0].message.content or ""
            return [line.strip() for line in raw.strip().splitlines() if line.strip()]
        except Exception:
            logger.exception("Failed to fetch headlines for %s", product_id)
            return []
