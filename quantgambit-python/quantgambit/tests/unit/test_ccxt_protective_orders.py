import asyncio

from quantgambit.execution.ccxt_clients import CcxtOrderClient


class FakeCcxtClient:
    def __init__(self):
        self.calls = []
        self.markets = {}

    async def create_order(self, symbol, type, side, amount, price=None, params=None):
        self.calls.append(
            {
                "symbol": symbol,
                "type": type,
                "side": side,
                "amount": amount,
                "price": price,
                "params": params or {},
            }
        )
        return {"success": True}

    async def privatePostTradeOrderAlgo(self, params):
        self.calls.append({"method": "okx_algo", "params": params})
        return {"success": True, "data": params}

    async def privatePostV5PositionTradingStop(self, params):
        self.calls.append({"method": "bybit_tpsl", "params": params})
        return {"success": True, "result": params}

    async def privatePostOrderOco(self, params):
        self.calls.append({"method": "binance_oco", "params": params})
        return {"success": True, "result": params}


def test_okx_protective_orders_use_stop_types():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("okx", client, symbol_format="okx")

    async def run_once():
        await wrapper.place_protective_orders(
            symbol="BTC-USDT-SWAP",
            side="buy",
            size=1.0,
            stop_loss=99.0,
            take_profit=101.0,
            client_order_id="cid-1",
        )

    asyncio.run(run_once())
    algo_call = client.calls[-1]
    assert algo_call["method"] == "okx_algo"
    params = algo_call["params"]
    assert params["instId"] == "BTC-USDT-SWAP"
    assert params["ordType"] == "oco"
    assert params["slTriggerPx"] == "99.0"
    assert params["tpTriggerPx"] == "101.0"
    assert params["tdMode"] == "isolated"
    assert params["clOrdId"] == "cid1oco"


def test_bybit_protective_orders_use_stop_types():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("bybit", client, symbol_format="bybit")

    async def run_once():
        await wrapper.place_protective_orders(
            symbol="BTC-USDT-SWAP",
            side="buy",
            size=2.0,
            stop_loss=90.0,
            take_profit=None,
            client_order_id="cid-2",
        )

    asyncio.run(run_once())
    # Bybit uses native SL/TP attached to the main order; no separate protective orders.
    assert client.calls == []


def test_bybit_native_oco_uses_market_tp_for_full_mode():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("bybit", client, symbol_format="bybit")

    async def run_once():
        await wrapper.place_native_oco(
            symbol="BTC-USDT-SWAP",
            side="sell",
            size=1.0,
            stop_loss=97.5,
            take_profit=95.0,
            client_order_id="cid-tpsl",
        )

    asyncio.run(run_once())
    tpsl_call = client.calls[-1]
    params = tpsl_call["params"]
    assert params["symbol"] == "BTCUSDT"
    assert params["tpslMode"] == "Full"
    assert params["stopLoss"] == "97.5"
    assert params["slOrderType"] == "Market"
    assert params["takeProfit"] == "95.0"
    assert params["tpOrderType"] == "Market"
    assert "tpLimitPrice" not in params


def test_binance_protective_orders_use_market_stop_types():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("binance", client, symbol_format="binance", market_type="perp", margin_mode="isolated")

    async def run_once():
        await wrapper.place_protective_orders(
            symbol="BTC-USDT-SWAP",
            side="sell",
            size=0.5,
            stop_loss=105.0,
            take_profit=95.0,
            client_order_id="cid-3",
        )

    asyncio.run(run_once())
    assert client.calls[0]["type"] == "STOP_MARKET"
    assert client.calls[0]["params"]["stopPrice"] == 105.0
    assert client.calls[0]["params"]["closePosition"] is True
    assert client.calls[1]["type"] == "TAKE_PROFIT_MARKET"
    assert client.calls[1]["params"]["stopPrice"] == 95.0
    assert client.calls[0]["symbol"] == "BTC/USDT"
    assert client.calls[0]["params"]["marginMode"] == "isolated"


def test_okx_native_oco_mapping():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("okx", client, symbol_format="okx", market_type="perp", margin_mode="isolated")

    async def run_once():
        await wrapper.place_native_oco(
            symbol="BTC-USDT-SWAP",
            side="buy",
            size=1.0,
            stop_loss=95.0,
            take_profit=110.0,
            client_order_id="cid-1",
        )

    asyncio.run(run_once())
    algo_call = client.calls[-1]
    assert algo_call["method"] == "okx_algo"
    params = algo_call["params"]
    assert params["instId"] == "BTC-USDT-SWAP"
    assert params["ordType"] == "oco"
    assert params["slTriggerPx"] == "95.0"
    assert params["tpTriggerPx"] == "110.0"
    assert params["tdMode"] == "isolated"


def test_okx_native_conditional_mapping():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("okx", client, symbol_format="okx", market_type="perp", margin_mode="cross")

    async def run_once():
        await wrapper.place_native_oco(
            symbol="ETH-USDT-SWAP",
            side="sell",
            size=2.0,
            stop_loss=1200.0,
            take_profit=None,
            client_order_id="cid-cond",
        )

    asyncio.run(run_once())
    algo_call = client.calls[-1]
    assert algo_call["method"] == "okx_algo"
    params = algo_call["params"]
    assert params["instId"] == "ETH-USDT-SWAP"
    assert params["ordType"] == "conditional"
    assert params["triggerPx"] == "1200.0"
    assert params["orderPx"] == "-1"
    assert params["tdMode"] == "cross"
    assert params["clOrdId"] == "cidcondsl"


def test_bybit_native_tpsl_mapping():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("bybit", client, symbol_format="bybit")

    async def run_once():
        await wrapper.place_native_oco(
            symbol="BTC-USDT-SWAP",
            side="sell",
            size=1.0,
            stop_loss=105.0,
            take_profit=95.0,
            client_order_id="cid-2",
        )

    asyncio.run(run_once())
    tpsl_call = client.calls[-1]
    assert tpsl_call["method"] == "bybit_tpsl"
    params = tpsl_call["params"]
    assert params["symbol"] == "BTCUSDT"
    assert params["stopLoss"] == "105.0"
    assert params["takeProfit"] == "95.0"


def test_bybit_native_tpsl_stop_only():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("bybit", client, symbol_format="bybit")

    async def run_once():
        await wrapper.place_native_oco(
            symbol="BTC-USDT-SWAP",
            side="sell",
            size=1.0,
            stop_loss=97.5,
            take_profit=None,
            client_order_id="cid-stop",
        )

    asyncio.run(run_once())
    tpsl_call = client.calls[-1]
    params = tpsl_call["params"]
    assert params["symbol"] == "BTCUSDT"
    assert params["tpslMode"] == "Full"
    assert params["stopLoss"] == "97.5"
    assert params["slOrderType"] == "Market"
    assert "takeProfit" not in params
    assert params["orderLinkId"] == "cid-stop:sl"


def test_binance_spot_oco_mapping():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("binance", client, symbol_format="binance_spot", market_type="spot")

    async def run_once():
        await wrapper.place_native_oco(
            symbol="BTC-USDT",
            side="sell",
            size=0.25,
            stop_loss=98.0,
            take_profit=105.0,
            client_order_id="cid-spot",
        )

    asyncio.run(run_once())
    oco_call = client.calls[-1]
    assert oco_call["method"] == "binance_oco"
    params = oco_call["params"]
    assert params["symbol"] == "BTCUSDT"
    assert params["price"] == "105.0"
    assert params["stopPrice"] == "98.0"
    assert params["stopLimitPrice"] == "98.0"
    assert params["listClientOrderId"] == "cid-spot:oco"


def test_binance_spot_symbol_normalization():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("binance", client, symbol_format="binance_spot", market_type="spot")

    async def run_once():
        await wrapper.place_order(
            symbol="BTC-USDT",
            side="buy",
            size=1.0,
            order_type="limit",
            price=100.0,
        )

    asyncio.run(run_once())
    assert client.calls[0]["symbol"] == "BTCUSDT"


def test_binance_spot_order_uses_spot_client_id():
    client = FakeCcxtClient()
    wrapper = CcxtOrderClient("binance", client, symbol_format="binance_spot", market_type="spot")

    async def run_once():
        await wrapper.place_order(
            symbol="ETH-USDT",
            side="sell",
            size=0.4,
            order_type="limit",
            price=2000.0,
            client_order_id="spot-123",
        )

    asyncio.run(run_once())
    assert client.calls[0]["params"]["newClientOrderId"] == "spot-123"


def test_fetch_spot_positions_prefers_free_balance():
    class SpotBalanceClient:
        async def fetch_balance(self):
            return {
                "free": {"ETH": 0.25, "USDT": 100.0},
                "total": {"ETH": 0.4, "USDT": 100.0},
            }

        async def fetch_ticker(self, symbol):
            assert symbol == "ETH/USDT"
            return {"last": 2000.0}

        async def fetch_my_trades(self, symbol, limit=50):
            return []

    wrapper = CcxtOrderClient("bybit", SpotBalanceClient(), symbol_format="bybit", market_type="spot")

    async def run_once():
        return await wrapper.fetch_positions(["ETH-USDT"])

    positions = asyncio.run(run_once())
    assert positions is not None
    assert len(positions) == 1
    assert positions[0]["symbol"] == "ETH/USDT"
    assert positions[0]["size"] == 0.25


def test_spot_sell_caps_order_to_free_balance():
    class SpotSellClient(FakeCcxtClient):
        def __init__(self):
            super().__init__()
            self.markets = {"BTC/USDT": {"precision": {"amount": 6}}}

        async def fetch_balance(self):
            return {
                "free": {"BTC": 0.44295089},
                "total": {"BTC": 0.44295089},
            }

        def amount_to_precision(self, symbol, amount):
            assert symbol == "BTC/USDT"
            return f"{amount:.6f}"

    client = SpotSellClient()
    wrapper = CcxtOrderClient("bybit", client, symbol_format="bybit", market_type="spot")

    async def run_once():
        await wrapper.place_order(
            symbol="BTC-USDT",
            side="sell",
            size=0.5,
            order_type="market",
        )

    asyncio.run(run_once())
    assert client.calls[0]["amount"] == 0.44295


def test_spot_sell_raises_when_no_free_balance():
    class SpotEmptyBalanceClient(FakeCcxtClient):
        async def fetch_balance(self):
            return {
                "free": {"BTC": 0.0},
                "total": {"BTC": 0.0},
            }

    client = SpotEmptyBalanceClient()
    wrapper = CcxtOrderClient("bybit", client, symbol_format="bybit", market_type="spot")

    async def run_once():
        await wrapper.place_order(
            symbol="BTC-USDT",
            side="sell",
            size=0.1,
            order_type="market",
        )

    try:
        asyncio.run(run_once())
    except ValueError as exc:
        assert "spot_exit_no_free_balance:BTC" in str(exc)
    else:
        raise AssertionError("expected ValueError when no free balance is available")
