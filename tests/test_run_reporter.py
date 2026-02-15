import csv
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.run_reporter import RunReporter


def make_reporter(tmp_path, db=None):
    """Helper to create a RunReporter with a temp repo path."""
    if db is None:
        db = AsyncMock()
        db.execute_fetchone = AsyncMock(return_value=None)
    return RunReporter(
        db=db,
        strategy="price_only",
        llm_provider="anthropic",
        model="claude-opus-4-6",
        product_id="BTC-USD",
        repo_path=tmp_path,
    )


class TestAppendCsv:
    def test_creates_csv_with_header_on_first_write(self, tmp_path):
        reporter = make_reporter(tmp_path)
        row = {
            "timestamp": "2026-02-15T14:00:00+00:00",
            "strategy": "price_only",
            "llm_provider": "anthropic",
            "model": "claude-opus-4-6",
            "product_id": "BTC-USD",
            "daily_pnl": 12.5,
            "unrealized_pnl": 3.2,
            "num_trades": 4,
            "fees_paid": 1.0,
            "portfolio_value": 1053.2,
            "open_positions": 1,
        }
        reporter._append_csv(row)

        csv_path = tmp_path / "runs" / "performance.csv"
        assert csv_path.exists()

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["strategy"] == "price_only"
        assert rows[0]["daily_pnl"] == "12.5"

    def test_appends_without_duplicating_header(self, tmp_path):
        reporter = make_reporter(tmp_path)
        row = {
            "timestamp": "2026-02-15T14:00:00+00:00",
            "strategy": "price_only",
            "llm_provider": "anthropic",
            "model": "claude-opus-4-6",
            "product_id": "BTC-USD",
            "daily_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "num_trades": 0,
            "fees_paid": 0.0,
            "portfolio_value": 0.0,
            "open_positions": 0,
        }
        reporter._append_csv(row)
        reporter._append_csv(row)

        csv_path = tmp_path / "runs" / "performance.csv"
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2
