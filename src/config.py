from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    coinbase_key_file: str = ""
    max_order_size_usd: float = 100.0
    max_daily_loss_usd: float = 500.0
    db_path: str = "trading_bot.db"

    # Strategy selection
    strategy: str = "price_only"  # "price_only" or "news"

    # Predictor selection
    predictor_type: str = "claude"  # "claude" or "kimi"

    # Prediction settings
    anthropic_api_key: str = ""
    grok_api_key: str = ""
    prediction_interval_minutes: int = 5
    prediction_model: str = "claude-opus-4-6"
    grok_model: str = "grok-3-mini-fast"
    trade_threshold_pct: float = 1.0
    trade_size_usd: float = 50.0
    product_id: str = "BTC-USD"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "moonshotai/kimi-k2"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
