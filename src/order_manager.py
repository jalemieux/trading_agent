import asyncio
import logging
from datetime import datetime, timezone

from src.coinbase_client import CoinbaseClient
from src.db import Database
from src.event_bus import EventBus
from src.events import OrderFailed, OrderFilled, OrderRequest
from src.risk_manager import RiskManager

logger = logging.getLogger(__name__)


def _get(obj, key, default=None):
    """Get a value from a dict or object attribute."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class OrderManager:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        risk_manager: RiskManager,
        coinbase: CoinbaseClient,
    ) -> None:
        self._db = db
        self._bus = bus
        self._risk = risk_manager
        self._coinbase = coinbase

    def register(self, bus: EventBus) -> None:
        bus.subscribe(OrderRequest, self._handle_order_request)

    async def _handle_order_request(self, order: OrderRequest) -> None:
        # Risk check
        approved = await self._risk.check(order)
        if not approved:
            return

        now = datetime.now(timezone.utc).isoformat()

        # Place order
        try:
            if order.order_type == "MARKET":
                result = self._place_market_order(order)
            else:
                result = self._place_limit_order(order)
        except Exception as e:
            logger.exception("Failed to place order")
            await self._bus.publish(OrderFailed(order_id=order.order_id, reason=str(e)))
            return

        if not _get(result, "success"):
            error = _get(result, "error_response") or {}
            reason = str(_get(error, "error", "Unknown error"))
            logger.error(
                "Order FAILED: %s %s %s — %s (full error: %s)",
                order.side, order.order_type, order.product_id, reason, error,
            )
            await self._persist_order(order, now, status="FAILED")
            await self._bus.publish(OrderFailed(order_id=order.order_id, reason=reason))
            return

        success_resp = _get(result, "success_response") or {}
        cb_order_id = _get(success_resp, "order_id", "")

        # Poll for fill details (market orders may not settle immediately)
        filled_price = 0.0
        filled_qty = 0.0
        fee = 0.0
        for attempt in range(5):
            order_details = self._coinbase.get_order(cb_order_id)
            details = _get(order_details, "order")
            filled_qty = float(_get(details, "filled_size", 0) if details else 0)
            if filled_qty > 0:
                filled_price = float(_get(details, "average_filled_price", 0) if details else 0)
                fee = float(_get(details, "total_fees", 0) if details else 0)
                break
            if attempt < 4:
                logger.info("Order %s not yet filled, retrying in 1s... (attempt %d/5)", cb_order_id, attempt + 1)
                await asyncio.sleep(1.0)

        # Persist
        await self._persist_order(
            order, now,
            coinbase_id=cb_order_id,
            filled_price=filled_price,
            filled_qty=filled_qty,
            fee=fee,
            status="FILLED",
        )

        await self._bus.publish(
            OrderFilled(
                order_id=order.order_id,
                product_id=order.product_id,
                side=order.side,
                filled_price=filled_price,
                filled_qty=filled_qty,
                fee=fee,
                coinbase_order_id=cb_order_id,
            )
        )

    def _place_market_order(self, order: OrderRequest) -> dict:
        if order.side == "BUY":
            return self._coinbase.market_buy(
                client_order_id=order.order_id,
                product_id=order.product_id,
                quote_size=str(order.quote_size),
            )
        else:
            return self._coinbase.market_sell(
                client_order_id=order.order_id,
                product_id=order.product_id,
                base_size=str(order.base_size),
            )

    def _place_limit_order(self, order: OrderRequest) -> dict:
        return self._coinbase.limit_order(
            client_order_id=order.order_id,
            product_id=order.product_id,
            side=order.side,
            base_size=str(order.base_size),
            limit_price=str(order.limit_price),
        )

    async def _persist_order(
        self,
        order: OrderRequest,
        created_at: str,
        coinbase_id: str | None = None,
        filled_price: float | None = None,
        filled_qty: float | None = None,
        fee: float | None = None,
        status: str = "PENDING",
    ) -> None:
        await self._db.execute(
            """INSERT INTO orders (id, product_id, side, type, price, quantity, status,
               coinbase_id, filled_price, filled_qty, fee, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order.order_id,
                order.product_id,
                order.side,
                order.order_type,
                order.limit_price,
                order.quote_size or order.base_size,
                status,
                coinbase_id,
                filled_price,
                filled_qty,
                fee,
                created_at,
            ),
        )
