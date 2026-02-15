import pytest
from src.prediction import Prediction, parse_prediction


def test_prediction_fields():
    p = Prediction(
        target_price=105000.0,
        timeframe_minutes=60,
        reasoning="Bullish",
        current_price=100000.0,
        timestamp="2026-02-14T10:00:00Z",
    )
    assert p.target_price == 105000.0
    assert p.timeframe_minutes == 60
    assert p.reasoning == "Bullish"
    assert p.current_price == 100000.0
    assert p.timestamp == "2026-02-14T10:00:00Z"


def test_parse_prediction_valid_json():
    raw = '{"target_price": 105000.0, "timeframe_minutes": 60, "reasoning": "Bullish momentum"}'
    result = parse_prediction(raw, current_price=100000.0)
    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
    assert result.timeframe_minutes == 60
    assert result.reasoning == "Bullish momentum"
    assert result.current_price == 100000.0


def test_parse_prediction_malformed_json():
    result = parse_prediction("not json at all", current_price=100000.0)
    assert result is None


def test_parse_prediction_missing_keys():
    raw = '{"target_price": 105000.0}'
    result = parse_prediction(raw, current_price=100000.0)
    assert result is None


def test_parse_prediction_api_wrapper():
    """Handles LLM responses that wrap JSON in markdown code blocks."""
    raw = '```json\n{"target_price": 105000.0, "timeframe_minutes": 60, "reasoning": "test"}\n```'
    result = parse_prediction(raw, current_price=100000.0)
    assert isinstance(result, Prediction)
    assert result.target_price == 105000.0
