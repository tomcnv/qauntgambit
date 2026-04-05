import asyncio

from quantgambit.config.watcher import ConfigWatcher
from quantgambit.config.models import BotConfig
from quantgambit.runtime.config_apply import RuntimeConfigApplier
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    async def xadd(self, stream, data):
        return "1-0"

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return True

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return True


class FakeApplier:
    def __init__(self, apply_result):
        self.apply_result = apply_result
        self.applied = 0

    async def apply(self, config):
        self.applied += 1
        return self.apply_result


def test_config_watcher_apply_result():
    watcher = ConfigWatcher(RedisStreamsClient(FakeRedis()), FakeApplier(True))
    assert watcher.applier.apply_result is True


def test_config_applier_updates_trading_hours():
    class FakeRuntime:
        def __init__(self):
            self.config = type(
                "cfg",
                (),
                {
                    "exchange": "okx",
                    "trading_mode": "live",
                    "trading_hours_start": 0,
                    "trading_hours_end": 24,
                    "order_intent_max_age_sec": None,
                },
            )()
            self.telemetry_ctx = type("ctx", (), {"exchange": "okx"})()
            self.state_manager = None
            self.execution_adapter = None
            self.exchange_router = None
            self.reconciler = None
            self.adapter_config = None
            self.paper_fill_engine = None
            self.paper_config = None
            self.redis_client = RedisStreamsClient(FakeRedis())
            self.reference_prices = None
            self.execution_manager = type("exec", (), {"position_manager": None})()
            self.action_handler = type("handler", (), {"execution_manager": None})()
            self.config_watcher = type("watcher", (), {"applier": type("ap", (), {"position_manager": None})()})()
            self.order_store = type("store", (), {"_max_intent_age_sec": None})()
            self.feature_worker = type(
                "feature",
                (),
                {
                    "config": type(
                        "cfg",
                        (),
                        {"trading_session_start_hour_utc": 0, "trading_session_end_hour_utc": 24},
                    )()
                },
            )()

    runtime = FakeRuntime()
    applier = RuntimeConfigApplier(runtime)
    cfg = BotConfig(
        tenant_id="t1",
        bot_id="b1",
        version=1,
        trading_mode="live",
        active_exchange="okx",
        symbols=["BTC"],
        trading_hours={"start_hour_utc": 9, "end_hour_utc": 17},
        order_intent_max_age_sec=120.0,
    )

    asyncio.run(applier.apply(cfg))
    assert runtime.config.trading_hours_start == 9
    assert runtime.config.trading_hours_end == 17
    assert runtime.feature_worker.config.trading_session_start_hour_utc == 9
    assert runtime.feature_worker.config.trading_session_end_hour_utc == 17
    assert runtime.config.order_intent_max_age_sec == 120.0
    assert runtime.order_store._max_intent_age_sec == 120.0
