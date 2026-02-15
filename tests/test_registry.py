from src.registry import STRATEGIES, LLM_PROVIDERS


def test_strategies_registry_has_expected_keys():
    assert "price_only" in STRATEGIES
    assert "news" in STRATEGIES


def test_llm_providers_registry_has_expected_keys():
    assert "anthropic" in LLM_PROVIDERS
    assert "openrouter" in LLM_PROVIDERS


def test_strategy_entries_have_class_and_description():
    for key, entry in STRATEGIES.items():
        assert "class" in entry, f"{key} missing 'class'"
        assert "description" in entry, f"{key} missing 'description'"


def test_provider_entries_have_required_fields():
    for key, entry in LLM_PROVIDERS.items():
        assert "class" in entry, f"{key} missing 'class'"
        assert "default_model" in entry, f"{key} missing 'default_model'"
        assert "key_env" in entry, f"{key} missing 'key_env'"
        assert "description" in entry, f"{key} missing 'description'"
