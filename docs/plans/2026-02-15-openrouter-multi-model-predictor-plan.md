# OpenRouter / Multi-Model Predictor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an LLM client abstraction layer and a KimiPredictor (via OpenRouter) so the bot can swap between Claude and Kimi (or future models) via config.

**Architecture:** Two-layer design: (1) `LLMClient` protocol for transport (Anthropic SDK vs OpenAI-compatible SDK), (2) `Predictor` protocol for model-specific prompting. Factory in `main.py` selects predictor based on `PREDICTOR_TYPE` env var. Strategy unchanged — already uses constructor injection.

**Tech Stack:** Python 3.12+, anthropic SDK, openai SDK (already a dependency for NewsService), pydantic-settings, pytest

**Design doc:** `docs/plans/2026-02-15-openrouter-multi-model-predictor-design.md`

---

### Task 1: Create `src/prediction.py` — Shared Prediction Dataclass + Predictor Protocol

**Files:**
- Create: `src/prediction.py`
- Test: `tests/test_prediction.py`

**Step 1: Write the test**

```python
# tests/test_prediction.py
from src.prediction import Prediction, Predictor


def test_prediction_fields():
    p = Prediction(
        target_price=105000.0,
        timeframe_minutes=60,
        reasoning="Bullish",
        current_price=100000.0,
        timestamp="2026-02-14T10:00:00Z",
    )
    assert p.target_price == 105000.0
    assert p.timeframe_minutes == 60
    assert p.reasoning == "Bullish"
    assert p.current_price == 100000.0
    assert p.timestamp == "2026-02-14T10:00:00Z"


def test_predictor_protocol_is_runtime_checkable():
    assert hasattr(Predictor, '__protocol_attrs__') or hasattr(Predictor, '_is_protocol')
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_prediction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.prediction'`

**Step 3: Write the implementation**

```python
# src/prediction.py
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.events import PriceUpdate


@dataclass
class Prediction:
    target_price: float
    timeframe_minutes: int
    reasoning: str
    current_price: float
    timestamp: str


@runtime_checkable
class Predictor(Protocol):
    async def predict(
        self, prices: list[PriceUpdate], headlines: list[str]
    ) -> Prediction | None: ...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_prediction.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/prediction.py tests/test_prediction.py
git commit -m "feat: add shared Prediction dataclass and Predictor protocol"
```

---

### Task 2: Create `src/llm_client.py` — LLMClient Protocol + Implementations

**Files:**
- Create: `src/llm_client.py`
- Test: `tests/test_llm_client.py`

**Step 1: Write the tests**

```python
# tests/test_llm_client.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.llm_client import AnthropicLLMClient, LLMClient, OpenAICompatibleLLMClient


def test_anthropic_client_satisfies_protocol():
    client = AnthropicLLMClient.__new__(AnthropicLLMClient)
    assert isinstance(client, LLMClient)


def test_openai_compatible_client_satisfies_protocol():
    client = OpenAICompatibleLLMClient.__new__(OpenAICompatibleLLMClient)
    assert isinstance(client, LLMClient)


async def test_anthropic_client_complete():
    client = AnthropicLLMClient(api_key="test-key", model="claude-opus-4-6")

    response = MagicMock()
    response.content = [MagicMock()]
    response.content[0].text = "Hello from Claude"
    client._client = MagicMock()
    client._client.messages.create = AsyncMock(return_value=response)

    result = await client.complete(system="Be helpful", user="Hi", max_tokens=100)
    assert result == "Hello from Claude"

    call_kwargs = client._client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-opus-4-6"
    assert call_kwargs["system"] == "Be helpful"
    assert call_kwargs["max_tokens"] == 100


async def test_openai_compatible_client_complete():
    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        model="moonshotai/kimi-k2",
        base_url="https://openrouter.ai/api/v1",
    )

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "Hello from Kimi"
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(return_value=response)

    result = await client.complete(system="Be helpful", user="Hi", max_tokens=100)
    assert result == "Hello from Kimi"

    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "moonshotai/kimi-k2"
    assert call_kwargs["max_tokens"] == 100
    messages = call_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "Be helpful"}
    assert messages[1] == {"role": "user", "content": "Hi"}


async def test_openai_compatible_client_handles_none_content():
    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        model="moonshotai/kimi-k2",
        base_url="https://openrouter.ai/api/v1",
    )

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = None
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(return_value=response)

    result = await client.complete(system="Be helpful", user="Hi")
    assert result == ""
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.llm_client'`

**Step 3: Write the implementation**

```python
# src/llm_client.py
from typing import Protocol, runtime_checkable

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI


@runtime_checkable
class LLMClient(Protocol):
    """Transport-level LLM API client."""

    async def complete(self, system: str, user: str, max_tokens: int = 512) -> str: ...


class AnthropicLLMClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, system: str, user: str, max_tokens: int = 512) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text


class OpenAICompatibleLLMClient:
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def complete(self, system: str, user: str, max_tokens: int = 512) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/llm_client.py tests/test_llm_client.py
git commit -m "feat: add LLMClient protocol with Anthropic and OpenAI-compatible implementations"
```

---

### Task 3: Refactor `ClaudePredictor` to Use `LLMClient`

**Files:**
- Modify: `src/claude_predictor.py`
- Modify: `tests/test_claude_predictor.py`

**Step 1: Update the tests**

The tests need to change because `ClaudePredictor` will now accept an `LLMClient` instead of an `api_key`. Update `tests/test_claude_predictor.py`:

- Replace `mock_anthropic_client` fixture with a mock `LLMClient`
- `ClaudePredictor(api_key="test-key")` becomes `ClaudePredictor(client=mock_llm_client)`
- Import `Prediction` from `src.prediction` instead of `src.claude_predictor`
- Mock `client.complete` as `AsyncMock(return_value='{"target_price": ...}')`

```python
# tests/test_claude_predictor.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.claude_predictor import ClaudePredictor
from src.events import PriceUpdate
from src.prediction import Prediction


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.complete = AsyncMock(
        return_value=(
            '{"target_price": 105000.0, "timeframe_minutes": 60, '
            '"reasoning": "Bullish momentum with strong ETF inflows"}'
        )
    )
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


async def test_predict_returns_prediction(mock_llm_client, prices, headlines):
    predictor = ClaudePredictor(client=mock_llm_client)

    result = await predictor.predict(prices, headlines)

    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    assert result.timeframe_minutes == 60
    assert result.reasoning == "Bullish momentum with strong ETF inflows"
    assert result.current_price == 101000.0


async def test_predict_calls_client_complete(mock_llm_client, prices, headlines):
    predictor = ClaudePredictor(client=mock_llm_client)

    await predictor.predict(prices, headlines)

    mock_llm_client.complete.assert_called_once()
    call_kwargs = mock_llm_client.complete.call_args.kwargs
    assert "crypto price prediction" in call_kwargs["system"].lower()
    assert "100000.0" in call_kwargs["user"]
    assert "ETF inflows" in call_kwargs["user"]


async def test_predict_api_error(mock_llm_client, prices, headlines):
    mock_llm_client.complete = AsyncMock(side_effect=Exception("API error"))
    predictor = ClaudePredictor(client=mock_llm_client)

    result = await predictor.predict(prices, headlines)
    assert result is None


async def test_predict_malformed_json(mock_llm_client, prices, headlines):
    mock_llm_client.complete = AsyncMock(return_value="not json")
    predictor = ClaudePredictor(client=mock_llm_client)

    result = await predictor.predict(prices, headlines)
    assert result is None


async def test_predict_empty_prices(mock_llm_client, headlines):
    predictor = ClaudePredictor(client=mock_llm_client)
    result = await predictor.predict([], headlines)
    assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_claude_predictor.py -v`
Expected: FAIL — constructor signature mismatch

**Step 3: Refactor the implementation**

```python
# src/claude_predictor.py
import json
import logging
from datetime import datetime, timezone

from src.events import PriceUpdate
from src.llm_client import LLMClient
from src.prediction import Prediction

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a crypto price prediction analyst. Analyze the provided "
    "price history and news to predict the short-term price target. "
    "Respond ONLY with valid JSON in this exact format:\n"
    '{"target_price": <float>, "timeframe_minutes": <int>, '
    '"reasoning": "<brief explanation>"}\n'
    "No other text."
)


class ClaudePredictor:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def predict(
        self, prices: list[PriceUpdate], headlines: list[str]
    ) -> Prediction | None:
        if not prices:
            return None

        current_price = prices[-1].price
        user_prompt = self._build_prompt(prices, headlines)

        try:
            raw = await self._client.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=512,
            )
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_claude_predictor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/claude_predictor.py tests/test_claude_predictor.py
git commit -m "refactor: ClaudePredictor accepts LLMClient instead of raw API key"
```

---

### Task 4: Create `src/kimi_predictor.py`

**Files:**
- Create: `src/kimi_predictor.py`
- Test: `tests/test_kimi_predictor.py`

**Step 1: Write the tests**

```python
# tests/test_kimi_predictor.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.events import PriceUpdate
from src.kimi_predictor import KimiPredictor
from src.prediction import Prediction, Predictor


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.complete = AsyncMock(
        return_value=(
            '{"target_price": 105000.0, "timeframe_minutes": 60, '
            '"reasoning": "Strong upward momentum detected"}'
        )
    )
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
    return ["1. Bitcoin bullish on ETF news"]


def test_kimi_predictor_satisfies_protocol():
    client = MagicMock()
    predictor = KimiPredictor(client=client)
    assert isinstance(predictor, Predictor)


async def test_predict_returns_prediction(mock_llm_client, prices, headlines):
    predictor = KimiPredictor(client=mock_llm_client)

    result = await predictor.predict(prices, headlines)

    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    assert result.timeframe_minutes == 60
    assert result.current_price == 101000.0


async def test_predict_calls_client_complete(mock_llm_client, prices, headlines):
    predictor = KimiPredictor(client=mock_llm_client)

    await predictor.predict(prices, headlines)

    mock_llm_client.complete.assert_called_once()
    call_kwargs = mock_llm_client.complete.call_args.kwargs
    assert "user" in call_kwargs
    assert "system" in call_kwargs


async def test_predict_api_error(mock_llm_client, prices, headlines):
    mock_llm_client.complete = AsyncMock(side_effect=Exception("API error"))
    predictor = KimiPredictor(client=mock_llm_client)

    result = await predictor.predict(prices, headlines)
    assert result is None


async def test_predict_malformed_json(mock_llm_client, prices, headlines):
    mock_llm_client.complete = AsyncMock(return_value="not json at all")
    predictor = KimiPredictor(client=mock_llm_client)

    result = await predictor.predict(prices, headlines)
    assert result is None


async def test_predict_empty_prices(mock_llm_client, headlines):
    predictor = KimiPredictor(client=mock_llm_client)
    result = await predictor.predict([], headlines)
    assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_kimi_predictor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.kimi_predictor'`

**Step 3: Write the implementation**

```python
# src/kimi_predictor.py
import json
import logging
from datetime import datetime, timezone

from src.events import PriceUpdate
from src.llm_client import LLMClient
from src.prediction import Prediction

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a quantitative crypto analyst. Given price history and recent news, "
    "predict the short-term price target.\n"
    "Respond ONLY with valid JSON in this exact format:\n"
    '{"target_price": <float>, "timeframe_minutes": <int>, '
    '"reasoning": "<brief explanation>"}\n'
    "No other text."
)


class KimiPredictor:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def predict(
        self, prices: list[PriceUpdate], headlines: list[str]
    ) -> Prediction | None:
        if not prices:
            return None

        current_price = prices[-1].price
        user_prompt = self._build_prompt(prices, headlines)

        try:
            raw = await self._client.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=512,
            )
            data = json.loads(raw)
            return Prediction(
                target_price=float(data["target_price"]),
                timeframe_minutes=int(data["timeframe_minutes"]),
                reasoning=str(data["reasoning"]),
                current_price=current_price,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.exception("Failed to parse Kimi prediction response")
            return None
        except Exception:
            logger.exception("Kimi prediction API call failed")
            return None

    def _build_prompt(
        self, prices: list[PriceUpdate], headlines: list[str]
    ) -> str:
        price_lines = "\n".join(
            f"  {p.timestamp}: ${p.price}" for p in prices
        )
        headline_lines = (
            "\n".join(f"  {h}" for h in headlines)
            if headlines
            else "  No recent news available"
        )

        return (
            f"Asset: {prices[0].product_id}\n\n"
            f"Price history (recent):\n{price_lines}\n\n"
            f"Latest price: ${prices[-1].price}\n\n"
            f"News headlines:\n{headline_lines}\n\n"
            "Predict the price target for the next short-term window."
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_kimi_predictor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/kimi_predictor.py tests/test_kimi_predictor.py
git commit -m "feat: add KimiPredictor for OpenRouter-based predictions"
```

---

### Task 5: Update `src/config.py` with OpenRouter Settings

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_config.py` (create if it doesn't exist)

**Step 1: Write the test**

```python
# tests/test_config.py
from src.config import Settings


def test_default_predictor_type():
    s = Settings(
        _env_file=None,
        coinbase_api_key="k",
        coinbase_api_secret="s",
    )
    assert s.predictor_type == "claude"


def test_openrouter_defaults():
    s = Settings(
        _env_file=None,
        coinbase_api_key="k",
        coinbase_api_secret="s",
    )
    assert s.openrouter_api_key == ""
    assert s.openrouter_model == "moonshotai/kimi-k2"
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `predictor_type` attribute not found

**Step 3: Add the fields to Settings**

In `src/config.py`, add these fields to the `Settings` class after the existing prediction fields:

```python
    # Predictor selection
    predictor_type: str = "claude"  # "claude" or "kimi"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "moonshotai/kimi-k2"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add predictor_type and OpenRouter settings to config"
```

---

### Task 6: Update `src/main.py` — Factory Wiring

**Files:**
- Modify: `src/main.py`
- Modify: `src/strategy_claude_prediction.py` (type hint update)

**Step 1: Update strategy type hint**

In `src/strategy_claude_prediction.py`, change the import and type hint:

- Replace `from src.claude_predictor import ClaudePredictor, Prediction` with:
  ```python
  from src.prediction import Prediction, Predictor
  ```
- Change `predictor: ClaudePredictor` parameter to `predictor: Predictor` in `__init__`
- Change `self._predictor: ClaudePredictor` type to just remove the annotation (duck typing via Protocol)

**Step 2: Update `main.py`**

Add a `_create_predictor` function and update the wiring:

```python
# Add imports at top of main.py
from src.llm_client import AnthropicLLMClient, OpenAICompatibleLLMClient
from src.kimi_predictor import KimiPredictor
from src.prediction import Predictor


def _create_predictor(settings: Settings) -> Predictor:
    if settings.predictor_type == "kimi":
        client = OpenAICompatibleLLMClient(
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            base_url=settings.openrouter_base_url,
        )
        return KimiPredictor(client=client)
    else:
        client = AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.prediction_model,
        )
        return ClaudePredictor(client=client)
```

Replace the existing predictor construction in `main()`:
```python
    # Before:
    # claude_predictor = ClaudePredictor(api_key=..., model=...)

    # After:
    predictor = _create_predictor(settings)
```

And update the strategy construction to use `predictor` instead of `claude_predictor`.

**Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add src/main.py src/strategy_claude_prediction.py
git commit -m "feat: add predictor factory in main.py, strategy accepts any Predictor"
```

---

### Task 7: Fix Downstream Imports of Prediction

**Files:**
- Modify: any file that imports `Prediction` from `src.claude_predictor`

Known files to check:
- `tests/test_strategy_news_prediction.py` — imports `Prediction` from `src.claude_predictor`
- `src/strategy_claude_prediction.py` — already handled in Task 6

**Step 1: Search for old imports**

Run: `grep -r "from src.claude_predictor import" tests/ src/`

**Step 2: Update each file**

Change `from src.claude_predictor import Prediction` to `from src.prediction import Prediction`.

**Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add -u
git commit -m "refactor: update Prediction imports to use src.prediction"
```

---

### Task 8: Update Documentation

**Files:**
- Modify: `docs/ai-components.md`
- Modify: `docs/ai-index.md`

**Step 1: Add LLMClient, KimiPredictor, Prediction to ai-components.md**

Add sections for:
- `LLMClient` protocol + `AnthropicLLMClient` + `OpenAICompatibleLLMClient` in `src/llm_client.py`
- `KimiPredictor` in `src/kimi_predictor.py`
- `Prediction` + `Predictor` protocol in `src/prediction.py`
- Update `ClaudePredictor` section to reflect new constructor signature

**Step 2: Update ai-index.md file map**

Add new files to the file map.

**Step 3: Commit**

```bash
git add docs/
git commit -m "docs: add LLM client and KimiPredictor to AI documentation"
```
