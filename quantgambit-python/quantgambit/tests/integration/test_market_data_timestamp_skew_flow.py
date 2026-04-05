import asyncio
import time

from quantgambit.ingest.market_data_worker import MarketDataWorker, MarketDataWorkerConfig
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    async def xadd(self, *args, **kwargs):
        return "1-0"


class SequenceProvider:
    def __init__(self, ticks):
        self.ticks = list(ticks)

    async def next_tick(self):
        if not self.ticks:
            raise StopAsyncIteration()
        return self.ticks.pop(0)


def test_market_data_skew_updates_quality_flags():
    ticks = [
        {"symbol": "BTC/USDT:USDT", "bid": 100.0, "ask": 101.0, "timestamp": 1.0}
        for _ in range(5)
    ]
    provider = SequenceProvider(ticks)
    quality = MarketDataQualityTracker()
    worker = MarketDataWorker(
        provider=provider,
        cache=ReferencePriceCache(),
        redis_client=RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        quality_tracker=quality,
        config=MarketDataWorkerConfig(
            idle_backoff_sec=0.0,
            stale_threshold_sec=999.0,
            max_clock_skew_sec=0.1,
        ),
    )

    async def run_once():
        try:
            await worker.run()
        except StopAsyncIteration:
            return

    asyncio.run(run_once())
    snapshot = asyncio.run(quality.snapshot("BTC-USDT-SWAP", now_ts=time.time()))
    assert snapshot["skew_count"] >= 5
    assert "clock_skew" in snapshot["flags"]
