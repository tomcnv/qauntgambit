import asyncio
import json
import time

from quantgambit.ingest.candle_worker import CandleWorker, CandleWorkerConfig
from quantgambit.signals.feature_worker import FeaturePredictionWorker, FeatureWorkerConfig
from quantgambit.signals.decision_worker import DecisionWorker, DecisionWorkerConfig
from quantgambit.signals.pipeline import StageContext
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.events = []
        self._values = {}

    async def xadd(self, stream, data, **kwargs):
        self.events.append((stream, data))
        return "1-0"

    async def set(self, key, value, **kwargs):
        self._values[key] = value
        return True

    async def get(self, key):
        return self._values.get(key)

    async def expire(self, key, ttl):
        return True

    async def hset(self, key, mapping=None, **kwargs):
        return True

    async def hgetall(self, key):
        return {}


class FakeTimescale:
    def __init__(self):
        self.candles = []

    async def write_candle(self, row):
        self.candles.append(row)


class FakeEngine:
    def __init__(self):
        self.inputs = []

    async def decide_with_context(self, decision_input):
        self.inputs.append(decision_input)
        ctx = StageContext(symbol=decision_input.symbol, data={}, rejection_reason="test")
        return False, ctx


class FakeStateManager:
    def get_account_state(self):
        return type(
            "account",
            (),
            {
                "equity": 1000.0,
                "daily_pnl": 0.0,
                "peak_balance": 1000.0,
                "consecutive_losses": 0,
            },
        )()

    def update_mfe_mae(self, symbol, price):
        return None

    async def list_open_positions(self):
        return []


def _tick_event(symbol: str, ts_sec: float, price: float) -> dict:
    ts_us = int(ts_sec * 1_000_000)
    tick = {
        "symbol": symbol,
        "timestamp": ts_sec,
        "bid": price - 0.5,
        "ask": price + 0.5,
        "last": price,
        "volume": 1.0,
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
    }
    payload = {
        "event_id": "1",
        "event_type": "market_tick",
        "schema_version": "v1",
        "timestamp": str(ts_sec),
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "symbol": symbol,
        "exchange": "bybit",
        "payload": tick,
    }
    return {"data": json.dumps(payload)}


def test_timescale_pipeline_flow():
    redis = FakeRedis()
    redis_client = RedisStreamsClient(redis)
    timescale = FakeTimescale()

    candle_worker = CandleWorker(
        redis_client=redis_client,
        timescale=timescale,
        tenant_id="t1",
        bot_id="b1",
        exchange="bybit",
        config=CandleWorkerConfig(timeframes_sec=(60,)),
    )
    feature_worker = FeaturePredictionWorker(
        redis_client=redis_client,
        bot_id="b1",
        exchange="bybit",
        config=FeatureWorkerConfig(
            gate_on_orderbook_gap=False,
            gate_on_orderbook_stale=False,
            gate_on_trade_stale=False,
            gate_on_candle_stale=False,
        ),
    )
    decision_worker = DecisionWorker(
        redis_client=redis_client,
        engine=FakeEngine(),
        bot_id="b1",
        exchange="bybit",
        tenant_id="t1",
        state_manager=FakeStateManager(),
        config=DecisionWorkerConfig(
            warmup_min_samples=0,
            warmup_min_age_sec=0.0,
            warmup_min_candles=0,
        ),
    )

    async def run_once():
        base_ts = time.time()
        tick_event = _tick_event("BTCUSDT", base_ts, 50000.0)
        tick_event_next = _tick_event("BTCUSDT", base_ts + 65.0, 50010.0)
        await candle_worker._handle_message(tick_event)
        await candle_worker._handle_message(tick_event_next)
        candle_events = [event for event in redis.events if event[0] == candle_worker.config.output_stream]
        assert candle_events, "candle event should be emitted"
        candle_payload = candle_events[-1][1]
        await feature_worker._handle_candle(candle_payload)
        await feature_worker._handle_message(tick_event_next)

        feature_events = [event for event in redis.events if event[0] == feature_worker.config.output_stream]
        assert feature_events, "feature snapshot should be emitted"
        feature_payload = feature_events[-1][1]
        await decision_worker._handle_message(feature_payload)

    asyncio.run(run_once())

    decision_events = [event for event in redis.events if event[0] == decision_worker.config.output_stream]
    assert decision_events, "decision event should be emitted"
    assert timescale.candles, "candle should be written to timescale"
