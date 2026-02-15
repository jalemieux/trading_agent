from collections import deque

from src.events import PriceUpdate


class PriceBuffer:
    def __init__(self, max_size: int = 50) -> None:
        self._max_size = max_size
        self._buffers: dict[str, deque[PriceUpdate]] = {}

    def add(self, update: PriceUpdate) -> None:
        if update.product_id not in self._buffers:
            self._buffers[update.product_id] = deque(maxlen=self._max_size)
        self._buffers[update.product_id].append(update)

    def snapshot(self, product_id: str) -> list[PriceUpdate]:
        if product_id not in self._buffers:
            return []
        return list(self._buffers[product_id])

    def latest(self, product_id: str) -> PriceUpdate | None:
        buf = self._buffers.get(product_id)
        if not buf:
            return None
        return buf[-1]
