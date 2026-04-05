import asyncio

from quantgambit.execution.sdk_clients import OkxSdkClient
from quantgambit.observability.telemetry import TelemetryContext


class FakeAdaptor:
    async def place_order(self, **kwargs):
        return {"success": True, "avg_fill_price": "101.2", "fee_usd": "0.07"}


class FakeTelemetry:
    def __init__(self):
        self.orders = []

    async def publish_order(self, ctx, symbol, payload):
        self.orders.append(payload)


def test_sdk_emits_telemetry_when_enabled():
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    client = OkxSdkClient(FakeAdaptor(), telemetry=telemetry, telemetry_context=ctx, emit_telemetry=True)

    asyncio.run(client.place_order(symbol="BTC", side="buy", size=1, order_type="market"))
    assert telemetry.orders
    assert telemetry.orders[0]["status"] == "filled"

