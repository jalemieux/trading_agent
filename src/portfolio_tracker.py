import asyncio
import logging
import uuid
from datetime import datetime, timezone

from src.coinbase_client import CoinbaseClient
from src.db import Database
from src.event_bus import EventBus

logger = logging.getLogger(__name__)


class PortfolioTracker:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        coinbase: CoinbaseClient,
        product_id: str,
        interval_seconds: int = 300,
    ) -> None:
        self._db = db
        self._bus = bus
        self._coinbase = coinbase
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None

        # Extract base/quote currencies from product_id (e.g. "SOL-USDC" -> "SOL", "USDC")
        parts = product_id.split("-")
        self._base_currency = parts[0]
        self._quote_currency = parts[1]
        self._product_id = product_id

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
        # Fetch real balances from Coinbase (sync call -> run in executor)
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, self._coinbase.get_accounts)
        except Exception:
            logger.exception("Failed to fetch Coinbase accounts, skipping snapshot")
            return

        accounts = result.get("accounts", [])

        # Find base and quote currency balances
        base_balance = 0.0
        quote_balance = 0.0
        for account in accounts:
            currency = account.get("currency", "")
            balance = float(account.get("available_balance", {}).get("value", "0"))
            if currency == self._base_currency:
                base_balance = balance
            elif currency == self._quote_currency:
                quote_balance = balance

        # Convert base currency to USD using latest price
        base_value = 0.0
        if base_balance > 0:
            price_row = await self._db.execute_fetchone(
                "SELECT price FROM price_history WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1",
                (self._product_id,),
            )
            if price_row:
                base_value = base_balance * price_row[0]

        total_value = base_value + quote_balance

        # Local PnL calculations (unchanged)
        positions = await self._db.execute_fetchall(
            "SELECT entry_price, quantity FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (self._product_id,),
        )

        unrealized_pnl = 0.0
        if positions:
            price_row = await self._db.execute_fetchone(
                "SELECT price FROM price_history WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1",
                (self._product_id,),
            )
            if price_row:
                current_price = price_row[0]
                for entry_price, quantity in positions:
                    unrealized_pnl += (current_price - entry_price) * quantity

        pnl_row = await self._db.execute_fetchone(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE status = 'CLOSED'"
        )
        realized_pnl_cumulative = pnl_row[0] if pnl_row else 0.0

        # Write snapshot
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO portfolio_snapshots
               (id, timestamp, total_value_usd, realized_pnl_cumulative, unrealized_pnl)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), now, total_value, realized_pnl_cumulative, unrealized_pnl),
        )
        logger.info("Portfolio snapshot: value=$%.2f, unrealized=$%.2f, realized=$%.2f",
                     total_value, unrealized_pnl, realized_pnl_cumulative)
