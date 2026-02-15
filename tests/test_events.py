from src.events import (
    KillSwitchActivated,
    OrderFailed,
    OrderFilled,
    OrderRequest,
    PositionChanged,
    PriceUpdate,
    RiskViolation,
)


def test_price_update_creation():
    e = PriceUpdate(product_id="BTC-USD", price=50000.0, timestamp="2026-01-01T00:00:00Z")
    assert e.product_id == "BTC-USD"
    assert e.price == 50000.0


def test_order_request_market_buy():
    e = OrderRequest(
        product_id="BTC-USD",
        side="BUY",
        order_type="MARKET",
        quote_size=100.0,
    )
    assert e.side == "BUY"
    assert e.base_size is None


def test_order_request_limit_sell():
    e = OrderRequest(
        product_id="ETH-USD",
        side="SELL",
        order_type="LIMIT",
        base_size=1.5,
        limit_price=3000.0,
    )
    assert e.order_type == "LIMIT"
    assert e.limit_price == 3000.0


def test_order_filled():
    e = OrderFilled(
        order_id="abc-123",
        product_id="BTC-USD",
        side="BUY",
        filled_price=50000.0,
        filled_qty=0.002,
        fee=0.20,
        coinbase_order_id="cb-456",
    )
    assert e.filled_price == 50000.0


def test_order_failed():
    e = OrderFailed(order_id="abc-123", reason="insufficient funds")
    assert e.reason == "insufficient funds"


def test_risk_violation():
    e = RiskViolation(order_id="abc-123", reason="exceeds max order size")
    assert "max order size" in e.reason


def test_position_changed():
    e = PositionChanged(
        position_id="pos-1",
        product_id="BTC-USD",
        side="LONG",
        quantity=0.002,
        entry_price=50000.0,
        status="OPEN",
    )
    assert e.status == "OPEN"


def test_kill_switch_activated():
    e = KillSwitchActivated(reason="daily loss exceeded")
    assert e.reason == "daily loss exceeded"
