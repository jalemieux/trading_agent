# Coinbase Trading Bot

**Coinbase Trading Bot** is an asynchronous, event-driven framework designed to bridge the gap between Large Language Model (LLM) reasoning and professional market execution. It provides a hardened infrastructure—Websocket management, order lifecycle persistence, and multi-stage risk validation—allowing developers to focus entirely on the strategy layer.


Built with Python 3.12+, asyncio, and the official Coinbase SDK.

## Features

- **Real-time market data** via Coinbase WebSocket (ticker channel)
- **Order lifecycle management** with fill tracking and fee accounting
- **Risk pipeline** -- max order size, daily P&L limit, kill switch
- **Position tracking** with realized P&L and daily summaries
- **Kill switch** -- emergency halt persisted across restarts
- **Event-driven architecture** -- all components communicate via async pub/sub
- **SQLite persistence** for positions, orders, and daily summaries
- **Claude-powered price prediction** — uses Claude Opus 4.6 to predict BTC price targets
- **Two strategy modes** — `price_only` (technical analysis only) or `news` (price + news sentiment)
- **Real-time crypto news** — fetches news/sentiment via Grok API (xAI) (news strategy)
- **Configurable trading** — adjustable prediction interval, trade threshold, size, and strategy
- **Trading dashboard** — Next.js web UI with portfolio equity curve, price charts, positions/orders tables, and prediction log

## Setup

### 1. Clone and install

```bash
git clone <repo-url> coinbase_trading_bot
cd coinbase_trading_bot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure API keys

Copy the example env file and fill in your Coinbase CDP API credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```
COINBASE_API_KEY=organizations/YOUR_ORG_ID/apiKeys/YOUR_KEY_ID
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\nYOUR_KEY\n-----END EC PRIVATE KEY-----\n"
MAX_ORDER_SIZE_USD=100
MAX_DAILY_LOSS_USD=500
DB_PATH=trading_bot.db
```

| Variable | Description | Default |
|----------|-------------|---------|
| `COINBASE_API_KEY` | CDP API key (ES256 format) | `""` |
| `COINBASE_API_SECRET` | CDP API secret (EC private key) | `""` |
| `COINBASE_KEY_FILE` | Path to CDP JSON key file (alternative to key/secret) | `""` |
| `MAX_ORDER_SIZE_USD` | Max USD value per order | `100` |
| `MAX_DAILY_LOSS_USD` | Daily loss limit before kill switch activates | `500` |
| `DB_PATH` | SQLite database file path | `trading_bot.db` |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude predictions | `""` |
| `GROK_API_KEY` | xAI API key for Grok news service | `""` |
| `PREDICTION_INTERVAL_MINUTES` | Minutes between prediction cycles | `5` |
| `PREDICTION_MODEL` | Claude model for predictions | `claude-opus-4-6` |
| `GROK_MODEL` | Grok model for news | `grok-3-mini-fast` |
| `TRADE_THRESHOLD_PCT` | Min % price difference to trigger trade | `1.0` |
| `TRADE_SIZE_USD` | USD amount per trade | `50.0` |
| `PRODUCT_ID` | Trading pair to monitor and trade | `BTC-USD` |
| `STRATEGY` | Strategy mode: `price_only` or `news` | `price_only` |

### 3. Run

```bash
python -m src.main
```

The bot initializes all components, connects to the Coinbase WebSocket for price data, and starts the selected prediction strategy. Shut down with `Ctrl+C` (graceful SIGINT/SIGTERM handling).

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=src

# Single module
pytest tests/test_risk_manager.py -v
```

Tests use mocked Coinbase responses -- no API keys or network access required.

### Live Smoke Test

Validates the full trading pipeline against the real Coinbase API:

```bash
python scripts/smoke_test.py
```

Walks through 7 stages interactively:
1. **Connectivity** — API keys, account info, product lookup
2. **Market Data** — WebSocket ticker subscription
3. **Buy** — Market buy $1 of SOL-USDC
4. **Verify** — Check position in DB
5. **Hold** — Confirm position stays open
6. **Sell** — Market sell all SOL
7. **Summary** — P&L, fees, final state

Requires `.env` with valid `COINBASE_API_KEY` and `COINBASE_API_SECRET`.
Uses a separate `smoke_test.db` database.

## Dashboard UI

```bash
cd ui
npm install
npm run dev     # development at http://localhost:3000
```

Set `DB_PATH` in `ui/.env.local` to point at your `trading_bot.db`.

The dashboard provides 6 pages:
- **Overview** — current price, daily P&L, kill switch status, open position
- **Portfolio** — equity curve chart with time range selector, drawdown stats
- **Positions** — filterable table (All / Open / Closed)
- **Orders** — full order log with fill prices and fees
- **Prices** — price chart with buy/sell trade markers
- **Predictions** — AI prediction log with expandable news headlines

## Architecture

All components are independent nodes connected through an async `EventBus`. See [docs/architecture.md](docs/architecture.md) for the full component diagram, event flow, data model, and risk pipeline.

```
                         Event Bus (asyncio pub/sub)
    ┌──────────┬──────────┬──────────┬──────────┬──────────┐
    │          │          │          │          │          │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼─────┐
│Market │ │Order  │ │Risk   │ │Pos.   │ │Kill   │ │Strategy │
│Data   │ │Mgr    │ │Mgr    │ │Track  │ │Switch │ │(select) │
└───┬───┘ └───┬───┘ └───────┘ └───┬───┘ └───────┘ └────┬────┘
    │         │                    │          ┌──────────┤
    │         │                    │          │          │
    │         │                    │   ┌──────▼──┐ ┌────▼─────┐
    │         │                    │   │PriceOnly│ │News      │
    │         │                    │   │Strategy │ │Strategy  │
    └─────────┴────────────────────┘   └────┬────┘ └────┬─────┘
              │                             │           │
     ┌────────▼────────┐              ┌─────▼───┐  ┌───▼──────┐
     │ Coinbase Client  │              │Claude   │  │Claude    │
     │ (SDK wrapper)    │              │PriceOnly│  │Predictor │
     └──────────────────┘              │Predictor│  │+ News Svc│
                                       └─────────┘  └──────────┘
```

## Risk Controls

Orders pass through a validation pipeline before execution:

1. **Kill switch check** -- is trading halted?
2. **Order size check** -- does the order exceed `MAX_ORDER_SIZE_USD`?
3. **Daily P&L check** -- has cumulative daily loss exceeded `MAX_DAILY_LOSS_USD`?

If the daily loss limit is breached, the kill switch activates automatically and persists to the database. It blocks all new orders until manually reset. Existing positions are **not** auto-closed.

## Project Structure

```
coinbase_trading_bot/
├── src/
│   ├── main.py                 # Entry point, wires components, strategy selection
│   ├── config.py               # Pydantic settings from .env
│   ├── event_bus.py            # Async pub/sub
│   ├── events.py               # Event dataclasses
│   ├── coinbase_client.py      # SDK wrapper (REST + WebSocket)
│   ├── market_data.py          # WebSocket price feeds
│   ├── order_manager.py        # Order placement and tracking
│   ├── risk_manager.py         # Limit validation pipeline
│   ├── position_tracker.py     # Position + P&L management
│   ├── kill_switch.py          # Emergency halt
│   ├── price_buffer.py          # In-memory price history buffer
│   ├── news_service.py          # Grok API news/sentiment client
│   ├── claude_predictor.py      # Claude API price predictions (news strategy)
│   ├── claude_price_only_predictor.py  # Claude API price-only predictions
│   ├── strategy_news_prediction.py    # News + price prediction strategy
│   ├── strategy_price_only.py         # Price-only prediction strategy
│   ├── portfolio_tracker.py    # Periodic portfolio snapshots
│   └── db.py                   # SQLite setup and migrations
├── ui/                         # Next.js dashboard (TypeScript + Tailwind)
│   ├── src/app/                # Pages and API routes
│   ├── src/components/         # Shared UI components
│   └── src/lib/                # DB connection and types
├── tests/                      # Unit + integration tests
├── scripts/
│   └── smoke_test.py           # Interactive live plumbing validation
├── docs/
│   ├── architecture.md         # Component diagram, data model, flows
│   ├── ai-index.md             # AI reference: system summary, file map
│   ├── ai-components.md        # AI reference: class details
│   ├── ai-data.md              # AI reference: event/DB schemas
│   ├── ai-traces.md            # AI reference: execution paths
│   ├── ai-troubleshooting.md   # AI reference: failure modes
│   ├── ai-extending.md         # AI reference: extension guide
│   └── plans/                  # Design documents
├── pyproject.toml
└── .env.example
```
