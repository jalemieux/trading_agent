import logging
from datetime import datetime, timezone

from src.db import Database
from src.event_bus import EventBus
from src.events import KillSwitchActivated

logger = logging.getLogger(__name__)


class KillSwitch:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def initialize(self) -> None:
        row = await self._db.execute_fetchone("SELECT active FROM kill_switch WHERE id = 1")
        if row:
            self._active = bool(row[0])

    async def activate(self, reason: str) -> None:
        self._active = True
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE kill_switch SET active = 1, reason = ?, activated_at = ? WHERE id = 1",
            (reason, now),
        )
        logger.warning("KILL SWITCH ACTIVATED: %s", reason)
        await self._bus.publish(KillSwitchActivated(reason=reason))

    async def deactivate(self) -> None:
        self._active = False
        await self._db.execute(
            "UPDATE kill_switch SET active = 0, reason = NULL, activated_at = NULL WHERE id = 1"
        )
        logger.info("Kill switch deactivated")
