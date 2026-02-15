# src/main.py
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
from src.risk_manager import RiskManager
from src.price_buffer import PriceBuffer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
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

    logger.info("Bot running with %s strategy (interval=%dm)",
                settings.strategy, settings.prediction_interval_minutes)
    await stop_event.wait()

    # Cleanup
    await portfolio_tracker.stop()
    await strategy.stop()
    await market_data.stop()
    await db.close()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
