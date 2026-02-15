from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    coinbase_key_file: str = ""
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
    product_id: str = "BTC-USD"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
