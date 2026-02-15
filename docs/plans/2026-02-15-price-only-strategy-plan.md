# Price-Only Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `PriceOnlyStrategy` that predicts using only price history (no news), rename existing strategy to `NewsPredictionStrategy`, and add a config flag to switch between them.

**Architecture:** Two strategy classes share the same loop/evaluate/position pattern but differ in their prediction cycle. Each strategy uses its own predictor. A `strategy` config field in `Settings` selects which one `main.py` wires up.

**Tech Stack:** Python 3.12, asyncio, Anthropic SDK, pytest, pydantic-settings

---

### Task 1: Create `ClaudePriceOnlyPredictor`

**Files:**
- Create: `src/claude_price_only_predictor.py`
- Test: `tests/test_claude_price_only_predictor.py`

**Step 1: Write the failing tests**

Create `tests/test_claude_price_only_predictor.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.claude_predictor import Prediction
from src.events import PriceUpdate


@pytest.fixture
def mock_anthropic_client():
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock()]
    response.content[0].text = (
        '{"target_price": 105000.0, "timeframe_minutes": 60, '
        '"reasoning": "Strong upward momentum in price action"}'
    )
    client.messages.create = AsyncMock(return_value=response)
    return client


@pytest.fixture
def prices():
    return [
        PriceUpdate(product_id="BTC-USD", price=100000.0, timestamp="2026-02-15T10:00:00Z"),
        PriceUpdate(product_id="BTC-USD", price=100500.0, timestamp="2026-02-15T10:01:00Z"),
        PriceUpdate(product_id="BTC-USD", price=101000.0, timestamp="2026-02-15T10:02:00Z"),
    ]


async def test_predict_returns_prediction(mock_anthropic_client, prices):
    from src.claude_price_only_predictor import ClaudePriceOnlyPredictor

    predictor = ClaudePriceOnlyPredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices)

    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    assert result.timeframe_minutes == 60
    assert result.reasoning == "Strong upward momentum in price action"
    assert result.current_price == 101000.0


async def test_predict_prompt_contains_prices_no_news(mock_anthropic_client, prices):
    from src.claude_price_only_predictor import ClaudePriceOnlyPredictor

    predictor = ClaudePriceOnlyPredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    await predictor.predict(prices)

    call_kwargs = mock_anthropic_client.messages.create.call_args
    user_msg = call_kwargs.kwargs["messages"][-1]["content"]
    system_msg = call_kwargs.kwargs["system"]
    assert "100000.0" in user_msg
    assert "101000.0" in user_msg
    assert "news" not in user_msg.lower()
    assert "headline" not in user_msg.lower()
    assert "news" not in system_msg.lower()


async def test_predict_empty_prices():
    from src.claude_price_only_predictor import ClaudePriceOnlyPredictor

    predictor = ClaudePriceOnlyPredictor(api_key="test-key")
    result = await predictor.predict([])
    assert result is None


async def test_predict_api_error(mock_anthropic_client, prices):
    from src.claude_price_only_predictor import ClaudePriceOnlyPredictor

    mock_anthropic_client.messages.create = AsyncMock(side_effect=Exception("API error"))
    predictor = ClaudePriceOnlyPredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices)
    assert result is None


async def test_predict_malformed_json(mock_anthropic_client, prices):
    from src.claude_price_only_predictor import ClaudePriceOnlyPredictor

    mock_anthropic_client.messages.create.return_value.content[0].text = "not json"
    predictor = ClaudePriceOnlyPredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices)
    assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_claude_price_only_predictor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.claude_price_only_predictor'`

**Step 3: Write minimal implementation**

Create `src/claude_price_only_predictor.py`:

```python
import json
import logging
from datetime import datetime, timezone

from anthropic import AsyncAnthropic

from src.claude_predictor import Prediction
from src.events import PriceUpdate

logger = logging.getLogger(__name__)


class ClaudePriceOnlyPredictor:
    def __init__(self, api_key: str, model: str = "claude-opus-4-6") -> None:
        self._model = model
        self._client = AsyncAnthropic(api_key=api_key)

    async def predict(self, prices: list[PriceUpdate]) -> Prediction | None:
        if not prices:
            return None

        current_price = prices[-1].price
        prompt = self._build_prompt(prices)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You are a crypto price prediction analyst. Analyze the provided "
                    "price history to predict the short-term price target using technical "
                    "analysis and price action patterns. "
                    "Respond ONLY with valid JSON in this exact format:\n"
                    '{"target_price": <float>, "timeframe_minutes": <int>, '
                    '"reasoning": "<brief explanation>"}\n'
                    "No other text."
                ),
            )
            raw = response.content[0].text
            data = json.loads(raw)
            return Prediction(
                target_price=float(data["target_price"]),
                timeframe_minutes=int(data["timeframe_minutes"]),
                reasoning=str(data["reasoning"]),
                current_price=current_price,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.exception("Failed to parse prediction response")
            return None
        except Exception:
            logger.exception("Prediction API call failed")
            return None

    def _build_prompt(self, prices: list[PriceUpdate]) -> str:
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

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_claude_price_only_predictor.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/claude_price_only_predictor.py tests/test_claude_price_only_predictor.py
git commit -m "feat: add ClaudePriceOnlyPredictor for price-only predictions"
```

---

### Task 2: Rename `ClaudePredictionStrategy` → `NewsPredictionStrategy`

**Files:**
- Rename: `src/strategy_claude_prediction.py` → `src/strategy_news_prediction.py`
- Rename: `tests/test_strategy_claude_prediction.py` → `tests/test_strategy_news_prediction.py`
- Modify: `src/main.py` (update import)

**Step 1: Rename source file and class**

```bash
git mv src/strategy_claude_prediction.py src/strategy_news_prediction.py
```

In `src/strategy_news_prediction.py`, rename the class:
- `ClaudePredictionStrategy` → `NewsPredictionStrategy`

**Step 2: Rename test file and update references**

```bash
git mv tests/test_strategy_claude_prediction.py tests/test_strategy_news_prediction.py
```

In `tests/test_strategy_news_prediction.py`, update:
- Import: `from src.strategy_news_prediction import NewsPredictionStrategy`
- All references from `ClaudePredictionStrategy` → `NewsPredictionStrategy`

**Step 3: Update `src/main.py` import**

Change:
```python
from src.strategy_claude_prediction import ClaudePredictionStrategy
```
To:
```python
from src.strategy_news_prediction import NewsPredictionStrategy
```

And update the instantiation:
```python
strategy = NewsPredictionStrategy(
```

**Step 4: Run all tests to verify nothing broke**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename ClaudePredictionStrategy to NewsPredictionStrategy"
```

---

### Task 3: Create `PriceOnlyStrategy`

**Files:**
- Create: `src/strategy_price_only.py`
- Test: `tests/test_strategy_price_only.py`

**Step 1: Write the failing tests**

Create `tests/test_strategy_price_only.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.claude_predictor import Prediction
from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.price_buffer import PriceBuffer
from src.strategy_price_only import PriceOnlyStrategy


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
def predictor():
    return MagicMock()


@pytest.fixture
def settings():
    s = MagicMock()
    s.trade_threshold_pct = 1.0
    s.trade_size_usd = 50.0
    s.prediction_interval_minutes = 5
    return s


@pytest.fixture
def strategy(bus, price_buffer, predictor, settings):
    return PriceOnlyStrategy(
        bus=bus,
        price_buffer=price_buffer,
        predictor=predictor,
        settings=settings,
        product_id="BTC-USD",
    )


async def test_on_price_feeds_buffer(bus, predictor, settings):
    buf = PriceBuffer()
    strat = PriceOnlyStrategy(
        bus=bus, price_buffer=buf, predictor=predictor,
        settings=settings, product_id="BTC-USD",
    )
    strat.register(bus)

    await bus.publish(PriceUpdate(product_id="BTC-USD", price=99000.0, timestamp="t1"))

    assert len(buf.snapshot("BTC-USD")) == 1


async def test_bullish_prediction_emits_buy(strategy, bus, predictor):
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=105420.0, timeframe_minutes=60,
        reasoning="Bullish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    ))

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 1
    assert orders[0].side == "BUY"
    assert orders[0].quote_size == 50.0
    assert orders[0].product_id == "BTC-USD"


async def test_bearish_prediction_emits_sell(strategy, bus, predictor):
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=95380.0, timeframe_minutes=60,
        reasoning="Bearish", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    ))
    strategy._has_open_position = AsyncMock(return_value=True)
    strategy._get_position_quantity = AsyncMock(return_value=0.001)

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 1
    assert orders[0].side == "SELL"
    assert orders[0].base_size == 0.001


async def test_neutral_prediction_no_order(strategy, bus, predictor):
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=100902.0, timeframe_minutes=60,
        reasoning="Sideways", current_price=100400.0,
        timestamp="2026-02-15T10:05:00Z",
    ))

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 0


async def test_no_prices_skips_prediction(bus, predictor, settings):
    empty_buf = PriceBuffer()
    strat = PriceOnlyStrategy(
        bus=bus, price_buffer=empty_buf, predictor=predictor,
        settings=settings, product_id="BTC-USD",
    )

    predictor.predict = AsyncMock()

    await strat._run_prediction_cycle()

    predictor.predict.assert_not_called()


async def test_prediction_failure_no_order(strategy, bus, predictor):
    predictor.predict = AsyncMock(return_value=None)

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 0


async def test_no_news_service_dependency(strategy):
    """PriceOnlyStrategy should have no news_service attribute."""
    assert not hasattr(strategy, "_news_service")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_strategy_price_only.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.strategy_price_only'`

**Step 3: Write minimal implementation**

Create `src/strategy_price_only.py`:

```python
import asyncio
import logging

from src.claude_price_only_predictor import ClaudePriceOnlyPredictor
from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.price_buffer import PriceBuffer

logger = logging.getLogger(__name__)


class PriceOnlyStrategy:
    def __init__(
        self,
        bus: EventBus,
        price_buffer: PriceBuffer,
        predictor: ClaudePriceOnlyPredictor,
        settings: Settings,
        product_id: str = "BTC-USD",
        db: Database | None = None,
    ) -> None:
        self._bus = bus
        self._price_buffer = price_buffer
        self._predictor = predictor
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
            "Price-only strategy started for %s (interval=%dm, threshold=%.1f%%)",
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
        logger.info("Price-only strategy stopped")

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

        logger.info("Requesting price-only prediction for %s...", self._product_id)
        prediction = await self._predictor.predict(prices)
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

    async def _evaluate(self, prediction) -> None:
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

Run: `pytest tests/test_strategy_price_only.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add src/strategy_price_only.py tests/test_strategy_price_only.py
git commit -m "feat: add PriceOnlyStrategy for price-only predictions"
```

---

### Task 4: Add config flag and wire `main.py`

**Files:**
- Modify: `src/config.py:4-22` (add `strategy` field)
- Modify: `src/main.py:1-120` (conditional wiring)
- Test: `tests/test_config_prediction.py` (add strategy config test)

**Step 1: Write the failing test**

Add to `tests/test_config_prediction.py`:

```python
def test_strategy_field_default():
    """Strategy defaults to price_only."""
    from src.config import Settings
    s = Settings(
        coinbase_api_key="k", coinbase_api_secret="s",
        anthropic_api_key="a", grok_api_key="g",
    )
    assert s.strategy == "price_only"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_prediction.py::test_strategy_field_default -v`
Expected: FAIL — `AttributeError: 'Settings' has no attribute 'strategy'`

**Step 3: Add config field**

In `src/config.py`, add to the Settings class:

```python
strategy: str = "price_only"  # "price_only" or "news"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_prediction.py::test_strategy_field_default -v`
Expected: PASS

**Step 5: Update `main.py` wiring**

Replace the strategy wiring block in `src/main.py` (lines 68-87) with conditional logic:

```python
    # Strategy selection
    price_buffer = PriceBuffer(max_size=50)

    if settings.strategy == "news":
        from src.news_service import NewsService
        from src.claude_predictor import ClaudePredictor
        from src.strategy_news_prediction import NewsPredictionStrategy

        news_service = NewsService(
            api_key=settings.grok_api_key,
            model=settings.grok_model,
        )
        predictor = ClaudePredictor(
            api_key=settings.anthropic_api_key,
            model=settings.prediction_model,
        )
        strategy = NewsPredictionStrategy(
            bus=bus,
            price_buffer=price_buffer,
            news_service=news_service,
            predictor=predictor,
            settings=settings,
            product_id=settings.product_id,
            db=db,
        )
    else:
        from src.claude_price_only_predictor import ClaudePriceOnlyPredictor
        from src.strategy_price_only import PriceOnlyStrategy

        predictor = ClaudePriceOnlyPredictor(
            api_key=settings.anthropic_api_key,
            model=settings.prediction_model,
        )
        strategy = PriceOnlyStrategy(
            bus=bus,
            price_buffer=price_buffer,
            predictor=predictor,
            settings=settings,
            product_id=settings.product_id,
            db=db,
        )

    strategy.register(bus)
```

Also move the top-level imports for `ClaudePredictor`, `NewsService`, and `ClaudePredictionStrategy` out of the top of main.py (they are now imported conditionally inside the function). Keep `PriceBuffer` as a top-level import.

Update the log line:

```python
    logger.info("Bot running with %s strategy (interval=%dm)",
                settings.strategy, settings.prediction_interval_minutes)
```

**Step 6: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add src/config.py src/main.py tests/test_config_prediction.py
git commit -m "feat: add strategy config flag and wire price_only/news in main.py"
```

---

### Task 5: Update documentation

**Files:**
- Modify: `docs/architecture.md`
- Modify: `README.md`
- Modify: `docs/ai-index.md`
- Modify: `docs/ai-components.md`

**Step 1: Update docs**

Add the new components (`PriceOnlyStrategy`, `ClaudePriceOnlyPredictor`) to component tables, update the strategy selection flow in architecture docs, document the `strategy` config field, and add a changelog entry.

**Step 2: Commit**

```bash
git add docs/ README.md
git commit -m "docs: add price-only strategy to documentation"
```
