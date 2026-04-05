from quantgambit.runtime.app import Runtime, RuntimeConfig
from quantgambit.portfolio.state_manager import InMemoryStateManager


class FakeRedis:
    pass


class DummyOrderbookProvider:
    def set_telemetry(self, telemetry, ctx):
        return None


class DummyMarketProvider:
    async def next_tick(self):
        return None


def test_runtime_applies_orderbook_feed_env(monkeypatch):
    monkeypatch.setenv("ORDERBOOK_TIMESTAMP_SOURCE", "local")
    monkeypatch.setenv("ORDERBOOK_MAX_CLOCK_SKEW_SEC", "1.25")
    runtime = Runtime(
        config=RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="okx", trading_mode="paper"),
        redis=FakeRedis(),
        timescale_pool=None,
        state_manager=InMemoryStateManager(),
        market_data_provider=DummyMarketProvider(),
        orderbook_provider=DummyOrderbookProvider(),
    )
    cfg = runtime.orderbook_feed_worker.config
    assert cfg.timestamp_source == "local"
    assert cfg.max_clock_skew_sec == 1.25
