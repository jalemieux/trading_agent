from dataclasses import dataclass, field
from typing import Optional
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class PriceUpdate:
    product_id: str
    price: float
    timestamp: str


@dataclass(frozen=True)
class OrderRequest:
    product_id: str
    side: str  # BUY or SELL
    order_type: str  # MARKET or LIMIT
    quote_size: Optional[float] = None  # USD amount (market buys)
    base_size: Optional[float] = None  # Asset amount (sells, limit orders)
    limit_price: Optional[float] = None
    order_id: str = field(default_factory=_new_id)


@dataclass(frozen=True)
class OrderFilled:
    order_id: str
    product_id: str
    side: str
    filled_price: float
    filled_qty: float
    fee: float
    coinbase_order_id: str


@dataclass(frozen=True)
class OrderFailed:
    order_id: str
    reason: str


@dataclass(frozen=True)
class RiskViolation:
    order_id: str
    reason: str


@dataclass(frozen=True)
class PositionChanged:
    position_id: str
    product_id: str
    side: str
    quantity: float
    entry_price: float
    status: str  # OPEN or CLOSED


@dataclass(frozen=True)
class KillSwitchActivated:
    reason: str
