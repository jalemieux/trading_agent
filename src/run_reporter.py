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
