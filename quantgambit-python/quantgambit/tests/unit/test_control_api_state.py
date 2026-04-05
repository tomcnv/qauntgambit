import asyncio
import json

from quantgambit.control.api import ControlAPI
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.kv = {}
        self.lists = {}

    async def get(self, key):
        return self.kv.get(key)

    async def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        return values[start : end + 1]


def test_control_api_fetches_state_and_history():
    redis = FakeRedis()
    state_key = "quantgambit:t1:b1:control:state"
    history_key = "quantgambit:t1:b1:control:command_history"
    redis.kv[state_key] = json.dumps(
        {
            "trading_paused": True,
            "pause_reason": "manual",
            "failover_state": "armed",
            "primary_exchange": "okx",
            "secondary_exchange": "bybit",
            "timestamp": "2024-01-01T00:00:00Z",
        }
    )
    redis.lists[history_key] = [
        json.dumps({"command_id": "c1", "status": "executed", "message": "ok"}),
        json.dumps({"command_id": "c2", "status": "failed", "message": "nope"}),
    ]

    api = ControlAPI(RedisStreamsClient(redis))

    state = asyncio.run(api._fetch_state("t1", "b1"))
    history = asyncio.run(api._fetch_command_history("t1", "b1", limit=10))

    assert state.trading_paused is True
    assert state.primary_exchange == "okx"
    assert len(history.items) == 2
