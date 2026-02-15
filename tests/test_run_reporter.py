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


class TestBuildRow:
    @pytest.mark.asyncio
    async def test_build_row_with_data(self, tmp_path):
        db = AsyncMock()
        # daily_summary: (total_pnl, num_trades, fees_paid)
        db.execute_fetchone = AsyncMock(side_effect=[
            (12.5, 4, 1.0),                    # daily_summary
            (1053.2, 3.2),                      # portfolio_snapshots
        ])
        # open positions count
        db.execute_fetchall = AsyncMock(return_value=[(1,)])

        reporter = make_reporter(tmp_path, db=db)
        row = await reporter._build_row()

        assert row["strategy"] == "price_only"
        assert row["daily_pnl"] == 12.5
        assert row["unrealized_pnl"] == 3.2
        assert row["num_trades"] == 4
        assert row["portfolio_value"] == 1053.2
        assert row["open_positions"] == 1

    @pytest.mark.asyncio
    async def test_build_row_no_data_returns_zeros(self, tmp_path):
        db = AsyncMock()
        db.execute_fetchone = AsyncMock(return_value=None)
        db.execute_fetchall = AsyncMock(return_value=[])

        reporter = make_reporter(tmp_path, db=db)
        row = await reporter._build_row()

        assert row["daily_pnl"] == 0.0
        assert row["unrealized_pnl"] == 0.0
        assert row["num_trades"] == 0
        assert row["fees_paid"] == 0.0
        assert row["portfolio_value"] == 0.0
        assert row["open_positions"] == 0
