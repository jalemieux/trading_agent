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
