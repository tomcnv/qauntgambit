import asyncio

from quantgambit.execution.manager import _aggregate_execution_trades, _reconcile_close_from_exchange


class _FakeExchangeClient:
    def __init__(self, trades):
        self._trades = trades

    async def fetch_executions(self, symbol, order_id=None, client_order_id=None, since_ms=None, limit=100):
        return list(self._trades)


def test_aggregate_execution_trades_prefers_order_id_match():
    trades = [
        {"order": "abc", "amount": 1.0, "price": 100.0, "fee": {"cost": 0.2}, "timestamp": 1000},
        {"order": "abc", "amount": 2.0, "price": 101.0, "fee": {"cost": 0.3}, "timestamp": 2000},
        {"order": "other", "amount": 5.0, "price": 200.0, "fee": {"cost": 1.0}, "timestamp": 3000},
    ]
    summary = _aggregate_execution_trades(trades, order_id="abc", client_order_id=None)
    assert summary is not None
    assert round(summary["avg_price"], 6) == round((1 * 100 + 2 * 101) / 3, 6)
    assert round(summary["total_qty"], 6) == 3.0
    assert round(summary["total_fees_usd"], 6) == 0.5
    assert summary["exit_timestamp"] == 2000.0


def test_aggregate_execution_trades_uses_bybit_info_fields():
    trades = [
        {
            "info": {
                "orderId": "bybit123",
                "orderLinkId": "cl-1",
                "execQty": "1.5",
                "execPrice": "91.54",
                "execFee": "0.12",
                "execTime": "1700000000123",
            }
        }
    ]
    summary = _aggregate_execution_trades(trades, order_id="bybit123", client_order_id=None)
    assert summary is not None
    assert round(summary["avg_price"], 6) == 91.54
    assert round(summary["total_qty"], 6) == 1.5
    assert round(summary["total_fees_usd"], 6) == 0.12
    assert summary["exit_timestamp"] == 1700000000.123


def test_reconcile_close_from_exchange_filters_and_returns_summary():
    trades = [
        {"order": "abc", "amount": 1.0, "price": 100.0, "fee": {"cost": 0.2}, "timestamp": 1000},
        {"order": "other", "amount": 1.0, "price": 200.0, "fee": {"cost": 0.5}, "timestamp": 1500},
    ]
    client = _FakeExchangeClient(trades)
    summary = asyncio.run(
        _reconcile_close_from_exchange(
            exchange_client=client,
            symbol="BTCUSDT",
            order_id="abc",
            client_order_id=None,
            exit_timestamp=2.0,
        )
    )
    assert summary is not None
    assert round(summary["avg_price"], 6) == 100.0
    assert round(summary["total_qty"], 6) == 1.0
