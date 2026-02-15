#!/usr/bin/env python3
"""Interactive smoke test for trading bot plumbing."""

import asyncio
import logging
import os
import sys

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.coinbase_client import CoinbaseClient
from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFilled, OrderRequest, PositionChanged, PriceUpdate
from src.kill_switch import KillSwitch
from src.market_data import MarketData
from src.order_manager import OrderManager
from src.position_tracker import PositionTracker
from src.risk_manager import RiskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("smoke_test")

# --- Constants ---
PRODUCT_ID = "SOL-USDC"
BUY_QUOTE_USD = 1.0  # $1 worth of SOL
SMOKE_DB = "smoke_test.db"

# --- ANSI Colors ---
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓ {msg}{RESET}")


def fail(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}")


def info(msg: str) -> None:
    print(f"  {CYAN}ℹ {msg}{RESET}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠ {msg}{RESET}")


def header(stage: int, title: str) -> None:
    print(f"\n{BOLD}{'='*50}")
    print(f"  Stage {stage}: {title}")
    print(f"{'='*50}{RESET}\n")


def prompt_continue() -> bool:
    """Prompt user to continue or quit. Returns True to continue."""
    try:
        resp = input(f"\n  {YELLOW}[Enter to continue / q to quit]{RESET} ")
        return resp.strip().lower() != "q"
    except (EOFError, KeyboardInterrupt):
        return False


async def run() -> None:
    print(f"\n{BOLD}{CYAN}Coinbase Trading Bot — Smoke Test{RESET}")
    print(f"{CYAN}Product: {PRODUCT_ID} | Trade size: ${BUY_QUOTE_USD}{RESET}\n")

    # Load settings (override DB path and risk limits for safety)
    settings = Settings()
    settings.db_path = SMOKE_DB
    settings.max_order_size_usd = 10.0
    settings.max_daily_loss_usd = 50.0

    # Wire components identically to main.py
    bus = EventBus()
    db = Database(SMOKE_DB)
    await db.initialize()

    kill_switch = KillSwitch(db=db, bus=bus)
    await kill_switch.initialize()
    if kill_switch.is_active:
        warn("Kill switch active from previous run — deactivating")
        await kill_switch.deactivate()

    risk_manager = RiskManager(db=db, bus=bus, kill_switch=kill_switch, settings=settings)

    coinbase = CoinbaseClient(
        api_key=settings.coinbase_api_key,
        api_secret=settings.coinbase_api_secret,
    )

    order_manager = OrderManager(db=db, bus=bus, risk_manager=risk_manager, coinbase=coinbase)
    order_manager.register(bus)

    position_tracker = PositionTracker(db=db, bus=bus)
    position_tracker.register(bus)

    market_data = MarketData(
        bus=bus,
        api_key=settings.coinbase_api_key,
        api_secret=settings.coinbase_api_secret,
    )

    # Collectors for events during each stage
    filled_events: list[OrderFilled] = []
    position_events: list[PositionChanged] = []

    async def collect_filled(e: OrderFilled) -> None:
        filled_events.append(e)

    async def collect_position(e: PositionChanged) -> None:
        position_events.append(e)

    bus.subscribe(OrderFilled, collect_filled)
    bus.subscribe(PositionChanged, collect_position)

    try:
        # --- Stage 1: Connectivity ---
        await stage_connectivity(coinbase)
        if not prompt_continue():
            return

        # --- Stage 2: Market Data ---
        await stage_market_data(market_data, bus)
        if not prompt_continue():
            return

        # --- Stage 3: Buy ---
        filled_events.clear()
        position_events.clear()
        await stage_buy(bus, filled_events, position_events)
        if not prompt_continue():
            return

        # --- Stage 4: Verify Position ---
        await stage_verify_position(db)
        if not prompt_continue():
            return

        # --- Stage 5: Hold ---
        await stage_hold(db)
        if not prompt_continue():
            return

        # --- Stage 6: Sell ---
        filled_events.clear()
        position_events.clear()
        buy_qty = await get_open_position_qty(db)
        await stage_sell(bus, buy_qty, filled_events, position_events)
        if not prompt_continue():
            return

        # --- Stage 7: Summary ---
        await stage_summary(db)

    finally:
        await market_data.stop()
        await db.close()
        print(f"\n{CYAN}Smoke test complete. Database saved to {SMOKE_DB}{RESET}\n")


# --- Placeholder stage functions (implemented in subsequent tasks) ---

async def stage_connectivity(coinbase: CoinbaseClient) -> None:
    header(1, "Connectivity")

    # Test 1: Get accounts
    info("Fetching accounts...")
    try:
        accounts_resp = coinbase.get_accounts()
        accounts = accounts_resp.get("accounts", [])
        ok(f"Connected — {len(accounts)} account(s) found")
        for acct in accounts:
            currency = acct.get("currency", "?")
            available = acct.get("available_balance", {}).get("value", "0")
            if float(available) > 0:
                info(f"  {currency}: {available}")
    except Exception as e:
        fail(f"get_accounts() failed: {e}")
        return

    # Test 2: Get product info
    info(f"Fetching product info for {PRODUCT_ID}...")
    try:
        product = coinbase.get_product(PRODUCT_ID)
        price = product.get("price", "?")
        status = product.get("status", "?")
        base_min = product.get("base_min_size", "?")
        quote_min = product.get("quote_min_size", "?")
        ok(f"{PRODUCT_ID} — price: ${price}, status: {status}")
        info(f"  min base: {base_min}, min quote: {quote_min}")
    except Exception as e:
        fail(f"get_product() failed: {e}")

async def stage_market_data(market_data: MarketData, bus: EventBus) -> None:
    header(2, "Market Data (WebSocket)")

    prices: list[float] = []
    price_event = asyncio.Event()

    async def on_price(event):
        prices.append(event.price)
        info(f"  tick #{len(prices)}: {event.product_id} = ${event.price}")
        if len(prices) >= 3:
            price_event.set()

    bus.subscribe(PriceUpdate, on_price)

    info(f"Subscribing to {PRODUCT_ID} ticker...")
    try:
        await market_data.start([PRODUCT_ID])
        ok("WebSocket opened")
    except Exception as e:
        fail(f"WebSocket failed to open: {e}")
        bus.unsubscribe(PriceUpdate, on_price)
        return

    info("Waiting for 3 price ticks (30s timeout)...")
    try:
        await asyncio.wait_for(price_event.wait(), timeout=30.0)
        ok(f"Received {len(prices)} ticks — market data working")
    except asyncio.TimeoutError:
        warn(f"Only received {len(prices)} ticks in 30s")

    bus.unsubscribe(PriceUpdate, on_price)

    # Stop market data after test
    await market_data.stop()
    ok("WebSocket closed")

async def stage_buy(bus: EventBus, filled: list, positions: list) -> None:
    pass

async def stage_verify_position(db: Database) -> None:
    pass

async def stage_hold(db: Database) -> None:
    pass

async def get_open_position_qty(db: Database) -> float:
    return 0.0

async def stage_sell(bus: EventBus, qty: float, filled: list, positions: list) -> None:
    pass

async def stage_summary(db: Database) -> None:
    pass


if __name__ == "__main__":
    asyncio.run(run())
