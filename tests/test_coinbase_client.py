from unittest.mock import MagicMock, patch
from dataclasses import dataclass

import pytest

from src.coinbase_client import CoinbaseClient


@pytest.fixture
def mock_rest_client():
    with patch("src.coinbase_client.RESTClient") as MockREST:
        mock = MockREST.return_value
        yield mock


@pytest.fixture
def client(mock_rest_client):
    return CoinbaseClient(api_key="test-key", api_secret="test-secret")


def test_market_buy(client, mock_rest_client):
    mock_rest_client.market_order_buy.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-order-1"},
    }
    result = client.market_buy(
        client_order_id="my-order-1",
        product_id="BTC-USD",
        quote_size="100",
    )
    assert result["success"] is True
    mock_rest_client.market_order_buy.assert_called_once_with(
        client_order_id="my-order-1",
        product_id="BTC-USD",
        quote_size="100",
    )


def test_market_sell(client, mock_rest_client):
    mock_rest_client.market_order_sell.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-order-2"},
    }
    result = client.market_sell(
        client_order_id="my-order-2",
        product_id="BTC-USD",
        base_size="0.002",
    )
    assert result["success"] is True
    mock_rest_client.market_order_sell.assert_called_once_with(
        client_order_id="my-order-2",
        product_id="BTC-USD",
        base_size="0.002",
    )


def test_limit_buy(client, mock_rest_client):
    mock_rest_client.limit_order_gtc.return_value = {
        "success": True,
        "success_response": {"order_id": "cb-order-3"},
    }
    result = client.limit_order(
        client_order_id="my-order-3",
        product_id="BTC-USD",
        side="BUY",
        base_size="0.002",
        limit_price="48000",
    )
    assert result["success"] is True


def test_cancel_orders(client, mock_rest_client):
    mock_rest_client.cancel_orders.return_value = {"results": [{"success": True}]}
    result = client.cancel_orders(["cb-order-1"])
    mock_rest_client.cancel_orders.assert_called_once_with(order_ids=["cb-order-1"])


def test_get_order(client, mock_rest_client):
    mock_rest_client.get_order.return_value = {
        "order": {"order_id": "cb-order-1", "status": "FILLED"}
    }
    result = client.get_order("cb-order-1")
    assert result["order"]["status"] == "FILLED"


def test_get_accounts(client, mock_rest_client):
    mock_rest_client.get_accounts.return_value = {"accounts": []}
    result = client.get_accounts()
    assert result["accounts"] == []


def test_get_product(client, mock_rest_client):
    mock_rest_client.get_product.return_value = {
        "product_id": "BTC-USD",
        "price": "50000.00",
    }
    result = client.get_product("BTC-USD")
    assert result["price"] == "50000.00"
