"""Decision worker consuming feature snapshots and emitting decisions."""

from __future__ import annotations

import uuid
import time
import os
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from quantgambit.ingest.schemas import validate_feature_snapshot
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput
from quantgambit.signals.pipeline import StageContext
from quantgambit.signals.prediction_audit import build_directional_fields
from quantgambit.storage.redis_streams import Event, RedisStreamsClient, decode_and_validate_event
from quantgambit.ingest.time_utils import now_recv_us, sec_to_us, us_to_sec
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter
from quantgambit.config.repository import ConfigRepository
from quantgambit.portfolio.state_manager import InMemoryStateManager

if TYPE_CHECKING:
    from quantgambit.core.latency import LatencyTracker
    from quantgambit.integration.decision_recording import DecisionRecorder
    from quantgambit.integration.config_registry import ConfigurationRegistry
    from quantgambit.integration.shadow_comparison import ShadowComparator


@dataclass
class DecisionWorkerConfig:
    source_stream: str = "events:features"
    output_stream: str = "events:decisions"
    consumer_group: str = "quantgambit_decisions"
    consumer_name: str = "decision_worker"
    block_ms: int = 1000
    warmup_min_samples: int = 5  # Minimum market data snapshots before trading
    warmup_min_age_sec: float = 0.0  # DISABLED - timestamps are unreliable, use sample count only
    # Warmup gate is now ENABLED by default - blocks trading until warmup completes
    warmup_min_candles: int = 0  # Disabled - candles not reliable with timestamp issues
    max_feature_age_sec: float = 10.0  # Skip features older than this to prevent backlog processing
    skip_stale_silently: bool = True  # If True, don't log/publish rejection for stale features (faster catch-up)
    min_data_quality_score: float = 0.3  # Reduced from 0.6 to allow decisions with degraded data
    warmup_gate_enabled: bool = True  # ENABLED - blocks trading until warmup samples received
    warmup_require_quality: bool = False  # Disabled - quality tracking is flaky
    warmup_quality_min_score: float = 0.4
    warmup_require_sync: bool = False  # Disabled - sync state tracking is unreliable
    shadow_mode: bool = False
    shadow_reason: str = "shadow_mode_enabled"
    shadow_stream: str = "events:decisions_shadow"
    shadow_snapshot_key: Optional[str] = None
    position_exists_reject_cooldown_sec: float = 5.0


class DecisionWorker:
    """Consume feature snapshots and emit decision events."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        engine: DecisionEngine,
        bot_id: str,
        exchange: str,
        tenant_id: Optional[str] = None,
        state_manager: Optional[InMemoryStateManager] = None,
        config_repository: Optional[ConfigRepository] = None,
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        config: Optional[DecisionWorkerConfig] = None,
        kill_switch=None,  # PersistentKillSwitch or compatible
        latency_tracker: Optional["LatencyTracker"] = None,
        decision_recorder: Optional["DecisionRecorder"] = None,  # Feature: trading-pipeline-integration, Requirements: 2.1, 2.2
        config_registry: Optional["ConfigurationRegistry"] = None,  # Feature: trading-pipeline-integration, Requirements: 1.1, 1.2, 1.6
    ):
        self.redis = redis_client
        self.engine = engine
        self.bot_id = bot_id
        self.exchange = exchange
        self.tenant_id = tenant_id
        self.state_manager = state_manager
        self.config_repository = config_repository
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.snapshots = RedisSnapshotWriter(redis_client.redis)
        self.config = config or DecisionWorkerConfig()
        self._kill_switch = kill_switch
        self._latency_tracker = latency_tracker
        self._decision_recorder = decision_recorder  # Feature: trading-pipeline-integration, Requirements: 2.1, 2.2
        self._config_registry = config_registry  # Feature: trading-pipeline-integration, Requirements: 1.1, 1.2, 1.6
        self._warmup = WarmupTracker(
            min_samples=self.config.warmup_min_samples,
            min_age_sec=self.config.warmup_min_age_sec,
        )
        self._warmup.min_candles = self.config.warmup_min_candles
        self._warmed_up_symbols: set[str] = set()  # Track which symbols have completed warmup
        self._positions_snapshot_enabled = os.getenv("POSITIONS_SNAPSHOT_ON_DECISION", "").lower() in {"1", "true", "yes"}
        self._positions_snapshot_interval = float(os.getenv("POSITIONS_SNAPSHOT_INTERVAL_SEC", "1.0"))
        self._last_positions_snapshot = 0.0
        self._kill_switch_block_count = 0  # Track blocks for telemetry
        self._cached_config_version: Optional[str] = None  # Cache config version to avoid async calls in hot path
        self._config_version_cache_time: float = 0.0  # Timestamp of last cache update
        self._config_version_cache_ttl: float = 60.0  # Cache TTL in seconds
        # Shadow comparator for dual-pipeline comparison (wired in by Runtime when SHADOW_MODE_ENABLED=true)
        # Feature: trading-pipeline-integration
        # Requirements: 4.1 - Support running live and shadow pipelines in parallel
        # Requirements: 4.2 - Compare decisions from both pipelines in real-time
        self._shadow_comparator = None  # Type: Optional[ShadowComparator]
        self._snapshot_valid_enabled = os.getenv("SNAPSHOT_VALIDATION_ENABLED", "true").lower() in {"1", "true", "yes"}
        self._snapshot_circuit_window_sec = float(os.getenv("SNAPSHOT_CIRCUIT_WINDOW_SEC", "60.0"))
        self._last_position_exists_reject_at: dict[str, float] = {}
        self._snapshot_circuit_threshold = float(os.getenv("SNAPSHOT_CIRCUIT_THRESHOLD", "0.2"))
        self._snapshot_circuit_recover_threshold = float(os.getenv("SNAPSHOT_CIRCUIT_RECOVER_THRESHOLD", "0.1"))
        self._snapshot_circuit_min_samples = int(os.getenv("SNAPSHOT_CIRCUIT_MIN_SAMPLES", "20"))
        self._snapshot_circuit_fail_open = os.getenv("SNAPSHOT_CIRCUIT_FAIL_OPEN", "false").lower() in {"1", "true", "yes"}
        self._snapshot_circuit_open = False
        self._snapshot_window = deque()
        self._invalid_window = deque()
        self._snapshot_metric_last_emit = 0.0
        self._snapshot_metric_interval_sec = float(os.getenv("SNAPSHOT_METRIC_INTERVAL_SEC", "5.0"))
        self._stale_skip_emit_interval_sec = float(os.getenv("STALE_SKIP_EMIT_INTERVAL_SEC", "30.0"))
        self._last_stale_skip_emit: dict[str, float] = {}
        self._decision_activity_window_sec = float(os.getenv("DECISION_ACTIVITY_WINDOW_SEC", "300.0"))
        self._decision_activity_events = deque()
        self._last_accepted_at: Optional[float] = None
        self._last_rejected_at: Optional[float] = None
        tenant_key = self.tenant_id or os.getenv("TENANT_ID", "t1")
        self._calibration_counts_key = f"quantgambit:{tenant_key}:{self.bot_id}:calibration:trade_counts"
        self._calibration_counts_cache: dict[str, int] = {}
        self._calibration_counts_last_fetch = 0.0
        self._calibration_counts_refresh_sec = float(os.getenv("CALIBRATION_COUNTS_REFRESH_SEC", "30.0"))

    async def _get_config_version(self) -> Optional[str]:
        """Get the current configuration version for decision events.
        
        Feature: trading-pipeline-integration
        Requirements: 1.1, 1.2, 1.6 - Track config version in decision events
        
        Returns:
            Config version ID string, or None if config_registry not available
        """
        if not self._config_registry:
            return None
        
        # Check if cache is still valid
        now = time.time()
        if self._cached_config_version and (now - self._config_version_cache_time) < self._config_version_cache_ttl:
            return self._cached_config_version
        
        try:
            config = await self._config_registry.get_live_config()
            self._cached_config_version = config.version_id
            self._config_version_cache_time = now
            return config.version_id
        except Exception as exc:
            log_warning("config_version_fetch_failed", error=str(exc))
            return self._cached_config_version  # Return stale cache on error

    async def _record_snapshot_validity(
        self,
        snapshot_ts: Optional[float],
        valid: bool,
    ) -> tuple[float, int, int]:
        """Track snapshot validity rates for circuit breaker and metrics."""
        if snapshot_ts is None:
            snapshot_ts = time.time()
        self._snapshot_window.append(snapshot_ts)
        if not valid:
            self._invalid_window.append(snapshot_ts)
        cutoff = snapshot_ts - self._snapshot_circuit_window_sec
        while self._snapshot_window and self._snapshot_window[0] < cutoff:
            self._snapshot_window.popleft()
        while self._invalid_window and self._invalid_window[0] < cutoff:
            self._invalid_window.popleft()
        total = len(self._snapshot_window)
        invalid = len(self._invalid_window)
        rate = (invalid / total) if total else 0.0
        if (
            self.telemetry
            and self.telemetry_context
            and (snapshot_ts - self._snapshot_metric_last_emit) >= self._snapshot_metric_interval_sec
        ):
            self._snapshot_metric_last_emit = snapshot_ts
            await self.telemetry.publish_latency(
                ctx=self.telemetry_context,
                payload={
                    "snapshot_invalid_rate": round(rate, 4),
                    "snapshot_invalid_count": invalid,
                    "snapshot_total_count": total,
                    "snapshot_circuit_open": self._snapshot_circuit_open,
                    "timestamp": snapshot_ts,
                },
            )
        return rate, total, invalid

    async def _update_snapshot_circuit(self, invalid_rate: float, total: int) -> None:
        if total < self._snapshot_circuit_min_samples:
            return
        if not self._snapshot_circuit_open and invalid_rate >= self._snapshot_circuit_threshold:
            self._snapshot_circuit_open = True
            log_warning(
                "snapshot_circuit_opened",
                invalid_rate=round(invalid_rate, 3),
                sample_count=total,
            )
            if self.telemetry and self.telemetry_context:
                await self.telemetry.publish_guardrail(
                    self.telemetry_context,
                    {
                        "type": "snapshot_circuit",
                        "status": "open",
                        "invalid_rate": round(invalid_rate, 3),
                        "sample_count": total,
                    },
                )
        if self._snapshot_circuit_open and invalid_rate <= self._snapshot_circuit_recover_threshold:
            self._snapshot_circuit_open = False
            log_info(
                "snapshot_circuit_closed",
                invalid_rate=round(invalid_rate, 3),
                sample_count=total,
            )
            if self.telemetry and self.telemetry_context:
                await self.telemetry.publish_guardrail(
                    self.telemetry_context,
                    {
                        "type": "snapshot_circuit",
                        "status": "closed",
                        "invalid_rate": round(invalid_rate, 3),
                        "sample_count": total,
                    },
                )

    async def _get_calibration_counts(self, now_ts: Optional[float]) -> dict[str, int]:
        if not self.redis:
            return self._calibration_counts_cache
        now_ts = float(now_ts or time.time())
        if (
            self._calibration_counts_cache
            and (now_ts - self._calibration_counts_last_fetch) < self._calibration_counts_refresh_sec
        ):
            return self._calibration_counts_cache
        try:
            raw = await self.redis.redis.hgetall(self._calibration_counts_key)
        except Exception as exc:
            log_warning("calibration_counts_fetch_failed", error=str(exc))
            return self._calibration_counts_cache
        counts: dict[str, int] = {}
        for key, value in (raw or {}).items():
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            if key == "last_updated_ts":
                continue
            try:
                counts[str(key)] = int(float(value))
            except (TypeError, ValueError):
                continue
        self._calibration_counts_cache = counts
        self._calibration_counts_last_fetch = now_ts
        return counts

    async def run(self) -> None:
        log_info("decision_worker_start", source=self.config.source_stream, output=self.config.output_stream)
        await self.redis.create_group(self.config.source_stream, self.config.consumer_group, start_id="$")
        while True:
            messages = await self.redis.read_group(
                self.config.consumer_group,
                self.config.consumer_name,
                {self.config.source_stream: ">"},
                block_ms=self.config.block_ms,
            )
            for stream_name, entries in messages:
                for message_id, payload in entries:
                    await self._handle_message(payload)
                    await self.redis.ack(stream_name, self.config.consumer_group, message_id)

    async def _handle_message(self, payload: dict) -> None:
        # Start latency tracking
        latency_start = None
        if self._latency_tracker:
            latency_start = self._latency_tracker.start_timer("decision_worker")
        
        try:
            await self._handle_message_inner(payload)
        finally:
            # End latency tracking
            if self._latency_tracker and latency_start is not None:
                self._latency_tracker.end_timer("decision_worker", latency_start)

    async def _handle_message_inner(self, payload: dict) -> None:
        try:
            event = decode_and_validate_event(payload)
        except Exception as exc:
            log_warning("decision_worker_invalid_event", error=str(exc))
            return
        if event.get("event_type") != "feature_snapshot":
            return
        snapshot = event.get("payload") or {}

        # If the kill switch is active (e.g. TRADING_DISABLED), keep the decision pipeline "alive"
        # by emitting explicit rejections. This prevents pipeline health from falsely showing
        # Decision as down while trading is intentionally disabled.
        if self._kill_switch and self._kill_switch.is_active():
            self._kill_switch_block_count += 1
            if self._kill_switch_block_count % 100 == 1:  # Log every 100th block to avoid spam
                log_warning(
                    "decision_worker_kill_switch_active",
                    bot_id=self.bot_id,
                    blocked_count=self._kill_switch_block_count,
                )
            symbol = snapshot.get("symbol")
            if symbol:
                decision_payload = {
                    "symbol": symbol,
                    "timestamp": snapshot.get("timestamp"),
                    "decision": "rejected",
                    "rejection_reason": "kill_switch_active",
                    "rejected_by": "kill_switch",
                    "shadow_mode": bool(self.config.shadow_mode),
                    "meta_reason": self.config.shadow_reason if self.config.shadow_mode else None,
                }
                try:
                    await self._publish_decision(symbol, decision_payload)
                except Exception as exc:
                    log_warning("decision_worker_kill_switch_publish_failed", error=str(exc), symbol=symbol)
            return
        
        # EARLY SKIP: Check message age before any heavy processing
        # This allows fast catch-up when backlogged
        if self.config.max_feature_age_sec > 0:
            feature_ts = snapshot.get("timestamp")
            if feature_ts:
                try:
                    age = time.time() - float(feature_ts)
                    if age > self.config.max_feature_age_sec:
                        symbol = snapshot.get("symbol")
                        try:
                            await self._record_warmup_progress_from_snapshot(snapshot)
                        except Exception as exc:
                            log_warning(
                                "decision_worker_warmup_snapshot_failed",
                                symbol=symbol,
                                error=str(exc),
                            )
                        if not self.config.skip_stale_silently:
                            log_warning(
                                "decision_worker_skip_stale",
                                symbol=symbol,
                                age_sec=round(age, 1),
                                max_age=self.config.max_feature_age_sec,
                            )
                        elif symbol:
                            last_emit = self._last_stale_skip_emit.get(symbol, 0.0)
                            now_ts = time.time()
                            if (now_ts - last_emit) >= self._stale_skip_emit_interval_sec:
                                self._last_stale_skip_emit[symbol] = now_ts
                                config_version = await self._get_config_version()
                                decision_payload = {
                                    "symbol": symbol,
                                    "timestamp": feature_ts,
                                    "decision": "rejected",
                                    "rejection_reason": "stale_feature_snapshot",
                                    "rejected_by": "decision_worker_fast_skip",
                                    "rejection_detail": {
                                        "age_sec": round(age, 3),
                                        "max_age_sec": self.config.max_feature_age_sec,
                                        "skip_stale_silently": True,
                                    },
                                    "config_version": config_version,
                                }
                                try:
                                    await self._publish_decision(symbol, decision_payload)
                                except Exception as exc:
                                    log_warning(
                                        "decision_worker_stale_skip_publish_failed",
                                        symbol=symbol,
                                        error=str(exc),
                                    )
                        return  # Skip without publishing - just catch up
                except (TypeError, ValueError):
                    pass  # Invalid timestamp, let downstream handle it
        try:
            validate_feature_snapshot(snapshot)
        except Exception as exc:
            log_warning("decision_worker_invalid_snapshot", error=str(exc))
            return
        snapshot_ts = snapshot.get("timestamp")
        try:
            snapshot_ts = float(snapshot_ts) if snapshot_ts is not None else None
        except (TypeError, ValueError):
            snapshot_ts = None
        snapshot_valid = bool(snapshot.get("valid", True))
        rate, total, invalid = await self._record_snapshot_validity(snapshot_ts, snapshot_valid)
        await self._update_snapshot_circuit(rate, total)
        if self._snapshot_circuit_open:
            log_warning(
                "decision_worker_snapshot_circuit_open",
                symbol=snapshot.get("symbol"),
                invalid_rate=round(rate, 3),
                sample_count=total,
            )
            if not self._snapshot_circuit_fail_open:
                return
            log_warning(
                "decision_worker_snapshot_circuit_fail_open",
                symbol=snapshot.get("symbol"),
                invalid_rate=round(rate, 3),
                sample_count=total,
            )
        if self._snapshot_valid_enabled and not snapshot_valid:
            log_warning(
                "decision_worker_invalid_snapshot_gated",
                symbol=snapshot.get("symbol"),
                reasons=snapshot.get("invalid_reasons"),
            )
            if not self._snapshot_circuit_fail_open:
                return
            log_warning(
                "decision_worker_invalid_snapshot_fail_open",
                symbol=snapshot.get("symbol"),
                reasons=snapshot.get("invalid_reasons"),
            )
        market_context = snapshot.get("market_context") or {}
        symbol = snapshot.get("symbol")
        calibration_counts = await self._get_calibration_counts(snapshot_ts)
        if calibration_counts:
            market_context["calibration"] = calibration_counts
            if symbol:
                market_context["n_trades"] = calibration_counts.get(symbol, 0)
        else:
            market_context.setdefault("n_trades", 0)
        if self.state_manager and symbol:
            price = market_context.get("price")
            if price is not None:
                try:
                    self.state_manager.update_mfe_mae(symbol, float(price))
                except (TypeError, ValueError):
                    pass
        quality_score = None
        raw_quality = market_context.get("data_quality_score")
        if raw_quality is not None:
            try:
                quality_score = float(raw_quality)
            except (TypeError, ValueError):
                quality_score = None
        candle_count = market_context.get("candle_count", 0)
        warmed, stats = self._warmup.record(snapshot["symbol"], snapshot.get("timestamp"), candle_count)
        warmup_ready, warmup_reasons = self._warmup_ready(warmed, market_context, quality_score)
        await self._write_warmup_snapshot(
            snapshot["symbol"],
            warmup_ready,
            stats,
            candle_count,
            warmup_reasons,
            quality_score,
            market_context,
        )
        # If warmup/quality/sync gates are not satisfied, skip decision processing entirely.
        if self.config.warmup_gate_enabled and not warmup_ready:
            sample_count = stats.get("count", 0)
            log_warning(
                "decision_worker_warmup_wait",
                symbol=snapshot.get("symbol"),
                reasons=warmup_reasons,
                sample_count=sample_count,
                min_samples=self.config.warmup_min_samples,
                progress_pct=round(100 * sample_count / max(1, self.config.warmup_min_samples), 1),
                candle_count=candle_count,
                quality_score=quality_score,
            )
            return
        
        # Log warmup completion (once per symbol)
        if symbol and warmup_ready and symbol not in self._warmed_up_symbols:
            self._warmed_up_symbols.add(symbol)
            log_info(
                "decision_worker_warmup_complete",
                symbol=symbol,
                sample_count=stats.get("count", 0),
                min_samples=self.config.warmup_min_samples,
            )
        
        if snapshot.get("timestamp") and self.config.max_feature_age_sec > 0:
            age = time.time() - float(snapshot["timestamp"])
            if age > self.config.max_feature_age_sec:
                log_warning("decision_worker_stale_snapshot", symbol=snapshot.get("symbol"), age_sec=round(age, 3))
                # Get config version for decision event tracking
                # Feature: trading-pipeline-integration, Requirements: 1.1, 1.2, 1.6
                config_version = await self._get_config_version()
                decision_payload = {
                    "symbol": snapshot["symbol"],
                    "timestamp": snapshot["timestamp"],
                    "decision": "rejected",
                    "rejection_reason": "stale_feature_snapshot",
                    "profile_id": None,
                    "signal": None,
                    "config_version": config_version,  # Feature: trading-pipeline-integration, Requirements: 1.1, 1.2, 1.6
                }
                await self._publish_decision(snapshot["symbol"], decision_payload)
                return
        if quality_score is not None and quality_score < self.config.min_data_quality_score:
            log_warning(
                "decision_worker_low_quality",
                symbol=snapshot.get("symbol"),
                quality_score=round(quality_score, 3),
            )
            # Get config version for decision event tracking
            # Feature: trading-pipeline-integration, Requirements: 1.1, 1.2, 1.6
            config_version = await self._get_config_version()
            decision_payload = {
                "symbol": snapshot["symbol"],
                "timestamp": snapshot["timestamp"],
                "decision": "rejected",
                "rejection_reason": "low_data_quality",
                "profile_id": None,
                "signal": None,
                "config_version": config_version,  # Feature: trading-pipeline-integration, Requirements: 1.1, 1.2, 1.6
            }
            await self._publish_decision(snapshot["symbol"], decision_payload)
            return
        decision_input = DecisionInput(
            symbol=snapshot["symbol"],
            market_context=market_context,
            features=snapshot.get("features") or {},
            prediction=snapshot.get("prediction"),
            account_state=self._account_state(),
            positions=await self._open_positions(),
            risk_limits=self._risk_limits(),
            profile_settings=self._profile_settings(),
        )
        self._debug_decision_state(decision_input.account_state, decision_input.positions)
        if not warmup_ready:
            ctx = StageContext(symbol=snapshot["symbol"], data={}, rejection_reason="warmup")
            ctx.rejection_stage = "warmup"
            ctx.stage_trace = [{"stage": "warmup", "result": "REJECT"}]
            ctx.rejection_detail = {
                "warmup_reasons": warmup_reasons,
                "candle_count": candle_count,
                "quality_score": quality_score,
            }
            result = False
        else:
            result, ctx = await self.engine.decide_with_context(decision_input)
        shadow_mode = self.config.shadow_mode
        decision_status = "accepted" if result else "rejected"
        if shadow_mode and result:
            decision_status = "shadow"
        # Get config version for decision event tracking
        # Feature: trading-pipeline-integration, Requirements: 1.1, 1.2, 1.6
        config_version = await self._get_config_version()
        # Use current time for decision timestamp, not market data timestamp
        # Market data timestamps can be delayed/stale but the decision is being made NOW
        decision_payload = {
            "symbol": snapshot["symbol"],
            "timestamp": time.time(),  # Decision time, not market data time
            "decision": decision_status,
            # Compatibility key used by some telemetry/dashboard consumers.
            "result": (
                "SHADOW"
                if decision_status == "shadow"
                else ("ACCEPTED" if decision_status == "accepted" else "REJECTED")
            ),
            "rejection_reason": ctx.rejection_reason,
            "profile_id": ctx.profile_id,
            "signal": _serialize_signal(ctx.signal),
            "shadow_mode": shadow_mode,
            "config_version": config_version,  # Feature: trading-pipeline-integration, Requirements: 1.1, 1.2, 1.6
        }
        if ctx.rejection_stage:
            decision_payload["rejected_by"] = ctx.rejection_stage
        if ctx.rejection_detail:
            decision_payload["rejection_detail"] = ctx.rejection_detail
        if ctx.stage_trace and os.getenv("DECISION_GATE_TRACE") == "1":
            decision_payload["stage_trace"] = ctx.stage_trace
        candidate = ctx.data.get("candidate")
        if candidate and hasattr(candidate, "to_dict"):
            decision_payload["candidate"] = candidate.to_dict()
            if isinstance(decision_payload.get("signal"), dict):
                decision_payload["signal"]["expected_edge_bps"] = getattr(candidate, "expected_edge_bps", None)
                decision_payload["signal"]["candidate_confidence"] = getattr(candidate, "confidence", None)
                sig = decision_payload["signal"]
                try:
                    sig.setdefault("strategy_id", getattr(candidate, "strategy_id", None))
                    sig.setdefault("profile_id", getattr(candidate, "profile_id", None))
                except Exception:
                    pass

        if isinstance(decision_payload.get("signal"), dict):
            # Ensure execution has enough metadata to persist positions correctly.
            # Several downstream components (risk/execution/positions snapshots) rely on these
            # fields being present in `signal` (not only at the top-level decision).
            sig = decision_payload["signal"]
            sig.setdefault("profile_id", ctx.profile_id)

            # Time budgets (scalping): fill defaults if strategy didn't provide them.
            # This prevents "infinite holds" when a dict-based signal omitted time budget fields.
            # Must run even when a candidate object isn't present.
            if (
                sig.get("time_to_work_sec") is None
                and sig.get("max_hold_sec") is None
                and sig.get("mfe_min_bps") is None
            ):
                try:
                    from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
                        get_time_budget_for_strategy,
                    )

                    tb = get_time_budget_for_strategy(str(sig.get("strategy_id") or ""))
                    sig.setdefault("time_to_work_sec", tb.time_to_work_sec)
                    sig.setdefault("max_hold_sec", tb.max_hold_sec)
                    sig.setdefault("mfe_min_bps", tb.mfe_min_bps)
                    sig.setdefault("expected_horizon_sec", tb.max_hold_sec)
                except Exception:
                    pass
        if warmup_reasons:
            decision_payload["warmup_reasons"] = warmup_reasons
        if shadow_mode and result:
            decision_payload["shadow_reason"] = self.config.shadow_reason
        prediction = snapshot.get("prediction")
        risk_context = _extract_risk_context(market_context, prediction)
        if risk_context:
            decision_payload["risk_context"] = risk_context
        # Add profile selection metadata for post-trade analysis (US-3, AC3.3)
        profile_selection_metadata = _extract_profile_selection_metadata(ctx, market_context)
        if profile_selection_metadata:
            decision_payload["profile_selection_metadata"] = profile_selection_metadata
        if prediction and isinstance(decision_payload.get("signal"), dict):
            decision_payload["signal"]["prediction_confidence"] = prediction.get("confidence")
        if prediction:
            decision_payload["prediction_confidence"] = prediction.get("confidence")
            # Persist full prediction payload for post-trade analysis and model evaluation.
            # This stays lightweight (small dict) and avoids guessing later.
            decision_payload["prediction"] = prediction

        if isinstance(decision_payload.get("signal"), dict):
            signal_side = decision_payload["signal"].get("side")
        else:
            signal_side = None
        directional_fields = build_directional_fields(
            prediction if isinstance(prediction, dict) else None,
            signal_side,
        )
        for key, value in directional_fields.items():
            decision_payload[key] = value

        model_alignment = ctx.data.get("model_direction_alignment")
        if isinstance(model_alignment, dict):
            decision_payload["model_direction_alignment"] = model_alignment
        self._log_gate_trace(
            symbol=snapshot["symbol"],
            decision_status=decision_status,
            ctx=ctx,
            market_context=market_context,
            quality_score=quality_score,
            candle_count=candle_count,
            warmup_reasons=warmup_reasons,
        )
        await self._publish_decision(snapshot["symbol"], decision_payload)
        
        # Record decision for replay and analysis
        # Feature: trading-pipeline-integration
        # Requirements: 2.1 - Record complete decision context
        # Requirements: 2.2 - Batch decision records for efficient database writes
        if self._decision_recorder:
            try:
                await self._decision_recorder.record(
                    symbol=snapshot["symbol"],
                    snapshot=market_context,  # Market snapshot at decision time
                    features=snapshot.get("features") or {},
                    ctx=ctx,
                    decision=decision_status,
                )
            except Exception as exc:
                # Don't block trading on recording failures
                log_warning(
                    "decision_recording_failed",
                    symbol=snapshot["symbol"],
                    error=str(exc),
                )
        
        await self._maybe_publish_positions_snapshot()
        if shadow_mode and result:
            await self._publish_shadow(snapshot["symbol"], decision_payload)
            await self._write_shadow_snapshot(snapshot["symbol"], snapshot.get("timestamp"), decision_payload)
        await self._write_profile_router_snapshot(snapshot["symbol"], snapshot.get("timestamp"), ctx, market_context)

    def _log_gate_trace(
        self,
        symbol: str,
        decision_status: str,
        ctx: StageContext,
        market_context: dict,
        quality_score: Optional[float],
        candle_count: int,
        warmup_reasons: list[str],
    ) -> None:
        if os.getenv("DECISION_GATE_TRACE") != "1":
            return
        log_info(
            "decision_gate_trace",
            symbol=symbol,
            bot_id=self.bot_id,
            decision=decision_status,
            rejection_reason=ctx.rejection_reason,
            rejection_stage=ctx.rejection_stage,
            rejection_detail=ctx.rejection_detail,
            profile_id=ctx.profile_id,
            stage_trace=ctx.stage_trace or [],
            warmup_reasons=warmup_reasons,
            candle_count=candle_count,
            quality_score=quality_score,
            data_quality_required=self.config.warmup_require_quality,
            warmup_gate_enabled=self.config.warmup_gate_enabled,
            market_data_ts=market_context.get("timestamp"),
        )

    async def _publish_decision(self, symbol: str, payload: dict) -> None:
        decision = str(payload.get("decision") or "").strip().lower()
        rejection_reason = str(payload.get("rejection_reason") or "").strip().lower()
        if (
            decision == "rejected"
            and rejection_reason == "position_exists"
        ):
            now_ts = time.time()
            last_ts = self._last_position_exists_reject_at.get(symbol, 0.0)
            if (now_ts - last_ts) < max(0.0, float(self.config.position_exists_reject_cooldown_sec)):
                log_info(
                    "decision_suppressed",
                    symbol=symbol,
                    bot_id=self.bot_id,
                    decision=payload.get("decision"),
                    rejection_reason=payload.get("rejection_reason"),
                )
                return
            self._last_position_exists_reject_at[symbol] = now_ts
        if payload.get("timestamp") is not None:
            timestamp_sec = float(payload["timestamp"])
            ts_us = sec_to_us(timestamp_sec)
        else:
            ts_us = now_recv_us()
            timestamp_sec = us_to_sec(ts_us)
        decision_id = str(payload.get("decision_id") or uuid.uuid4())
        payload["decision_id"] = decision_id
        event = Event(
            event_id=decision_id,
            event_type="decision",
            schema_version="v1",
            timestamp=str(timestamp_sec),
            ts_recv_us=ts_us,
            ts_canon_us=ts_us,
            ts_exchange_s=None,
            bot_id=self.bot_id,
            symbol=symbol,
            exchange=self.exchange,
            payload=payload,
        )
        await self.redis.publish_event(self.config.output_stream, event)
        log_info(
            "decision_emitted",
            symbol=symbol,
            bot_id=self.bot_id,
            decision=payload.get("decision"),
            rejection_reason=payload.get("rejection_reason"),
        )
        await self._write_decision_activity_snapshot(symbol, payload, timestamp_sec)
        # also publish via telemetry for signals table/stream
        if self.telemetry and self.telemetry_context:
            try:
                signal_payload = _serialize_signal(payload.get("signal") or {}) or {}
                signal_payload.setdefault("decision", payload.get("decision"))
                signal_payload.setdefault("reason", payload.get("meta_reason") or payload.get("reason"))
                signal_payload.setdefault("timestamp", payload.get("timestamp"))
                signal_payload.setdefault("symbol", symbol)
                await self.telemetry.publish_signal(self.telemetry_context, signal_payload)
            except Exception:
                pass

    async def _write_decision_activity_snapshot(self, symbol: str, payload: dict, timestamp_sec: float) -> None:
        tenant_id = self.tenant_id or "t1"
        decision = str(payload.get("decision") or "").strip().lower()
        rejection_reason = str(payload.get("rejection_reason") or "").strip() or None
        rejection_stage = str(payload.get("rejected_by") or "").strip() or None

        self._decision_activity_events.append(
            {
                "timestamp": float(timestamp_sec),
                "decision": decision,
                "symbol": symbol,
                "rejection_reason": rejection_reason,
                "rejection_stage": rejection_stage,
            }
        )
        cutoff = float(timestamp_sec) - self._decision_activity_window_sec
        while self._decision_activity_events and float(self._decision_activity_events[0].get("timestamp") or 0.0) < cutoff:
            self._decision_activity_events.popleft()

        if decision == "accepted":
            self._last_accepted_at = float(timestamp_sec)
        elif decision == "rejected":
            self._last_rejected_at = float(timestamp_sec)

        decision_counts = Counter()
        rejection_reason_counts = Counter()
        rejection_stage_counts = Counter()
        symbol_decision_counts: dict[str, Counter] = {}
        symbol_rejection_reason_counts: dict[str, Counter] = {}
        symbol_rejection_stage_counts: dict[str, Counter] = {}
        symbol_last_decision_at: dict[str, float] = {}
        symbol_last_accepted_at: dict[str, float] = {}
        symbol_last_rejected_at: dict[str, float] = {}
        for item in self._decision_activity_events:
            item_decision = str(item.get("decision") or "").strip().lower()
            item_symbol = str(item.get("symbol") or "").strip()
            if item_decision:
                decision_counts[item_decision] += 1
            if item_symbol:
                symbol_decision_counts.setdefault(item_symbol, Counter())[item_decision] += 1
                symbol_last_decision_at[item_symbol] = float(item.get("timestamp") or timestamp_sec)
                if item_decision == "accepted":
                    symbol_last_accepted_at[item_symbol] = float(item.get("timestamp") or timestamp_sec)
                elif item_decision == "rejected":
                    symbol_last_rejected_at[item_symbol] = float(item.get("timestamp") or timestamp_sec)
            if item_decision == "rejected":
                reason = item.get("rejection_reason")
                stage = item.get("rejection_stage")
                if reason:
                    rejection_reason_counts[str(reason)] += 1
                    if item_symbol:
                        symbol_rejection_reason_counts.setdefault(item_symbol, Counter())[str(reason)] += 1
                if stage:
                    rejection_stage_counts[str(stage)] += 1
                    if item_symbol:
                        symbol_rejection_stage_counts.setdefault(item_symbol, Counter())[str(stage)] += 1

        symbol_activity = []
        for item_symbol, counts in symbol_decision_counts.items():
            reason_counts = symbol_rejection_reason_counts.get(item_symbol) or Counter()
            stage_counts = symbol_rejection_stage_counts.get(item_symbol) or Counter()
            symbol_activity.append(
                {
                    "symbol": item_symbol,
                    "accepted_count": int(counts.get("accepted", 0)),
                    "rejected_count": int(counts.get("rejected", 0)),
                    "shadow_count": int(counts.get("shadow", 0)),
                    "total_count": int(sum(counts.values())),
                    "last_decision_at": symbol_last_decision_at.get(item_symbol),
                    "last_accepted_at": symbol_last_accepted_at.get(item_symbol),
                    "last_rejected_at": symbol_last_rejected_at.get(item_symbol),
                    "dominant_rejection_reason": reason_counts.most_common(1)[0][0] if reason_counts else None,
                    "dominant_rejection_stage": stage_counts.most_common(1)[0][0] if stage_counts else None,
                }
            )
        symbol_activity.sort(
            key=lambda item: (
                -int(item.get("rejected_count") or 0),
                -int(item.get("total_count") or 0),
                str(item.get("symbol") or ""),
            )
        )

        snapshot = {
            "timestamp": float(timestamp_sec),
            "window_sec": self._decision_activity_window_sec,
            "last_decision_at": float(timestamp_sec),
            "last_decision_symbol": symbol,
            "last_decision": decision,
            "last_rejection_reason": rejection_reason,
            "last_rejection_stage": rejection_stage,
            "last_accepted_at": self._last_accepted_at,
            "last_rejected_at": self._last_rejected_at,
            "decision_counts": dict(decision_counts),
            "accepted_count": int(decision_counts.get("accepted", 0)),
            "rejected_count": int(decision_counts.get("rejected", 0)),
            "shadow_count": int(decision_counts.get("shadow", 0)),
            "total_count": int(sum(decision_counts.values())),
            "dominant_rejection_reason": rejection_reason_counts.most_common(1)[0][0] if rejection_reason_counts else None,
            "dominant_rejection_stage": rejection_stage_counts.most_common(1)[0][0] if rejection_stage_counts else None,
            "symbol_activity": symbol_activity[:10],
        }
        key = f"quantgambit:{tenant_id}:{self.bot_id}:decision_activity:latest"
        await self.snapshots.write(key, snapshot)

    async def _publish_shadow(self, symbol: str, payload: dict) -> None:
        if payload.get("timestamp") is not None:
            timestamp_sec = float(payload["timestamp"])
            ts_us = sec_to_us(timestamp_sec)
        else:
            ts_us = now_recv_us()
            timestamp_sec = us_to_sec(ts_us)
        decision_id = str(payload.get("decision_id") or uuid.uuid4())
        payload["decision_id"] = decision_id
        event = Event(
            event_id=decision_id,
            event_type="decision_shadow",
            schema_version="v1",
            timestamp=str(timestamp_sec),
            ts_recv_us=ts_us,
            ts_canon_us=ts_us,
            ts_exchange_s=None,
            bot_id=self.bot_id,
            symbol=symbol,
            exchange=self.exchange,
            payload=payload,
        )
        await self.redis.publish_event(self.config.shadow_stream, event)
        log_info(
            "shadow_decision_emitted",
            symbol=symbol,
            bot_id=self.bot_id,
        )

    async def _write_shadow_snapshot(
        self,
        symbol: str,
        timestamp: Optional[float],
        payload: dict,
    ) -> None:
        key = self.config.shadow_snapshot_key
        if not key:
            tenant_id = self.tenant_id or "t1"
            key = f"quantgambit:{tenant_id}:{self.bot_id}:decision_shadow:{symbol}:latest"
        snapshot = dict(payload)
        snapshot["timestamp"] = float(timestamp) if timestamp is not None else time.time()
        await self.snapshots.write(key, snapshot)

    def _risk_limits(self) -> Optional[dict]:
        def _normalize_pct(value: object) -> Optional[float]:
            try:
                val = float(value)
            except (TypeError, ValueError):
                return None
            return val / 100.0 if val > 1.0 else val

        if self.config_repository and self.tenant_id:
            config = self.config_repository.current_config(self.tenant_id, self.bot_id)
            if config and config.risk:
                normalized = dict(config.risk)
                for key, value in list(normalized.items()):
                    if "pct" in key and value is not None:
                        normalized_val = _normalize_pct(value)
                        if normalized_val is not None:
                            normalized[key] = normalized_val
                return normalized
        # Fallback to env when no config is loaded
        def _env_float(key: str, default: float) -> float:
            val = os.getenv(key)
            if not val or not val.strip():
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        def _env_int(key: str, default: int) -> int:
            val = os.getenv(key)
            if not val or not val.strip():
                return default
            try:
                return int(val)
            except (TypeError, ValueError):
                return default

        def _env_pct(key: str, default: float) -> float:
            val = _env_float(key, default)
            return val / 100.0 if val > 1.0 else val

        return {
            "max_positions": _env_int("MAX_POSITIONS", 4),
            "max_positions_per_symbol": _env_int("MAX_POSITIONS_PER_SYMBOL", 1),
            "max_total_exposure_pct": _env_pct("MAX_TOTAL_EXPOSURE_PCT", 0.50),
            "max_exposure_per_symbol_pct": _env_pct("MAX_EXPOSURE_PER_SYMBOL_PCT", 0.20),
            "max_daily_loss_pct": _env_pct("MAX_DAILY_DRAWDOWN_PCT", 0.05),
            "max_drawdown_pct": _env_pct("MAX_DRAWDOWN_PCT", 0.10),
            "max_consecutive_losses": _env_int("MAX_CONSECUTIVE_LOSSES", 3),
            "min_position_size_usd": _env_float("MIN_POSITION_SIZE_USD", 10.0),
        }

    def _profile_settings(self) -> Optional[dict]:
        if not self.config_repository or not self.tenant_id:
            return None
        config = self.config_repository.current_config(self.tenant_id, self.bot_id)
        return config.profile_settings if config else None

    def _account_state(self) -> Optional[dict]:
        if not self.state_manager:
            return None
        account = self.state_manager.get_account_state()
        equity = account.equity
        if not equity:
            try:
                # Use TRADING_CAPITAL_USD as primary, fallback to PAPER_EQUITY
                equity = float(os.getenv("TRADING_CAPITAL_USD", os.getenv("PAPER_EQUITY", "0")))
            except (TypeError, ValueError):
                equity = 0.0
        return {
            "equity": equity,
            "daily_pnl": account.daily_pnl,
            "peak_balance": account.peak_balance,
            "consecutive_losses": account.consecutive_losses,
        }

    async def _open_positions(self) -> Optional[list]:
        if not self.state_manager:
            return None
        return await self.state_manager.list_open_positions()

    async def _write_warmup_snapshot(
        self,
        symbol: str,
        ready: bool,
        stats: dict,
        candle_count: int,
        reasons: list[str],
        quality_score: Optional[float],
        market_context: dict,
    ) -> None:
        tenant_id = self.tenant_id or "t1"
        key = f"quantgambit:{tenant_id}:{self.bot_id}:warmup:{symbol}"
        snapshot = {
            "symbol": symbol,
            "ready": ready,
            "reasons": reasons,
            "sample_count": stats["count"],
            "first_ts": stats.get("first_ts"),
            "latest_ts": stats.get("latest_ts"),
            "min_samples": self.config.warmup_min_samples,
            "min_age_sec": self.config.warmup_min_age_sec,
            "candle_count": candle_count,
            "min_candles": self.config.warmup_min_candles,
            "quality_score": quality_score,
            "orderbook_sync_state": market_context.get("orderbook_sync_state"),
            "trade_sync_state": market_context.get("trade_sync_state"),
            "candle_sync_state": market_context.get("candle_sync_state"),
            "quality_flags": market_context.get("data_quality_flags"),
            "warmup_gate_enabled": self.config.warmup_gate_enabled,
            "warmup_require_quality": self.config.warmup_require_quality,
            "warmup_quality_min_score": self.config.warmup_quality_min_score,
            "warmup_require_sync": self.config.warmup_require_sync,
        }
        await self.snapshots.write(key, snapshot)

    async def _record_warmup_progress_from_snapshot(self, snapshot: dict) -> None:
        symbol = snapshot.get("symbol")
        if not symbol:
            return
        market_context = snapshot.get("market_context") or {}
        quality_score = None
        raw_quality = market_context.get("data_quality_score")
        if raw_quality is not None:
            try:
                quality_score = float(raw_quality)
            except (TypeError, ValueError):
                quality_score = None
        candle_count = market_context.get("candle_count", 0)
        warmed, stats = self._warmup.record(symbol, snapshot.get("timestamp"), candle_count)
        warmup_ready, warmup_reasons = self._warmup_ready(warmed, market_context, quality_score)
        await self._write_warmup_snapshot(
            symbol,
            warmup_ready,
            stats,
            candle_count,
            warmup_reasons,
            quality_score,
            market_context,
        )

    def _warmup_ready(
        self,
        warmed: bool,
        market_context: dict,
        quality_score: Optional[float],
    ) -> tuple[bool, list[str]]:
        if not self.config.warmup_gate_enabled:
            return True, []
        reasons = []
        if not warmed:
            reasons.append("warmup")
        if self.config.warmup_require_quality:
            if quality_score is None:
                reasons.append("quality_missing")
            elif quality_score < self.config.warmup_quality_min_score:
                reasons.append("quality_low")
        if self.config.warmup_require_sync:
            flags = set(market_context.get("data_quality_flags") or [])
            # Only block on critical flags that indicate truly broken data
            # "out_of_order" and "clock_skew" are often transient and handled by bootstrap
            critical_flags = {"orderbook_gap", "orderbook_stale"}
            if flags.intersection(critical_flags):
                reasons.append("data_stale")
            # Allow more sync states - bootstrap and gap_tolerated are acceptable
            acceptable_orderbook_states = (None, "synced", "snapshot", "bootstrap_from_delta", "gap_tolerated")
            if market_context.get("orderbook_sync_state") not in acceptable_orderbook_states:
                reasons.append("orderbook_unsynced")
            # Trade sync is informational only - don't block warmup for it
            # if market_context.get("trade_sync_state") not in (None, "synced"):
            #     reasons.append("trade_unsynced")
            # Candle sync - only block if candle_stale flag is present
            if "candle_stale" in flags:
                reasons.append("candle_unsynced")
        return not reasons, reasons

    async def _write_profile_router_snapshot(
        self,
        symbol: str,
        timestamp: Optional[float],
        ctx: StageContext,
        market_context: dict,
    ) -> None:
        scores = ctx.data.get("profile_scores") if isinstance(ctx.data, dict) else None
        if not scores:
            return
        normalized_scores = []
        for score in scores:
            entry = dict(score)
            entry.setdefault("eligible", True)
            entry.setdefault("eligibility_reasons", [])
            normalized_scores.append(entry)
        signal = ctx.signal if isinstance(ctx.signal, dict) else {}
        selected_strategy_id = signal.get("strategy_id") if isinstance(signal, dict) else None
        snapshot_ts = float(timestamp) if timestamp is not None else time.time()
        ts_hour = datetime.fromtimestamp(snapshot_ts, tz=timezone.utc).hour
        inferred_session = "asia" if ts_hour < 8 else "europe" if ts_hour < 13 else "us"
        resolved_session = market_context.get("session") or inferred_session
        resolved_regime = market_context.get("market_regime") or market_context.get("volatility_regime") or "unknown"
        snapshot = {
            "symbol": symbol,
            "timestamp": snapshot_ts,
            "selected_profile_id": ctx.profile_id,
            "selected_strategy_id": selected_strategy_id,
            "session": resolved_session,
            "regime": resolved_regime,
            "risk_mode": market_context.get("risk_mode"),
            "scores": normalized_scores,
        }
        tenant_id = self.tenant_id or "t1"
        key_latest = f"quantgambit:{tenant_id}:{self.bot_id}:profile_router:latest"
        key_symbol = f"quantgambit:{tenant_id}:{self.bot_id}:profile_router:{symbol}:latest"
        await self.snapshots.write(key_latest, snapshot)
        await self.snapshots.write(key_symbol, snapshot)

    def _debug_decision_state(self, account_state: Optional[dict], positions: Optional[list]) -> None:
        if os.getenv("DECISION_DEBUG_STATE", "").lower() not in {"1", "true", "yes"}:
            return
        serialized_positions = [_serialize_position(position) for position in (positions or [])]
        log_info(
            "decision_state_debug",
            bot_id=self.bot_id,
            account_state=account_state or {},
            positions=serialized_positions,
        )

    async def _maybe_publish_positions_snapshot(self) -> None:
        if not self._positions_snapshot_enabled:
            return
        if not (self.telemetry and self.telemetry_context and self.state_manager):
            return
        now = time.time()
        if now - self._last_positions_snapshot < self._positions_snapshot_interval:
            return
        self._last_positions_snapshot = now
        positions = await self.state_manager.list_open_positions()
        payload = {
            "positions": [
                {
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "size": pos.size,
                    "reference_price": pos.reference_price,
                    "entry_price": pos.entry_price,
                    "stop_loss": pos.stop_loss,
                    "take_profit": pos.take_profit,
                    "opened_at": pos.opened_at,
                    "age_sec": (now - pos.opened_at) if pos.opened_at else None,
                    "guard_status": "protected" if (pos.stop_loss or pos.take_profit) else "unprotected",
                    "prediction_confidence": pos.prediction_confidence,
                    "strategy_id": pos.strategy_id,
                    "profile_id": pos.profile_id,
                }
                for pos in positions
            ],
            "count": len(positions),
        }
        await self.telemetry.publish_positions(self.telemetry_context, payload)


def _serialize_position(position) -> dict:
    if position is None:
        return {}
    if isinstance(position, dict):
        return position
    payload = {}
    for key in (
        "symbol",
        "side",
        "size",
        "size_usd",
        "entry_price",
        "current_price",
        "unrealized_pnl",
        "realized_pnl",
    ):
        if hasattr(position, key):
            payload[key] = getattr(position, key)
    return payload

def _serialize_signal(signal) -> Optional[dict]:
    if signal is None:
        return None
    if isinstance(signal, dict):
        return signal
    payload = {}
    for key in (
        "strategy_id",
        "symbol",
        "side",
        "size",
        "entry_price",
        "stop_loss",
        "take_profit",
        "meta_reason",
        "profile_id",
        # Signal strength telemetry
        "signal_strength",
        "confidence",
        "confirmation_count",
        # Time budget parameters (MFT scalping)
        "expected_horizon_sec",
        "time_to_work_sec",
        "max_hold_sec",
        "max_hold_time_seconds",
        "mfe_min_bps",
    ):
        if hasattr(signal, key):
            value = getattr(signal, key)
            # Handle enum values (e.g., SignalStrength.STRONG -> "strong")
            if hasattr(value, "value"):
                value = value.value
            payload[key] = value
    if payload:
        return payload
    return None


def _extract_risk_context(market_context: dict, prediction: Optional[dict]) -> Optional[dict]:
    payload: dict = {}
    for key in (
        "volatility_regime",
        "liquidity_regime",
        "market_regime",
        "regime_confidence",
        "risk_mode",
        "risk_scale",
    ):
        value = market_context.get(key)
        if value is not None:
            payload[key] = value
    if prediction and prediction.get("confidence") is not None:
        payload["prediction_confidence"] = prediction.get("confidence")
    return payload or None


def _extract_profile_selection_metadata(ctx: StageContext, market_context: dict) -> Optional[dict]:
    """
    Extract profile selection metadata for post-trade analysis.
    
    This allows answering questions like:
    - "What session was active when this profile was selected?"
    - "What were the top scoring profiles?"
    - "Why were other profiles rejected?"
    
    Requirements: US-3 (AC3.3)
    
    Returns dict with profile selection metadata or None if no data available.
    """
    metadata: dict = {}
    
    # Selected profile
    if ctx.profile_id:
        metadata["selected_profile"] = ctx.profile_id
    
    # Session info (critical for debugging session mismatch bugs)
    session = market_context.get("session")
    if session:
        metadata["session"] = session
    
    hour_utc = market_context.get("hour_utc")
    if hour_utc is not None:
        metadata["hour_utc"] = hour_utc
    
    # Profile scores from router
    profile_scores = ctx.data.get("profile_scores") if isinstance(ctx.data, dict) else None
    if profile_scores:
        # Top 3 scores for debugging
        top_scores = []
        rejection_count = 0
        for score in profile_scores[:5]:  # Limit to top 5
            score_entry = {
                "profile_id": score.get("profile_id"),
                "score": score.get("score"),
                "adjusted_score": score.get("adjusted_score"),
                "eligible": score.get("eligible", True),
            }
            # Include rejection reasons for ineligible profiles
            if not score.get("eligible", True):
                rejection_count += 1
                reasons = score.get("eligibility_reasons") or score.get("reasons") or []
                if reasons:
                    score_entry["rejection_reasons"] = reasons[:3]  # Limit reasons
            top_scores.append(score_entry)
        
        metadata["top_scores"] = top_scores
        metadata["rejection_count"] = rejection_count
        metadata["total_profiles_evaluated"] = len(profile_scores)
    
    return metadata if metadata else None


class WarmupTracker:
    """Track per-symbol warmup readiness."""

    def __init__(self, min_samples: int, min_age_sec: float):
        self.min_samples = min_samples
        self.min_age_sec = min_age_sec
        self.min_candles = 0
        self._counts: dict[str, int] = {}
        self._first_ts: dict[str, float] = {}

    def record(self, symbol: str, timestamp: Optional[float], candle_count: int) -> tuple[bool, dict]:
        if symbol not in self._counts:
            self._counts[symbol] = 0
            if timestamp:
                self._first_ts[symbol] = float(timestamp)
        self._counts[symbol] += 1
        count_ready = self._counts[symbol] >= self.min_samples
        candle_ready = candle_count >= self.min_candles if self.min_candles > 0 else True
        
        # If min_age_sec is disabled (<=0), just use sample count
        if self.min_age_sec <= 0:
            return count_ready and candle_ready, self._stats(symbol, timestamp, candle_count)
        
        # If timestamps are missing, fall back to sample count only (be forgiving)
        first_ts = self._first_ts.get(symbol)
        if not first_ts or not timestamp:
            # No timestamp available - use sample count as fallback
            return count_ready and candle_ready, self._stats(symbol, timestamp, candle_count)
        
        age_ready = (float(timestamp) - first_ts) >= self.min_age_sec
        return count_ready and age_ready and candle_ready, self._stats(symbol, timestamp, candle_count)

    def _stats(self, symbol: str, timestamp: Optional[float], candle_count: int) -> dict:
        return {
            "count": self._counts.get(symbol, 0),
            "first_ts": self._first_ts.get(symbol),
            "latest_ts": float(timestamp) if timestamp else None,
            "candle_count": candle_count,
        }
