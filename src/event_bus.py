import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

Handler = Callable[[Any], Coroutine[Any, Any, None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Handler) -> None:
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: Handler) -> None:
        self._subscribers[event_type].remove(handler)

    async def publish(self, event: Any) -> None:
        event_type = type(event)
        for handler in self._subscribers.get(event_type, []):
            try:
                await handler(event)
            except Exception:
                logger.exception("Handler %s failed for event %s", handler, event)
