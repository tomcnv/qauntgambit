import asyncio
import json

from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.risk.overrides import RiskOverrideStore
from quantgambit.risk.risk_worker import RiskWorker, RiskWorkerConfig
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.events = []

    async def xadd(self, stream, data, **kwargs):
        self.events.append((stream, data))
        return "1-0"

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return 1


def _decision_event(payload: dict, ts: float = 1.0) -> dict:
    ts_us = int(ts * 1_000_000)
    return {
        "event_id": "evt-1",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": str(ts),
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": payload,
    }


def test_risk_override_blocks_positions():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    overrides = RiskOverrideStore()

    async def apply_override():
        await overrides.apply_overrides({"max_positions": 0}, ttl_seconds=60, scope={"bot_id": "b1"})

    asyncio.run(apply_override())

    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(max_positions=4),
        override_store=overrides,
    )
    payload = _decision_event(
        {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "size": 1.0, "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        }
    )

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_positions_exceeded"


def test_risk_override_prune_emits_dropped_count():
    overrides = RiskOverrideStore(time_fn=lambda: 0.0)

    async def seed():
        await overrides.apply_overrides({"max_positions": 1}, ttl_seconds=5, scope={"bot_id": "b1"})
        await overrides.apply_overrides({"max_positions": 2}, ttl_seconds=10, scope={"bot_id": "b1"})

    asyncio.run(seed())
    overrides._time_fn = lambda: 6.0

    async def prune():
        return await overrides.prune_expired()

    result = asyncio.run(prune())
    assert result["dropped"] == 1


def test_risk_override_disables_trading():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    overrides = RiskOverrideStore()

    async def apply_override():
        await overrides.apply_overrides({"trading_enabled": False}, ttl_seconds=60, scope={"bot_id": "b1"})

    asyncio.run(apply_override())

    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(max_positions=4),
        override_store=overrides,
    )
    payload = _decision_event(
        {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "size": 1.0, "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        }
    )

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "risk_override_disabled"


def test_risk_override_enforces_total_exposure_limit():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    state.add_position(symbol="BTC", side="long", size=1.0, entry_price=100.0, opened_at=1.0)
    overrides = RiskOverrideStore()

    async def apply_override():
        await overrides.apply_overrides({"max_total_exposure_pct": 0.05}, ttl_seconds=60, scope={"bot_id": "b1"})

    asyncio.run(apply_override())

    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(max_total_exposure_pct=0.50),
        override_store=overrides,
    )
    payload = _decision_event(
        {
            "symbol": "ETH",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "size": 1.0, "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        }
    )

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_total_exposure_exceeded"


def test_risk_override_enforces_symbol_exposure_limit():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=10000.0)
    state.add_position(symbol="BTC", side="long", size=1.0, entry_price=10000.0)
    overrides = RiskOverrideStore()

    async def apply_override():
        await overrides.apply_overrides(
            {"max_exposure_per_symbol_pct": 0.05},
            ttl_seconds=60,
            scope={"bot_id": "b1"},
        )

    asyncio.run(apply_override())

    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(
            max_positions=10,
            max_positions_per_symbol=10,
            max_total_exposure_pct=2.0,
        ),
        override_store=overrides,
    )
    payload = _decision_event(
        {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "size": 1.0, "entry_price": 100.0},
            "status": "accepted",
        }
    )

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_exposure_per_symbol_exceeded"
