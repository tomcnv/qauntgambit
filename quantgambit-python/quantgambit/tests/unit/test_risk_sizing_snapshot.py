import asyncio

from quantgambit.risk.risk_worker import RiskWorker, RiskWorkerConfig
from quantgambit.storage.redis_streams import RedisStreamsClient
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.risk.overrides import RiskOverrideStore


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        # One accepted decision event
        payload = {
            "event_id": "1",
            "event_type": "decision",
            "schema_version": "v1",
            "timestamp": "1",
            "ts_recv_us": 1000000,
            "ts_canon_us": 1000000,
            "ts_exchange_s": None,
            "bot_id": "b1",
            "payload": {
                "symbol": "BTCUSDT",
                "timestamp": 1,
                "decision": "accepted",
                "signal": {"side": "buy", "size": 1.0, "entry_price": 25000.0},
                "status": "accepted",
            },
        }
        return [("events:decisions", [("1-0", {"data": RedisStreamsClient.encode_event(payload)})])]

    async def xack(self, stream, group, message_id):
        return 1

    async def xadd(self, stream, data, **kwargs):
        return "1-0"

    async def set(self, key, value):
        self.data[key] = value

    async def expire(self, key, ttl):
        return True

    async def write(self, key, payload):
        # Allow use as snapshot_writer
        self.data[key] = payload


async def _run_worker():
    redis = FakeRedis()
    state_manager = InMemoryStateManager()
    state_manager.update_account_state(equity=173020.43, peak_balance=173020.43)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state_manager,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(account_equity=10000.0, max_total_exposure_pct=0.10, max_notional_total=5000.0),
        override_store=RiskOverrideStore(),
        snapshot_writer=redis,
        snapshot_key="risk:latest_decision",
    )
    # Minimal decision event payload
    await worker._handle_message(
            {
                "data": '{"event_id":"1","event_type":"decision","schema_version":"v1","timestamp":"1","ts_recv_us":1000000,"ts_canon_us":1000000,"ts_exchange_s":null,"bot_id":"b1","payload":{"symbol":"BTCUSDT","timestamp":1,"decision":"accepted","signal":{"side":"buy","size":1.0,"entry_price":25000.0},"status":"accepted"}}'
            }
        )
    return redis


def test_risk_worker_writes_sizing_snapshot():
    redis = asyncio.run(_run_worker())
    assert "risk:latest_decision" in redis.data
    payload = redis.data["risk:latest_decision"]
    assert payload["limits"]["max_total_exposure_pct"] == 0.10
    assert payload["limits"]["max_notional_total"] == 5000.0
    assert payload["remaining"]["total_usd"] is not None
    assert payload["equity"] == 173020.43
    assert payload["account_balance"] == 173020.43
    assert payload["account_equity"] == 173020.43
    assert payload["deployable_capital"] == 10000.0
