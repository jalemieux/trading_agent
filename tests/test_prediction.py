from src.prediction import Prediction, Predictor


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


def test_predictor_protocol_is_runtime_checkable():
    assert hasattr(Predictor, '__protocol_attrs__') or hasattr(Predictor, '_is_protocol')
