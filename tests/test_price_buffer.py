from src.events import PriceUpdate
from src.price_buffer import PriceBuffer


def test_add_and_snapshot():
    buf = PriceBuffer(max_size=3)
    buf.add(PriceUpdate(product_id="BTC-USD", price=100.0, timestamp="t1"))
    buf.add(PriceUpdate(product_id="BTC-USD", price=200.0, timestamp="t2"))

    snap = buf.snapshot("BTC-USD")
    assert len(snap) == 2
    assert snap[0].price == 100.0
    assert snap[1].price == 200.0


def test_snapshot_empty():
    buf = PriceBuffer()
    assert buf.snapshot("BTC-USD") == []


def test_max_size_eviction():
    buf = PriceBuffer(max_size=2)
    buf.add(PriceUpdate(product_id="BTC-USD", price=1.0, timestamp="t1"))
    buf.add(PriceUpdate(product_id="BTC-USD", price=2.0, timestamp="t2"))
    buf.add(PriceUpdate(product_id="BTC-USD", price=3.0, timestamp="t3"))

    snap = buf.snapshot("BTC-USD")
    assert len(snap) == 2
    assert snap[0].price == 2.0
    assert snap[1].price == 3.0


def test_separate_product_ids():
    buf = PriceBuffer()
    buf.add(PriceUpdate(product_id="BTC-USD", price=100.0, timestamp="t1"))
    buf.add(PriceUpdate(product_id="ETH-USD", price=3.0, timestamp="t2"))

    assert len(buf.snapshot("BTC-USD")) == 1
    assert len(buf.snapshot("ETH-USD")) == 1


def test_latest():
    buf = PriceBuffer()
    assert buf.latest("BTC-USD") is None

    buf.add(PriceUpdate(product_id="BTC-USD", price=100.0, timestamp="t1"))
    buf.add(PriceUpdate(product_id="BTC-USD", price=200.0, timestamp="t2"))

    latest = buf.latest("BTC-USD")
    assert latest is not None
    assert latest.price == 200.0
