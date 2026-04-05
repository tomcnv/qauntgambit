import asyncio

from quantgambit.execution.live_adapters import OkxLiveAdapter, BybitLiveAdapter, BinanceLiveAdapter


class FakeClient:
    def __init__(self, response):
        self.response = response

    async def place_order(self, **kwargs):
        return self.response


def test_okx_fill_parser():
    response = {
        "code": "0",
        "data": [{"fillPx": "101.5", "fee": "0.12"}],
    }
    adapter = OkxLiveAdapter(FakeClient(response))
    result = asyncio.run(adapter.place_order(symbol="BTC", side="buy", size=1, order_type="market"))
    assert result.success is True
    assert adapter.last_fill.fill_price == 101.5


def test_bybit_fill_parser():
    response = {
        "retCode": 0,
        "result": {"list": [{"avgPrice": "102.0", "cumExecFee": "0.2"}]},
    }
    adapter = BybitLiveAdapter(FakeClient(response))
    result = asyncio.run(adapter.place_order(symbol="BTC", side="buy", size=1, order_type="market"))
    assert result.success is True
    assert adapter.last_fill.fill_price == 102.0


def test_binance_fill_parser():
    response = {
        "status": "FILLED",
        "fills": [{"price": "103.0", "commission": "0.3"}],
    }
    adapter = BinanceLiveAdapter(FakeClient(response))
    result = asyncio.run(adapter.place_order(symbol="BTC", side="buy", size=1, order_type="market"))
    assert result.success is True
    assert adapter.last_fill.fill_price == 103.0
