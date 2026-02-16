# src/main.py
import argparse
import asyncio
import logging
import signal
from pathlib import Path

from src.coinbase_client import CoinbaseClient
from src.config import Settings
from src.db import Database
from src.event_bus import EventBus
from src.kill_switch import KillSwitch
from src.market_data import MarketData
from src.order_manager import OrderManager
from src.portfolio_tracker import PortfolioTracker
from src.position_tracker import PositionTracker
from src.run_reporter import RunReporter
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

    # Portfolio tracker (must be created before OrderManager)
    portfolio_tracker = PortfolioTracker(
        db=db,
        bus=bus,
        coinbase=coinbase,
        product_id=settings.product_id,
        interval_seconds=settings.prediction_interval_minutes * 60,
    )

    # Order manager
    order_manager = OrderManager(
        db=db, bus=bus, risk_manager=risk_manager,
        coinbase=coinbase, portfolio_tracker=portfolio_tracker,
    )
    order_manager.register(bus)

    # Position tracker
    position_tracker = PositionTracker(db=db, bus=bus)
    position_tracker.register(bus)

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

    logger.info("Bot running with %s strategy + %s/%s (interval=%dm)",
                args.strategy, args.llm, model, settings.prediction_interval_minutes)
    await stop_event.wait()

    # Cleanup
    await run_reporter.stop()
    await portfolio_tracker.stop()
    await strategy.stop()
    await market_data.stop()
    await db.close()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
