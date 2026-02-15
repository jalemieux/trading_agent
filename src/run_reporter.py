import asyncio
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.db import Database

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "timestamp",
    "strategy",
    "llm_provider",
    "model",
    "product_id",
    "daily_pnl",
    "unrealized_pnl",
    "num_trades",
    "fees_paid",
    "portfolio_value",
    "open_positions",
]


class RunReporter:
    def __init__(
        self,
        db: Database,
        strategy: str,
        llm_provider: str,
        model: str,
        product_id: str,
        repo_path: Path,
    ) -> None:
        self._db = db
        self._strategy = strategy
        self._llm_provider = llm_provider
        self._model = model
        self._product_id = product_id
        self._csv_path = Path(repo_path) / "runs" / "performance.csv"
        self._task: asyncio.Task | None = None

    def _append_csv(self, row: dict) -> None:
        """Append a row to runs/performance.csv, creating file + header if needed."""
        self._csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self._csv_path.exists()

        with open(self._csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    async def _build_row(self) -> dict:
        """Query DB and build a CSV row dict."""
        now = datetime.now(timezone.utc).isoformat()

        # Today's daily summary
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = await self._db.execute_fetchone(
            "SELECT total_pnl, num_trades, fees_paid FROM daily_summary WHERE date = ?",
            (today,),
        )

        # Latest portfolio snapshot
        snapshot = await self._db.execute_fetchone(
            "SELECT total_value_usd, unrealized_pnl FROM portfolio_snapshots "
            "ORDER BY timestamp DESC LIMIT 1",
        )

        # Open position count
        open_pos = await self._db.execute_fetchall(
            "SELECT COUNT(*) FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (self._product_id,),
        )

        return {
            "timestamp": now,
            "strategy": self._strategy,
            "llm_provider": self._llm_provider,
            "model": self._model,
            "product_id": self._product_id,
            "daily_pnl": daily[0] if daily else 0.0,
            "unrealized_pnl": snapshot[1] if snapshot else 0.0,
            "num_trades": daily[1] if daily else 0,
            "fees_paid": daily[2] if daily else 0.0,
            "portfolio_value": snapshot[0] if snapshot else 0.0,
            "open_positions": open_pos[0][0] if open_pos else 0,
        }
