# Run Reporter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `RunReporter` component that appends an hourly CSV row to `runs/performance.csv` and auto-commits+pushes to GitHub.

**Architecture:** Timer-driven async loop (same pattern as `PortfolioTracker`). Queries existing DB tables for metrics. Shells out to git for commit+push. No EventBus interaction needed.

**Tech Stack:** Python asyncio, csv stdlib, asyncio.create_subprocess_exec for git

---

### Task 1: Create RunReporter with CSV append logic

**Files:**
- Create: `src/run_reporter.py`
- Create: `tests/test_run_reporter.py`

**Step 1: Write failing tests for CSV append**

```python
# tests/test_run_reporter.py
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_reporter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.run_reporter'`

**Step 3: Implement RunReporter class with `_append_csv`**

```python
# src/run_reporter.py
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_reporter.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/run_reporter.py tests/test_run_reporter.py
git commit -m "feat: add RunReporter with CSV append logic"
```

---

### Task 2: Add DB query and row-building logic

**Files:**
- Modify: `src/run_reporter.py`
- Modify: `tests/test_run_reporter.py`

**Step 1: Write failing tests for `_build_row`**

Add to `tests/test_run_reporter.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_reporter.py::TestBuildRow -v`
Expected: FAIL — `AttributeError: 'RunReporter' object has no attribute '_build_row'`

**Step 3: Implement `_build_row`**

Add to `RunReporter` class in `src/run_reporter.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_reporter.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/run_reporter.py tests/test_run_reporter.py
git commit -m "feat: add RunReporter DB query and row building"
```

---

### Task 3: Add git commit+push and the hourly loop

**Files:**
- Modify: `src/run_reporter.py`
- Modify: `tests/test_run_reporter.py`

**Step 1: Write failing tests for git push and report loop**

Add to `tests/test_run_reporter.py`:

```python
from unittest.mock import patch, AsyncMock as StdAsyncMock


class TestGitPush:
    @pytest.mark.asyncio
    async def test_git_push_runs_commands(self, tmp_path):
        reporter = make_reporter(tmp_path)

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", new_callable=lambda: AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process
            await reporter._git_push()

        # Should have called git add, git commit, git push
        assert mock_exec.call_count == 3
        calls = [c.args for c in mock_exec.call_args_list]
        assert calls[0][:2] == ("git", "add")
        assert calls[1][:2] == ("git", "commit")
        assert calls[2][:2] == ("git", "push")

    @pytest.mark.asyncio
    async def test_git_push_logs_warning_on_failure(self, tmp_path, caplog):
        reporter = make_reporter(tmp_path)

        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"push failed"))

        with patch("asyncio.create_subprocess_exec", new_callable=lambda: AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process
            await reporter._git_push()  # Should not raise


class TestReportLoop:
    @pytest.mark.asyncio
    async def test_report_once_builds_row_appends_and_pushes(self, tmp_path):
        db = AsyncMock()
        db.execute_fetchone = AsyncMock(return_value=None)
        db.execute_fetchall = AsyncMock(return_value=[])

        reporter = make_reporter(tmp_path, db=db)

        with patch.object(reporter, "_git_push", new_callable=AsyncMock) as mock_push:
            await reporter._report_once()

        csv_path = tmp_path / "runs" / "performance.csv"
        assert csv_path.exists()
        mock_push.assert_awaited_once()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_reporter.py::TestGitPush -v`
Expected: FAIL — `AttributeError: 'RunReporter' object has no attribute '_git_push'`

**Step 3: Implement `_git_push`, `_report_once`, `start`, `stop`**

Add to `RunReporter` class in `src/run_reporter.py`:

```python
    async def start(self) -> None:
        """Start the hourly reporting loop."""
        self._task = asyncio.create_task(self._report_loop())
        logger.info("RunReporter started (hourly)")

    async def stop(self) -> None:
        """Stop the reporting loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("RunReporter stopped")

    async def _report_loop(self) -> None:
        """Run _report_once every hour."""
        while True:
            try:
                await self._report_once()
            except Exception:
                logger.exception("RunReporter failed")
            await asyncio.sleep(3600)

    async def _report_once(self) -> None:
        """Build row, append to CSV, commit+push."""
        row = await self._build_row()
        self._append_csv(row)
        await self._git_push()
        logger.info("Run data committed: pnl=$%.2f, trades=%d, value=$%.2f",
                     row["daily_pnl"], row["num_trades"], row["portfolio_value"])

    async def _git_push(self) -> None:
        """git add + commit + push the CSV file. Logs warning on failure."""
        csv_rel = self._csv_path.relative_to(self._csv_path.parent.parent)
        repo_dir = str(self._csv_path.parent.parent)

        commands = [
            ("git", "add", str(csv_rel)),
            ("git", "commit", "-m", f"run-data: {self._strategy}/{self._llm_provider}/{self._model}"),
            ("git", "push"),
        ]

        for cmd in commands:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=repo_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning("git command failed: %s — %s", " ".join(cmd), stderr.decode())
                return
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_reporter.py -v`
Expected: PASS (all 7 tests)

**Step 5: Commit**

```bash
git add src/run_reporter.py tests/test_run_reporter.py
git commit -m "feat: add RunReporter git push and hourly loop"
```

---

### Task 4: Wire RunReporter into main.py

**Files:**
- Modify: `src/main.py:1-18` (add import)
- Modify: `src/main.py:155-170` (add wiring, start, stop)

**Step 1: No test needed — integration wiring only**

**Step 2: Add import to `src/main.py`**

Add after line 15 (`from src.position_tracker import PositionTracker`):

```python
from src.run_reporter import RunReporter
```

**Step 3: Add RunReporter construction and start**

After line 159 (`await portfolio_tracker.start()`), add:

```python
    # Run reporter (hourly git commits of performance data)
    run_reporter = RunReporter(
        db=db,
        strategy=args.strategy,
        llm_provider=args.llm,
        model=model,
        product_id=settings.product_id,
        repo_path=Path(__file__).resolve().parent.parent,
    )
    await run_reporter.start()
```

Add `from pathlib import Path` to the top imports.

**Step 4: Add stop to cleanup section**

After line 166 (`await portfolio_tracker.stop()`), add:

```python
    await run_reporter.stop()
```

**Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/main.py
git commit -m "feat: wire RunReporter into main.py startup/shutdown"
```

---

### Task 5: Update documentation

**Files:**
- Modify: `docs/ai-index.md` — add RunReporter to component list and file map
- Modify: `docs/ai-components.md` — add RunReporter class documentation
- Modify: `docs/architecture.md` — add RunReporter to component table and changelog
- Modify: `README.md` — mention hourly performance reporting in Features

**Step 1: Update each doc file with RunReporter details**

Add RunReporter to the component/file tables in each doc. Mention:
- Purpose: hourly CSV performance reporting to git
- Constructor: `db, strategy, llm_provider, model, product_id, repo_path`
- Methods: `start(), stop(), _report_loop(), _report_once(), _build_row(), _append_csv(), _git_push()`
- Dependencies: Database (queries), git (subprocess)
- Output file: `runs/performance.csv`

**Step 2: Commit**

```bash
git add docs/ README.md
git commit -m "docs: add RunReporter to architecture and component docs"
```
