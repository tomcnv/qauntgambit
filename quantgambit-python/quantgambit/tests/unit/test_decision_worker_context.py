import asyncio
import json
import time

from quantgambit.config.models import BotConfig
from quantgambit.config.repository import ConfigRepository
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
    def __init__(self):
        self.inputs = []

    async def decide_with_context(self, decision_input):
        self.inputs.append(decision_input)
        ctx = StageContext(symbol=decision_input.symbol, data={}, rejection_reason="test")
        return False, ctx


class FakeAcceptEngine:
    def __init__(self):
        self.inputs = []

    async def decide_with_context(self, decision_input):
        self.inputs.append(decision_input)
        # No candidate in ctx.data on purpose; this validates signal-level fallback path.
        ctx = StageContext(
            symbol=decision_input.symbol,
            signal={
                "side": "buy",
                "size": 0.01,
                "strategy_id": "mean_reversion_fade",
            },
            data={},
        )
        return True, ctx


class FakeStateManager:
    def get_account_state(self):
        return type(
            "account",
            (),
            {
                "equity": 1000.0,
                "daily_pnl": -10.0,
                "peak_balance": 1200.0,
                "consecutive_losses": 2,
            },
        )()

    def update_mfe_mae(self, symbol, price):
        return None

    async def list_open_positions(self):
        return [{"symbol": "BTC", "size": 1.0, "side": "long"}]


def test_decision_worker_passes_portfolio_context():
    redis = FakeRedis()
    engine = FakeEngine()
    config_repository = ConfigRepository()
    config_repository.apply(
        BotConfig(
            tenant_id="t1",
            bot_id="b1",
            version=1,
            active_exchange="okx",
            symbols=["BTC"],
            risk={"max_positions": 2},
        )
    )
    worker = DecisionWorker(
        redis_client=RedisStreamsClient(redis),
        engine=engine,
        bot_id="b1",
        exchange="okx",
        tenant_id="t1",
        state_manager=FakeStateManager(),
        config_repository=config_repository,
        config=DecisionWorkerConfig(
            warmup_min_samples=0,
            warmup_min_age_sec=0.0,
            warmup_min_candles=0,
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
    assert engine.inputs
    decision_input = engine.inputs[0]
    assert decision_input.account_state["equity"] == 1000.0
    assert decision_input.positions
    assert decision_input.risk_limits == {"max_positions": 2}


def test_decision_worker_fills_time_budget_without_candidate():
    redis = FakeRedis()
    engine = FakeAcceptEngine()
    config_repository = ConfigRepository()
    config_repository.apply(
        BotConfig(
            tenant_id="t1",
            bot_id="b1",
            version=1,
            active_exchange="okx",
            symbols=["BTC"],
            risk={"max_positions": 2},
        )
    )
    worker = DecisionWorker(
        redis_client=RedisStreamsClient(redis),
        engine=engine,
        bot_id="b1",
        exchange="okx",
        tenant_id="t1",
        state_manager=FakeStateManager(),
        config_repository=config_repository,
        config=DecisionWorkerConfig(
            warmup_min_samples=0,
            warmup_min_age_sec=0.0,
            warmup_min_candles=0,
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
    event_payload = json.loads(redis.events[-1][1]["data"])
    signal = event_payload.get("payload", {}).get("signal", {})
    assert signal.get("strategy_id") == "mean_reversion_fade"
    assert signal.get("time_to_work_sec") == 20.0
    assert signal.get("max_hold_sec") == 120.0
    assert signal.get("mfe_min_bps") == 3.0
