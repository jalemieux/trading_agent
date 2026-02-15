from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    coinbase_key_file: str = ""
    max_order_size_usd: float = 100.0
    max_daily_loss_usd: float = 500.0
    db_path: str = "trading_bot.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
