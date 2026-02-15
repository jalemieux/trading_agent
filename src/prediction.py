from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.events import PriceUpdate


@dataclass
class Prediction:
    target_price: float
    timeframe_minutes: int
    reasoning: str
    current_price: float
    timestamp: str


@runtime_checkable
class Predictor(Protocol):
    async def predict(
        self, prices: list[PriceUpdate], headlines: list[str]
    ) -> Prediction | None: ...
