import asyncio

from quantgambit.execution.live_adapters import OkxLiveAdapter
from quantgambit.execution.sdk_clients import OkxSdkClient
from quantgambit.execution.adapters import OkxExchangeClient
from quantgambit.market.reference_prices import ReferencePriceCache


class FakeAdaptor:
    async def place_order(self, **kwargs):
        return {"success": True, "avg_fill_price": "101.0", "fee_usd": "0.1"}


def test_live_adapter_and_reference_price():
    sdk_client = OkxSdkClient(FakeAdaptor())
    live_adapter = OkxLiveAdapter(sdk_client)

    cache = ReferencePriceCache()
    cache.update("BTC", 100.0)

    client = OkxExchangeClient(live_adapter, reference_prices=cache)
    result = asyncio.run(client.close_position("BTC", "long", 1.0))

    assert result.status == "filled"
    assert result.fill_price == 101.0
    assert result.reference_price == 100.0
