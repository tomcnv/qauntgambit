import asyncio

from quantgambit.execution.live_adapters import OkxAdaptorWrapper


class FakeOrderResult:
    def __init__(self):
        self.success = True
        self.avg_fill_price = 101.0
        self.price = 100.0
        self.raw_response = {"fee": "0.05"}


class FakeAdaptor:
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
        return FakeOrderResult()


def test_deeptrader_adaptor_wrapper_extracts_fill():
    wrapper = OkxAdaptorWrapper(FakeAdaptor())
    result = asyncio.run(wrapper.place_order("BTC", "buy", 1, "market"))
    assert result.success is True
    assert wrapper.last_fill.fill_price == 101.0
    assert wrapper.last_fill.fee_usd == 0.05
