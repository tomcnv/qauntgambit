import asyncio
import json
from pathlib import Path

from quantgambit.execution.order_updates_ws import (
    OkxOrderUpdateProvider,
    OkxWsCredentials,
    _parse_okx_order_update,
    _parse_bybit_order_update,
    _parse_binance_order_update,
    _parse_binance_spot_order_update,
)
from quantgambit.ingest.schemas import validate_order_update
from quantgambit.observability.telemetry import TelemetryContext


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []
        self.health = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append((ctx, payload))

    async def publish_health_snapshot(self, ctx, payload):
        self.health.append((ctx, payload))


def _assert_update_schema_valid(update):
    assert update is not None
    payload = update.to_payload()
    validate_order_update(payload)
    return payload


def _load_fixture(name: str) -> dict:
    path = Path(__file__).resolve().parent.parent / "fixtures" / "order_updates" / name
    return json.loads(path.read_text())


def test_parse_okx_order_update():
    message = {
        "arg": {"channel": "orders"},
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "ordId": "123",
                "clOrdId": "c1",
                "state": "filled",
                "side": "buy",
                "accFillSz": "1",
                "sz": "1",
                "avgPx": "25000",
                "fee": "-0.1",
                "ts": "1700000000000",
            }
        ],
    }
    update = _parse_okx_order_update(message)
    assert update is not None
    assert update.symbol == "BTC-USDT-SWAP"
    assert update.status == "filled"
    assert update.order_id == "123"
    assert update.filled_size == 1.0
    assert update.remaining_size == 0.0


def test_parse_okx_order_update_fixture_schema_valid():
    message = _load_fixture("okx_live_market_filled.json")
    update = _parse_okx_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "filled"


def test_parse_okx_order_update_stop_loss_fixture():
    message = _load_fixture("okx_order_stop_loss.json")
    update = _parse_okx_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["close_reason"] == "stop_loss_hit"
    assert payload["position_effect"] == "close"


def test_parse_okx_order_update_fields_complete():
    message = _load_fixture("okx_live_market_filled.json")
    update = _parse_okx_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["order_id"] == "3171835436819177472"
    assert payload["client_order_id"] == "qg9bcd96daae84478e91"
    assert payload["status"] == "filled"
    assert payload["filled_size"] == 0.01
    assert payload["remaining_size"] == 0.0
    assert payload["fill_price"] == 88980.6
    assert payload["fee_usd"] == -0.00444903


def test_parse_okx_order_partial_fixture_schema_valid():
    message = _load_fixture("okx_order_partial.json")
    update = _parse_okx_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "partially_filled"
    assert payload["filled_size"] == 1.0
    assert payload["remaining_size"] == 1.0


def test_parse_okx_order_canceled_fixture_schema_valid():
    message = _load_fixture("okx_live_limit_canceled.json")
    update = _parse_okx_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "canceled"


def test_parse_okx_order_update_tpsl_fixture():
    message = _load_fixture("okx_live_tpsl_filled.json")
    update = _parse_okx_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["close_reason"] == "protective_tpsl"
    assert payload["position_effect"] == "close"


def test_parse_okx_order_update_sl_trigger_px():
    message = {
        "arg": {"channel": "orders"},
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "ordId": "125",
                "state": "filled",
                "side": "sell",
                "accFillSz": "1",
                "sz": "1",
                "slTriggerPx": "29500",
                "uTime": "1700000000999",
            }
        ],
    }
    update = _parse_okx_order_update(message)
    assert update is not None
    assert update.close_reason == "stop_loss_hit"


def test_parse_okx_close_reason_from_order_type():
    message = {
        "arg": {"channel": "orders"},
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "ordId": "124",
                "state": "filled",
                "side": "sell",
                "accFillSz": "1",
                "sz": "1",
                "ordType": "stop",
                "reduceOnly": "true",
                "ts": "1700000000000",
            }
        ],
    }
    update = _parse_okx_order_update(message)
    assert update is not None
    assert update.close_reason == "stop_loss_hit"
    assert update.position_effect == "close"


def test_parse_bybit_order_update():
    message = {
        "topic": "order",
        "data": [
            {
                "symbol": "BTCUSDT",
                "orderId": "456",
                "orderLinkId": "c2",
                "orderStatus": "Filled",
                "side": "Buy",
                "qty": "2",
                "cumExecQty": "1",
                "avgPrice": "20000",
                "cumExecFee": "0.2",
                "updatedTime": 1700000000000,
            }
        ],
    }
    update = _parse_bybit_order_update(message)
    assert update is not None
    assert update.symbol == "BTCUSDT"
    assert update.status == "filled"
    assert update.order_id == "456"
    assert update.filled_size == 1.0
    assert update.remaining_size == 1.0


def test_parse_bybit_order_update_fixture_schema_valid():
    message = _load_fixture("bybit_order_filled.json")
    update = _parse_bybit_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["close_reason"] == "stop_loss_hit"
    assert payload["position_effect"] == "close"


def test_parse_bybit_order_update_take_profit_fixture():
    message = _load_fixture("bybit_order_take_profit.json")
    update = _parse_bybit_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["close_reason"] == "take_profit_hit"
    assert payload["position_effect"] == "close"


def test_parse_bybit_order_update_fields_complete():
    message = _load_fixture("bybit_order_filled.json")
    update = _parse_bybit_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["order_id"] == "bybit-123"
    assert payload["client_order_id"] == "cid-bybit-1"
    assert payload["status"] == "filled"
    assert payload["filled_size"] == 2.0
    assert payload["remaining_size"] == 0.0
    assert payload["fill_price"] == 28000.0
    assert payload["fee_usd"] == 0.2
    assert payload["close_reason"] == "stop_loss_hit"
    assert payload["position_effect"] == "close"


def test_parse_bybit_order_partial_fixture_schema_valid():
    message = _load_fixture("bybit_order_partial.json")
    update = _parse_bybit_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "partially_filled"
    assert payload["filled_size"] == 1.0
    assert payload["remaining_size"] == 1.0


def test_parse_bybit_order_canceled_fixture_schema_valid():
    message = _load_fixture("bybit_order_canceled.json")
    update = _parse_bybit_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "canceled"


def test_parse_binance_order_update_fixture_schema_valid():
    message = _load_fixture("binance_order_filled.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "filled"
    assert payload["filled_size"] == 0.002
    assert payload["remaining_size"] == 0.0
    assert payload["fill_price"] == 87465.4
    assert payload["fee_usd"] == 0.06997232
    assert payload.get("close_reason") is None


def test_parse_bybit_close_reason_from_stop_order_type():
    message = {
        "topic": "order",
        "data": [
            {
                "symbol": "BTCUSDT",
                "orderId": "457",
                "orderStatus": "Filled",
                "side": "Sell",
                "qty": "1",
                "stopOrderType": "TakeProfit",
                "reduceOnly": True,
                "updatedTime": 1700000000000,
            }
        ],
    }
    update = _parse_bybit_order_update(message)
    assert update is not None
    assert update.close_reason == "take_profit_hit"
    assert update.position_effect == "close"


def test_parse_binance_order_update():
    message = {
        "e": "ORDER_TRADE_UPDATE",
        "E": 1700000000000,
        "o": {
            "s": "BTCUSDT",
            "S": "BUY",
            "X": "FILLED",
            "i": 789,
            "c": "c3",
            "l": "1",
            "q": "1",
            "z": "1",
            "ap": "30000",
            "n": "0.3",
        },
    }
    update = _parse_binance_order_update(message)
    assert update is not None
    assert update.symbol == "BTCUSDT"
    assert update.status == "filled"
    assert update.order_id == "789"
    assert update.filled_size == 1.0
    assert update.remaining_size == 0.0


def test_parse_binance_order_update_fixture_schema_valid():
    message = _load_fixture("binance_order_filled.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "filled"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["filled_size"] == 0.002
    assert payload["fill_price"] == 87465.4


def test_parse_binance_order_cancelled_fixture_schema_valid():
    message = _load_fixture("binance_order_canceled.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "canceled"
    assert payload["remaining_size"] == 0.004
    assert payload["filled_size"] == 0.0
    assert payload.get("close_reason") is None


def test_parse_binance_order_expired_fixture_schema_valid():
    message = _load_fixture("binance_order_expired.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "expired"
    assert payload["filled_size"] == 0.0
    assert payload["remaining_size"] == 0.05


def test_parse_binance_reduce_only_fill_fixture_schema_valid():
    message = _load_fixture("binance_order_reduce_only_fill.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "filled"
    assert payload["filled_size"] == 0.002
    # Binance flags reduce-only as "R": true in raw; schema keeps reduce_only optional
    assert payload.get("reduce_only") in (None, True)
    assert payload.get("close_reason") in (None, "position_reduce", "position_close")

def test_parse_binance_order_update_live_fixture_schema_valid():
    message = _load_fixture("binance_order_trade_update_live.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["symbol"] == "BTCUSDT"
    assert payload["status"] == "filled"
    assert payload["fill_price"] == 87302.3


def test_parse_binance_stop_market_close_fixture():
    message = _load_fixture("binance_order_stop_market_new.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] in ("pending", "filled")
    assert payload["close_reason"] in ("stop_loss_hit", "position_close")
    assert payload["position_effect"] == "close"


def test_parse_binance_take_profit_market_fixture():
    message = _load_fixture("binance_order_take_profit_market_new.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] in ("pending", "filled")
    assert payload["close_reason"] == "take_profit_hit"
    assert payload["position_effect"] == "close"
    if payload["status"] == "filled":
        assert payload["fee_usd"] == 0.02


def test_parse_binance_order_update_reduce_only_fixture_schema_valid():
    message = _load_fixture("binance_order_trade_update_reduce_only.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["symbol"] == "BTCUSDT"
    assert payload["status"] == "filled"
    assert payload["close_reason"] == "position_close"
    assert payload["position_effect"] == "close"


def test_parse_binance_order_update_fields_complete():
    message = _load_fixture("binance_order_trade_update_live.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["order_id"] == "11253211072"
    assert payload["client_order_id"] == "JPyTNWLwJUjA1558tAyZEG"
    assert payload["status"] == "filled"
    assert payload["filled_size"] == 0.002
    assert payload["remaining_size"] == 0.0
    assert payload["fill_price"] == 87302.3
    assert payload["fee_usd"] == 0.06984184
    assert payload.get("close_reason") is None
    assert payload.get("position_effect") is None


def test_parse_binance_order_update_close_position_fixture():
    message = _load_fixture("binance_order_close_position.json")
    update = _parse_binance_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["close_reason"] == "position_close"
    assert payload["position_effect"] == "close"


def test_parse_binance_close_reason_from_order_type():
    message = {
        "e": "ORDER_TRADE_UPDATE",
        "E": 1700000000000,
        "o": {
            "s": "BTCUSDT",
            "S": "SELL",
            "X": "FILLED",
            "i": 790,
            "c": "c4",
            "l": "1",
            "q": "1",
            "z": "1",
            "o": "TAKE_PROFIT_MARKET",
            "R": True,
        },
    }
    update = _parse_binance_order_update(message)
    assert update is not None
    assert update.close_reason == "take_profit_hit"
    assert update.position_effect == "close"


def test_order_updates_okx_schema_valid():
    message = _load_fixture("okx_live_market_filled.json")
    payload = _assert_update_schema_valid(_parse_okx_order_update(message))
    assert payload["symbol"] == "BTC-USDT-SWAP"
    assert payload["status"] == "filled"


def test_order_updates_okx_reduce_only_close_reason():
    message = {
        "arg": {"channel": "orders"},
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "ordId": "556",
                "state": "filled",
                "side": "sell",
                "accFillSz": "1",
                "sz": "1",
                "reduceOnly": True,
                "uTime": "1700000000001",
            }
        ],
    }
    update = _parse_okx_order_update(message)
    assert update is not None
    assert update.close_reason == "position_close"
    assert update.position_effect == "close"


def test_order_updates_okx_reduce_only_live_fixtures():
    message = _load_fixture("okx_live_reduce_only_filled.json")
    update = _parse_okx_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["status"] == "filled"
    assert payload["close_reason"] == "position_close"
    assert payload["position_effect"] == "close"


def test_order_updates_bybit_schema_valid():
    message = {
        "topic": "order",
        "data": [
            {
                "symbol": "ETHUSDT",
                "orderId": "666",
                "orderLinkId": "cid-6:tp",
                "orderStatus": "Filled",
                "side": "Sell",
                "qty": "3",
                "cumExecQty": "3",
                "avgPrice": "2000",
                "cumExecFee": "0.3",
                "updatedTime": 1700000000000,
                "orderType": "Market",
                "stopOrderType": "TakeProfit",
                "reduceOnly": True,
            }
        ],
    }
    payload = _assert_update_schema_valid(_parse_bybit_order_update(message))
    assert payload["symbol"] == "ETHUSDT"
    assert payload["status"] == "filled"


def test_order_updates_bybit_reduce_only_close_reason():
    message = {
        "topic": "order",
        "data": [
            {
                "symbol": "ETHUSDT",
                "orderId": "667",
                "orderStatus": "Filled",
                "side": "Sell",
                "qty": "1",
                "reduceOnly": True,
                "updatedTime": 1700000000001,
            }
        ],
    }
    update = _parse_bybit_order_update(message)
    assert update is not None
    assert update.close_reason == "position_close"
    assert update.position_effect == "close"


def test_order_updates_binance_schema_valid():
    message = {
        "e": "ORDER_TRADE_UPDATE",
        "E": 1700000000000,
        "o": {
            "s": "BTCUSDT",
            "S": "BUY",
            "X": "FILLED",
            "i": 777,
            "c": "cid-7:sl",
            "l": "1",
            "q": "1",
            "z": "1",
            "ap": "30000",
            "n": "0.2",
            "o": "STOP_MARKET",
            "R": True,
        },
    }
    payload = _assert_update_schema_valid(_parse_binance_order_update(message))
    assert payload["symbol"] == "BTCUSDT"
    assert payload["status"] == "filled"


def test_order_updates_binance_close_position_flag():
    message = {
        "e": "ORDER_TRADE_UPDATE",
        "E": 1700000000001,
        "o": {
            "s": "BTCUSDT",
            "S": "SELL",
            "X": "FILLED",
            "i": 778,
            "c": "cid-7",
            "l": "1",
            "q": "1",
            "z": "1",
            "o": "MARKET",
            "cp": True,
        },
    }
    update = _parse_binance_order_update(message)
    assert update is not None
    assert update.close_reason == "position_close"
    assert update.position_effect == "close"


def test_order_updates_binance_spot_schema_valid():
    message = {
        "e": "executionReport",
        "E": 1700000000000,
        "s": "BTCUSDT",
        "S": "SELL",
        "X": "FILLED",
        "i": 888,
        "c": "cid-8:tp",
        "z": "1",
        "q": "1",
        "L": "30500",
        "n": "0.2",
        "o": "TAKE_PROFIT",
    }
    payload = _assert_update_schema_valid(_parse_binance_spot_order_update(message))
    assert payload["symbol"] == "BTCUSDT"
    assert payload["status"] == "filled"


def test_parse_binance_spot_order_update_fixture_schema_valid():
    message = _load_fixture("binance_spot_order_filled.json")
    update = _parse_binance_spot_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["symbol"] == "BTCUSDT"
    assert payload["status"] == "filled"


def test_parse_binance_spot_order_update_cancel_fixture():
    message = _load_fixture("binance_spot_order_canceled.json")
    update = _parse_binance_spot_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["symbol"] == "BTCUSDT"
    assert payload["status"] == "canceled"


def test_parse_binance_spot_order_update_oco_stop_loss_fixture():
    message = _load_fixture("binance_spot_order_oco_stop_loss_limit_new.json")
    update = _parse_binance_spot_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["symbol"] == "BTCUSDT"
    assert payload["close_reason"] == "stop_loss_hit"
    assert payload["position_effect"] == "close"


def test_parse_binance_spot_order_update_oco_limit_fixture():
    message = _load_fixture("binance_spot_order_oco_limit_maker_new.json")
    update = _parse_binance_spot_order_update(message)
    payload = _assert_update_schema_valid(update)
    assert payload["symbol"] == "BTCUSDT"
    assert payload["status"] == "pending"


def test_parse_binance_spot_order_update():
    message = {
        "e": "executionReport",
        "E": 1700000000000,
        "s": "BTCUSDT",
        "S": "BUY",
        "X": "FILLED",
        "i": 321,
        "c": "spot-1",
        "z": "1",
        "q": "1",
        "L": "30500",
        "n": "0.2",
    }
    update = _parse_binance_spot_order_update(message)
    assert update is not None
    assert update.symbol == "BTCUSDT"
    assert update.status == "filled"
    assert update.order_id == "321"
    assert update.filled_size == 1.0
    assert update.remaining_size == 0.0


def test_parse_partial_status_normalized():
    message = {
        "topic": "order",
        "data": [
            {
                "symbol": "BTCUSDT",
                "orderId": "789",
                "orderStatus": "PartiallyFilled",
                "side": "Buy",
                "qty": "1",
                "updatedTime": 1700000000000,
            }
        ],
    }
    update = _parse_bybit_order_update(message)
    assert update is not None
    assert update.status == "partially_filled"


def test_parse_bybit_spot_topic():
    message = {
        "topic": "order.spot",
        "data": [
            {
                "symbol": "BTCUSDT",
                "orderId": "999",
                "orderStatus": "Cancelled",
                "side": "Sell",
                "qty": "1",
                "updatedTime": 1700000000000,
            }
        ],
    }
    update = _parse_bybit_order_update(message)
    assert update is not None
    assert update.status == "canceled"
    assert update.order_id == "999"


def test_order_updates_backoff_emits_telemetry():
    provider = OkxOrderUpdateProvider(
        OkxWsCredentials(api_key="k", secret_key="s", passphrase="p", testnet=True)
    )
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    provider.set_telemetry(telemetry, ctx)

    async def run_once():
        provider._register_failure("connect_failed", detail="boom")
        await asyncio.sleep(0)

    asyncio.run(run_once())
    assert telemetry.guardrails
    _, guard_payload = telemetry.guardrails[0]
    assert guard_payload["type"] == "ws_backoff"
    assert guard_payload["exchange"] == "okx"
    assert guard_payload["reason"] == "connect_failed"
    assert guard_payload["detail"] == "boom"
    assert telemetry.health
    _, health_payload = telemetry.health[0]
    assert health_payload["status"] == "reconnecting"


def test_order_updates_stale_guardrail_emits_telemetry():
    provider = OkxOrderUpdateProvider(
        OkxWsCredentials(api_key="k", secret_key="s", passphrase="p", testnet=True)
    )
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    provider.set_telemetry(telemetry, ctx)

    async def run_once():
        provider._emit_stale_guardrail("timeout")
        await asyncio.sleep(0)

    asyncio.run(run_once())
    assert telemetry.guardrails
    _, guard_payload = telemetry.guardrails[0]
    assert guard_payload["type"] == "ws_stale"
    assert guard_payload["exchange"] == "okx"
    assert guard_payload["reason"] == "timeout"
    assert telemetry.health
    _, health_payload = telemetry.health[0]
    assert health_payload["status"] == "stale"
