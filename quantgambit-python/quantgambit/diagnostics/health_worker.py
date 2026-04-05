"""Health and diagnostics worker with tiered backlog management."""

from __future__ import annotations

import asyncio
import time
import json
from dataclasses import dataclass, field
from typing import Iterable, Optional, Dict

from quantgambit.observability.logger import log_info, log_warning
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.ingest.monotonic_clock import MonotonicClock
from quantgambit.ingest.time_utils import consume_future_event_excluded_count
from quantgambit.storage.redis_streams import RedisStreamsClient
from quantgambit.io.backlog_policy import (
    BacklogPolicy,
    BacklogPolicyConfig,
    BacklogTier,
    StreamBacklogConfig,
    StreamType,
)


@dataclass
class HealthWorkerConfig:
    """
    Configuration for the health worker.
    
    Attributes:
        streams: Stream names to monitor
        interval_sec: Health check interval
        # Legacy threshold (deprecated - use backlog_config instead)
        max_stream_depth: Deprecated, use backlog_config.streams[].soft_threshold
        # Backlog policy configuration
        backlog_config: Tiered backlog policy configuration
        # Consumer lag tracking
        track_consumer_lag: Whether to track consumer lag
        consumer_groups: Consumer group names per stream for lag tracking
    """
    
    streams: Iterable[str] = ("events:market_data", "events:features", "events:decisions")
    interval_sec: float = 5.0
    max_stream_depth: int = 1000  # Deprecated, kept for backward compat
    backlog_config: Optional[BacklogPolicyConfig] = None
    track_consumer_lag: bool = True
    consumer_groups: Dict[str, str] = field(default_factory=dict)
    inactivity_warn_sec: float = 60.0
    inactivity_degrade_sec: float = 180.0
    trading_mode: str = "live"
    market_type: str = "perp"
    position_guard_enabled: bool = False
    position_guard_max_age_sec: float = 0.0
    position_guard_max_age_hard_sec: float = 0.0
    position_guard_tp_limit_exit_enabled: bool = False


class HealthWorker:
    """
    Periodically emits queue depth and heartbeat telemetry.
    
    Now with tiered backlog management:
    - NORMAL: All systems go
    - SOFT: Elevated backlog, warn and reduce position sizes
    - HARD: Critical backlog, may trim/compact with resync
    
    The queue_overflow flag is replaced with backlog_tier which provides
    more nuanced signaling based on both depth AND consumer lag.
    """

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        telemetry: TelemetryPipeline,
        telemetry_context: TelemetryContext,
        quality_tracker: Optional[MarketDataQualityTracker] = None,
        monotonic_clock: Optional[MonotonicClock] = None,
        config: Optional[HealthWorkerConfig] = None,
    ):
        self.redis = redis_client
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.quality_tracker = quality_tracker
        self.monotonic_clock = monotonic_clock
        self.config = config or HealthWorkerConfig()
        self._last_status: Optional[str] = None
        self._last_tick_age_sec: Optional[float] = None
        self._qa_counts: dict[str, int] = {"stale": 0, "skew": 0, "gap": 0, "out_of_order": 0, "total": 0}
        self._qa_last_report: float = time.time()
        
        # Initialize backlog policy
        backlog_cfg = self.config.backlog_config or BacklogPolicyConfig()
        self._backlog_policy = BacklogPolicy(
            config=backlog_cfg,
            # Callbacks will be set by runtime if needed
            trim_callback=None,
            resync_callback=None,
            compact_callback=None,
        )

    async def run(self) -> None:
        log_info("health_worker_start", streams=list(self.config.streams))
        while True:
            await self._emit_once()
            await asyncio.sleep(self.config.interval_sec)

    async def _emit_once(self) -> None:
        now = time.time()
        payload = {"health_heartbeat": True, "timestamp": now}
        status = "ok"
        
        # Collect stream depths
        stream_depths: Dict[str, int] = {}
        for stream in self.config.streams:
            length = await self.redis.stream_length(stream)
            stream_depths[stream] = length
            payload[f"{stream}_depth"] = length
        
        # Collect consumer lag if enabled
        consumer_lags: Dict[str, int] = {}
        if self.config.track_consumer_lag:
            consumer_lags = await self._get_consumer_lags()
            for stream, lag in consumer_lags.items():
                payload[f"{stream}_lag"] = lag
        
        # Check backlog policy and get tier
        backlog_metrics = await self._backlog_policy.check_and_enforce(
            stream_depths=stream_depths,
            consumer_lags=consumer_lags,
        )
        
        # Add backlog metrics to payload
        payload["backlog_tier"] = backlog_metrics.overall_tier.value
        payload["backlog_total_depth"] = backlog_metrics.total_depth
        payload["backlog_total_lag"] = backlog_metrics.total_lag
        payload["backlog_trimmed"] = backlog_metrics.total_trimmed
        payload["backlog_compacted"] = backlog_metrics.total_compacted
        payload["backlog_resyncs"] = backlog_metrics.total_resyncs
        
        # Per-stream tier info
        stream_tiers = {}
        for stream_name, state in backlog_metrics.streams.items():
            stream_tiers[stream_name] = state.tier.value
        payload["stream_tiers"] = stream_tiers
        
        # Determine status based on backlog tier AND lag
        # CRITICAL: queue_overflow requires BOTH high tier AND lag > 0
        # High depth with lag=0 means consumers are caught up - just high retention, not overflow
        if backlog_metrics.total_lag > 0:
            # There's actual lag - consumers are behind
            if backlog_metrics.overall_tier == BacklogTier.HARD:
                status = "degraded"
                payload["queue_overflow"] = True
                payload["queue_overflow_reason"] = "hard_tier_with_lag"
            elif backlog_metrics.overall_tier == BacklogTier.SOFT:
                status = "degraded"
                payload["queue_overflow"] = True
                payload["queue_overflow_reason"] = "soft_tier_with_lag"
            else:
                payload["queue_overflow"] = False
        else:
            # lag=0: consumers are caught up, regardless of depth
            # This is NOT overflow - just high retention
            payload["queue_overflow"] = False
            if backlog_metrics.overall_tier in (BacklogTier.SOFT, BacklogTier.HARD):
                payload["backlog_note"] = "high_depth_but_caught_up"
                # Still report the tier for visibility, but don't degrade
                payload["backlog_tier_info"] = f"{backlog_metrics.overall_tier.value}_lag_zero"
        
        # Legacy compatibility: check old threshold too
        # But only trigger overflow if lag > 0
        for stream in self.config.streams:
            length = stream_depths.get(stream, 0)
            lag = consumer_lags.get(stream, 0)
            if length > self.config.max_stream_depth and lag > 0:
                # Only flag overflow if there's actual lag
                if not payload.get("queue_overflow"):
                    status = "degraded"
                    payload["queue_overflow"] = True
                    payload["queue_overflow_reason"] = "legacy_threshold_with_lag"
        
        qa_payload = self._consume_qa_metrics()
        if qa_payload:
            payload.update(qa_payload)
            # If any QA metrics are present (non-zero), treat as degraded
            if any(
                qa_payload.get(k, 0) > 0
                for k in (
                    "market_data_stale_pct",
                    "market_data_skew_pct",
                    "market_data_gap_pct",
                    "market_data_out_of_order_pct",
                )
            ):
                status = "degraded"

        if self.quality_tracker is not None:
            payload["orderbook_issue_summary"] = self.quality_tracker.orderbook_issue_summary()
        if self.monotonic_clock is not None:
            payload["monotonic_clock_summary"] = self.monotonic_clock.summary()
        future_excluded = consume_future_event_excluded_count()
        if future_excluded > 0:
            payload["future_event_excluded_count"] = future_excluded
        candle_summary = await self._read_candle_late_tick_summary()
        if candle_summary:
            payload["candle_late_tick_summary"] = candle_summary
        
        # Warmup gating: if any warmup keys are not ready, degrade and surface flag
        warmup_not_ready, warmup_counts = await self._check_warmup()
        if warmup_counts:
            payload.update(warmup_counts)
        if warmup_not_ready:
            payload["warmup_pending"] = True
            status = "degraded"

        control_state = await self._read_control_state()
        if control_state:
            execution_readiness = {
                "trading_active": bool(control_state.get("trading_active", not bool(control_state.get("trading_paused")))),
                "trading_paused": bool(control_state.get("trading_paused")),
                "pause_reason": control_state.get("pause_reason"),
                "trading_disabled": bool(control_state.get("trading_disabled")),
                "kill_switch_active": bool(control_state.get("kill_switch_active")),
                "config_drift_active": bool(control_state.get("config_drift_active")),
                "exchange_credentials_configured": bool(control_state.get("exchange_credentials_configured")),
                "execution_ready": bool(control_state.get("execution_ready")),
                "execution_block_reason": control_state.get("execution_block_reason"),
                "execution_last_checked_at": control_state.get("execution_last_checked_at"),
            }
            payload["execution_readiness"] = execution_readiness
            pause_reason = str(execution_readiness.get("pause_reason") or "").strip().lower()
            paused = bool(execution_readiness["trading_paused"])
            execution_ready = bool(execution_readiness["execution_ready"])
            intentionally_paused = paused and pause_reason in {"manual_pause", "halted", "stopped"}
            if not execution_ready and not intentionally_paused:
                status = "degraded"

        live_perp_guard_required = (
            str(self.config.trading_mode or "").strip().lower() == "live"
            and str(self.config.market_type or "").strip().lower() not in {"", "spot"}
        )
        position_guard_status = "running" if self.config.position_guard_enabled else "stopped"
        position_guard_reason = None
        if live_perp_guard_required:
            if not self.config.position_guard_enabled:
                position_guard_status = "misconfigured"
                position_guard_reason = "live_perp_guard_disabled"
                status = "degraded"
            elif self.config.position_guard_max_age_sec <= 0:
                position_guard_status = "misconfigured"
                position_guard_reason = "live_perp_guard_max_age_zero"
                status = "degraded"
        payload["position_guardian"] = {
            "status": position_guard_status,
            "reason": position_guard_reason,
            "timestamp": now,
            "config": {
                "enabled": bool(self.config.position_guard_enabled),
                "maxAgeSec": float(self.config.position_guard_max_age_sec),
                "hardMaxAgeSec": float(self.config.position_guard_max_age_hard_sec),
                "tpLimitExitEnabled": bool(self.config.position_guard_tp_limit_exit_enabled),
                "marketType": self.config.market_type,
                "tradingMode": self.config.trading_mode,
            },
        }
        existing_execution_readiness = payload.get("execution_readiness")
        if isinstance(existing_execution_readiness, dict):
            existing_execution_readiness["position_guard_status"] = position_guard_status
            existing_execution_readiness["position_guard_reason"] = position_guard_reason

        latest_guardrail = await self._read_guardrail_latest()
        exchange_session = self._extract_exchange_session_status(latest_guardrail)
        if exchange_session:
            payload["exchange_session"] = exchange_session
            status = "degraded"
            existing = payload.get("execution_readiness")
            if isinstance(existing, dict):
                existing["exchange_session_status"] = exchange_session["status"]
                existing["exchange_session_provider"] = exchange_session.get("provider")
                existing["exchange_session_reason"] = exchange_session.get("reason")
                if existing.get("execution_ready", False):
                    existing["execution_ready"] = False
                    existing["execution_block_reason"] = exchange_session["status"]

        decision_activity = await self._read_decision_activity()
        if decision_activity:
            payload["decision_activity"] = decision_activity
            last_decision_at = self._coerce_float(decision_activity.get("last_decision_at"))
            last_accepted_at = self._coerce_float(decision_activity.get("last_accepted_at"))
            accepted_count = int(decision_activity.get("accepted_count") or 0)
            rejected_count = int(decision_activity.get("rejected_count") or 0)
            total_count = int(decision_activity.get("total_count") or 0)
            inactivity = {
                "status": "active",
                "dominant_rejection_reason": decision_activity.get("dominant_rejection_reason"),
                "dominant_rejection_stage": decision_activity.get("dominant_rejection_stage"),
            }
            symbol_activity = decision_activity.get("symbol_activity")
            if isinstance(symbol_activity, list):
                inactivity["symbol_activity"] = symbol_activity
                top_rejected = None
                for item in symbol_activity:
                    if not isinstance(item, dict):
                        continue
                    if top_rejected is None or int(item.get("rejected_count") or 0) > int(top_rejected.get("rejected_count") or 0):
                        top_rejected = item
                if top_rejected:
                    inactivity["top_rejected_symbol"] = top_rejected.get("symbol")
                    inactivity["top_rejected_symbol_reason"] = top_rejected.get("dominant_rejection_reason")
                    inactivity["top_rejected_symbol_stage"] = top_rejected.get("dominant_rejection_stage")
            if last_decision_at is not None:
                inactivity["last_decision_age_sec"] = round(max(0.0, now - last_decision_at), 3)
            if last_accepted_at is not None:
                inactivity["last_accept_age_sec"] = round(max(0.0, now - last_accepted_at), 3)

            if total_count <= 0:
                inactivity["status"] = "no_activity"
            elif accepted_count <= 0 and rejected_count > 0:
                inactivity["status"] = "rejection_only"
            if warmup_not_ready and inactivity["status"] != "active":
                inactivity["status"] = "warmup"

            age_for_inactivity = None
            if last_accepted_at is not None:
                age_for_inactivity = max(0.0, now - last_accepted_at)
            elif last_decision_at is not None:
                age_for_inactivity = max(0.0, now - last_decision_at)

            if age_for_inactivity is not None:
                inactivity["inactive_age_sec"] = round(age_for_inactivity, 3)
                if age_for_inactivity >= self.config.inactivity_warn_sec and inactivity["status"] == "active":
                    inactivity["status"] = "quiet"
                if age_for_inactivity >= self.config.inactivity_degrade_sec and not warmup_not_ready:
                    status = "degraded"
                    inactivity["status"] = "inactive"

            payload["trading_activity"] = inactivity

        # Provide a stable "services" map for the dashboard serviceHealth panel.
        # This intentionally does not include external processes like the legacy
        # position guardian, which may not be running in ECS.
        payload["services"] = {
            "python_engine": {"status": "running"},
            "health_worker": {"status": "running"},
            "position_guardian": {"status": position_guard_status},
        }

        payload["status"] = status
        if self._last_status != status:
            payload["status_change"] = {"from": self._last_status, "to": status}
            log_info(
                "health_status_change",
                from_status=self._last_status,
                to_status=status,
                backlog_tier=backlog_metrics.overall_tier.value,
                total_lag=backlog_metrics.total_lag,
            )
        self._last_status = status
        await self.telemetry.publish_latency(ctx=self.telemetry_context, payload=payload)
        await self.telemetry.publish_health_snapshot(ctx=self.telemetry_context, payload=payload)

    @staticmethod
    def _coerce_float(value: Optional[object]) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    async def _read_decision_activity(self) -> Optional[Dict[str, object]]:
        tenant_id = getattr(self.telemetry_context, "tenant_id", None)
        bot_id = getattr(self.telemetry_context, "bot_id", None)
        if not tenant_id or not bot_id:
            return None
        key = f"quantgambit:{tenant_id}:{bot_id}:decision_activity:latest"
        try:
            raw = await self.redis.redis.get(key)
        except Exception:
            return None
        if not raw:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            parsed = json.loads(raw)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _read_control_state(self) -> Optional[Dict[str, object]]:
        tenant_id = getattr(self.telemetry_context, "tenant_id", None)
        bot_id = getattr(self.telemetry_context, "bot_id", None)
        if not tenant_id or not bot_id:
            return None
        key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
        try:
            raw = await self.redis.redis.get(key)
        except Exception:
            return None
        if not raw:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            parsed = json.loads(raw)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _read_guardrail_latest(self) -> Optional[Dict[str, object]]:
        tenant_id = getattr(self.telemetry_context, "tenant_id", None)
        bot_id = getattr(self.telemetry_context, "bot_id", None)
        if not tenant_id or not bot_id:
            return None
        key = f"quantgambit:{tenant_id}:{bot_id}:guardrail:latest"
        try:
            raw = await self.redis.redis.get(key)
        except Exception:
            return None
        if not raw:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            parsed = json.loads(raw)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _extract_exchange_session_status(guardrail: Optional[Dict[str, object]]) -> Optional[Dict[str, object]]:
        if not isinstance(guardrail, dict):
            return None
        guardrail_type = str(guardrail.get("type") or "").strip().lower()
        provider = str(guardrail.get("provider") or guardrail.get("source") or "").strip().lower()
        if provider not in {"order_updates", "orderbook", "trade"}:
            return None
        if guardrail_type == "auth_failed":
            return {
                "status": f"exchange_auth_failed:{provider}",
                "provider": provider,
                "reason": guardrail.get("reason"),
                "detail": guardrail.get("detail"),
            }
        if guardrail_type == "ws_stale":
            return {
                "status": f"exchange_session_stale:{provider}",
                "provider": provider,
                "reason": guardrail.get("reason"),
                "detail": guardrail.get("detail"),
            }
        return None

    async def _get_consumer_lags(self) -> Dict[str, int]:
        """
        Get consumer lag for each stream.
        
        Lag = stream length - entries read by consumer group
        If lag = 0, consumer is caught up (no overflow even if depth is high)
        """
        lags: Dict[str, int] = {}
        tenant = getattr(self.telemetry_context, "tenant_id", None)
        bot = getattr(self.telemetry_context, "bot_id", None)
        
        for stream in self.config.streams:
            try:
                # Try to get consumer group info
                # Consumer group naming convention: quantgambit_{worker}:{tenant}:{bot}
                groups = await self.redis.redis.xinfo_groups(stream)
                
                if not groups:
                    # No consumer groups, can't determine lag
                    continue
                
                # Find the relevant consumer group (match tenant/bot if available)
                for group in groups:
                    group_name = group.get("name", "")
                    # Check if this is our consumer group
                    if tenant and bot and f"{tenant}:{bot}" in group_name:
                        lag = group.get("lag", 0)
                        if lag is not None:
                            lags[stream] = lag
                        break
                    elif not tenant or not bot:
                        # No tenant/bot context, use first group's lag
                        lag = group.get("lag", 0)
                        if lag is not None:
                            lags[stream] = lag
                        break
            except Exception:
                # Stream might not exist or no groups
                continue
        
        return lags

    async def _check_warmup(self) -> tuple[bool, dict]:
        """Return (has_not_ready, counts) for warmup snapshots."""
        tenant = getattr(self.telemetry_context, "tenant_id", None)
        bot = getattr(self.telemetry_context, "bot_id", None)
        if not (tenant and bot):
            return False, {}
        try:
            keys = await self.redis.redis.keys(f"quantgambit:{tenant}:{bot}:warmup:*")
        except Exception:
            return False, {}
        total = len(keys or [])
        not_ready = 0
        for key in keys or []:
            try:
                raw = await self.redis.redis.get(key)
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                data = json.loads(raw)
                if not data.get("ready"):
                    not_ready += 1
            except Exception:
                continue
        return bool(not_ready), {"warmup_keys": total, "warmup_not_ready": not_ready}

    def record_market_tick(
        self,
        age_sec: float,
        is_stale: bool,
        is_skew: bool,
        is_gap: bool,
        is_out_of_order: bool,
    ) -> None:
        self._last_tick_age_sec = age_sec
        self._qa_counts["total"] += 1
        if is_stale:
            self._qa_counts["stale"] += 1
        if is_skew:
            self._qa_counts["skew"] += 1
        if is_gap:
            self._qa_counts["gap"] += 1
        if is_out_of_order:
            self._qa_counts["out_of_order"] += 1

    def _consume_qa_metrics(self) -> dict:
        now = time.time()
        elapsed = max(now - self._qa_last_report, 1e-6)
        total = self._qa_counts["total"]
        if total == 0 and self._last_tick_age_sec is None:
            return {}
        stale_pct = (self._qa_counts["stale"] / total * 100.0) if total else 0.0
        skew_pct = (self._qa_counts["skew"] / total * 100.0) if total else 0.0
        gap_pct = (self._qa_counts["gap"] / total * 100.0) if total else 0.0
        out_of_order_pct = (self._qa_counts["out_of_order"] / total * 100.0) if total else 0.0
        qps = total / elapsed if elapsed > 0 else 0.0
        payload = {
            "market_data_stale_pct": round(stale_pct, 3),
            "market_data_skew_pct": round(skew_pct, 3),
            "market_data_gap_pct": round(gap_pct, 3),
            "market_data_out_of_order_pct": round(out_of_order_pct, 3),
            "market_data_qps": round(qps, 3),
        }
        if self._last_tick_age_sec is not None:
            payload["last_tick_age_sec"] = round(self._last_tick_age_sec, 3)
        self._qa_counts = {"stale": 0, "skew": 0, "gap": 0, "out_of_order": 0, "total": 0}
        self._qa_last_report = now
        return payload

    async def _read_candle_late_tick_summary(self) -> Optional[dict]:
        if not self.telemetry_context:
            return None
        tenant = getattr(self.telemetry_context, "tenant_id", None)
        bot = getattr(self.telemetry_context, "bot_id", None)
        if not (tenant and bot):
            return None
        key = f"quantgambit:{tenant}:{bot}:candle:late_ticks"
        try:
            raw = await self.redis.redis.get(key)
        except Exception:
            return None
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            return None

    def get_backlog_policy(self) -> BacklogPolicy:
        """Get the backlog policy for external access."""
        return self._backlog_policy
    
    def should_reduce_size(self) -> bool:
        """Check if position sizes should be reduced due to backlog."""
        return self._backlog_policy.should_reduce_size()
    
    def should_block_entries(self) -> bool:
        """Check if new entries should be blocked due to backlog."""
        return self._backlog_policy.should_block_entries()
