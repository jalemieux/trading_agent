from src.llm_client import AnthropicLLMClient, GroqLLMClient, OpenAICompatibleLLMClient
from src.strategies.news import NewsPredictionStrategy
from src.strategies.price_only import PriceOnlyStrategy

STRATEGIES = {
    "price_only": {
        "class": PriceOnlyStrategy,
        "description": "Technical analysis from price history only",
    },
    "news": {
        "class": NewsPredictionStrategy,
        "description": "Price history + real-time news sentiment via Grok API",
    },
}

LLM_PROVIDERS = {
    "anthropic": {
        "class": AnthropicLLMClient,
        "default_model": "claude-opus-4-6",
        "key_env": "ANTHROPIC_API_KEY",
        "description": "Anthropic Claude API",
    },
    "groq": {
        "class": GroqLLMClient,
        "default_model": "openai/gpt-oss-120b",
        "key_env": "GROQ_API_KEY",
        "description": "Groq API (fast inference)",
    },
    "openrouter": {
        "class": OpenAICompatibleLLMClient,
        "default_model": "moonshotai/kimi-k2",
        "key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "description": "OpenRouter API (Kimi, Llama, etc.)",
    },
}
