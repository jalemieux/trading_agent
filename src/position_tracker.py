import logging
import uuid
from datetime import date, datetime, timezone

from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFilled, PositionChanged

logger = logging.getLogger(__name__)


class PositionTracker:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus

    def register(self, bus: EventBus) -> None:
        bus.subscribe(OrderFilled, self._handle_order_filled)

    async def _handle_order_filled(self, event: OrderFilled) -> None:
        # Ensure the order exists in the DB so fee lookups work later
        await self._upsert_order(event)

        if event.side == "BUY":
            await self._open_or_add_position(event)
        else:
            await self._reduce_or_close_position(event)

    async def _upsert_order(self, event: OrderFilled) -> None:
        """Insert or update the order record from the fill event."""
        now = datetime.now(timezone.utc).isoformat()
        existing = await self._db.execute_fetchone(
            "SELECT id FROM orders WHERE id = ?", (event.order_id,)
        )
        if existing:
            await self._db.execute(
                """UPDATE orders SET status = 'FILLED', filled_price = ?, filled_qty = ?,
                   fee = ?, coinbase_id = ?, filled_at = ? WHERE id = ?""",
                (event.filled_price, event.filled_qty, event.fee,
                 event.coinbase_order_id, now, event.order_id),
            )
        else:
            await self._db.execute(
                """INSERT INTO orders (id, product_id, side, type, quantity, status,
                   filled_price, filled_qty, fee, coinbase_id, created_at, filled_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event.order_id, event.product_id, event.side, "MARKET",
                 event.filled_qty, "FILLED", event.filled_price, event.filled_qty,
                 event.fee, event.coinbase_order_id, now, now),
            )

    async def _open_or_add_position(self, event: OrderFilled) -> None:
        # Check for existing open position in this product
        row = await self._db.execute_fetchone(
            "SELECT id, entry_price, quantity FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (event.product_id,),
        )

        now = datetime.now(timezone.utc).isoformat()

        if row:
            # Average into existing position
            pos_id, old_price, old_qty = row
            new_qty = old_qty + event.filled_qty
            new_price = ((old_price * old_qty) + (event.filled_price * event.filled_qty)) / new_qty
            await self._db.execute(
                "UPDATE positions SET entry_price = ?, quantity = ? WHERE id = ?",
                (new_price, new_qty, pos_id),
            )
        else:
            pos_id = str(uuid.uuid4())
            await self._db.execute(
                """INSERT INTO positions (id, product_id, side, entry_price, quantity, status, opened_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (pos_id, event.product_id, "LONG", event.filled_price, event.filled_qty, "OPEN", now),
            )

        # Link order to position
        await self._db.execute(
            "UPDATE orders SET position_id = ? WHERE id = ?", (pos_id, event.order_id)
        )

        pos = await self._db.execute_fetchone(
            "SELECT quantity, entry_price FROM positions WHERE id = ?", (pos_id,)
        )
        await self._bus.publish(
            PositionChanged(
                position_id=pos_id,
                product_id=event.product_id,
                side="LONG",
                quantity=pos[0],
                entry_price=pos[1],
                status="OPEN",
            )
        )

    async def _reduce_or_close_position(self, event: OrderFilled) -> None:
        row = await self._db.execute_fetchone(
            "SELECT id, entry_price, quantity FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (event.product_id,),
        )
        if not row:
            logger.warning("Sell for %s but no open position found", event.product_id)
            return

        pos_id, entry_price, current_qty = row
        sell_qty = min(event.filled_qty, current_qty)
        remaining = current_qty - sell_qty

        # Calculate realized P&L
        pnl = (event.filled_price - entry_price) * sell_qty - event.fee
        # Include buy-side fee proportionally
        buy_fee_row = await self._db.execute_fetchone(
            "SELECT COALESCE(SUM(fee), 0) FROM orders WHERE position_id = ? AND side = 'BUY'",
            (pos_id,),
        )
        buy_fee_total = buy_fee_row[0] if buy_fee_row else 0
        # Proportion of buy fee attributable to this sell
        buy_fee_portion = buy_fee_total * (sell_qty / current_qty) if current_qty > 0 else 0
        pnl -= buy_fee_portion

        now = datetime.now(timezone.utc).isoformat()

        if remaining <= 1e-10:
            # Fully closed
            await self._db.execute(
                "UPDATE positions SET status = 'CLOSED', quantity = 0, realized_pnl = ?, closed_at = ? WHERE id = ?",
                (pnl, now, pos_id),
            )
            status = "CLOSED"
            remaining = 0.0
        else:
            # Partially closed
            await self._db.execute(
                "UPDATE positions SET quantity = ?, realized_pnl = COALESCE(realized_pnl, 0) + ? WHERE id = ?",
                (remaining, pnl, pos_id),
            )
            status = "OPEN"

        # Link order
        await self._db.execute(
            "UPDATE orders SET position_id = ? WHERE id = ?", (pos_id, event.order_id)
        )

        # Update daily summary
        today = date.today().isoformat()
        existing = await self._db.execute_fetchone(
            "SELECT total_pnl, num_trades, fees_paid FROM daily_summary WHERE date = ?", (today,)
        )
        total_fee = event.fee + buy_fee_portion
        if existing:
            await self._db.execute(
                "UPDATE daily_summary SET total_pnl = total_pnl + ?, num_trades = num_trades + 1, fees_paid = fees_paid + ? WHERE date = ?",
                (pnl, total_fee, today),
            )
        else:
            await self._db.execute(
                "INSERT INTO daily_summary (date, total_pnl, num_trades, fees_paid) VALUES (?, ?, 1, ?)",
                (today, pnl, total_fee),
            )

        pos = await self._db.execute_fetchone(
            "SELECT entry_price FROM positions WHERE id = ?", (pos_id,)
        )
        await self._bus.publish(
            PositionChanged(
                position_id=pos_id,
                product_id=event.product_id,
                side="LONG",
                quantity=remaining,
                entry_price=pos[0] if pos else entry_price,
                status=status,
            )
        )
