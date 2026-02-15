import logging

from coinbase.rest import RESTClient

logger = logging.getLogger(__name__)


class CoinbaseClient:
    def __init__(self, api_key: str, api_secret: str) -> None:
        self._client = RESTClient(api_key=api_key, api_secret=api_secret)

    def market_buy(self, client_order_id: str, product_id: str, quote_size: str) -> dict:
        return self._client.market_order_buy(
            client_order_id=client_order_id,
            product_id=product_id,
            quote_size=quote_size,
        )

    def market_sell(self, client_order_id: str, product_id: str, base_size: str) -> dict:
        return self._client.market_order_sell(
            client_order_id=client_order_id,
            product_id=product_id,
            base_size=base_size,
        )

    def limit_order(
        self,
        client_order_id: str,
        product_id: str,
        side: str,
        base_size: str,
        limit_price: str,
    ) -> dict:
        return self._client.limit_order_gtc(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            base_size=base_size,
            limit_price=limit_price,
        )

    def cancel_orders(self, order_ids: list[str]) -> dict:
        return self._client.cancel_orders(order_ids=order_ids)

    def get_order(self, order_id: str) -> dict:
        return self._client.get_order(order_id)

    def get_accounts(self) -> dict:
        return self._client.get_accounts()

    def get_product(self, product_id: str) -> dict:
        return self._client.get_product(product_id)
