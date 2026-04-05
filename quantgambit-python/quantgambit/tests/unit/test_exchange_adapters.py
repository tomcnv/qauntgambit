import asyncio

from quantgambit.execution.adapters import OkxExchangeClient
from quantgambit.execution.live_adapters import OkxLiveAdapter


class FakeFill:
    def __init__(self, fill_price=101.0, fee_usd=0.02):
        self.fill_price = fill_price
        self.fee_usd = fee_usd


class FakeExchangeAdapter:
    def __init__(self):
        self.calls = []
        self.last_fill = FakeFill()

    async def place_order(
        self,
        symbol,
        side,
        size,
        order_type,
        price=None,
        reduce_only=False,
        stop_loss=None,
        take_profit=None,
        client_order_id=None,
        post_only=False,
        time_in_force=None,
    ):
        self.calls.append({
            "symbol": symbol,
            "side": side,
            "size": size,
            "order_type": order_type,
            "price": price,
            "reduce_only": reduce_only,
        })
        return {"success": True, "status": "filled", "order_id": "fake-1"}


def test_close_position_long_maps_to_sell():
    adapter = FakeExchangeAdapter()
    client = OkxExchangeClient(adapter)

    result = asyncio.run(client.close_position("BTC", "long", 1.0))
    assert result.status == "filled"
    assert result.fill_price == 101.0
    assert result.fee_usd == 0.02
    assert adapter.calls[0]["side"] == "sell"
    assert adapter.calls[0]["reduce_only"] is True


def test_fetch_order_status_normalizes_ccxt_response():
    class FakeCcxtClient:
        async def fetch_order_status(self, order_id: str, symbol: str):
            return {
                "id": order_id,
                "status": "closed",
                "average": "100.5",
                "fee": {"cost": "0.1"},
            }

    adapter = OkxLiveAdapter(FakeCcxtClient())
    client = OkxExchangeClient(adapter)
    status = asyncio.run(client.fetch_order_status("order-1", "BTC-USDT-SWAP"))
    assert status.status == "filled"
    assert status.order_id == "order-1"
    assert status.fill_price == 100.5
    assert status.fee_usd == 0.1


def test_open_position_preserves_rejection_reason():
    class RejectingAdapter:
        async def place_order(
            self,
            symbol,
            side,
            size,
            order_type,
            price=None,
            reduce_only=False,
            stop_loss=None,
            take_profit=None,
            client_order_id=None,
            post_only=False,
            time_in_force=None,
        ):
            return {
                "success": False,
                "status": "rejected",
                "reason": "insufficient_margin",
                "order_id": None,
            }

    client = OkxExchangeClient(RejectingAdapter())
    status = asyncio.run(client.open_position("BTC", "buy", 1.0))
    assert status.status == "rejected"
    assert status.reason == "insufficient_margin"
