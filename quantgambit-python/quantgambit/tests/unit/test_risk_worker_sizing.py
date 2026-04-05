import asyncio
import json

from quantgambit.risk.risk_worker import RiskWorker, RiskWorkerConfig
from quantgambit.storage.redis_streams import RedisStreamsClient
from quantgambit.portfolio.state_manager import InMemoryStateManager


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


class FakePriceProvider:
    def __init__(self, price):
        self.price = price

    def get_reference_price_with_ts(self, symbol):
        return self.price, 0.0


def _build_decision(symbol="BTC", size=None, stop_loss=None):
    return {
        "event_id": "1",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": symbol,
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "size": size, "entry_price": 100.0, "stop_loss": stop_loss},
            "status": "accepted",
        },
    }


def test_risk_worker_applies_notional_and_leverage_caps():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        price_provider=FakePriceProvider(100.0),
        config=RiskWorkerConfig(
            risk_per_trade_pct=1.0,  # intentionally high to force caps
            max_notional_total=200.0,
            max_notional_per_symbol=150.0,
            max_leverage=2.0,
            max_position_size_usd=None,
            min_position_size_usd=0.0,
        ),
    )
    payload = _build_decision()

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    sized = event_payload["payload"]["signal"]
    sizing_ctx = sized["sizing_context"]
    # Risk budget would be 1000*1.0 = 1000; leverage cap 2x -> 2000 notional / $100 = 20 units
    # But max_notional_total=200 and per_symbol=150 should cap to 1.5 units
    assert abs(sized["size"] - 1.5) < 1e-6
    assert sizing_ctx["max_notional_total"] == 200.0
    assert sizing_ctx["max_notional_symbol"] == 150.0
    assert sizing_ctx["leverage_cap_units"] >= 0


def test_risk_worker_rejects_when_notional_exhausted():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    state.add_position("BTC", "long", 2.0, reference_price=100.0)  # 200 notional
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        price_provider=FakePriceProvider(100.0),
        config=RiskWorkerConfig(
            risk_per_trade_pct=1.0,
            max_notional_total=200.0,
            max_notional_per_symbol=150.0,
            max_leverage=2.0,
            max_position_size_usd=None,
            min_position_size_usd=0.0,
        ),
    )
    payload = _build_decision()

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["status"] == "rejected"
    assert event_payload["payload"]["rejection_reason"] in {
        "exposure_limit",
        "max_net_exposure_exceeded",
        "max_exposure_per_symbol_exceeded",
        "max_positions_per_symbol_exceeded",
    }
