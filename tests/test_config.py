from src.config import Settings


def test_openrouter_api_key_default():
    s = Settings(
        _env_file=None,
        coinbase_api_key="k",
        coinbase_api_secret="s",
    )
    assert s.openrouter_api_key == ""
