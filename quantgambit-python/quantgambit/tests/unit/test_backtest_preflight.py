from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from quantgambit.api.backtest_endpoints import ValidationError, _preflight_validate_backtest_data


class _FakeConn:
    def __init__(self, decision_count: int, candle_count: int, availability: dict):
        self._decision_count = decision_count
        self._candle_count = candle_count
        self._availability = availability

    async def fetchval(self, query: str, *args):
        if "FROM decision_events" in query:
            return self._decision_count
        if "FROM market_candles" in query:
            return self._candle_count
        return 0

    async def fetchrow(self, query: str, *args):
        return self._availability


class _AcquireCtx:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


@pytest.mark.asyncio
async def test_preflight_rejects_missing_source_data():
    now = datetime.now(timezone.utc)
    conn = _FakeConn(
        decision_count=0,
        candle_count=0,
        availability={
            "decision_min_ts": now,
            "decision_max_ts": now,
            "candle_min_ts": now,
            "candle_max_ts": now,
        },
    )
    pool = _FakePool(conn)

    with pytest.raises(ValidationError) as exc:
        await _preflight_validate_backtest_data(
            timescale_pool=pool,
            symbol="BTC-USDT-SWAP",
            start_dt=now,
            end_dt=now + timedelta(hours=1),
            require_decision_events=True,
        )
    details = exc.value.details or {}
    assert details.get("decision_events_count") == 0
    assert details.get("market_candles_count") == 0
    assert "BTCUSDTSWAP" in details.get("symbol_candidates", [])


@pytest.mark.asyncio
async def test_preflight_allows_when_data_exists():
    now = datetime.now(timezone.utc)
    conn = _FakeConn(
        decision_count=25,
        candle_count=120,
        availability={
            "decision_min_ts": now,
            "decision_max_ts": now,
            "candle_min_ts": now,
            "candle_max_ts": now,
        },
    )
    pool = _FakePool(conn)

    await _preflight_validate_backtest_data(
        timescale_pool=pool,
        symbol="BTCUSDT",
        start_dt=now,
        end_dt=now + timedelta(hours=1),
        require_decision_events=True,
    )
