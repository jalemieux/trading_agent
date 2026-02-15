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
