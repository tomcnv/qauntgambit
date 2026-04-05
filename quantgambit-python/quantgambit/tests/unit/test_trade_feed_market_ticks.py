import asyncio

from quantgambit.ingest.trade_feed import TradeFeedWorker, TradeFeedConfig
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.events = []

    async def xadd(self, stream, data):
        self.events.append((stream, data))
        return "1-0"


class FakeTradeProvider:
    def __init__(self, trade):
        self.trade = trade
        self._sent = False

    async def next_trade(self):
        if self._sent:
            await asyncio.sleep(0.01)
            return None
        self._sent = True
        return dict(self.trade)


def test_trade_feed_emits_market_tick_when_enabled():
    redis = FakeRedis()
    provider = FakeTradeProvider(
        {
            "symbol": "BTC-USDT-SWAP",
            "timestamp": 100.0,
            "price": 101.0,
            "size": 0.5,
            "side": "buy",
        }
    )
    worker = TradeFeedWorker(
        provider,
        RedisStreamsClient(redis),
        bot_id="b1",
        exchange="okx",
        config=TradeFeedConfig(emit_market_ticks=True),
    )

    async def run_once():
        trade = await provider.next_trade()
        await worker._publish_market_tick(trade)

    asyncio.run(run_once())
    assert any(stream == "events:market_data" for stream, _ in redis.events)
