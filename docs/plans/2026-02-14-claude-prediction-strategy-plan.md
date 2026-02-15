# Claude Prediction Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a trading strategy that uses Claude Opus 4.6 to predict BTC price targets from price history + Grok news/sentiment, and auto-trades on a timer.

**Architecture:** Strategy + Shared Services pattern. Three reusable services (PriceBuffer, NewsService, ClaudePredictor) orchestrated by ClaudePredictionStrategy. Strategy subscribes to PriceUpdate, runs a prediction loop on a timer, and emits OrderRequest events into the existing pipeline.

**Tech Stack:** Python 3.12, asyncio, anthropic SDK, openai SDK (for Grok xAI API), existing EventBus + risk management

---

### Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml:9-15`
- Modify: `.env.example`

**Step 1: Add anthropic and openai to pyproject.toml**

Add `anthropic` and `openai` to the dependencies list in `pyproject.toml`:

```toml
dependencies = [
    "coinbase-advanced-py>=1.8.0",
    "aiosqlite>=0.20.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "python-dotenv>=1.0",
    "anthropic>=0.42.0",
    "openai>=1.60.0",
]
```

**Step 2: Install dependencies**

Run: `.venv/bin/pip install -e ".[dev]"`

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add anthropic and openai dependencies for Claude prediction strategy"
```

---

### Task 2: Add Config Settings

**Files:**
- Modify: `src/config.py:4-9`
- Modify: `.env.example`

**Step 1: Write the failing test**

Create `tests/test_config_prediction.py`:

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
    assert s.prediction_model == "claude-opus-4-6"
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
        prediction_model="claude-sonnet-4-5-20250929",
        trade_threshold_pct=2.5,
        trade_size_usd=100.0,
    )
    assert s.anthropic_api_key == "ant-key"
    assert s.grok_api_key == "grok-key"
    assert s.prediction_interval_minutes == 10
    assert s.prediction_model == "claude-sonnet-4-5-20250929"
    assert s.trade_threshold_pct == 2.5
    assert s.trade_size_usd == 100.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_prediction.py -v`
Expected: FAIL — `anthropic_api_key` field doesn't exist yet

**Step 3: Add fields to Settings**

In `src/config.py`, add fields after line 9 (`db_path`):

```python
class Settings(BaseSettings):
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    max_order_size_usd: float = 100.0
    max_daily_loss_usd: float = 500.0
    db_path: str = "trading_bot.db"

    # Claude prediction strategy
    anthropic_api_key: str = ""
    grok_api_key: str = ""
    prediction_interval_minutes: int = 5
    prediction_model: str = "claude-opus-4-6"
    grok_model: str = "grok-3-mini-fast"
    trade_threshold_pct: float = 1.0
    trade_size_usd: float = 50.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

**Step 4: Update .env.example**

Append to `.env.example`:

```
ANTHROPIC_API_KEY=sk-ant-your-key
GROK_API_KEY=xai-your-key
PREDICTION_INTERVAL_MINUTES=5
PREDICTION_MODEL=claude-opus-4-6
GROK_MODEL=grok-3-mini-fast
TRADE_THRESHOLD_PCT=1.0
TRADE_SIZE_USD=50.0
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_config_prediction.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/config.py .env.example tests/test_config_prediction.py
git commit -m "feat: add prediction strategy config settings"
```

---

### Task 3: PriceBuffer Service

**Files:**
- Create: `src/price_buffer.py`
- Create: `tests/test_price_buffer.py`

**Step 1: Write failing tests**

Create `tests/test_price_buffer.py`:

```python
from src.events import PriceUpdate
from src.price_buffer import PriceBuffer


def test_add_and_snapshot():
    buf = PriceBuffer(max_size=3)
    buf.add(PriceUpdate(product_id="BTC-USD", price=100.0, timestamp="t1"))
    buf.add(PriceUpdate(product_id="BTC-USD", price=200.0, timestamp="t2"))

    snap = buf.snapshot("BTC-USD")
    assert len(snap) == 2
    assert snap[0].price == 100.0
    assert snap[1].price == 200.0


def test_snapshot_empty():
    buf = PriceBuffer()
    assert buf.snapshot("BTC-USD") == []


def test_max_size_eviction():
    buf = PriceBuffer(max_size=2)
    buf.add(PriceUpdate(product_id="BTC-USD", price=1.0, timestamp="t1"))
    buf.add(PriceUpdate(product_id="BTC-USD", price=2.0, timestamp="t2"))
    buf.add(PriceUpdate(product_id="BTC-USD", price=3.0, timestamp="t3"))

    snap = buf.snapshot("BTC-USD")
    assert len(snap) == 2
    assert snap[0].price == 2.0
    assert snap[1].price == 3.0


def test_separate_product_ids():
    buf = PriceBuffer()
    buf.add(PriceUpdate(product_id="BTC-USD", price=100.0, timestamp="t1"))
    buf.add(PriceUpdate(product_id="ETH-USD", price=3.0, timestamp="t2"))

    assert len(buf.snapshot("BTC-USD")) == 1
    assert len(buf.snapshot("ETH-USD")) == 1


def test_latest():
    buf = PriceBuffer()
    assert buf.latest("BTC-USD") is None

    buf.add(PriceUpdate(product_id="BTC-USD", price=100.0, timestamp="t1"))
    buf.add(PriceUpdate(product_id="BTC-USD", price=200.0, timestamp="t2"))

    latest = buf.latest("BTC-USD")
    assert latest is not None
    assert latest.price == 200.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_price_buffer.py -v`
Expected: FAIL — `price_buffer` module doesn't exist

**Step 3: Implement PriceBuffer**

Create `src/price_buffer.py`:

```python
from collections import deque

from src.events import PriceUpdate


class PriceBuffer:
    def __init__(self, max_size: int = 50) -> None:
        self._max_size = max_size
        self._buffers: dict[str, deque[PriceUpdate]] = {}

    def add(self, update: PriceUpdate) -> None:
        if update.product_id not in self._buffers:
            self._buffers[update.product_id] = deque(maxlen=self._max_size)
        self._buffers[update.product_id].append(update)

    def snapshot(self, product_id: str) -> list[PriceUpdate]:
        if product_id not in self._buffers:
            return []
        return list(self._buffers[product_id])

    def latest(self, product_id: str) -> PriceUpdate | None:
        buf = self._buffers.get(product_id)
        if not buf:
            return None
        return buf[-1]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_price_buffer.py -v`
Expected: PASS (5 passed)

**Step 5: Commit**

```bash
git add src/price_buffer.py tests/test_price_buffer.py
git commit -m "feat: add PriceBuffer service for accumulating price history"
```

---

### Task 4: NewsService (Grok API)

**Files:**
- Create: `src/news_service.py`
- Create: `tests/test_news_service.py`

**Step 1: Write failing tests**

Create `tests/test_news_service.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.news_service import NewsService


@pytest.fixture
def mock_openai_client():
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = (
        "1. Bitcoin surges past $100k on ETF inflows\n"
        "2. Fed signals rate pause, crypto markets rally\n"
        "3. Whale accumulation hits 6-month high"
    )
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


async def test_fetch_headlines(mock_openai_client):
    service = NewsService(api_key="test-key")
    service._client = mock_openai_client

    headlines = await service.fetch_headlines("BTC-USD")

    assert isinstance(headlines, list)
    assert len(headlines) > 0
    assert any("Bitcoin" in h for h in headlines)

    # Verify the API was called
    mock_openai_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_openai_client.chat.completions.create.call_args
    assert "BTC-USD" in str(call_kwargs)


async def test_fetch_headlines_api_error(mock_openai_client):
    mock_openai_client.chat.completions.create = AsyncMock(
        side_effect=Exception("API error")
    )
    service = NewsService(api_key="test-key")
    service._client = mock_openai_client

    headlines = await service.fetch_headlines("BTC-USD")
    assert headlines == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_news_service.py -v`
Expected: FAIL — `news_service` module doesn't exist

**Step 3: Implement NewsService**

Create `src/news_service.py`:

```python
import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class NewsService:
    def __init__(self, api_key: str, model: str = "grok-3-mini-fast") -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )

    async def fetch_headlines(self, product_id: str) -> list[str]:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a crypto news analyst. Return the 5 most important "
                            "recent news headlines and sentiment about the requested asset. "
                            "One headline per line, numbered. Be concise."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"What are the latest news and sentiment for {product_id}?",
                    },
                ],
            )
            raw = response.choices[0].message.content or ""
            return [line.strip() for line in raw.strip().splitlines() if line.strip()]
        except Exception:
            logger.exception("Failed to fetch headlines for %s", product_id)
            return []
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_news_service.py -v`
Expected: PASS (2 passed)

**Step 5: Commit**

```bash
git add src/news_service.py tests/test_news_service.py
git commit -m "feat: add NewsService for fetching crypto news via Grok API"
```

---

### Task 5: ClaudePredictor Service

**Files:**
- Create: `src/claude_predictor.py`
- Create: `tests/test_claude_predictor.py`

**Step 1: Write failing tests**

Create `tests/test_claude_predictor.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.claude_predictor import ClaudePredictor, Prediction
from src.events import PriceUpdate


@pytest.fixture
def mock_anthropic_client():
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock()]
    response.content[0].text = (
        '{"target_price": 105000.0, "timeframe_minutes": 60, '
        '"reasoning": "Bullish momentum with strong ETF inflows"}'
    )
    client.messages.create = AsyncMock(return_value=response)
    return client


@pytest.fixture
def prices():
    return [
        PriceUpdate(product_id="BTC-USD", price=100000.0, timestamp="2026-02-14T10:00:00Z"),
        PriceUpdate(product_id="BTC-USD", price=100500.0, timestamp="2026-02-14T10:01:00Z"),
        PriceUpdate(product_id="BTC-USD", price=101000.0, timestamp="2026-02-14T10:02:00Z"),
    ]


@pytest.fixture
def headlines():
    return [
        "1. Bitcoin surges on ETF inflows",
        "2. Fed signals rate pause",
    ]


async def test_predict_returns_prediction(mock_anthropic_client, prices, headlines):
    predictor = ClaudePredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices, headlines)

    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    assert result.timeframe_minutes == 60
    assert result.reasoning == "Bullish momentum with strong ETF inflows"
    assert result.current_price == 101000.0  # last price in list


async def test_predict_prompt_contains_prices_and_headlines(
    mock_anthropic_client, prices, headlines
):
    predictor = ClaudePredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    await predictor.predict(prices, headlines)

    call_kwargs = mock_anthropic_client.messages.create.call_args
    user_msg = call_kwargs.kwargs["messages"][-1]["content"]
    assert "100000.0" in user_msg
    assert "101000.0" in user_msg
    assert "ETF inflows" in user_msg


async def test_predict_api_error(mock_anthropic_client, prices, headlines):
    mock_anthropic_client.messages.create = AsyncMock(
        side_effect=Exception("API error")
    )
    predictor = ClaudePredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices, headlines)
    assert result is None


async def test_predict_malformed_json(mock_anthropic_client, prices, headlines):
    mock_anthropic_client.messages.create.return_value.content[0].text = "not json"
    predictor = ClaudePredictor(api_key="test-key")
    predictor._client = mock_anthropic_client

    result = await predictor.predict(prices, headlines)
    assert result is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_claude_predictor.py -v`
Expected: FAIL — `claude_predictor` module doesn't exist

**Step 3: Implement ClaudePredictor**

Create `src/claude_predictor.py`:

```python
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from anthropic import AsyncAnthropic

from src.events import PriceUpdate

logger = logging.getLogger(__name__)


@dataclass
class Prediction:
    target_price: float
    timeframe_minutes: int
    reasoning: str
    current_price: float
    timestamp: str


class ClaudePredictor:
    def __init__(self, api_key: str, model: str = "claude-opus-4-6") -> None:
        self._model = model
        self._client = AsyncAnthropic(api_key=api_key)

    async def predict(
        self, prices: list[PriceUpdate], headlines: list[str]
    ) -> Prediction | None:
        if not prices:
            return None

        current_price = prices[-1].price
        prompt = self._build_prompt(prices, headlines)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You are a crypto price prediction analyst. Analyze the provided "
                    "price history and news to predict the short-term price target. "
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
            logger.exception("Failed to parse Claude prediction response")
            return None
        except Exception:
            logger.exception("Claude prediction API call failed")
            return None

    def _build_prompt(
        self, prices: list[PriceUpdate], headlines: list[str]
    ) -> str:
        price_lines = "\n".join(
            f"  {p.timestamp}: ${p.price}" for p in prices
        )
        headline_lines = "\n".join(f"  {h}" for h in headlines) if headlines else "  No recent news available"

        return (
            f"Product: {prices[0].product_id}\n\n"
            f"Recent price history:\n{price_lines}\n\n"
            f"Current price: ${prices[-1].price}\n\n"
            f"Recent news and sentiment:\n{headline_lines}\n\n"
            "Based on this data, predict the short-term price target."
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_claude_predictor.py -v`
Expected: PASS (4 passed)

**Step 5: Commit**

```bash
git add src/claude_predictor.py tests/test_claude_predictor.py
git commit -m "feat: add ClaudePredictor service for AI price predictions"
```

---

### Task 6: ClaudePredictionStrategy

**Files:**
- Create: `src/strategy_claude_prediction.py`
- Create: `tests/test_strategy_claude_prediction.py`

**Step 1: Write failing tests**

Create `tests/test_strategy_claude_prediction.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.claude_predictor import Prediction
from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.price_buffer import PriceBuffer
from src.strategy_claude_prediction import ClaudePredictionStrategy


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def price_buffer():
    buf = PriceBuffer(max_size=50)
    # Pre-fill with some prices
    for i in range(5):
        buf.add(PriceUpdate(
            product_id="BTC-USD",
            price=100000.0 + i * 100,
            timestamp=f"2026-02-14T10:0{i}:00Z",
        ))
    return buf


@pytest.fixture
def news_service():
    service = MagicMock()
    service.fetch_headlines = AsyncMock(return_value=["Bitcoin bullish"])
    return service


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
def strategy(bus, price_buffer, news_service, predictor, settings):
    return ClaudePredictionStrategy(
        bus=bus,
        price_buffer=price_buffer,
        news_service=news_service,
        predictor=predictor,
        settings=settings,
        product_id="BTC-USD",
    )


async def test_on_price_feeds_buffer(bus, news_service, predictor, settings):
    buf = PriceBuffer()
    strat = ClaudePredictionStrategy(
        bus=bus, price_buffer=buf, news_service=news_service,
        predictor=predictor, settings=settings, product_id="BTC-USD",
    )
    strat.register(bus)

    await bus.publish(PriceUpdate(product_id="BTC-USD", price=99000.0, timestamp="t1"))

    assert len(buf.snapshot("BTC-USD")) == 1


async def test_bullish_prediction_emits_buy(strategy, bus, predictor):
    # Target 5% above current (100400) → well above 1% threshold
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=105420.0, timeframe_minutes=60,
        reasoning="Bullish", current_price=100400.0,
        timestamp="2026-02-14T10:05:00Z",
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
    # Target 5% below current → should sell
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=95380.0, timeframe_minutes=60,
        reasoning="Bearish", current_price=100400.0,
        timestamp="2026-02-14T10:05:00Z",
    ))
    # Mock an open position via the DB query the strategy uses
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
    # Target only 0.5% above current → below 1% threshold
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=100902.0, timeframe_minutes=60,
        reasoning="Sideways", current_price=100400.0,
        timestamp="2026-02-14T10:05:00Z",
    ))

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 0


async def test_no_prices_skips_prediction(bus, news_service, predictor, settings):
    empty_buf = PriceBuffer()
    strat = ClaudePredictionStrategy(
        bus=bus, price_buffer=empty_buf, news_service=news_service,
        predictor=predictor, settings=settings, product_id="BTC-USD",
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


async def test_buy_blocked_when_position_open(strategy, bus, predictor):
    # Bullish but already have a position → no BUY
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=105420.0, timeframe_minutes=60,
        reasoning="Bullish", current_price=100400.0,
        timestamp="2026-02-14T10:05:00Z",
    ))
    strategy._has_open_position = AsyncMock(return_value=True)

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 0


async def test_sell_blocked_when_no_position(strategy, bus, predictor):
    # Bearish but no position → no SELL
    predictor.predict = AsyncMock(return_value=Prediction(
        target_price=95380.0, timeframe_minutes=60,
        reasoning="Bearish", current_price=100400.0,
        timestamp="2026-02-14T10:05:00Z",
    ))
    strategy._has_open_position = AsyncMock(return_value=False)

    orders: list[OrderRequest] = []
    async def capture(event: OrderRequest):
        orders.append(event)
    bus.subscribe(OrderRequest, capture)

    await strategy._run_prediction_cycle()

    assert len(orders) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy_claude_prediction.py -v`
Expected: FAIL — `strategy_claude_prediction` module doesn't exist

**Step 3: Implement ClaudePredictionStrategy**

Create `src/strategy_claude_prediction.py`:

```python
import asyncio
import logging

from src.claude_predictor import ClaudePredictor, Prediction
from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderRequest, PriceUpdate
from src.news_service import NewsService
from src.price_buffer import PriceBuffer

logger = logging.getLogger(__name__)


class ClaudePredictionStrategy:
    def __init__(
        self,
        bus: EventBus,
        price_buffer: PriceBuffer,
        news_service: NewsService,
        predictor: ClaudePredictor,
        settings: Settings,
        product_id: str = "BTC-USD",
        db: Database | None = None,
    ) -> None:
        self._bus = bus
        self._price_buffer = price_buffer
        self._news_service = news_service
        self._predictor = predictor
        self._settings = settings
        self._product_id = product_id
        self._db = db
        self._task: asyncio.Task | None = None

    def register(self, bus: EventBus) -> None:
        bus.subscribe(PriceUpdate, self._on_price)

    async def _on_price(self, event: PriceUpdate) -> None:
        self._price_buffer.add(event)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._prediction_loop())
        logger.info(
            "Claude prediction strategy started for %s (interval=%dm, threshold=%.1f%%)",
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
        logger.info("Claude prediction strategy stopped")

    async def _prediction_loop(self) -> None:
        interval = self._settings.prediction_interval_minutes * 60
        while True:
            await asyncio.sleep(interval)
            try:
                await self._run_prediction_cycle()
            except Exception:
                logger.exception("Prediction cycle failed")

    async def _run_prediction_cycle(self) -> None:
        prices = self._price_buffer.snapshot(self._product_id)
        if not prices:
            logger.warning("No price data for %s, skipping prediction", self._product_id)
            return

        headlines = await self._news_service.fetch_headlines(self._product_id)
        prediction = await self._predictor.predict(prices, headlines)
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

    async def _evaluate(self, prediction: Prediction) -> None:
        diff_pct = (
            (prediction.target_price - prediction.current_price)
            / prediction.current_price
            * 100
        )

        threshold = self._settings.trade_threshold_pct

        if diff_pct > threshold:
            # Bullish — buy if no open position
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
            # Bearish — sell if we have a position
            if not await self._has_open_position():
                logger.info("Bearish (%.1f%%) but no position to sell, holding", diff_pct)
                return
            qty = await self._get_position_quantity()
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

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_strategy_claude_prediction.py -v`
Expected: PASS (8 passed)

**Step 5: Commit**

```bash
git add src/strategy_claude_prediction.py tests/test_strategy_claude_prediction.py
git commit -m "feat: add ClaudePredictionStrategy with trade decision logic"
```

---

### Task 7: Wire Into main.py

**Files:**
- Modify: `src/main.py:1-92`

**Step 1: Add strategy wiring to main.py**

Add imports at the top (after existing imports, line 14):

```python
from src.claude_predictor import ClaudePredictor
from src.news_service import NewsService
from src.price_buffer import PriceBuffer
from src.strategy_claude_prediction import ClaudePredictionStrategy
```

Add strategy setup after the market_data block (after line 60), before the logger.info on line 62:

```python
    # Claude prediction strategy
    price_buffer = PriceBuffer(max_size=50)
    news_service = NewsService(
        api_key=settings.grok_api_key,
        model=settings.grok_model,
    )
    claude_predictor = ClaudePredictor(
        api_key=settings.anthropic_api_key,
        model=settings.prediction_model,
    )
    strategy = ClaudePredictionStrategy(
        bus=bus,
        price_buffer=price_buffer,
        news_service=news_service,
        predictor=claude_predictor,
        settings=settings,
        product_id="BTC-USD",
        db=db,
    )
    strategy.register(bus)
```

Start the strategy and market data before the stop_event wait (replace lines 62-82):

```python
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
    await market_data.start(product_ids=["BTC-USD"])
    await strategy.start()

    logger.info("Bot running with Claude prediction strategy (interval=%dm)",
                settings.prediction_interval_minutes)
    await stop_event.wait()

    # Cleanup
    await strategy.stop()
    await market_data.stop()
    await db.close()
    logger.info("Shutdown complete")
```

**Step 2: Run full test suite to verify nothing breaks**

Run: `pytest tests/ -v`
Expected: All existing tests PASS

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: wire ClaudePredictionStrategy into main.py startup"
```

---

### Task 8: Update Documentation

**Files:**
- Modify: `docs/ai-index.md` (add new components to file map)
- Modify: `docs/ai-components.md` (add PriceBuffer, NewsService, ClaudePredictor, ClaudePredictionStrategy)
- Modify: `README.md` (add Claude prediction feature, new env vars)
- Modify: `.env.example` (already done in Task 2)

**Step 1: Update README.md**

Add to the Features section:
- Claude-powered price prediction strategy (Opus 4.6)
- Real-time crypto news/sentiment via Grok API
- Configurable prediction interval, trade threshold, and trade size

Add to the Setup section the new env vars:
- `ANTHROPIC_API_KEY`
- `GROK_API_KEY`
- `PREDICTION_INTERVAL_MINUTES`
- `PREDICTION_MODEL`
- `TRADE_THRESHOLD_PCT`
- `TRADE_SIZE_USD`

**Step 2: Update ai-index.md**

Add new files to the file map:
- `src/price_buffer.py` — In-memory ring buffer for price history
- `src/news_service.py` — Grok API client for crypto news/sentiment
- `src/claude_predictor.py` — Claude API client for price predictions
- `src/strategy_claude_prediction.py` — Timer-based prediction strategy

**Step 3: Update ai-components.md**

Add component documentation for all four new classes following the existing format.

**Step 4: Commit**

```bash
git add docs/ README.md
git commit -m "docs: add Claude prediction strategy to project documentation"
```

---

### Task 9: Run Full Test Suite

**Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS (existing 48 + new ~19 = ~67 total)

**Step 2: Run with coverage**

Run: `pytest tests/ --cov=src --cov-report=term-missing -v`
Verify new files have reasonable coverage.
