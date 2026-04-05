from datetime import datetime, timezone

from quantgambit.storage.timescale import TelemetryRow, TimescaleWriter


class FakeConn:
    def __init__(self):
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append((query, args))
        return "INSERT 0 1"


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


async def _write_order_event(payload):
    conn = FakeConn()
    writer = TimescaleWriter(FakePool(conn))
    row = TelemetryRow(
        tenant_id="t1",
        bot_id="b1",
        symbol="BTCUSDT",
        exchange="bybit",
        timestamp=datetime(2026, 3, 24, tzinfo=timezone.utc),
        payload=payload,
    )
    await writer.write("order_events", row)
    return conn.calls


def test_timescale_writer_populates_order_event_columns():
    import asyncio

    calls = asyncio.run(
        _write_order_event(
            {
                "status": "filled",
                "event_type": "execution_update",
                "reason": "stop_loss_hit",
                "order_id": "oid-1",
                "client_order_id": "cid-1",
                "fill_price": 71000.5,
                "filled_size": 0.01,
                "fee_usd": 0.25,
            }
        )
    )
    assert len(calls) == 1
    query, args = calls[0]
    assert "order_id, client_order_id, event_type, status, reason" in query
    assert args[5] == "oid-1"
    assert args[6] == "cid-1"
    assert args[7] == "execution_update"
    assert args[8] == "filled"
    assert args[9] == "stop_loss_hit"
    assert args[10] == 71000.5
    assert args[11] == 0.01
    assert args[12] == 0.25
