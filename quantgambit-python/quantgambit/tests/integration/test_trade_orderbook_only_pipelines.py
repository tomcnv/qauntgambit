import asyncio

from quantgambit.market.trades import TradeStatsCache
from quantgambit.signals.feature_worker import FeaturePredictionWorker, FeatureWorkerConfig
from quantgambit.storage.redis_streams import RedisStreamsClient
from quantgambit.ingest.time_utils import us_to_sec


class DummyRedis:
    async def xadd(self, *args, **kwargs):
        return "1-0"

    async def get(self, *args, **kwargs):
        return None

    async def set(self, *args, **kwargs):
        return True

    async def lpush(self, *args, **kwargs):
        return 1

    async def ltrim(self, *args, **kwargs):
        return True

    async def expire(self, *args, **kwargs):
        return True


def _build_worker(trade_cache=None):
    config = FeatureWorkerConfig(
        gate_on_orderbook_gap=False,
        gate_on_orderbook_stale=False,
        gate_on_trade_stale=False,
        gate_on_candle_stale=False,
    )
    return FeaturePredictionWorker(
        redis_client=RedisStreamsClient(DummyRedis()),
        bot_id="b1",
        exchange="okx",
        config=config,
        trade_cache=trade_cache,
        quality_tracker=None,
    )


def test_trade_only_pipeline_builds_snapshot():
    cache = TradeStatsCache(window_sec=10.0, profile_window_sec=10.0)
    now_us = 10_000_000
    cache.update_trade("BTCUSDT", now_us, price=100.0, size=1.0, side="buy")
    worker = _build_worker(trade_cache=cache)
    tick = {
        "symbol": "BTCUSDT",
        "timestamp": us_to_sec(now_us),
        "last": 100.0,
        "source": "trade_feed",
        "ts_canon_us": now_us,
    }
    snapshot = asyncio.run(worker._build_snapshot("BTCUSDT", tick))
    assert snapshot is not None
    assert snapshot["features"]["price"] == 100.0
    assert snapshot["features"]["trades_per_second"] > 0


def test_orderbook_only_pipeline_builds_snapshot():
    worker = _build_worker(trade_cache=None)
    now_us = 20_000_000
    tick = {
        "symbol": "ETHUSDT",
        "timestamp": us_to_sec(now_us),
        "bid": 2000.0,
        "ask": 2001.0,
        "bids": [[2000.0, 1.0]],
        "asks": [[2001.0, 1.0]],
        "source": "orderbook_feed",
        "ts_canon_us": now_us,
    }
    snapshot = asyncio.run(worker._build_snapshot("ETHUSDT", tick))
    assert snapshot is not None
    assert snapshot["features"]["price"] == 2000.5
    assert snapshot["features"]["bid_depth_usd"] > 0
    assert snapshot["features"]["ask_depth_usd"] > 0
