import asyncio
import json

from quantgambit.diagnostics.health_worker import HealthWorker, HealthWorkerConfig
from quantgambit.io.backlog_policy import BacklogPolicyConfig, BacklogTier
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.ingest.monotonic_clock import MonotonicClock


class FakeRedis:
    def __init__(self, depths, consumer_lags=None):
        self.depths = depths
        self.consumer_lags = consumer_lags or {}
        self.data = {}
        self.redis = self  # For xinfo_groups access

    async def stream_length(self, stream):
        return self.depths.get(stream, 0)
    
    async def xinfo_groups(self, stream):
        """Return fake consumer group info with lag."""
        lag = self.consumer_lags.get(stream, 0)
        return [{"name": "quantgambit_test:t1:b1", "lag": lag}]
    
    async def keys(self, pattern):
        return []
    
    async def get(self, key):
        return self.data.get(key)


class FakeTelemetry:
    def __init__(self):
        self.payloads = []

    async def publish_latency(self, ctx, payload):
        self.payloads.append(("latency", payload))

    async def publish_health_snapshot(self, ctx, payload):
        self.payloads.append(("health", payload))


def test_health_worker_ok_when_depth_high_but_lag_zero():
    """High depth with lag=0 should NOT trigger overflow (when in soft tier)."""
    from quantgambit.io.backlog_policy import StreamBacklogConfig, StreamType
    
    redis = FakeRedis(
        depths={"events:market_data": 15000},  # Above soft but below hard
        consumer_lags={"events:market_data": 0},  # But lag=0 (caught up)
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(
            max_stream_depth=1000,  # Legacy threshold
            backlog_config=BacklogPolicyConfig(
                streams={
                    "events:market_data": StreamBacklogConfig(
                        stream_type=StreamType.MARKET_DATA,
                        soft_threshold=10000,  # 15000 is above soft
                        hard_threshold=30000,  # 15000 is below hard
                    ),
                },
                lag_soft_threshold=100,
                lag_hard_threshold=500,
            ),
        ),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads
    payload = health_payloads[-1]
    # Should NOT be overflow because lag=0 (soft tier with lag=0 is OK)
    assert payload["queue_overflow"] == False
    assert payload["status"] == "ok"
    assert payload.get("backlog_note") == "high_depth_but_caught_up"


def test_health_worker_degraded_on_depth_with_lag():
    """High depth WITH lag should trigger overflow."""
    redis = FakeRedis(
        depths={"events:market_data": 2000},
        consumer_lags={"events:market_data": 500},  # Has lag
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(
            max_stream_depth=1000,
            backlog_config=BacklogPolicyConfig(
                lag_soft_threshold=100,
                lag_hard_threshold=500,
            ),
        ),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads
    assert health_payloads[-1]["status"] == "degraded"
    assert health_payloads[-1]["queue_overflow"] == True


def test_health_worker_backlog_tier_hard_with_lag():
    """Hard tier WITH lag should trigger overflow."""
    from quantgambit.io.backlog_policy import StreamBacklogConfig, StreamType
    
    redis = FakeRedis(
        depths={"events:market_data": 40000},  # Above hard threshold
        consumer_lags={"events:market_data": 6000},  # Above hard lag threshold - HAS LAG
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(
            backlog_config=BacklogPolicyConfig(
                streams={
                    "events:market_data": StreamBacklogConfig(
                        stream_type=StreamType.MARKET_DATA,
                        soft_threshold=10000,
                        hard_threshold=30000,
                    ),
                },
                lag_soft_threshold=1000,
                lag_hard_threshold=5000,
            ),
        ),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads
    payload = health_payloads[-1]
    assert payload["backlog_tier"] == "hard"
    assert payload["queue_overflow"] == True
    assert payload["queue_overflow_reason"] == "hard_tier_with_lag"
    assert payload["status"] == "degraded"


def test_health_worker_backlog_tier_hard_no_lag_is_ok():
    """Hard tier with lag=0 should NOT trigger overflow (just high retention)."""
    from quantgambit.io.backlog_policy import StreamBacklogConfig, StreamType
    
    redis = FakeRedis(
        depths={"events:market_data": 40000},  # Above hard threshold
        consumer_lags={"events:market_data": 0},  # BUT lag=0 - consumers caught up!
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(
            backlog_config=BacklogPolicyConfig(
                streams={
                    "events:market_data": StreamBacklogConfig(
                        stream_type=StreamType.MARKET_DATA,
                        soft_threshold=10000,
                        hard_threshold=30000,
                    ),
                },
                lag_soft_threshold=1000,
                lag_hard_threshold=5000,
            ),
        ),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads
    payload = health_payloads[-1]
    assert payload["backlog_tier"] == "hard"  # Tier is still hard (depth-based)
    assert payload["queue_overflow"] == False  # But NOT overflow because lag=0
    assert payload["status"] == "ok"  # Status is OK
    assert payload.get("backlog_note") == "high_depth_but_caught_up"


def test_health_worker_emits_status_change():
    redis = FakeRedis(
        depths={"events:market_data": 0},
        consumer_lags={"events:market_data": 0},
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(
            max_stream_depth=1,
            backlog_config=BacklogPolicyConfig(
                lag_soft_threshold=1,
                lag_hard_threshold=5,
            ),
        ),
    )

    async def run_twice():
        await worker._emit_once()
        redis.depths["events:market_data"] = 10
        redis.consumer_lags["events:market_data"] = 10  # Add lag to trigger overflow
        await worker._emit_once()

    asyncio.run(run_twice())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads[0]["status_change"]["to"] == "ok"
    assert health_payloads[1]["status_change"]["to"] == "degraded"


def test_health_worker_reports_market_data_qa():
    redis = FakeRedis(depths={}, consumer_lags={})
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(max_stream_depth=1),
    )

    async def run_once():
        worker.record_market_tick(age_sec=0.5, is_stale=False, is_skew=True, is_gap=False, is_out_of_order=True)
        worker.record_market_tick(age_sec=0.6, is_stale=True, is_skew=False, is_gap=True, is_out_of_order=False)
        await worker._emit_once()

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads
    payload = health_payloads[-1]
    assert payload["market_data_stale_pct"] > 0.0
    assert payload["market_data_skew_pct"] > 0.0
    assert payload["market_data_gap_pct"] > 0.0
    assert payload["market_data_out_of_order_pct"] > 0.0
    assert payload["market_data_qps"] > 0.0
    assert payload["last_tick_age_sec"] == 0.6


def test_health_worker_reports_inactive_rejection_only_trading_activity():
    redis = FakeRedis(depths={"events:market_data": 0}, consumer_lags={})
    now = 1000.0
    redis.data["quantgambit:t1:b1:decision_activity:latest"] = json.dumps(
        {
            "timestamp": now - 240.0,
            "window_sec": 300.0,
            "last_decision_at": now - 240.0,
            "last_decision": "rejected",
            "last_rejection_reason": "no_signal",
            "last_rejection_stage": "signal_check",
            "last_accepted_at": None,
            "last_rejected_at": now - 240.0,
            "accepted_count": 0,
            "rejected_count": 12,
            "shadow_count": 0,
            "total_count": 12,
            "dominant_rejection_reason": "no_signal",
            "dominant_rejection_stage": "signal_check",
            "symbol_activity": [
                {
                    "symbol": "BTCUSDT",
                    "accepted_count": 0,
                    "rejected_count": 8,
                    "shadow_count": 0,
                    "total_count": 8,
                    "last_decision_at": now - 240.0,
                    "last_accepted_at": None,
                    "last_rejected_at": now - 240.0,
                    "dominant_rejection_reason": "no_signal",
                    "dominant_rejection_stage": "signal_check",
                },
                {
                    "symbol": "ETHUSDT",
                    "accepted_count": 0,
                    "rejected_count": 4,
                    "shadow_count": 0,
                    "total_count": 4,
                    "last_decision_at": now - 200.0,
                    "last_accepted_at": None,
                    "last_rejected_at": now - 200.0,
                    "dominant_rejection_reason": "stale_feature_snapshot",
                    "dominant_rejection_stage": "decision_worker_fast_skip",
                },
            ],
        }
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(
            inactivity_warn_sec=60.0,
            inactivity_degrade_sec=180.0,
        ),
    )

    async def run_once():
        import quantgambit.diagnostics.health_worker as hw
        original = hw.time.time
        hw.time.time = lambda: now
        try:
            await worker._emit_once()
        finally:
            hw.time.time = original

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads
    payload = health_payloads[-1]
    assert payload["status"] == "degraded"
    assert payload["trading_activity"]["status"] == "inactive"
    assert payload["trading_activity"]["dominant_rejection_reason"] == "no_signal"
    assert payload["trading_activity"]["dominant_rejection_stage"] == "signal_check"
    assert payload["trading_activity"]["top_rejected_symbol"] == "BTCUSDT"
    assert payload["trading_activity"]["top_rejected_symbol_reason"] == "no_signal"


def test_health_worker_degrades_on_execution_not_ready_when_not_paused():
    redis = FakeRedis(depths={"events:market_data": 0}, consumer_lags={})
    redis.data["quantgambit:t1:b1:control:state"] = json.dumps(
        {
            "trading_active": True,
            "trading_paused": False,
            "pause_reason": None,
            "execution_ready": False,
            "execution_block_reason": "orderbook_stale:BTCUSDT",
            "execution_last_checked_at": 123.0,
        }
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads
    payload = health_payloads[-1]
    assert payload["status"] == "degraded"
    assert payload["execution_readiness"]["execution_ready"] is False
    assert payload["execution_readiness"]["execution_block_reason"] == "orderbook_stale:BTCUSDT"


def test_health_worker_surfaces_kill_switch_and_trading_disabled_flags():
    redis = FakeRedis(depths={"events:market_data": 0}, consumer_lags={})
    redis.data["quantgambit:t1:b1:control:state"] = json.dumps(
        {
            "trading_active": True,
            "trading_paused": False,
            "pause_reason": None,
            "trading_disabled": True,
            "kill_switch_active": True,
            "config_drift_active": False,
            "exchange_credentials_configured": True,
            "execution_ready": False,
            "execution_block_reason": "kill_switch_active",
            "execution_last_checked_at": 321.0,
        }
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    payload = health_payloads[-1]
    assert payload["status"] == "degraded"
    assert payload["execution_readiness"]["trading_disabled"] is True
    assert payload["execution_readiness"]["kill_switch_active"] is True
    assert payload["execution_readiness"]["execution_block_reason"] == "kill_switch_active"


def test_health_worker_surfaces_missing_exchange_credentials():
    redis = FakeRedis(depths={"events:market_data": 0}, consumer_lags={})
    redis.data["quantgambit:t1:b1:control:state"] = json.dumps(
        {
            "trading_active": True,
            "trading_paused": False,
            "pause_reason": None,
            "trading_disabled": False,
            "kill_switch_active": False,
            "config_drift_active": False,
            "exchange_credentials_configured": False,
            "execution_ready": False,
            "execution_block_reason": "exchange_credentials_missing",
            "execution_last_checked_at": 400.0,
        }
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    payload = [payload for name, payload in telemetry.payloads if name == "health"][-1]
    assert payload["status"] == "degraded"
    assert payload["execution_readiness"]["exchange_credentials_configured"] is False
    assert payload["execution_readiness"]["execution_block_reason"] == "exchange_credentials_missing"


def test_health_worker_marks_live_perp_guard_misconfigured():
    redis = FakeRedis(depths={"events:market_data": 0}, consumer_lags={})
    redis.data["quantgambit:t1:b1:control:state"] = json.dumps(
        {
            "trading_active": True,
            "trading_paused": False,
            "pause_reason": None,
            "trading_disabled": False,
            "kill_switch_active": False,
            "config_drift_active": False,
            "exchange_credentials_configured": True,
            "execution_ready": True,
            "execution_block_reason": None,
            "execution_last_checked_at": 401.0,
        }
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(
            trading_mode="live",
            market_type="perp",
            position_guard_enabled=False,
            position_guard_max_age_sec=0.0,
            position_guard_max_age_hard_sec=0.0,
        ),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    payload = [payload for name, payload in telemetry.payloads if name == "health"][-1]
    assert payload["status"] == "degraded"
    assert payload["position_guardian"]["status"] == "misconfigured"
    assert payload["position_guardian"]["reason"] == "live_perp_guard_disabled"
    assert payload["services"]["position_guardian"]["status"] == "misconfigured"
    assert payload["execution_readiness"]["position_guard_status"] == "misconfigured"
    assert payload["execution_readiness"]["position_guard_reason"] == "live_perp_guard_disabled"


def test_health_worker_surfaces_exchange_auth_failure_from_guardrail():
    redis = FakeRedis(depths={"events:market_data": 0}, consumer_lags={})
    redis.data["quantgambit:t1:b1:control:state"] = json.dumps(
        {
            "trading_active": True,
            "trading_paused": False,
            "pause_reason": None,
            "trading_disabled": False,
            "kill_switch_active": False,
            "config_drift_active": False,
            "exchange_credentials_configured": True,
            "execution_ready": True,
            "execution_block_reason": None,
            "execution_last_checked_at": 500.0,
        }
    )
    redis.data["quantgambit:t1:b1:guardrail:latest"] = json.dumps(
        {
            "type": "auth_failed",
            "provider": "order_updates",
            "reason": "login_failed",
            "detail": "bad_key",
        }
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    payload = [payload for name, payload in telemetry.payloads if name == "health"][-1]
    assert payload["status"] == "degraded"
    assert payload["exchange_session"]["status"] == "exchange_auth_failed:order_updates"
    assert payload["execution_readiness"]["execution_ready"] is False
    assert payload["execution_readiness"]["execution_block_reason"] == "exchange_auth_failed:order_updates"


def test_health_worker_includes_orderbook_issue_summary():
    redis = FakeRedis(depths={"events:market_data": 0})
    telemetry = FakeTelemetry()
    quality = MarketDataQualityTracker()
    quality.update_orderbook(symbol="BTC", timestamp=100.0, now_ts=100.0, gap=True)
    quality.update_orderbook(symbol="ETH", timestamp=101.0, now_ts=101.0, out_of_order=True)
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        quality_tracker=quality,
        config=HealthWorkerConfig(max_stream_depth=1),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads
    payload = health_payloads[-1]
    assert "orderbook_issue_summary" in payload
    summary = payload["orderbook_issue_summary"]
    assert {"symbol": "BTC", "orderbook_gap_count": 1, "orderbook_out_of_order_count": 0} in summary
    assert {"symbol": "ETH", "orderbook_gap_count": 0, "orderbook_out_of_order_count": 1} in summary


def test_health_worker_includes_monotonic_clock_summary():
    redis = FakeRedis(depths={"events:market_data": 0})
    telemetry = FakeTelemetry()
    clock = MonotonicClock()
    clock.update("BTC", 100)
    clock.update("BTC", 100)
    clock.update("ETH", 200)
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        monotonic_clock=clock,
        config=HealthWorkerConfig(max_stream_depth=1),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads
    payload = health_payloads[-1]
    assert "monotonic_clock_summary" in payload
    summary = payload["monotonic_clock_summary"]
    assert {"symbol": "BTC", "monotonic_adjustments_count": 1, "monotonic_total_drift_us": 1, "monotonic_max_adjustment_us": 1} in summary


def test_health_worker_backlog_metrics():
    """Test that backlog metrics are included in payload."""
    redis = FakeRedis(
        depths={"events:market_data": 5000, "events:features": 3000},
        consumer_lags={"events:market_data": 100, "events:features": 50},
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(
            streams=["events:market_data", "events:features"],
        ),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    health_payloads = [payload for name, payload in telemetry.payloads if name == "health"]
    assert health_payloads
    payload = health_payloads[-1]
    
    # Check backlog metrics are present
    assert "backlog_tier" in payload
    assert "backlog_total_depth" in payload
    assert "backlog_total_lag" in payload
    assert payload["backlog_total_depth"] == 8000
    assert payload["backlog_total_lag"] == 150
    
    # Check per-stream depths
    assert payload["events:market_data_depth"] == 5000
    assert payload["events:features_depth"] == 3000
    
    # Check per-stream lags
    assert payload["events:market_data_lag"] == 100
    assert payload["events:features_lag"] == 50


def test_health_worker_should_reduce_size():
    """Test should_reduce_size helper."""
    redis = FakeRedis(
        depths={"events:market_data": 15000},  # Above soft threshold
        consumer_lags={"events:market_data": 2000},  # Above soft lag threshold
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(
            backlog_config=BacklogPolicyConfig(
                lag_soft_threshold=1000,
                lag_hard_threshold=5000,
            ),
        ),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    
    # Should recommend reducing size due to soft tier
    assert worker.should_reduce_size() == True
    assert worker.should_block_entries() == False  # Not hard tier


def test_health_worker_should_block_entries():
    """Test should_block_entries helper."""
    redis = FakeRedis(
        depths={"events:market_data": 40000},  # Above hard threshold
        consumer_lags={"events:market_data": 10000},  # Above hard lag threshold
    )
    telemetry = FakeTelemetry()
    worker = HealthWorker(
        redis_client=redis,
        telemetry=telemetry,
        telemetry_context=type("ctx", (), {"tenant_id": "t1", "bot_id": "b1"})(),
        config=HealthWorkerConfig(
            backlog_config=BacklogPolicyConfig(
                lag_soft_threshold=1000,
                lag_hard_threshold=5000,
            ),
        ),
    )

    async def run_once():
        await worker._emit_once()

    asyncio.run(run_once())
    
    # Should block entries due to hard tier
    assert worker.should_reduce_size() == True
    assert worker.should_block_entries() == True
