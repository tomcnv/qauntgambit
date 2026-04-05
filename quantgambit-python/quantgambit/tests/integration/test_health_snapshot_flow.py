import asyncio
import json

from quantgambit.diagnostics.health_worker import HealthWorker, HealthWorkerConfig
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self, lengths=None):
        self.lengths = lengths or {}
        self.data = {}
        self.expiry = {}

    async def xlen(self, stream):
        return self.lengths.get(stream, 0)

    async def set(self, key, value):
        self.data[key] = value
        return True

    async def expire(self, key, ttl):
        self.expiry[key] = ttl
        return True


def test_health_snapshot_includes_qa_counters():
    redis = FakeRedis({"events:market_data": 0})
    pipeline = TelemetryPipeline(snapshot_writer=RedisSnapshotWriter(redis))
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    worker = HealthWorker(
        redis_client=RedisStreamsClient(redis),
        telemetry=pipeline,
        telemetry_context=ctx,
        config=HealthWorkerConfig(max_stream_depth=100),
    )
    worker.record_market_tick(age_sec=0.5, is_stale=False, is_skew=False, is_gap=True, is_out_of_order=False)
    worker.record_market_tick(age_sec=0.6, is_stale=False, is_skew=False, is_gap=False, is_out_of_order=True)

    asyncio.run(worker._emit_once())

    key = "quantgambit:t1:b1:health:latest"
    payload = json.loads(redis.data[key])
    assert payload["market_data_gap_pct"] == 50.0
    assert payload["market_data_out_of_order_pct"] == 50.0
