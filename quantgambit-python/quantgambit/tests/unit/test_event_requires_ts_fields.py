import pytest

from quantgambit.storage.redis_streams import Event, RedisStreamsClient


class FakeRedis:
    async def xadd(self, stream, data, maxlen=None, approximate=None):
        return "1-0"


@pytest.mark.asyncio
async def test_publish_event_requires_ts_fields():
    client = RedisStreamsClient(FakeRedis())
    event = Event(
        event_id="e1",
        event_type="test",
        schema_version="v1",
        timestamp="0",
        ts_recv_us=None,
        ts_canon_us=None,
        ts_exchange_s=None,
        bot_id="b1",
        payload={"ok": True},
    )
    with pytest.raises(ValueError):
        await client.publish_event("events:test", event)
