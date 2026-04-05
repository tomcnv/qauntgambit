import asyncio

from quantgambit.execution.sdk_clients import OkxSdkClient, OrderResponse


class FakeAdaptor:
    async def place_order(self, **kwargs):
        return {"success": True, "avg_fill_price": "101.2", "fee_usd": "0.07"}


def test_sdk_client_maps_response():
    client = OkxSdkClient(FakeAdaptor())
    response = asyncio.run(client.place_order(symbol="BTC", side="buy", size=1, order_type="market"))

    assert isinstance(response, OrderResponse)
    assert response.success is True
    assert response.fill_price == 101.2
    assert response.fee_usd == 0.07

