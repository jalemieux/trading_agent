import logging
from datetime import date

from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderRequest, RiskViolation
from src.kill_switch import KillSwitch

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        kill_switch: KillSwitch,
        settings: Settings,
    ) -> None:
        self._db = db
        self._bus = bus
        self._kill_switch = kill_switch
        self._settings = settings

    async def check(self, order: OrderRequest) -> bool:
        # 1. Kill switch
        if self._kill_switch.is_active:
            await self._bus.publish(
                RiskViolation(order_id=order.order_id, reason="Kill switch is active")
            )
            return False

        # 2. Check daily P&L
        today = date.today().isoformat()
        row = await self._db.execute_fetchone(
            "SELECT total_pnl FROM daily_summary WHERE date = ?", (today,)
        )
        if row and row[0] <= -self._settings.max_daily_loss_usd:
            await self._kill_switch.activate(
                f"Daily loss ${abs(row[0]):.2f} exceeded limit ${self._settings.max_daily_loss_usd:.2f}"
            )
            await self._bus.publish(
                RiskViolation(
                    order_id=order.order_id, reason="Daily loss limit exceeded"
                )
            )
            return False

        # 3. Max order size (only for buys — sells close positions)
        if order.side == "BUY" and order.quote_size is not None:
            if order.quote_size > self._settings.max_order_size_usd:
                await self._bus.publish(
                    RiskViolation(
                        order_id=order.order_id,
                        reason=f"Order ${order.quote_size:.2f} exceeds max order size ${self._settings.max_order_size_usd:.2f}",
                    )
                )
                return False

        return True
