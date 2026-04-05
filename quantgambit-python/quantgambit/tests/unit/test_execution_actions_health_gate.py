import asyncio
import json
import time

import pytest

from quantgambit.control.runtime_state import ControlRuntimeState
from quantgambit.execution.actions import ExecutionActionHandler


class _FakeRedis:
    def __init__(self, data):
        self.data = data

    async def hgetall(self, key):
        return self.data.get(key, {})

    async def get(self, key):
        return self.data.get(key)


@pytest.mark.asyncio
async def test_resume_rejected_when_orderbook_stale():
    key = "orderbook_health:okx:BTC-USDT-SWAP"
    data = {
        key: {
            "staleness_ms": 6000,
            "last_ts": int(time.time() * 1000) - 6000,
        }
    }
    handler = ExecutionActionHandler(
        runtime_state=ControlRuntimeState(),
        redis_client=_FakeRedis(data),
        exchange="okx",
        orderbook_symbols=["BTC-USDT-SWAP"],
        orderbook_staleness_ms=5000,
    )
    status, message = await handler.resume()
    assert status == "rejected"
    assert message.startswith("orderbook_stale")


@pytest.mark.asyncio
async def test_resume_allows_when_orderbook_fresh():
    key = "orderbook_health:okx:BTC-USDT-SWAP"
    data = {
        key: {
            "staleness_ms": 1000,
            "last_ts": int(time.time() * 1000) - 1000,
        }
    }
    handler = ExecutionActionHandler(
        runtime_state=ControlRuntimeState(),
        redis_client=_FakeRedis(data),
        exchange="okx",
        orderbook_symbols=["BTC-USDT-SWAP"],
        orderbook_staleness_ms=5000,
    )
    status, message = await handler.resume()
    assert status == "executed"
    assert message == "resumed"


@pytest.mark.asyncio
async def test_resume_allows_when_orderbook_fresh_under_canonical_health_key():
    key = "orderbook_health:okx:BTCUSDT"
    data = {
        key: {
            "staleness_ms": 1000,
            "last_ts": int(time.time() * 1000) - 1000,
        }
    }
    handler = ExecutionActionHandler(
        runtime_state=ControlRuntimeState(),
        redis_client=_FakeRedis(data),
        exchange="okx",
        orderbook_symbols=["BTC-USDT-SWAP"],
        orderbook_staleness_ms=5000,
    )
    status, message = await handler.resume()
    assert status == "executed"
    assert message == "resumed"


@pytest.mark.asyncio
async def test_resume_rejected_when_live_mode_missing_exchange_credentials(monkeypatch):
    key = "orderbook_health:okx:BTC-USDT-SWAP"
    data = {
        key: {
            "staleness_ms": 1000,
            "last_ts": int(time.time() * 1000) - 1000,
        }
    }
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.delenv("EXCHANGE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("EXCHANGE_SECRET_ID", raising=False)
    handler = ExecutionActionHandler(
        runtime_state=ControlRuntimeState(),
        redis_client=_FakeRedis(data),
        exchange="okx",
        orderbook_symbols=["BTC-USDT-SWAP"],
        orderbook_staleness_ms=5000,
    )
    status, message = await handler.resume()
    assert status == "rejected"
    assert message == "exchange_credentials_missing"


@pytest.mark.asyncio
async def test_resume_allows_when_quality_snapshot_is_fresh_and_legacy_hash_missing(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "t1")
    monkeypatch.setenv("BOT_ID", "b1")
    key = "quantgambit:t1:b1:quality:BTCUSDT:latest"
    data = {
        key: json.dumps(
            {
                "symbol": "BTCUSDT",
                "status": "ok",
                "orderbook_age_sec": 0.2,
                "orderbook_sync_state": "synced",
            }
        )
    }
    handler = ExecutionActionHandler(
        runtime_state=ControlRuntimeState(),
        redis_client=_FakeRedis(data),
        exchange="okx",
        orderbook_symbols=["BTC-USDT-SWAP"],
        orderbook_staleness_ms=5000,
    )
    status, message = await handler.resume()
    assert status == "executed"
    assert message == "resumed"
