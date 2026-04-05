import asyncio
import json
import time

from quantgambit.signals.decision_worker import DecisionWorker, DecisionWorkerConfig
from quantgambit.signals.pipeline import StageContext
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.events = []

    async def xadd(self, stream, data):
        self.events.append((stream, data))
        return "1-0"

    async def set(self, key, value):
        return True

    async def expire(self, key, ttl):
        return True


class FakeEngine:
    async def decide_with_context(self, decision_input):
        ctx = StageContext(symbol=decision_input.symbol, data={})
        ctx.profile_id = "profile-1"
        ctx.signal = {"side": "buy", "size": 1.0}
        return True, ctx


def test_decision_worker_emits_shadow_decision():
    redis = FakeRedis()
    engine = FakeEngine()
    worker = DecisionWorker(
        redis_client=RedisStreamsClient(redis),
        engine=engine,
        bot_id="b1",
        exchange="okx",
        config=DecisionWorkerConfig(
            warmup_min_samples=0,
            warmup_min_age_sec=0.0,
            warmup_min_candles=0,
            shadow_mode=True,
            shadow_reason="shadow_validation",
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
            "timestamp": time.time(),
            "features": {"price": 100.0},
            "market_context": {
                "price": 100.0,
                "data_quality_score": 0.9,
                "data_quality_flags": [],
                "orderbook_sync_state": "synced",
                "trade_sync_state": "synced",
                "candle_sync_state": "synced",
            },
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    assert redis.events
    payloads = [json.loads(item[1]["data"]) for item in redis.events]
    decision = next(item["payload"] for item in payloads if item["event_type"] == "decision")
    assert decision["decision"] == "shadow"
    assert decision["shadow_mode"] is True
    assert decision["shadow_reason"] == "shadow_validation"
    assert any(item["event_type"] == "decision_shadow" for item in payloads)
