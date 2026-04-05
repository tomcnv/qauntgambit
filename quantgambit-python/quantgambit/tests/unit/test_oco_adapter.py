import asyncio

from quantgambit.execution.oco_adapters import OkxOcoLiveAdapter


class FakeClient:
    def __init__(self):
        self.calls = []

    async def place_protective_orders(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True}

    async def place_order(self, **kwargs):
        self.calls.append({"fallback": True, **kwargs})
        return {"success": True}


def test_oco_adapter_delegates_to_client():
    client = FakeClient()
    adapter = OkxOcoLiveAdapter(client)

    async def run_once():
        await adapter.place_protective_orders(
            symbol="BTC-USDT-SWAP",
            side="buy",
            size=1.0,
            stop_loss=95.0,
            take_profit=110.0,
            client_order_id="cid-1",
        )

    asyncio.run(run_once())
    assert client.calls
    assert client.calls[0]["stop_loss"] == 95.0


def test_oco_adapter_tags_native_protective_orders():
    client = FakeClient()
    adapter = OkxOcoLiveAdapter(client)

    async def run_once():
        await adapter.place_protective_orders(
            symbol="BTC-USDT-SWAP",
            side="buy",
            size=1.0,
            stop_loss=90.0,
            take_profit=105.0,
            client_order_id="cid-2",
        )

    asyncio.run(run_once())
    assert client.calls
    assert client.calls[0]["client_order_id"] == "cid-2:tpsl"
