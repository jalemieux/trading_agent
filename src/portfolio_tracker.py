import asyncio
import logging
import uuid
from datetime import datetime, timezone

from src.db import Database
from src.event_bus import EventBus

logger = logging.getLogger(__name__)


class PortfolioTracker:
    def __init__(self, db: Database, bus: EventBus, interval_seconds: int = 300) -> None:
        self._db = db
        self._bus = bus
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._snapshot_loop())
        logger.info("PortfolioTracker started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PortfolioTracker stopped")

    async def _snapshot_loop(self) -> None:
        while True:
            try:
                await self.take_snapshot()
            except Exception:
                logger.exception("Portfolio snapshot failed")
            await asyncio.sleep(self._interval)

    async def take_snapshot(self) -> None:
        # Get all open positions
        positions = await self._db.execute_fetchall(
            "SELECT product_id, entry_price, quantity FROM positions WHERE status = 'OPEN'"
        )

        position_value = 0.0
        unrealized_pnl = 0.0
        num_open = len(positions)

        for product_id, entry_price, quantity in positions:
            # Get latest price for this product
            price_row = await self._db.execute_fetchone(
                "SELECT price FROM price_history WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1",
                (product_id,),
            )
            if price_row:
                current_price = price_row[0]
                position_value += current_price * quantity
                unrealized_pnl += (current_price - entry_price) * quantity
            else:
                # Use entry price if no price history available
                position_value += entry_price * quantity

        # Cumulative realized P&L from all closed positions
        pnl_row = await self._db.execute_fetchone(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE status = 'CLOSED'"
        )
        realized_pnl_cumulative = pnl_row[0] if pnl_row else 0.0

        total_value = position_value + realized_pnl_cumulative

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO portfolio_snapshots
               (id, timestamp, total_value_usd, position_value_usd, realized_pnl_cumulative, unrealized_pnl, num_open_positions)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), now, total_value, position_value, realized_pnl_cumulative, unrealized_pnl, num_open),
        )
        logger.info("Portfolio snapshot: value=$%.2f, unrealized=$%.2f, realized=$%.2f",
                     total_value, unrealized_pnl, realized_pnl_cumulative)
