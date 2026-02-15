# Strategy / LLM Provider Decoupling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decouple prediction strategies from LLM providers so any strategy works with any LLM backend, controlled via CLI args. Eliminate the predictor layer entirely.

**Architecture:** Two-layer design — strategies own prompts and data gathering, calling `self._llm_client.complete(system, user)` directly. A Strategy ABC holds all shared logic (timer loop, evaluation, position checks). A registry maps CLI args to strategy/provider classes. The predictor classes (`ClaudePredictor`, `KimiPredictor`, `ClaudePriceOnlyPredictor`) are deleted.

**Tech Stack:** Python 3.12, asyncio, argparse, pydantic-settings

**Design doc:** `docs/plans/2026-02-15-strategy-llm-decoupling-design.md`

---

### Task 1: Add `parse_prediction()` Helper to `src/prediction.py`

**Files:**
- Modify: `src/prediction.py`
- Test: `tests/test_prediction.py`

**Step 1: Write the failing test**

Add to `tests/test_prediction.py`:

```python
import pytest
from src.prediction import Prediction, parse_prediction


def test_parse_prediction_valid_json():
    raw = '{"target_price": 105000.0, "timeframe_minutes": 60, "reasoning": "Bullish momentum"}'
    result = parse_prediction(raw, current_price=100000.0)
    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    assert result.timeframe_minutes == 60
    assert result.reasoning == "Bullish momentum"
    assert result.current_price == 100000.0


def test_parse_prediction_malformed_json():
    result = parse_prediction("not json at all", current_price=100000.0)
    assert result is None


def test_parse_prediction_missing_keys():
    raw = '{"target_price": 105000.0}'
    result = parse_prediction(raw, current_price=100000.0)
    assert result is None


def test_parse_prediction_api_wrapper():
    """Handles LLM responses that wrap JSON in markdown code blocks."""
    raw = '```json\n{"target_price": 105000.0, "timeframe_minutes": 60, "reasoning": "test"}\n```'
    result = parse_prediction(raw, current_price=100000.0)
    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_prediction.py::test_parse_prediction_valid_json -v`
Expected: FAIL — `ImportError: cannot import name 'parse_prediction'`

**Step 3: Implement `parse_prediction` in `src/prediction.py`**

Replace `src/prediction.py` entirely:

```python
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class Prediction:
    target_price: float
    timeframe_minutes: int
    reasoning: str
    current_price: float
    timestamp: str


def parse_prediction(raw: str, current_price: float) -> Prediction | None:
    """Parse an LLM response into a Prediction. Returns None on failure."""
    # Strip markdown code blocks if present
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    try:
        data = json.loads(stripped)
        return Prediction(
            target_price=float(data["target_price"]),
            timeframe_minutes=int(data["timeframe_minutes"]),
            reasoning=str(data["reasoning"]),
            current_price=current_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("Failed to parse prediction response: %s", raw[:200])
        return None
```

Note: The `Predictor` protocol is removed. The `PriceUpdate` import is removed (no longer needed here).

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_prediction.py -v`
Expected: All prediction tests PASS

**Step 5: Commit**

```bash
git add src/prediction.py tests/test_prediction.py
git commit -m "feat: add parse_prediction() helper, remove Predictor protocol"
```

---

### Task 2: Create Strategy ABC — `src/strategy.py`

**Files:**
- Create: `src/strategy.py`
- Test: `tests/test_strategy_base.py`

**Step 1: Write the failing tests**

Create `tests/test_strategy_base.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.prediction import Prediction
from src.price_buffer import PriceBuffer
from src.strategy import Strategy


class StubStrategy(Strategy):
    """Minimal concrete strategy for testing the base class."""

    def __init__(self, prediction_result, **kwargs):
        super().__init__(**kwargs)
        self._prediction_result = prediction_result

    async def _gather_and_predict(self) -> Prediction | None:
        return self._prediction_result


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def price_buffer():
    buf = PriceBuffer(max_size=50)
    for i in range(5):
        buf.add(PriceUpdate(
            product_id="BTC-USD",
            price=100000.0 + i * 100,
            timestamp=f"2026-02-15T10:0{i}:00Z",
        ))
    return buf


@pytest.fixture
def settings():
    s = MagicMock()
    s.trade_threshold_pct = 1.0
    s.trade_size_usd = 50.0
    s.prediction_interval_minutes = 5
    return s


def _make_strategy(bus, price_buffer, settings, prediction, db=None):
    return StubStrategy(
        prediction_result=prediction,
        bus=bus,
        price_buffer=price_buffer,
        settings=settings,
        product_id="BTC-USD",
        db=db,
    )


async def test_on_price_feeds_buffer(bus, settings):
    buf = PriceBuffer()
    strat = _make_strategy(bus, buf, settings, prediction=None)
    strat.register(bus)

    await bus.publish(PriceUpdate(product_id="BTC-USD", price=99000.0, timestamp="t1"))
    assert len(buf.snapshot("BTC-USD")) == 1


async def test_bullish_emits_buy(bus, price_buffer, settings):
    prediction = Prediction(
        target_price=105420.0, timeframe_minutes=60,
        reasoning="Bullish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    )
    strat = _make_strategy(bus, price_buffer, settings, prediction)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()

    assert len(orders) == 1
    assert orders[0].side == "BUY"
    assert orders[0].quote_size == 50.0


async def test_bearish_emits_sell(bus, price_buffer, settings):
    prediction = Prediction(
        target_price=95380.0, timeframe_minutes=60,
        reasoning="Bearish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    )
    strat = _make_strategy(bus, price_buffer, settings, prediction)
    strat._has_open_position = AsyncMock(return_value=True)
    strat._get_position_quantity = AsyncMock(return_value=0.001)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()

    assert len(orders) == 1
    assert orders[0].side == "SELL"
    assert orders[0].base_size == 0.001


async def test_neutral_no_order(bus, price_buffer, settings):
    prediction = Prediction(
        target_price=100902.0, timeframe_minutes=60,
        reasoning="Sideways", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    )
    strat = _make_strategy(bus, price_buffer, settings, prediction)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()
    assert len(orders) == 0


async def test_buy_blocked_when_position_open(bus, price_buffer, settings):
    prediction = Prediction(
        target_price=105420.0, timeframe_minutes=60,
        reasoning="Bullish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    )
    strat = _make_strategy(bus, price_buffer, settings, prediction)
    strat._has_open_position = AsyncMock(return_value=True)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()
    assert len(orders) == 0


async def test_sell_blocked_when_no_position(bus, price_buffer, settings):
    prediction = Prediction(
        target_price=95380.0, timeframe_minutes=60,
        reasoning="Bearish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    )
    strat = _make_strategy(bus, price_buffer, settings, prediction)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()
    assert len(orders) == 0


async def test_none_prediction_skips(bus, price_buffer, settings):
    strat = _make_strategy(bus, price_buffer, settings, prediction=None)

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()
    assert len(orders) == 0


async def test_no_prices_skips(bus, settings):
    empty_buf = PriceBuffer()
    strat = _make_strategy(bus, empty_buf, settings, prediction=Prediction(
        target_price=105420.0, timeframe_minutes=60,
        reasoning="Bullish", current_price=100400.0,
        timestamp="t",
    ))

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strat._run_prediction_cycle()
    assert len(orders) == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_strategy_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.strategy'`

**Step 3: Implement `src/strategy.py`**

Create `src/strategy.py`:

```python
import abc
import asyncio
import logging

from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.prediction import Prediction
from src.price_buffer import PriceBuffer

logger = logging.getLogger(__name__)


class Strategy(abc.ABC):
    def __init__(
        self,
        bus: EventBus,
        price_buffer: PriceBuffer,
        settings: Settings,
        product_id: str = "BTC-USD",
        db: Database | None = None,
    ) -> None:
        self._bus = bus
        self._price_buffer = price_buffer
        self._settings = settings
        self._product_id = product_id
        self._db = db
        self._task: asyncio.Task | None = None

    def register(self, bus: EventBus) -> None:
        bus.subscribe(PriceUpdate, self._on_price)

    async def _on_price(self, event: PriceUpdate) -> None:
        self._price_buffer.add(event)
        count = len(self._price_buffer.snapshot(event.product_id))
        if count == 1:
            logger.info("First price tick for %s: $%.2f", event.product_id, event.price)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._prediction_loop())
        logger.info(
            "Strategy started for %s (interval=%dm, threshold=%.1f%%)",
            self._product_id,
            self._settings.prediction_interval_minutes,
            self._settings.trade_threshold_pct,
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Strategy stopped")

    async def _prediction_loop(self) -> None:
        interval = self._settings.prediction_interval_minutes * 60
        logger.info("Waiting 30s for initial price data...")
        await asyncio.sleep(30)
        while True:
            logger.info("Starting prediction cycle...")
            try:
                await self._run_prediction_cycle()
            except Exception:
                logger.exception("Prediction cycle failed")
            logger.info("Prediction cycle complete, next in %d minutes", interval // 60)
            await asyncio.sleep(interval)

    async def _run_prediction_cycle(self) -> None:
        prices = self._price_buffer.snapshot(self._product_id)
        if not prices:
            logger.warning("No price data for %s, skipping prediction", self._product_id)
            return

        prediction = await self._gather_and_predict()
        if prediction is None:
            logger.warning("Prediction returned None, skipping")
            return

        logger.info(
            "Prediction: target=$%.2f (current=$%.2f) in %dm — %s",
            prediction.target_price,
            prediction.current_price,
            prediction.timeframe_minutes,
            prediction.reasoning,
        )

        await self._evaluate(prediction)

    @abc.abstractmethod
    async def _gather_and_predict(self) -> Prediction | None:
        """Gather data, build prompts, call LLM, parse response."""
        ...

    async def _evaluate(self, prediction: Prediction) -> None:
        if prediction.current_price <= 0:
            logger.warning("Invalid current price %.2f, skipping", prediction.current_price)
            return

        diff_pct = (
            (prediction.target_price - prediction.current_price)
            / prediction.current_price
            * 100
        )

        threshold = self._settings.trade_threshold_pct

        if diff_pct > threshold:
            if await self._has_open_position():
                logger.info("Bullish (%.1f%%) but position already open, holding", diff_pct)
                return
            logger.info("Bullish signal (%.1f%%), placing BUY", diff_pct)
            await self._bus.publish(OrderRequest(
                product_id=self._product_id,
                side="BUY",
                order_type="MARKET",
                quote_size=self._settings.trade_size_usd,
            ))

        elif diff_pct < -threshold:
            if not await self._has_open_position():
                logger.info("Bearish (%.1f%%) but no position to sell, holding", diff_pct)
                return
            qty = await self._get_position_quantity()
            if qty <= 0:
                logger.warning("Position quantity is zero, skipping SELL")
                return
            logger.info("Bearish signal (%.1f%%), placing SELL for %.6f", diff_pct, qty)
            await self._bus.publish(OrderRequest(
                product_id=self._product_id,
                side="SELL",
                order_type="MARKET",
                base_size=qty,
            ))

        else:
            logger.info("Neutral (%.1f%%), holding", diff_pct)

    async def _has_open_position(self) -> bool:
        if self._db is None:
            return False
        row = await self._db.execute_fetchone(
            "SELECT id FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (self._product_id,),
        )
        return row is not None

    async def _get_position_quantity(self) -> float:
        if self._db is None:
            return 0.0
        row = await self._db.execute_fetchone(
            "SELECT quantity FROM positions WHERE product_id = ? AND status = 'OPEN'",
            (self._product_id,),
        )
        return float(row[0]) if row else 0.0
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_strategy_base.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add src/strategy.py tests/test_strategy_base.py
git commit -m "feat: add Strategy ABC with shared evaluation and timer logic"
```

---

### Task 3: Create `PriceOnlyStrategy` — `src/strategies/price_only.py`

**Files:**
- Create: `src/strategies/__init__.py`
- Create: `src/strategies/price_only.py`
- Test: `tests/test_strategies_price_only.py`

**Step 1: Write the failing tests**

Create `tests/test_strategies_price_only.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.prediction import Prediction
from src.price_buffer import PriceBuffer
from src.strategies.price_only import PriceOnlyStrategy


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def price_buffer():
    buf = PriceBuffer(max_size=50)
    for i in range(5):
        buf.add(PriceUpdate(
            product_id="BTC-USD",
            price=100000.0 + i * 100,
            timestamp=f"2026-02-15T10:0{i}:00Z",
        ))
    return buf


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.complete = AsyncMock(
        return_value=(
            '{"target_price": 105000.0, "timeframe_minutes": 60, '
            '"reasoning": "Strong upward momentum in price action"}'
        )
    )
    return client


@pytest.fixture
def settings():
    s = MagicMock()
    s.trade_threshold_pct = 1.0
    s.trade_size_usd = 50.0
    s.prediction_interval_minutes = 5
    return s


@pytest.fixture
def strategy(bus, price_buffer, mock_llm_client, settings):
    return PriceOnlyStrategy(
        bus=bus,
        price_buffer=price_buffer,
        llm_client=mock_llm_client,
        settings=settings,
        product_id="BTC-USD",
    )


async def test_gather_and_predict_calls_llm(strategy, mock_llm_client):
    result = await strategy._gather_and_predict()

    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    mock_llm_client.complete.assert_called_once()

    # Verify prompt contains price data but no news
    call_kwargs = mock_llm_client.complete.call_args.kwargs
    assert "100000.0" in call_kwargs["user"]
    assert "news" not in call_kwargs["user"].lower()
    assert "headline" not in call_kwargs["user"].lower()


async def test_gather_and_predict_api_error(strategy, mock_llm_client):
    mock_llm_client.complete = AsyncMock(side_effect=Exception("API error"))

    result = await strategy._gather_and_predict()
    assert result is None


async def test_gather_and_predict_malformed_json(strategy, mock_llm_client):
    mock_llm_client.complete = AsyncMock(return_value="not json")

    result = await strategy._gather_and_predict()
    assert result is None


async def test_gather_and_predict_no_prices(bus, mock_llm_client, settings):
    empty_buf = PriceBuffer()
    strat = PriceOnlyStrategy(
        bus=bus, price_buffer=empty_buf, llm_client=mock_llm_client,
        settings=settings, product_id="BTC-USD",
    )

    result = await strat._gather_and_predict()
    assert result is None
    mock_llm_client.complete.assert_not_called()


async def test_full_cycle_bullish_buy(strategy, bus, mock_llm_client):
    """End-to-end: LLM returns bullish → BUY order emitted."""
    mock_llm_client.complete = AsyncMock(
        return_value='{"target_price": 105420.0, "timeframe_minutes": 60, "reasoning": "Bullish"}'
    )

    orders: list[OrderRequest] = []
    bus.subscribe(OrderRequest, lambda e: orders.append(e))

    await strategy._run_prediction_cycle()

    assert len(orders) == 1
    assert orders[0].side == "BUY"


async def test_no_news_service_dependency(strategy):
    """PriceOnlyStrategy should have no news_service attribute."""
    assert not hasattr(strategy, "_news_service")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_strategies_price_only.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.strategies'`

**Step 3: Create `src/strategies/__init__.py`**

```python
```

(Empty file.)

**Step 4: Implement `src/strategies/price_only.py`**

```python
import logging

from src.llm_client import LLMClient
from src.prediction import Prediction, parse_prediction
from src.price_buffer import PriceBuffer
from src.strategy import Strategy

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a crypto price prediction analyst. Analyze the provided "
    "price history to predict the short-term price target using technical "
    "analysis and price action patterns. "
    "Respond ONLY with valid JSON in this exact format:\n"
    '{"target_price": <float>, "timeframe_minutes": <int>, '
    '"reasoning": "<brief explanation>"}\n'
    "No other text."
)


class PriceOnlyStrategy(Strategy):
    def __init__(self, llm_client: LLMClient, **kwargs) -> None:
        super().__init__(**kwargs)
        self._llm_client = llm_client

    async def _gather_and_predict(self) -> Prediction | None:
        prices = self._price_buffer.snapshot(self._product_id)
        if not prices:
            return None

        current_price = prices[-1].price
        prompt = self._build_prompt(prices)

        try:
            raw = await self._llm_client.complete(
                system=SYSTEM_PROMPT,
                user=prompt,
                max_tokens=512,
            )
        except Exception:
            logger.exception("LLM API call failed")
            return None

        return parse_prediction(raw, current_price)

    def _build_prompt(self, prices) -> str:
        price_lines = "\n".join(
            f"  {p.timestamp}: ${p.price}" for p in prices
        )
        return (
            f"Product: {prices[0].product_id}\n\n"
            f"Recent price history:\n{price_lines}\n\n"
            f"Current price: ${prices[-1].price}\n\n"
            "Based on the price action and technical patterns, "
            "predict the short-term price target."
        )
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_strategies_price_only.py -v`
Expected: All 6 tests PASS

**Step 6: Commit**

```bash
git add src/strategies/__init__.py src/strategies/price_only.py tests/test_strategies_price_only.py
git commit -m "feat: add PriceOnlyStrategy using Strategy ABC + LLMClient"
```

---

### Task 4: Create `NewsPredictionStrategy` — `src/strategies/news.py`

**Files:**
- Create: `src/strategies/news.py`
- Test: `tests/test_strategies_news.py`

**Step 1: Write the failing tests**

Create `tests/test_strategies_news.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db import Database
from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.prediction import Prediction
from src.price_buffer import PriceBuffer
from src.strategies.news import NewsPredictionStrategy


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def price_buffer():
    buf = PriceBuffer(max_size=50)
    buf.add(PriceUpdate(product_id="BTC-USD", price=50000.0, timestamp="2026-01-01T00:00:00Z"))
    return buf


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.complete = AsyncMock(
        return_value=(
            '{"target_price": 55000.0, "timeframe_minutes": 60, '
            '"reasoning": "Bullish momentum with strong ETF inflows"}'
        )
    )
    return client


@pytest.fixture
def news_service():
    service = MagicMock()
    service.fetch_headlines = AsyncMock(return_value=["Bitcoin surges on ETF inflows"])
    return service


@pytest.fixture
def settings():
    s = MagicMock()
    s.trade_threshold_pct = 1.0
    s.trade_size_usd = 50.0
    s.prediction_interval_minutes = 5
    return s


@pytest.fixture
def strategy(bus, price_buffer, mock_llm_client, news_service, settings):
    return NewsPredictionStrategy(
        bus=bus,
        price_buffer=price_buffer,
        llm_client=mock_llm_client,
        news_service=news_service,
        settings=settings,
        product_id="BTC-USD",
    )


async def test_gather_and_predict_calls_llm_with_news(strategy, mock_llm_client, news_service):
    result = await strategy._gather_and_predict()

    assert isinstance(result, Prediction)
    assert result.target_price == 55000.0
    mock_llm_client.complete.assert_called_once()
    news_service.fetch_headlines.assert_called_once()

    # Prompt should include news headlines
    call_kwargs = mock_llm_client.complete.call_args.kwargs
    assert "ETF inflows" in call_kwargs["user"]


async def test_gather_and_predict_api_error(strategy, mock_llm_client):
    mock_llm_client.complete = AsyncMock(side_effect=Exception("API error"))

    result = await strategy._gather_and_predict()
    assert result is None


async def test_gather_and_predict_no_prices(bus, mock_llm_client, news_service, settings):
    empty_buf = PriceBuffer()
    strat = NewsPredictionStrategy(
        bus=bus, price_buffer=empty_buf, llm_client=mock_llm_client,
        news_service=news_service, settings=settings, product_id="BTC-USD",
    )

    result = await strat._gather_and_predict()
    assert result is None
    mock_llm_client.complete.assert_not_called()


async def test_prediction_logging():
    """Predictions and news headlines are logged to the database."""
    db = Database(":memory:")
    await db.initialize()
    bus = EventBus()
    price_buffer = PriceBuffer()
    price_buffer.add(PriceUpdate(product_id="BTC-USD", price=50000.0, timestamp="2026-01-01T00:00:00Z"))

    mock_llm = MagicMock()
    mock_llm.complete = AsyncMock(
        return_value='{"target_price": 50100.0, "timeframe_minutes": 5, "reasoning": "bullish momentum"}'
    )

    mock_news = MagicMock()
    mock_news.fetch_headlines = AsyncMock(return_value=["BTC surges - bullish", "Fed holds rates - neutral"])

    settings = MagicMock()
    settings.trade_threshold_pct = 0.1
    settings.trade_size_usd = 50.0
    settings.prediction_interval_minutes = 5

    strategy = NewsPredictionStrategy(
        bus=bus, price_buffer=price_buffer, llm_client=mock_llm,
        news_service=mock_news, settings=settings, product_id="BTC-USD", db=db,
    )

    await strategy._run_prediction_cycle()

    # Check prediction was logged
    rows = await db.execute_fetchall(
        "SELECT product_id, action, predicted_price, current_price, reasoning FROM predictions"
    )
    assert len(rows) == 1
    assert rows[0][0] == "BTC-USD"
    assert rows[0][2] == 50100.0

    # Check news was logged
    news_rows = await db.execute_fetchall("SELECT headline FROM news_history")
    assert len(news_rows) == 2

    await db.close()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_strategies_news.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.strategies.news'`

**Step 3: Implement `src/strategies/news.py`**

```python
import logging
import uuid
from datetime import datetime, timezone

from src.llm_client import LLMClient
from src.news_service import NewsService
from src.prediction import Prediction, parse_prediction
from src.strategy import Strategy

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a crypto price prediction analyst. Analyze the provided "
    "price history and news to predict the short-term price target. "
    "Respond ONLY with valid JSON in this exact format:\n"
    '{"target_price": <float>, "timeframe_minutes": <int>, '
    '"reasoning": "<brief explanation>"}\n'
    "No other text."
)


class NewsPredictionStrategy(Strategy):
    def __init__(
        self,
        llm_client: LLMClient,
        news_service: NewsService,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._llm_client = llm_client
        self._news_service = news_service

    async def _gather_and_predict(self) -> Prediction | None:
        prices = self._price_buffer.snapshot(self._product_id)
        if not prices:
            return None

        current_price = prices[-1].price

        headlines = await self._news_service.fetch_headlines(
            self._product_id,
            lookback_minutes=self._settings.prediction_interval_minutes,
        )
        logger.info("Got %d headlines, requesting prediction...", len(headlines))

        prompt = self._build_prompt(prices, headlines)

        try:
            raw = await self._llm_client.complete(
                system=SYSTEM_PROMPT,
                user=prompt,
                max_tokens=512,
            )
        except Exception:
            logger.exception("LLM API call failed")
            return None

        prediction = parse_prediction(raw, current_price)
        if prediction:
            await self._log_prediction(prediction, headlines)
        return prediction

    def _build_prompt(self, prices, headlines: list[str]) -> str:
        price_lines = "\n".join(
            f"  {p.timestamp}: ${p.price}" for p in prices
        )
        headline_lines = (
            "\n".join(f"  {h}" for h in headlines)
            if headlines
            else "  No recent news available"
        )
        return (
            f"Product: {prices[0].product_id}\n\n"
            f"Recent price history:\n{price_lines}\n\n"
            f"Current price: ${prices[-1].price}\n\n"
            f"Recent news and sentiment:\n{headline_lines}\n\n"
            "Based on this data, predict the short-term price target."
        )

    async def _log_prediction(self, prediction: Prediction, headlines: list[str]) -> None:
        if self._db is None:
            return

        diff_pct = (
            (prediction.target_price - prediction.current_price)
            / prediction.current_price * 100
        ) if prediction.current_price > 0 else 0

        threshold = self._settings.trade_threshold_pct
        if diff_pct > threshold:
            action = "BUY"
        elif diff_pct < -threshold:
            action = "SELL"
        else:
            action = "HOLD"

        pred_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """INSERT INTO predictions (id, product_id, action, predicted_price, current_price,
               confidence, reasoning, model, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pred_id, self._product_id, action, prediction.target_price,
             prediction.current_price, abs(diff_pct), prediction.reasoning,
             "llm", now),
        )

        for headline in headlines:
            await self._db.execute(
                """INSERT INTO news_history (id, prediction_id, headline, source, sentiment, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), pred_id, headline, None, None, now),
            )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_strategies_news.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/strategies/news.py tests/test_strategies_news.py
git commit -m "feat: add NewsPredictionStrategy using Strategy ABC + LLMClient"
```

---

### Task 5: Create Registry — `src/registry.py`

**Files:**
- Create: `src/registry.py`
- Test: `tests/test_registry.py`

**Step 1: Write the failing tests**

Create `tests/test_registry.py`:

```python
from src.registry import STRATEGIES, LLM_PROVIDERS


def test_strategies_registry_has_expected_keys():
    assert "price_only" in STRATEGIES
    assert "news" in STRATEGIES


def test_llm_providers_registry_has_expected_keys():
    assert "anthropic" in LLM_PROVIDERS
    assert "openrouter" in LLM_PROVIDERS


def test_strategy_entries_have_class_and_description():
    for key, entry in STRATEGIES.items():
        assert "class" in entry, f"{key} missing 'class'"
        assert "description" in entry, f"{key} missing 'description'"


def test_provider_entries_have_required_fields():
    for key, entry in LLM_PROVIDERS.items():
        assert "class" in entry, f"{key} missing 'class'"
        assert "default_model" in entry, f"{key} missing 'default_model'"
        assert "key_env" in entry, f"{key} missing 'key_env'"
        assert "description" in entry, f"{key} missing 'description'"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.registry'`

**Step 3: Implement `src/registry.py`**

```python
from src.llm_client import AnthropicLLMClient, OpenAICompatibleLLMClient
from src.strategies.news import NewsPredictionStrategy
from src.strategies.price_only import PriceOnlyStrategy

STRATEGIES = {
    "price_only": {
        "class": PriceOnlyStrategy,
        "description": "Technical analysis from price history only",
    },
    "news": {
        "class": NewsPredictionStrategy,
        "description": "Price history + real-time news sentiment via Grok API",
    },
}

LLM_PROVIDERS = {
    "anthropic": {
        "class": AnthropicLLMClient,
        "default_model": "claude-opus-4-6",
        "key_env": "ANTHROPIC_API_KEY",
        "description": "Anthropic Claude API",
    },
    "openrouter": {
        "class": OpenAICompatibleLLMClient,
        "default_model": "moonshotai/kimi-k2",
        "key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "description": "OpenRouter API (Kimi, Llama, etc.)",
    },
}
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_registry.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/registry.py tests/test_registry.py
git commit -m "feat: add strategy and LLM provider registries"
```

---

### Task 6: Rewrite `src/main.py` with argparse + Registry

**Files:**
- Modify: `src/main.py`

**Step 1: Rewrite `src/main.py`**

```python
# src/main.py
import argparse
import asyncio
import logging
import signal

from src.coinbase_client import CoinbaseClient
from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.kill_switch import KillSwitch
from src.market_data import MarketData
from src.order_manager import OrderManager
from src.portfolio_tracker import PortfolioTracker
from src.position_tracker import PositionTracker
from src.price_buffer import PriceBuffer
from src.registry import LLM_PROVIDERS, STRATEGIES
from src.risk_manager import RiskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coinbase Trading Bot")

    parser.add_argument(
        "--strategy",
        choices=list(STRATEGIES.keys()),
        default="price_only",
        help=" | ".join(f"{k}: {v['description']}" for k, v in STRATEGIES.items()),
    )
    parser.add_argument(
        "--llm",
        choices=list(LLM_PROVIDERS.keys()),
        default="anthropic",
        help=" | ".join(f"{k}: {v['description']}" for k, v in LLM_PROVIDERS.items()),
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model ID (default depends on --llm provider)",
    )

    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = Settings()
    bus = EventBus()

    # Database
    db = Database(settings.db_path)
    await db.initialize()
    logger.info("Database initialized at %s", settings.db_path)

    # Kill switch
    kill_switch = KillSwitch(db=db, bus=bus)
    await kill_switch.initialize()
    if kill_switch.is_active:
        logger.warning("Kill switch is ACTIVE from previous session")

    # Risk manager
    risk_manager = RiskManager(db=db, bus=bus, kill_switch=kill_switch, settings=settings)

    # Coinbase client
    coinbase = CoinbaseClient(
        api_key=settings.coinbase_api_key,
        api_secret=settings.coinbase_api_secret,
        key_file=settings.coinbase_key_file,
    )

    # Order manager
    order_manager = OrderManager(db=db, bus=bus, risk_manager=risk_manager, coinbase=coinbase)
    order_manager.register(bus)

    # Position tracker
    position_tracker = PositionTracker(db=db, bus=bus)
    position_tracker.register(bus)

    # Portfolio tracker
    portfolio_tracker = PortfolioTracker(
        db=db,
        bus=bus,
        coinbase=coinbase,
        product_id=settings.product_id,
        interval_seconds=settings.prediction_interval_minutes * 60,
    )

    # Market data
    market_data = MarketData(
        bus=bus,
        api_key=settings.coinbase_api_key,
        api_secret=settings.coinbase_api_secret,
        key_file=settings.coinbase_key_file,
        db=db,
    )

    # --- LLM client from registry ---
    provider_config = LLM_PROVIDERS[args.llm]
    model = args.model or provider_config["default_model"]

    # Resolve API key from settings by env var name
    key_env = provider_config["key_env"].lower()
    api_key = getattr(settings, key_env, "")

    provider_kwargs = {"api_key": api_key, "model": model}
    if "base_url" in provider_config:
        provider_kwargs["base_url"] = provider_config["base_url"]

    llm_client = provider_config["class"](**provider_kwargs)

    # --- Strategy from registry ---
    price_buffer = PriceBuffer(max_size=50)

    strategy_kwargs = {
        "bus": bus,
        "price_buffer": price_buffer,
        "llm_client": llm_client,
        "settings": settings,
        "product_id": settings.product_id,
        "db": db,
    }

    # News strategy needs additional dependency
    if args.strategy == "news":
        from src.news_service import NewsService
        strategy_kwargs["news_service"] = NewsService(
            api_key=settings.grok_api_key,
            model=settings.grok_model,
        )

    strategy_class = STRATEGIES[args.strategy]["class"]
    strategy = strategy_class(**strategy_kwargs)
    strategy.register(bus)

    logger.info("All components initialized. Starting market data...")
    logger.info("Risk limits: max_order=$%.2f, max_daily_loss=$%.2f",
                settings.max_order_size_usd, settings.max_daily_loss_usd)

    # Graceful shutdown
    stop_event = asyncio.Event()

    def shutdown():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    # Start market data + strategy
    await market_data.start(product_ids=[settings.product_id])
    await strategy.start()
    await portfolio_tracker.start()

    logger.info("Bot running with %s strategy + %s/%s (interval=%dm)",
                args.strategy, args.llm, model, settings.prediction_interval_minutes)
    await stop_event.wait()

    # Cleanup
    await portfolio_tracker.stop()
    await strategy.stop()
    await market_data.stop()
    await db.close()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: New tests PASS. Old strategy/predictor tests will FAIL (they import deleted modules — we'll remove them next).

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "refactor: rewrite main.py with argparse CLI + registry-based wiring"
```

---

### Task 7: Update `src/config.py` — Remove Strategy/Predictor Fields

**Files:**
- Modify: `src/config.py`
- Modify: `tests/test_config_prediction.py`

**Step 1: Update `src/config.py`**

Remove these fields: `strategy`, `predictor_type`, `prediction_model`, `openrouter_model`, `openrouter_base_url`.

Keep: `openrouter_api_key` (it's a secret that still loads from `.env`).

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    coinbase_key_file: str = ""
    max_order_size_usd: float = 100.0
    max_daily_loss_usd: float = 500.0
    db_path: str = "trading_bot.db"

    # API keys (secrets from .env)
    anthropic_api_key: str = ""
    grok_api_key: str = ""
    openrouter_api_key: str = ""

    # Trading settings
    prediction_interval_minutes: int = 5
    grok_model: str = "grok-3-mini-fast"
    trade_threshold_pct: float = 1.0
    trade_size_usd: float = 50.0
    product_id: str = "BTC-USD"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

**Step 2: Update `tests/test_config_prediction.py`**

```python
from src.config import Settings


def test_prediction_settings_defaults():
    s = Settings(
        _env_file=None,
        coinbase_api_key="k",
        coinbase_api_secret="s",
    )
    assert s.anthropic_api_key == ""
    assert s.grok_api_key == ""
    assert s.prediction_interval_minutes == 5
    assert s.grok_model == "grok-3-mini-fast"
    assert s.trade_threshold_pct == 1.0
    assert s.trade_size_usd == 50.0


def test_prediction_settings_override():
    s = Settings(
        _env_file=None,
        coinbase_api_key="k",
        coinbase_api_secret="s",
        anthropic_api_key="ant-key",
        grok_api_key="grok-key",
        prediction_interval_minutes=10,
        trade_threshold_pct=2.5,
        trade_size_usd=100.0,
    )
    assert s.anthropic_api_key == "ant-key"
    assert s.grok_api_key == "grok-key"
    assert s.prediction_interval_minutes == 10
    assert s.trade_threshold_pct == 2.5
    assert s.trade_size_usd == 100.0
```

**Step 3: Run tests**

Run: `pytest tests/test_config_prediction.py tests/test_config.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add src/config.py tests/test_config_prediction.py
git commit -m "refactor: remove strategy/predictor fields from Settings (now CLI args)"
```

---

### Task 8: Update `.env.example`

**Files:**
- Modify: `.env.example`

**Step 1: Update `.env.example`**

```
COINBASE_API_KEY=organizations/YOUR_ORG_ID/apiKeys/YOUR_KEY_ID
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\nYOUR_KEY\n-----END EC PRIVATE KEY-----\n"
COINBASE_KEY_FILE=
MAX_ORDER_SIZE_USD=100
MAX_DAILY_LOSS_USD=500
DB_PATH=trading_bot.db
ANTHROPIC_API_KEY=sk-ant-your-key
GROK_API_KEY=xai-your-key
OPENROUTER_API_KEY=
PREDICTION_INTERVAL_MINUTES=5
GROK_MODEL=grok-3-mini-fast
TRADE_THRESHOLD_PCT=1.0
TRADE_SIZE_USD=50.0
PRODUCT_ID=BTC-USD
```

Removed lines: `PREDICTION_MODEL`, `STRATEGY`, `PREDICTOR_TYPE`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` (these are now CLI args or registry defaults).

**Step 2: Commit**

```bash
git add .env.example
git commit -m "refactor: remove strategy/predictor/model lines from .env.example"
```

---

### Task 9: Delete Old Files + Old Tests

**Files:**
- Delete: `src/claude_predictor.py`
- Delete: `src/kimi_predictor.py`
- Delete: `src/claude_price_only_predictor.py`
- Delete: `src/strategy_news_prediction.py`
- Delete: `src/strategy_price_only.py`
- Delete: `tests/test_claude_predictor.py`
- Delete: `tests/test_kimi_predictor.py`
- Delete: `tests/test_claude_price_only_predictor.py`
- Delete: `tests/test_strategy_news_prediction.py`
- Delete: `tests/test_strategy_price_only.py`

**Step 1: Delete the files**

```bash
git rm src/claude_predictor.py src/kimi_predictor.py src/claude_price_only_predictor.py
git rm src/strategy_news_prediction.py src/strategy_price_only.py
git rm tests/test_claude_predictor.py tests/test_kimi_predictor.py tests/test_claude_price_only_predictor.py
git rm tests/test_strategy_news_prediction.py tests/test_strategy_price_only.py
```

**Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS (no imports reference deleted files)

**Step 3: Commit**

```bash
git commit -m "refactor: delete old predictor and strategy files

Replaced by:
- src/strategy.py (ABC)
- src/strategies/price_only.py
- src/strategies/news.py
- src/registry.py"
```

---

### Task 10: Final Verification

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 2: Verify CLI help works**

Run: `python -m src.main --help`
Expected: Shows `--strategy`, `--llm`, `--model` args with descriptions from registry

**Step 3: Verify no remaining imports of deleted modules**

Search for `claude_predictor`, `kimi_predictor`, `claude_price_only_predictor`, `strategy_news_prediction`, `strategy_price_only` in `src/` and `tests/`. Should find zero hits.

**Step 4: Verify no references to removed config fields**

Search for `predictor_type`, `prediction_model` (as a Settings field reference), `openrouter_model`, `openrouter_base_url` in `src/` and `tests/`. Should find zero hits (except in docs/plans/).

---

### Task 11: Update Documentation

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/ai-components.md`
- Modify: `docs/ai-index.md`
- Modify: `docs/ai-data.md`
- Modify: `docs/ai-traces.md`
- Modify: `docs/ai-extending.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Step 1: Update `docs/architecture.md`**

- Replace strategy/predictor component descriptions with new two-layer architecture
- Update component table: remove predictor entries, add `src/strategy.py`, `src/strategies/`, `src/registry.py`
- Update data flow diagram to show Strategy → LLMClient instead of Strategy → Predictor → LLMClient
- Add ADR entry: "Decoupled strategies from LLM providers — strategies own prompts, registry maps CLI args"
- Add changelog entry

**Step 2: Update AI docs**

- `docs/ai-components.md`: Remove ClaudePredictor, KimiPredictor, ClaudePriceOnlyPredictor entries. Add Strategy ABC, PriceOnlyStrategy, NewsPredictionStrategy, registry entries.
- `docs/ai-index.md`: Update file map and dependency graph.
- `docs/ai-data.md`: Remove Predictor protocol. Update event routing if needed.
- `docs/ai-traces.md`: Update prediction cycle trace to show Strategy → LLMClient flow.
- `docs/ai-extending.md`: Update "how to add a strategy" and "how to add an LLM provider" sections.

**Step 3: Update `README.md`**

- Update usage section to show CLI args: `python -m src.main --strategy news --llm anthropic --model claude-opus-4-6`
- Update features list if referencing predictor swapping

**Step 4: Update `CLAUDE.md`**

- Update the "Run" command to mention CLI args
- Update architecture description

**Step 5: Commit**

```bash
git add docs/ README.md CLAUDE.md
git commit -m "docs: update architecture and AI docs for strategy/LLM decoupling"
```
