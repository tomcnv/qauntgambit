import asyncio

from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.market.updater import MarketDataUpdater


class FakeProvider:
    def __init__(self, ticks):
        self.ticks = list(ticks)

    async def next_tick(self):
        if not self.ticks:
            return None
        return self.ticks.pop(0)


def test_market_data_updater_updates_mid():
    cache = ReferencePriceCache()
    provider = FakeProvider([
        {"symbol": "BTC", "bid": 99.0, "ask": 101.0, "last": 100.0},
    ])
    updater = MarketDataUpdater(cache, provider)

    async def run_once():
        await asyncio.wait_for(updater.run(), timeout=0.01)

    try:
        asyncio.run(run_once())
    except asyncio.TimeoutError:
        pass

    assert cache.get_reference_price("BTC") == 100.0


def test_market_data_updater_skips_stale():
    cache = ReferencePriceCache()
    provider = FakeProvider([
        {"symbol": "BTC", "bid": 99.0, "ask": 101.0, "last": 100.0, "timestamp": 1},
    ])
    updater = MarketDataUpdater(cache, provider, stale_threshold_sec=0.001)

    async def run_once():
        await asyncio.wait_for(updater.run(), timeout=0.01)

    try:
        asyncio.run(run_once())
    except asyncio.TimeoutError:
        pass

    assert cache.get_reference_price("BTC") is None


def test_market_data_updater_heartbeat():
    cache = ReferencePriceCache()
    provider = FakeProvider([None])
    updater = MarketDataUpdater(cache, provider, stale_threshold_sec=0.001, heartbeat_interval_sec=0.0)

    class FakeTelemetry:
        def __init__(self):
            self.payloads = []

        async def publish_latency(self, ctx, payload):
            self.payloads.append(payload)

    telemetry = FakeTelemetry()
    updater.telemetry = telemetry
    updater.telemetry_context = object()

    async def run_once():
        await asyncio.wait_for(updater.run(), timeout=0.01)

    try:
        asyncio.run(run_once())
    except asyncio.TimeoutError:
        pass

    assert telemetry.payloads
