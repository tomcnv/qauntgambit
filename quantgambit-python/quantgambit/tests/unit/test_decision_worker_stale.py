import asyncio
import json
import time

from quantgambit.signals.decision_worker import DecisionWorker, DecisionWorkerConfig
from quantgambit.signals.decision_engine import DecisionEngine
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.events = []
        self.data = {}
        self.expiry = {}

    async def xadd(self, stream, data):
        self.events.append((stream, data))
        return "1-0"

    async def set(self, key, value):
        self.data[key] = value
        return True

    async def expire(self, key, ttl):
        self.expiry[key] = ttl
        return True


def test_decision_worker_skips_stale_snapshot_silently():
    """Test that stale snapshots emit a rate-limited rejection diagnostic.
    
    The early skip remains a performance optimization, but it now emits a
    low-noise rejection event so prolonged no-trade periods are diagnosable.
    """
    redis = FakeRedis()
    # Use legacy pipeline for backwards compatibility with minimal test data
    # Disable warmup gate since test only sends 1 sample (needs 5 by default)
    worker = DecisionWorker(
        redis_client=RedisStreamsClient(redis),
        engine=DecisionEngine(use_gating_system=False),
        bot_id="b1",
        exchange="okx",
        config=DecisionWorkerConfig(
            max_feature_age_sec=1.0,  # Enable stale check
            warmup_gate_enabled=False,
            skip_stale_silently=True,  # Default: skip without publishing
        ),
    )
    ts_us = int(time.time() * 1_000_000)
    payload = {
        "event_id": "1",
        "event_type": "feature_snapshot",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": time.time() - 10,  # 10 seconds old, exceeds 1.0s threshold
            "features": {"price": 100.0},
            "market_context": {"price": 100.0},
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    assert len(redis.events) == 1
    event = json.loads(redis.events[0][1]["data"])
    assert event["payload"]["rejection_reason"] == "stale_feature_snapshot"
    assert event["payload"]["rejected_by"] == "decision_worker_fast_skip"
    summary = json.loads(redis.data["quantgambit:t1:b1:decision_activity:latest"])
    assert summary["rejected_count"] == 1
    assert summary["accepted_count"] == 0
    assert summary["dominant_rejection_reason"] == "stale_feature_snapshot"
    assert summary["dominant_rejection_stage"] == "decision_worker_fast_skip"
    assert summary["symbol_activity"][0]["symbol"] == "BTC"
    assert summary["symbol_activity"][0]["dominant_rejection_reason"] == "stale_feature_snapshot"
    warmup = json.loads(redis.data["quantgambit:t1:b1:warmup:BTC"])
    assert warmup["symbol"] == "BTC"
    assert warmup["sample_count"] == 1
    assert warmup["min_samples"] == 5
    assert warmup["candle_count"] == 0
    assert warmup["ready"] is True


def test_decision_worker_rejects_low_quality():
    redis = FakeRedis()
    # Use legacy pipeline for backwards compatibility with minimal test data
    # Disable warmup gate since test only sends 1 sample (needs 5 by default)
    worker = DecisionWorker(
        redis_client=RedisStreamsClient(redis),
        engine=DecisionEngine(use_gating_system=False),
        bot_id="b1",
        exchange="okx",
        config=DecisionWorkerConfig(
            max_feature_age_sec=999.0,
            min_data_quality_score=0.8,
            warmup_gate_enabled=False,
        ),
    )
    ts_us = int(time.time() * 1_000_000)
    payload = {
        "event_id": "2",
        "event_type": "feature_snapshot",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": time.time(),
            "features": {"price": 100.0},
            "market_context": {"price": 100.0, "data_quality_score": 0.5},
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    assert redis.events
    event = json.loads(redis.events[0][1]["data"])
    assert event["payload"]["rejection_reason"] == "low_data_quality"


def test_decision_worker_suppresses_duplicate_position_exists_rejections():
    redis = FakeRedis()
    worker = DecisionWorker(
        redis_client=RedisStreamsClient(redis),
        engine=DecisionEngine(use_gating_system=False),
        bot_id="b1",
        exchange="okx",
        config=DecisionWorkerConfig(
            position_exists_reject_cooldown_sec=60.0,
            warmup_gate_enabled=False,
        ),
    )

    async def run_once():
        await worker._publish_decision(
            "BTC",
            {
                "timestamp": time.time(),
                "decision": "rejected",
                "rejection_reason": "position_exists",
            },
        )
        await worker._publish_decision(
            "BTC",
            {
                "timestamp": time.time(),
                "decision": "rejected",
                "rejection_reason": "position_exists",
            },
        )

    asyncio.run(run_once())

    assert len(redis.events) == 1
    event = json.loads(redis.events[0][1]["data"])
    assert event["payload"]["rejection_reason"] == "position_exists"
