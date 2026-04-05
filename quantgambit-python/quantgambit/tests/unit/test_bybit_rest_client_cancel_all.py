import asyncio

from quantgambit.core.clock import WallClock
from quantgambit.io.adapters.bybit.rest_client import BybitRESTClient, BybitRESTConfig


def _build_client() -> BybitRESTClient:
    return BybitRESTClient(
        WallClock(),
        BybitRESTConfig(api_key="k", api_secret="s", base_url="https://api-demo.bybit.com", category="spot"),
    )


def test_cancel_all_orders_falls_back_to_individual_cancels_for_survivors(monkeypatch):
    client = _build_client()
    calls = {"request": 0, "get_open_orders": 0, "cancel_order": []}
    survivor = {
        "symbol": "BTCUSDT",
        "orderId": "123",
        "orderLinkId": "client-123:tp",
    }

    async def fake_request(method, endpoint, params=None, sign=True):
        calls["request"] += 1
        assert endpoint == "/v5/order/cancel-all"
        return {"list": []}

    async def fake_get_open_orders(symbol=None, limit=50):
        calls["get_open_orders"] += 1
        if calls["get_open_orders"] == 1:
            return [survivor]
        return []

    async def fake_cancel_order(symbol, order_id=None, client_order_id=None):
        calls["cancel_order"].append((symbol, order_id, client_order_id))
        return {"orderId": order_id, "orderLinkId": client_order_id}

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "get_open_orders", fake_get_open_orders)
    monkeypatch.setattr(client, "cancel_order", fake_cancel_order)

    result = asyncio.run(client.cancel_all_orders("BTCUSDT"))

    assert calls["request"] == 1
    assert calls["get_open_orders"] == 2
    assert calls["cancel_order"] == [("BTCUSDT", "123", "client-123:tp")]
    assert result["verified"] is True
    assert result["remaining"] == []
    assert result["list"] == [{"orderId": "123", "orderLinkId": "client-123:tp"}]


def test_cancel_all_orders_returns_bulk_result_when_no_survivors(monkeypatch):
    client = _build_client()

    async def fake_request(method, endpoint, params=None, sign=True):
        return {"list": [{"orderId": "bulk-1"}]}

    async def fake_get_open_orders(symbol=None, limit=50):
        return []

    async def fake_cancel_order(symbol, order_id=None, client_order_id=None):
        raise AssertionError("cancel_order should not be called when there are no survivors")

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "get_open_orders", fake_get_open_orders)
    monkeypatch.setattr(client, "cancel_order", fake_cancel_order)

    result = asyncio.run(client.cancel_all_orders("ETHUSDT"))

    assert result["verified"] is True
    assert result["remaining"] == []
    assert result["list"] == [{"orderId": "bulk-1"}]
