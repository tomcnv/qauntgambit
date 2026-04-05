import asyncio
from quantgambit.control.command_manager import ControlManager
import json


def test_build_runtime_env_bybit_demo_overrides_testnet():
    manager = ControlManager.__new__(ControlManager)
    manager.default_env = {}
    scope = {}
    payload = {
        "exchange": "bybit",
        "is_demo": True,
        "is_testnet": True,
    }
    env, _parity = manager._build_runtime_env(scope, payload, include_diagnostics=True)
    assert env["ORDER_UPDATES_DEMO"] == "true"
    assert env["ORDERBOOK_TESTNET"] == "false"
    assert env["TRADE_TESTNET"] == "false"
    assert env["ORDER_UPDATES_TESTNET"] == "false"
    assert env["MARKET_DATA_TESTNET"] == "false"
    assert env["BYBIT_DEMO"] == "true"
    assert env["BYBIT_TESTNET"] == "false"


def test_build_runtime_env_testnet_sets_exchange_flag():
    manager = ControlManager.__new__(ControlManager)
    manager.default_env = {}
    scope = {}
    payload = {
        "exchange": "bybit",
        "is_testnet": True,
    }
    env, _parity = manager._build_runtime_env(scope, payload, include_diagnostics=True)
    assert env["ORDERBOOK_TESTNET"] == "true"
    assert env["ORDER_UPDATES_TESTNET"] == "true"
    assert env["BYBIT_TESTNET"] == "true"


def test_build_runtime_env_allow_all_sessions_disables_session_filter():
    manager = ControlManager.__new__(ControlManager)
    manager.default_env = {}
    scope = {}
    payload = {
        "profile_overrides": {
            "bot_type": "standard",
            "allow_all_sessions": True,
        }
    }
    env, _parity = manager._build_runtime_env(scope, payload, include_diagnostics=True)
    assert env["SESSION_FILTER_ENABLED"] == "false"
    assert env["SESSION_FILTER_ENFORCE_PREFERENCES"] == "false"
    assert env["SESSION_FILTER_ENFORCE_STRATEGY_SESSIONS"] == "false"


def test_assess_runtime_health_accepts_running_engine():
    ok, detail = ControlManager._assess_runtime_health(
        {
            "status": "ok",
            "services": {
                "python_engine": {
                    "status": "running",
                }
            },
        }
    )
    assert ok is True
    assert detail == "runtime_ready"


def test_assess_runtime_health_accepts_warmup_pending_runtime():
    ok, detail = ControlManager._assess_runtime_health(
        {
            "status": "degraded",
            "warmup_pending": True,
            "services": {
                "python_engine": {
                    "status": "running",
                }
            },
        }
    )
    assert ok is True
    assert detail == "runtime_warmup"


def test_assess_runtime_health_accepts_starting_warmup_runtime():
    ok, detail = ControlManager._assess_runtime_health(
        {
            "status": "starting",
            "warmup_pending": True,
            "services": {
                "python_engine": {
                    "status": "running",
                }
            },
        }
    )
    assert ok is True
    assert detail == "runtime_warmup"


def test_assess_runtime_health_rejects_synthetic_starting_snapshot():
    ok, detail = ControlManager._assess_runtime_health(
        {
            "status": "starting",
            "warmup_pending": True,
            "control_synthetic": True,
            "services": {
                "python_engine": {
                    "status": "running",
                }
            },
        }
    )
    assert ok is False
    assert detail == "runtime_health_pending"


def test_assess_runtime_health_rejects_stopped_runtime():
    ok, detail = ControlManager._assess_runtime_health(
        {
            "status": "stopped",
            "services": {
                "python_engine": {
                    "status": "stopped",
                }
            },
        }
    )
    assert ok is False
    assert detail == "health_status:stopped"


def test_publish_starting_health_writes_warmup_snapshot():
    class FakeRedis:
        def __init__(self):
            self.writes = {}

        async def set(self, key, value, ex=None):
            self.writes[key] = {"value": value, "ex": ex}
            return True

    manager = ControlManager.__new__(ControlManager)
    fake_redis = FakeRedis()
    manager.redis_client = type("FakeClient", (), {"redis": fake_redis})()

    import asyncio
    asyncio.run(
        manager._publish_starting_health(
            "t1",
            "b1",
            {"exchange": "bybit", "trading_mode": "live"},
        )
    )

    record = fake_redis.writes["quantgambit:t1:b1:health:latest"]
    payload = json.loads(record["value"])
    assert payload["status"] == "starting"
    assert payload["warmup_pending"] is True
    assert payload["control_synthetic"] is True
    assert payload["services"]["python_engine"]["status"] == "running"
    assert record["ex"] == 90


def test_wait_for_runtime_ready_requires_real_pm2_runtime():
    class FakeReader:
        async def read(self, key):
            return {
                "status": "starting",
                "warmup_pending": True,
                "control_synthetic": True,
                "services": {"python_engine": {"status": "running"}},
            }

    manager = ControlManager.__new__(ControlManager)
    manager.snapshot_reader = FakeReader()
    manager.launch_mode = "pm2"
    manager.ready_timeout_sec = 0.01
    manager.ready_poll_interval_sec = 0.005
    manager._runtime_launch_observed = lambda tenant_id, bot_id: asyncio.sleep(0, result=False)

    ok, detail = asyncio.run(manager._wait_for_runtime_ready("t1", "b1"))
    assert ok is False
    assert detail == "runtime_process_missing"


def test_wait_for_runtime_ready_accepts_real_health_without_pm2_observation():
    class FakeReader:
        async def read(self, key):
            return {
                "status": "ok",
                "services": {"python_engine": {"status": "running"}},
            }

    manager = ControlManager.__new__(ControlManager)
    manager.snapshot_reader = FakeReader()
    manager.launch_mode = "pm2"
    manager.ready_timeout_sec = 0.05
    manager.ready_poll_interval_sec = 0.005
    manager._runtime_launch_observed = lambda tenant_id, bot_id: asyncio.sleep(0, result=False)

    ok, detail = asyncio.run(manager._wait_for_runtime_ready("t1", "b1"))
    assert ok is True
    assert detail == "runtime_ready"


def test_wait_for_runtime_ready_ignores_synthetic_health_until_real_snapshot():
    class FakeReader:
        def __init__(self):
            self.calls = 0

        async def read(self, key):
            self.calls += 1
            if self.calls == 1:
                return {
                    "status": "starting",
                    "warmup_pending": True,
                    "control_synthetic": True,
                    "services": {"python_engine": {"status": "running"}},
                }
            return {
                "status": "degraded",
                "warmup_pending": True,
                "services": {"python_engine": {"status": "running"}},
            }

    manager = ControlManager.__new__(ControlManager)
    manager.snapshot_reader = FakeReader()
    manager.launch_mode = "pm2"
    manager.ready_timeout_sec = 0.2
    manager.ready_poll_interval_sec = 0.005
    manager._runtime_launch_observed = lambda tenant_id, bot_id: asyncio.sleep(0, result=True)

    ok, detail = asyncio.run(manager._wait_for_runtime_ready("t1", "b1"))
    assert ok is True
    assert detail == "runtime_warmup"


def test_build_runtime_env_ai_spot_swing_selects_deepseek_provider():
    manager = ControlManager.__new__(ControlManager)
    manager.default_env = {
        "PREDICTION_PROVIDER": "onnx",
        "PREDICTION_MODEL_PATH": "prediction_scalp.onnx",
        "PREDICTION_MODEL_CONFIG": "models/registry/latest.json",
    }
    manager._load_runtime_env_defaults = lambda _env_file: dict(manager.default_env)
    scope = {}
    payload = {
        "exchange": "bybit",
        "market_type": "spot",
        "profile_overrides": {
            "bot_type": "ai_spot_swing",
            "ai_provider": "deepseek_context",
            "ai_confidence_floor": 0.81,
            "ai_shadow_mode": False,
            "ai_sessions": ["london", "ny"],
        },
    }
    env, _parity = manager._build_runtime_env(scope, payload, include_diagnostics=True)
    assert env["PREDICTION_PROVIDER"] == "deepseek_context"
    assert "PREDICTION_MODEL_PATH" not in env
    assert "PREDICTION_MODEL_CONFIG" not in env
    assert env["AI_PROVIDER_MIN_CONFIDENCE"] == "0.81"
    assert env["AI_SHADOW_ONLY"] == "false"
    assert env["AI_ENABLED_SESSIONS"] == "london,ny"
    assert env["AI_PROVIDER_TIMEOUT_MS"] == "5000"
    assert env["COPILOT_LLM_TIMEOUT_SEC"] == "5.0"
    assert env["DATA_READINESS_TRADE_LAG_GREEN_MS"] == "1000"
    assert env["DATA_READINESS_TRADE_LAG_YELLOW_MS"] == "2500"
    assert env["DATA_READINESS_TRADE_LAG_RED_MS"] == "5000"


def test_build_runtime_env_ai_shadow_mode_keeps_live_provider_and_scopes_snapshot_keys():
    manager = ControlManager.__new__(ControlManager)
    manager.default_env = {
        "PREDICTION_PROVIDER": "heuristic",
        "PREDICTION_SCORE_SNAPSHOT_KEY": "quantgambit:foreign-tenant:foreign-bot:prediction:score:latest",
    }
    manager._load_runtime_env_defaults = lambda _env_file: dict(manager.default_env)
    scope = {
        "tenant_id": "t1",
        "bot_id": "b1",
    }
    payload = {
        "tenant_id": "t1",
        "bot_id": "b1",
        "exchange": "bybit",
        "market_type": "spot",
        "profile_overrides": {
            "bot_type": "ai_spot_swing",
            "ai_provider": "deepseek_context",
            "ai_shadow_mode": True,
        },
    }
    env, _parity = manager._build_runtime_env(scope, payload, include_diagnostics=True)
    assert env["PREDICTION_PROVIDER"] == "heuristic"
    assert env["PREDICTION_SHADOW_PROVIDER"] == "deepseek_context"
    assert env["AI_SHADOW_ONLY"] == "true"
    assert env["MODEL_DIRECTION_ALIGNMENT_ALLOW_MISSING_PREDICTION"] == "true"
    assert env["PREDICTION_SCORE_SNAPSHOT_KEY"] == "quantgambit:t1:b1:prediction:score:latest"
    assert env["PREDICTION_DRIFT_SNAPSHOT_KEY"] == "quantgambit:t1:b1:prediction:drift:latest"


def test_build_runtime_env_payload_values_override_env_file_defaults():
    manager = ControlManager.__new__(ControlManager)
    manager.default_env = {}
    manager._load_runtime_env_defaults = lambda _env_file: {
        "PREDICTION_PROVIDER": "onnx",
        "PREDICTION_MODEL_PATH": "prediction_scalp.onnx",
        "EXECUTION_PROVIDER": "none",
        "ORDERBOOK_SOURCE": "internal",
    }
    scope = {}
    payload = {
        "exchange": "bybit",
        "market_type": "spot",
        "execution_provider": "ccxt",
        "orderbook_source": "external",
        "profile_overrides": {
            "bot_type": "ai_spot_swing",
            "ai_provider": "deepseek_context",
        },
    }
    env, _parity = manager._build_runtime_env(scope, payload, include_diagnostics=True)
    assert env["EXECUTION_PROVIDER"] == "ccxt"
    assert env["ORDERBOOK_SOURCE"] == "external"
    assert env["PREDICTION_PROVIDER"] == "deepseek_context"
    assert "PREDICTION_MODEL_PATH" not in env


def test_build_runtime_env_derives_spot_streams_when_payload_streams_missing():
    manager = ControlManager.__new__(ControlManager)
    manager.default_env = {}
    scope = {}
    payload = {
        "exchange": "bybit",
        "market_type": "spot",
    }
    env, _parity = manager._build_runtime_env(scope, payload, include_diagnostics=True)
    assert env["ORDERBOOK_EVENT_STREAM"] == "events:orderbook_feed:bybit:spot"
    assert env["TRADE_STREAM"] == "events:trades:bybit:spot"
    assert env["MARKET_DATA_STREAM"] == "events:market_data:bybit:spot"


def test_build_runtime_env_live_standard_sets_trade_lag_defaults_in_payload():
    manager = ControlManager.__new__(ControlManager)
    manager.default_env = {}
    manager._load_runtime_env_defaults = lambda _env_file: {}
    scope = {}
    payload = {
        "exchange": "bybit",
        "market_type": "perp",
        "trading_mode": "live",
        "profile_overrides": {
            "bot_type": "standard",
        },
    }
    env, _parity = manager._build_runtime_env(scope, payload, include_diagnostics=True)
    assert env["ENV_FILE"] == ".env.runtime-live"
    assert env["DATA_READINESS_TRADE_LAG_GREEN_MS"] == "1500"
    assert env["DATA_READINESS_TRADE_LAG_YELLOW_MS"] == "4000"
    assert env["DATA_READINESS_TRADE_LAG_RED_MS"] == "6000"


def test_build_runtime_env_preserves_explicit_streams():
    manager = ControlManager.__new__(ControlManager)
    manager.default_env = {}
    scope = {}
    payload = {
        "exchange": "bybit",
        "market_type": "spot",
        "streams": {
            "orderbook": "events:orderbook_feed:custom",
            "trades": "events:trades:custom",
            "market": "events:market_data:custom",
        },
    }
    env, _parity = manager._build_runtime_env(scope, payload, include_diagnostics=True)
    assert env["ORDERBOOK_EVENT_STREAM"] == "events:orderbook_feed:custom"
    assert env["TRADE_STREAM"] == "events:trades:custom"
    assert env["MARKET_DATA_STREAM"] == "events:market_data:custom"
