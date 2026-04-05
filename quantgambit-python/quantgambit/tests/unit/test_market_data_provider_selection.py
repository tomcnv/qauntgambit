import pytest

from quantgambit.market.ccxt_provider import CcxtTickerProvider
from quantgambit.market.ws_provider import WebsocketTickerProvider
from quantgambit.runtime.entrypoint import (
    ResilientMarketDataProvider,
    _normalize_market_data_symbols,
    _select_market_data_provider,
)


def test_select_market_data_provider_ccxt():
    raw_symbols = "BTC-USDT-SWAP"
    symbols = _normalize_market_data_symbols(raw_symbols, "okx", "perp")
    provider = _select_market_data_provider(
        exchange="okx",
        market_type="perp",
        provider_name="ccxt",
        raw_symbols=raw_symbols,
        symbols=symbols,
        poll_interval=0.5,
        testnet=True,
    )
    assert isinstance(provider, CcxtTickerProvider)


def test_select_market_data_provider_ws():
    raw_symbols = "BTC-USDT-SWAP"
    symbols = _normalize_market_data_symbols(raw_symbols, "okx", "perp")
    provider = _select_market_data_provider(
        exchange="okx",
        market_type="perp",
        provider_name="ws",
        raw_symbols=raw_symbols,
        symbols=symbols,
        poll_interval=0.5,
        testnet=True,
    )
    assert isinstance(provider, WebsocketTickerProvider)


def test_select_market_data_provider_empty_symbols():
    provider = _select_market_data_provider(
        exchange="okx",
        market_type="perp",
        provider_name="ws",
        raw_symbols="",
        symbols=[],
        poll_interval=0.5,
        testnet=True,
    )
    assert provider is None


def test_select_market_data_provider_auto_wraps_fallback():
    raw_symbols = "BTC-USDT-SWAP"
    symbols = _normalize_market_data_symbols(raw_symbols, "okx", "perp")
    provider = _select_market_data_provider(
        exchange="okx",
        market_type="perp",
        provider_name="auto",
        raw_symbols=raw_symbols,
        symbols=symbols,
        poll_interval=0.5,
        testnet=True,
    )
    assert isinstance(provider, ResilientMarketDataProvider)


class DummyProvider:
    def __init__(self, *, ticks=None, fail=0):
        self.ticks = list(ticks or [])
        self.fail = fail

    async def next_tick(self):
        if self.fail > 0:
            self.fail -= 1
            raise RuntimeError("no data")
        if self.ticks:
            return self.ticks.pop(0)
        return None


class DummyTelemetry:
    def __init__(self):
        self.events = []

    async def publish_guardrail(self, ctx, payload):
        self.events.append(payload)


class DummyTimescaleWriter:
    def __init__(self):
        self.rows = []

    async def write(self, table, row):
        self.rows.append((table, row))


class DummySnapshotWriter:
    def __init__(self):
        self.writes = {}

    async def write(self, key, payload):
        self.writes[key] = payload


@pytest.mark.asyncio
async def test_resilient_provider_switches_on_failure():
    primary = DummyProvider(fail=1)
    fallback_tick = {"symbol": "BTCUSDT", "timestamp": 1, "bid": 1, "ask": 2, "last": 1.5}
    fallback = DummyProvider(ticks=[fallback_tick])
    provider = ResilientMarketDataProvider(
        providers=[primary, fallback],
        provider_names=["ws", "ccxt"],
        switch_threshold=1,
        idle_backoff_sec=0.0,
        guardrail_cooldown_sec=0.0,
    )
    telemetry = DummyTelemetry()
    provider.set_telemetry(telemetry, object())
    tick = await provider.next_tick()
    assert tick == fallback_tick
    assert provider.active_provider_name == "ccxt"
    assert any(event.get("type") == "market_data_provider_switch" for event in telemetry.events)


@pytest.mark.asyncio
async def test_resilient_provider_timescale_metrics():
    primary = DummyProvider(fail=2)
    fallback = DummyProvider(ticks=[{"symbol": "BTCUSDT", "timestamp": 1, "bid": 1, "ask": 2}])
    provider = ResilientMarketDataProvider(
        providers=[primary, fallback],
        provider_names=["ws", "ccxt"],
        switch_threshold=1,
        idle_backoff_sec=0.0,
        guardrail_cooldown_sec=0.0,
    )
    writer = DummyTimescaleWriter()
    provider.set_timescale_writer(writer, tenant_id="t1", bot_id="b1", exchange="okx", table="md_events")
    await provider.next_tick()
    assert writer.rows, "timescale writer should receive provider event"
    table, row = writer.rows[0]
    assert table == "md_events"
    assert row.bot_id == "b1"


@pytest.mark.asyncio
async def test_resilient_provider_writes_snapshot_on_switch():
    primary = DummyProvider(fail=1)
    fallback = DummyProvider(ticks=[{"symbol": "BTCUSDT", "timestamp": 1, "bid": 1, "ask": 2}])
    provider = ResilientMarketDataProvider(
        providers=[primary, fallback],
        provider_names=["ws", "ccxt"],
        switch_threshold=1,
        idle_backoff_sec=0.0,
        guardrail_cooldown_sec=0.0,
    )
    snapshot = DummySnapshotWriter()
    provider.set_snapshot_writer(snapshot, "quantgambit:t1:b1:market_data:provider")
    await provider.next_tick()
    assert "quantgambit:t1:b1:market_data:provider" in snapshot.writes
    payload = snapshot.writes["quantgambit:t1:b1:market_data:provider"]
    assert payload["active_provider"] == "ccxt"


@pytest.mark.asyncio
async def test_resilient_provider_emits_failure_guardrail():
    primary = DummyProvider(fail=2)
    fallback = DummyProvider(fail=2)
    provider = ResilientMarketDataProvider(
        providers=[primary, fallback],
        provider_names=["ws", "ccxt"],
        switch_threshold=1,
        idle_backoff_sec=0.0,
        guardrail_cooldown_sec=0.0,
    )
    telemetry = DummyTelemetry()
    provider.set_telemetry(telemetry, object())
    tick = await provider.next_tick()
    assert tick is None
    assert any(event.get("type") == "market_data_provider_failure" for event in telemetry.events)
