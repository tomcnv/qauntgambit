import asyncio
import time

from quantgambit.signals.feature_worker import FeaturePredictionWorker
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    async def get(self, key):
        return None

    async def xadd(self, stream, data):
        return "1-0"


def test_snapshot_paths_do_not_call_time(monkeypatch):
    def boom():
        raise AssertionError("time.time called inside snapshot path")

    monkeypatch.setattr(time, "time", boom)
    worker = FeaturePredictionWorker(RedisStreamsClient(FakeRedis()), bot_id="b1", exchange="okx")

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    assert snapshot is not None
