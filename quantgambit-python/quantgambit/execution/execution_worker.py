"""Execution worker consuming decisions and emitting intents."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Dict, Set, TYPE_CHECKING
import asyncio
import os
import time
import uuid

from quantgambit.observability.logger import log_warning, log_info
from quantgambit.execution.manager import ExecutionIntent, ExecutionManager, OrderStatus
from quantgambit.execution.order_statuses import normalize_order_status, is_open_status, is_terminal_status
from quantgambit.execution.idempotency import build_client_order_id
from quantgambit.execution.idempotency_store import RedisIdempotencyStore, IdempotencyConfig
from quantgambit.execution.symbols import normalize_exchange_symbol
from quantgambit.observability.schemas import order_payload
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter
from quantgambit.storage.redis_streams import RedisStreamsClient, decode_and_validate_event

if TYPE_CHECKING:
    from quantgambit.core.latency import LatencyTracker
    from quantgambit.config.trading_mode import TradingModeManager
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


@dataclass
class ExecutionWorkerConfig:
    source_stream: str = "events:risk_decisions"
    consumer_group: str = "quantgambit_execution"
    consumer_name: str = "execution_worker"
    block_ms: int = 1000
    max_retries: int = 2
    base_backoff_sec: float = 0.25
    max_backoff_sec: float = 2.0
    status_poll_interval_sec: float = 0.5
    status_poll_attempts: int = 6
    max_decision_age_sec: float = 60.0  # Increased from 5.0 - market data timestamps can be delayed
    max_reference_price_age_sec: float = 60.0  # Increased from 5.0
    max_orderbook_age_sec: float = 60.0  # Increased from 5.0
    dedupe_ttl_sec: int = 300
    # Per-symbol throttling to prevent rapid-fire orders
    min_order_interval_sec: float = 60.0  # Minimum 60 seconds between orders for same symbol (was 10)
    # Block new positions if symbol already has open position
    block_if_position_exists: bool = True
    # Use exchange positions as an additional authoritative gate for anti-stacking.
    enforce_exchange_position_gate: bool = True
    # Hard cap on per-order notional at execution layer (0 disables).
    hard_max_order_notional_usd: float = 0.0
    # Hard cap on resulting per-symbol notional at execution layer (0 disables).
    hard_max_symbol_notional_usd: float = 0.0
    # Allow replacement flow to close and reopen when a stronger signal appears
    allow_position_replacement: bool = False
    # When replacing, only allow opposite-side replacement (default True).
    # Set False to allow same-side replacement (close + reopen same side).
    replace_opposite_only: bool = True
    # Exit signal gating
    exit_min_hold_sec: float = 0.0
    exit_enforce_fee_check: bool = True
    # Exit signal dedupe to prevent repeated closes within a short window
    exit_dedupe_ttl_sec: int = 10
    # Optional short cooldown for non-safety exit signals to reduce close churn
    exit_min_signal_interval_sec: float = 2.0
    exit_no_position_cooldown_sec: float = 10.0
    # Entry execution mode: market (default) or maker_post_only
    entry_execution_mode: str = "market"
    entry_maker_fill_window_ms: int = 800
    entry_maker_max_reposts: int = 1
    entry_maker_price_offset_ticks: int = 0
    entry_maker_fallback_to_market: bool = True
    entry_maker_skip_cooldown_ms: int = 2000
    entry_stop_out_cooldown_ms: int = 60000
    entry_max_attempts_per_symbol_per_min: int = 12
    entry_maker_enable_symbols: Optional[Set[str]] = None
    entry_partial_accept: bool = True
    entry_min_fill_notional_usd: float = 10.0
    entry_max_spread_bps: float = 0.0
    entry_max_spread_ticks: int = 0
    entry_max_reference_age_ms: int = 1500
    entry_max_orderbook_age_ms: int = 1500
    market_type: str = "perp"
    # Auto entry mode tuning (ENTRY_EXECUTION_MODE=auto).
    # Goal: increase fill rate by using market orders when urgency/edge warrants it,
    # while still allowing maker-post-only when it is likely to fill cheaply.
    entry_auto_taker_edge_multiple: float = 8.0
    entry_auto_taker_max_spread_bps: float = 0.2
    entry_auto_force_market_ttw_sec: float = 25.0
    execution_experiment_id: str = "maker-first-v1"


class ExecutionWorker:
    """Consumes decisions and emits execution intents."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        execution_manager: ExecutionManager,
        bot_id: str,
        exchange: str,
        tenant_id: Optional[str] = None,
        idempotency_store: Optional[RedisIdempotencyStore] = None,
        config: Optional[ExecutionWorkerConfig] = None,
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        kill_switch=None,  # PersistentKillSwitch or compatible
        latency_tracker: Optional["LatencyTracker"] = None,
        trading_mode_manager: Optional["TradingModeManager"] = None,
        blocked_signal_telemetry: Optional["BlockedSignalTelemetry"] = None,
    ):
        self.redis = redis_client
        self.execution_manager = execution_manager
        self.bot_id = bot_id
        self.exchange = exchange
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.config = config or ExecutionWorkerConfig()
        self.snapshots = RedisSnapshotWriter(redis_client.redis)
        self._kill_switch = kill_switch
        self._latency_tracker = latency_tracker
        self._trading_mode_manager = trading_mode_manager
        self._blocked_signal_telemetry = blocked_signal_telemetry
        self.idempotency_store = idempotency_store or RedisIdempotencyStore(
            redis_client.redis,
            bot_id=self.bot_id,
            tenant_id=tenant_id,
            config=IdempotencyConfig(ttl_sec=self.config.dedupe_ttl_sec),
        )
        self._exit_idempotency_store = RedisIdempotencyStore(
            redis_client.redis,
            bot_id=self.bot_id,
            tenant_id=tenant_id,
            config=IdempotencyConfig(ttl_sec=self.config.exit_dedupe_ttl_sec, namespace="quantgambit_exit"),
        )
        # Per-symbol throttling: track last order time and in-flight orders
        self._last_order_time: Dict[str, float] = {}
        self._in_flight_symbols: Set[str] = set()
        self._symbol_locks: Dict[str, asyncio.Lock] = {}
        self._kill_switch_block_count = 0  # Track blocks for telemetry
        self._last_exit_signal_time: Dict[str, float] = {}
        self._exit_no_position_until: Dict[str, float] = {}
        self._last_throttle_error_time: Dict[str, float] = {}
        self._last_throttle_window_order_time: Dict[str, float] = {}
        self._entry_attempts: Dict[str, list[float]] = {}
        self._entry_skip_until: Dict[str, float] = {}
        self._stop_out_skip_until: Dict[str, float] = {}
        allowed_raw = os.getenv("PREDICTION_ALLOWED_DIRECTIONS", "")
        self._allowed_directions: Set[str] = {
            token.strip().lower() for token in allowed_raw.split(",") if token.strip()
        }

    async def run(self) -> None:
        log_info("execution_worker_start", source=self.config.source_stream)
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
            latency_start = self._latency_tracker.start_timer("execution_worker")
        
        try:
            await self._handle_message_inner(payload)
        finally:
            # End latency tracking
            if self._latency_tracker and latency_start is not None:
                self._latency_tracker.end_timer("execution_worker", latency_start)

    async def _handle_message_inner(self, payload: dict) -> None:
        # CRITICAL: Check kill switch before any execution
        if self._kill_switch and self._kill_switch.is_active():
            self._kill_switch_block_count += 1
            if self._kill_switch_block_count % 100 == 1:  # Log every 100th block to avoid spam
                log_warning(
                    "execution_worker_kill_switch_active",
                    bot_id=self.bot_id,
                    blocked_count=self._kill_switch_block_count,
                )
            return
        
        try:
            event = decode_and_validate_event(payload)
        except Exception as exc:
            log_warning("execution_worker_invalid_event", error=str(exc))
            await self._record_error(
                stage="decode",
                error_message=str(exc),
                error_code="invalid_event",
                payload={"source": "execution_worker"},
            )
            return
        if event.get("event_type") != "risk_decision":
            return
        decision = event.get("payload") or {}
        decision_id = str(decision.get("decision_id") or event.get("event_id") or "")
        if not decision_id:
            decision_id = str(uuid.uuid4())
        if decision.get("shadow_mode") or decision.get("status") == "shadow":
            return
        if decision.get("status") != "accepted":
            return
        decision_ts = decision.get("timestamp")
        if decision_ts and time.time() - float(decision_ts) > self.config.max_decision_age_sec:
            log_warning("execution_worker_stale_decision", symbol=decision.get("symbol"), bot_id=self.bot_id)
            return
        if not self._is_reference_price_fresh(decision.get("symbol")):
            log_warning("execution_worker_stale_reference_price", symbol=decision.get("symbol"), bot_id=self.bot_id)
            return
        if not self._is_orderbook_fresh(decision.get("symbol")):
            log_warning("execution_worker_stale_orderbook", symbol=decision.get("symbol"), bot_id=self.bot_id)
            return
        signal = decision.get("signal") or {}
        if not signal:
            log_warning("execution_worker_missing_signal", symbol=decision.get("symbol"), bot_id=self.bot_id)
            return
        self._record_stop_out_exit(decision, signal)
        is_replace_signal = bool(signal.get("replace_position")) and self.config.allow_position_replacement
        is_exit_signal = signal.get("is_exit_signal", False) or signal.get("reduce_only", False)

        # Hard direction policy enforcement at execution layer so no upstream
        # stage/strategy path can bypass short disable.
        side_for_policy = str(signal.get("side") or "").lower()
        is_entry_signal = not is_exit_signal and not is_replace_signal
        if is_entry_signal and self._allowed_directions:
            side_direction = "down" if side_for_policy == "short" else "up" if side_for_policy == "long" else None
            if side_direction and side_direction not in self._allowed_directions:
                await self._record_error(
                    stage="entry_gate",
                    error_message=f"direction_policy_blocked:{side_direction}",
                    symbol=decision.get("symbol"),
                    error_code="direction_policy_blocked",
                )
                log_warning(
                    "execution_worker_direction_policy_blocked",
                    symbol=decision.get("symbol"),
                    side=side_for_policy,
                    side_direction=side_direction,
                    allowed=sorted(self._allowed_directions),
                )
                return
        
        # Per-symbol throttling: prevent rapid-fire orders
        symbol = decision.get("symbol")
        if symbol:
            # Detect exit signals early - they bypass throttle (Requirement 8)
            if not is_exit_signal:
                await self._normalize_entry_size(symbol, decision, signal)
            
            # Check if there's already an order in-flight for this symbol
            if symbol in self._in_flight_symbols:
                log_warning(
                    "execution_worker_symbol_in_flight",
                    symbol=symbol,
                    bot_id=self.bot_id,
                    reason="order_already_in_progress",
                )
                await self._record_error(
                    stage="throttle",
                    error_message="symbol_in_flight",
                    symbol=symbol,
                    error_code="throttled_in_flight",
                )
                return
            
            # Get mode-specific min_order_interval_sec
            min_order_interval = self.config.min_order_interval_sec
            if self._trading_mode_manager:
                mode_config = self._trading_mode_manager.get_config(symbol)
                min_order_interval = mode_config.min_order_interval_sec
            
            # EXIT SIGNALS BYPASS THROTTLE (Requirement 8.1, 8.3)
            # Exit signals must never be blocked by execution throttle
            if is_exit_signal or is_replace_signal:
                # Guard against rapid-fire non-safety exit churn from repeated pipeline ticks.
                if is_exit_signal:
                    exit_type = str(signal.get("exit_type") or "").lower()
                    is_safety_exit = exit_type == "safety"
                    min_exit_interval = max(0.0, float(self.config.exit_min_signal_interval_sec))
                    no_position_until = self._exit_no_position_until.get(symbol, 0.0)
                    if time.time() < no_position_until:
                        await self._record_error(
                            stage="exit_gate",
                            error_message=f"exit_signal_no_position_cooldown:{no_position_until - time.time():.2f}s",
                            symbol=symbol,
                            error_code="exit_signal_no_position_cooldown",
                        )
                        return
                    if (not is_safety_exit) and min_exit_interval > 0:
                        last_exit_time = self._last_exit_signal_time.get(symbol, 0.0)
                        since_last_exit = time.time() - last_exit_time
                        if since_last_exit < min_exit_interval:
                            log_warning(
                                "execution_worker_exit_signal_throttled",
                                symbol=symbol,
                                bot_id=self.bot_id,
                                exit_type=exit_type or "unknown",
                                since_last_exit=since_last_exit,
                                min_interval=min_exit_interval,
                            )
                            await self._record_error(
                                stage="exit_gate",
                                error_message=f"exit_signal_rate_limited:{since_last_exit:.2f}s",
                                symbol=symbol,
                                error_code="exit_signal_rate_limited",
                            )
                            return
                log_info(
                    "execution_worker_throttle_bypassed",
                    symbol=symbol,
                    bot_id=self.bot_id,
                    reason="exit_signal" if is_exit_signal else "replace_signal",
                    is_exit_signal=is_exit_signal,
                    is_replace_signal=is_replace_signal,
                )
                if is_exit_signal:
                    self._last_exit_signal_time[symbol] = time.time()
            else:
                # Check minimum time between orders for same symbol (entry signals only)
                last_time = self._last_order_time.get(symbol, 0)
                time_since_last = time.time() - last_time
                if time_since_last < min_order_interval:
                    last_reported_order_time = self._last_throttle_window_order_time.get(symbol)
                    should_report = last_reported_order_time != last_time
                    if should_report:
                        self._last_throttle_window_order_time[symbol] = last_time
                        self._last_throttle_error_time[symbol] = time.time()
                        log_warning(
                            "execution_worker_throttled",
                            symbol=symbol,
                            bot_id=self.bot_id,
                            time_since_last=time_since_last,
                            min_interval=min_order_interval,
                            mode=self._trading_mode_manager.get_mode(symbol).value if self._trading_mode_manager else "default",
                        )
                        await self._record_error(
                            stage="throttle",
                            error_message=f"throttled: {time_since_last:.1f}s < {min_order_interval}s",
                            symbol=symbol,
                            error_code="throttled_cooldown",
                        )
                        # Emit blocked signal telemetry (Requirement 9.1)
                        if self._blocked_signal_telemetry:
                            await self._blocked_signal_telemetry.record_blocked(
                                symbol=symbol,
                                gate_name="execution_throttle",
                                reason=f"throttled: {time_since_last:.1f}s < {min_order_interval}s",
                                metrics={
                                    "time_since_last": time_since_last,
                                    "min_interval": min_order_interval,
                                    "mode": self._trading_mode_manager.get_mode(symbol).value if self._trading_mode_manager else "default",
                                },
                            )
                    return
            
            # Hard execution-layer protection for entry signals:
            # - block if local or exchange position exists (anti-stacking)
            # - enforce per-order and resulting per-symbol notional caps
            if not is_exit_signal and not is_replace_signal:
                local_pos = None
                exchange_pos = None
                if self.config.block_if_position_exists:
                    try:
                        local_pos = await self._find_local_position(symbol)
                    except Exception as e:
                        log_warning("execution_worker_position_check_failed", error=str(e))
                    if self.config.enforce_exchange_position_gate:
                        try:
                            exchange_pos = await self._find_exchange_position(symbol)
                        except Exception as e:
                            log_warning("execution_worker_exchange_position_check_failed", error=str(e))

                    if local_pos or exchange_pos:
                        existing_side = (local_pos or exchange_pos).get("side")
                        existing_size = (local_pos or exchange_pos).get("size")
                        source = "exchange" if exchange_pos else "local"
                        self._last_order_time[symbol] = time.time()
                        log_warning(
                            "execution_worker_position_exists",
                            symbol=symbol,
                            bot_id=self.bot_id,
                            source=source,
                            existing_size=existing_size,
                            existing_side=existing_side,
                        )
                        await self._record_error(
                            stage="throttle",
                            error_message=f"position_exists_{source}: {existing_side} {existing_size}",
                            symbol=symbol,
                            error_code="position_exists",
                        )
                        return

                requested_size = _safe_float(signal.get("size"))
                ref_price = await self._resolve_reference_price(symbol, signal)
                if requested_size is not None and requested_size > 0 and ref_price is not None and ref_price > 0:
                    requested_notional = requested_size * ref_price
                    if (
                        self.config.hard_max_order_notional_usd > 0
                        and requested_notional > self.config.hard_max_order_notional_usd
                    ):
                        log_warning(
                            "execution_worker_order_notional_blocked",
                            symbol=symbol,
                            bot_id=self.bot_id,
                            requested_notional=requested_notional,
                            hard_max_order_notional_usd=self.config.hard_max_order_notional_usd,
                        )
                        await self._record_error(
                            stage="risk_hard_guard",
                            error_message=f"order_notional_exceeded:{requested_notional:.2f}",
                            symbol=symbol,
                            error_code="order_notional_exceeded",
                        )
                        return

                    if self.config.hard_max_symbol_notional_usd > 0:
                        existing_size_local = (local_pos or {}).get("size", 0.0)
                        existing_size_exchange = (exchange_pos or {}).get("size", 0.0)
                        existing_size = max(existing_size_local, existing_size_exchange)
                        resulting_notional = (existing_size + requested_size) * ref_price
                        if resulting_notional > self.config.hard_max_symbol_notional_usd:
                            log_warning(
                                "execution_worker_symbol_notional_blocked",
                                symbol=symbol,
                                bot_id=self.bot_id,
                                resulting_notional=resulting_notional,
                                hard_max_symbol_notional_usd=self.config.hard_max_symbol_notional_usd,
                            )
                            await self._record_error(
                                stage="risk_hard_guard",
                                error_message=f"symbol_notional_exceeded:{resulting_notional:.2f}",
                                symbol=symbol,
                                error_code="symbol_notional_exceeded",
                            )
                            return
            
            if is_replace_signal:
                try:
                    positions = await self.execution_manager.position_manager.list_open_positions()
                    symbol_positions = [p for p in positions if p.symbol == symbol]
                    existing_position = symbol_positions[0] if symbol_positions else None
                except Exception as e:
                    log_warning("execution_worker_replace_position_check_failed", error=str(e))
                    existing_position = None
                if existing_position is None:
                    log_warning(
                        "execution_worker_replace_no_position",
                        symbol=symbol,
                        bot_id=self.bot_id,
                        reason="no_position_to_replace",
                    )
                    is_replace_signal = False
                elif not _is_opposite_position(signal.get("side"), existing_position.side):
                    if not self.config.replace_opposite_only:
                        log_info(
                            "execution_worker_replace_same_side_allowed",
                            symbol=symbol,
                            bot_id=self.bot_id,
                            existing_side=existing_position.side,
                            new_side=signal.get("side"),
                        )
                    else:
                        log_warning(
                            "execution_worker_replace_same_side_blocked",
                            symbol=symbol,
                            bot_id=self.bot_id,
                            existing_side=existing_position.side,
                            new_side=signal.get("side"),
                        )
                        await self._record_error(
                            stage="replace",
                            error_message="replace_same_side_blocked",
                            symbol=symbol,
                            error_code="replace_same_side_blocked",
                        )
                        return
                else:
                    close_side = "sell" if existing_position.side == "long" else "buy"
                    close_client_order_id = build_client_order_id(
                        self.bot_id,
                        f"{decision_id}:replace_close",
                        decision.get("symbol"),
                        close_side,
                        existing_position.size,
                    )
                    if await self._intent_exists(close_client_order_id):
                        log_warning(
                            "execution_worker_replace_close_exists",
                            client_order_id=close_client_order_id,
                            symbol=symbol,
                        )
                        return
                    if not await self._mark_idempotent(close_client_order_id):
                        log_warning(
                            "execution_worker_replace_close_duplicate",
                            client_order_id=close_client_order_id,
                            symbol=symbol,
                        )
                        return
                    close_intent = ExecutionIntent(
                        symbol=decision.get("symbol"),
                        side=close_side,
                        size=existing_position.size,
                        client_order_id=close_client_order_id,
                        reduce_only=True,
                        is_exit_signal=True,
                    )
                    await self._record_intent(
                        intent=close_intent,
                        status="created",
                        decision_id=decision_id,
                        snapshot_metrics={
                            "replace_action": "close",
                            "replace_reason": signal.get("replace_reason"),
                        },
                    )
                    if not await self._execute_with_retry(close_intent, decision.get("timestamp")):
                        log_warning(
                            "execution_worker_replace_close_failed",
                            symbol=symbol,
                            bot_id=self.bot_id,
                        )
                        return
            
            # For exit signals, verify position still exists and isn't already being closed
            if is_exit_signal:
                if symbol and not await self._mark_exit_idempotent(symbol, decision_id):
                    log_warning(
                        "execution_worker_exit_deduped",
                        symbol=symbol,
                        bot_id=self.bot_id,
                        reason="exit_signal_recently_processed",
                    )
                    return
                try:
                    positions = await self.execution_manager.position_manager.list_open_positions()
                    symbol_positions = [p for p in positions if p.symbol == symbol]
                    if not symbol_positions:
                        if signal.get("size") is None:
                            log_warning(
                                "execution_worker_exit_no_position",
                                symbol=symbol,
                                bot_id=self.bot_id,
                                reason="position_missing_and_size_unknown",
                            )
                            await self._record_error(
                                stage="throttle",
                                error_message="exit_signal_no_position",
                                symbol=symbol,
                                error_code="no_position_to_close",
                            )
                            return
                        log_warning(
                            "execution_worker_exit_no_position",
                            symbol=symbol,
                            bot_id=self.bot_id,
                            reason="local_state_missing_attempt_exchange_close",
                        )
                except Exception as e:
                    log_warning("execution_worker_exit_position_check_failed", error=str(e))

                # Enforce fee-aware exit gating for strategic exits
                fee_aware = signal.get("fee_aware") or {}
                fee_check_passed = fee_aware.get("fee_check_passed")
                fee_check_bypassed = fee_aware.get("fee_check_bypassed", False)
                exit_type = (signal.get("exit_type") or "").lower()
                if fee_check_passed is None:
                    # Backward-compatible default:
                    # - fail-closed for explicit invalidation exits
                    # - fail-open for safety/legacy signals that omit exit_type metadata
                    fee_check_passed = exit_type != "invalidation"
                if self.config.exit_enforce_fee_check and not fee_check_passed and not fee_check_bypassed:
                    log_warning(
                        "execution_worker_exit_fee_blocked",
                        symbol=symbol,
                        bot_id=self.bot_id,
                        exit_type=exit_type,
                        reason=fee_aware.get("reason") or "fee_check_blocked",
                        net_pnl_bps=fee_aware.get("net_pnl_bps"),
                        min_required_bps=fee_aware.get("min_required_bps"),
                        shortfall_bps=fee_aware.get("shortfall_bps"),
                    )
                    await self._record_error(
                        stage="exit_gate",
                        error_message="fee_check_blocked",
                        symbol=symbol,
                        error_code="exit_fee_blocked",
                    )
                    return

                # Enforce minimum hold time for non-safety exits
                if self.config.exit_min_hold_sec > 0 and exit_type != "safety":
                    hold_time_sec = signal.get("hold_time_sec")
                    try:
                        hold_time_sec = float(hold_time_sec) if hold_time_sec is not None else None
                    except (TypeError, ValueError):
                        hold_time_sec = None
                    if hold_time_sec is not None and hold_time_sec < self.config.exit_min_hold_sec:
                        log_warning(
                            "execution_worker_exit_min_hold_blocked",
                            symbol=symbol,
                            bot_id=self.bot_id,
                            hold_time_sec=hold_time_sec,
                            min_hold_sec=self.config.exit_min_hold_sec,
                            exit_type=exit_type,
                        )
                        await self._record_error(
                            stage="exit_gate",
                            error_message="min_hold_not_met",
                            symbol=symbol,
                            error_code="exit_min_hold_blocked",
                        )
                        return
            
            # Log exit signals for visibility
            if is_exit_signal:
                log_info(
                    "execution_worker_exit_signal",
                    symbol=symbol,
                    bot_id=self.bot_id,
                    side=signal.get("side"),
                    signal_type=signal.get("signal_type"),
                    meta_reason=signal.get("meta_reason"),
                )
        is_entry_signal = not is_exit_signal and not is_replace_signal
        if is_entry_signal:
            if not self._allow_entry_after_stop_out(decision.get("symbol")):
                await self._record_error(
                    stage="entry_gate",
                    error_message="stop_out_cooldown_active",
                    symbol=decision.get("symbol"),
                    error_code="stop_out_cooldown",
                )
                return
            if not self._allow_entry_by_skip_cooldown(decision.get("symbol"), signal.get("side")):
                await self._record_error(
                    stage="entry_gate",
                    error_message="maker_skip_cooldown_active",
                    symbol=decision.get("symbol"),
                    error_code="maker_skip_cooldown",
                )
                return
            if not self._allow_entry_attempt_rate(decision.get("symbol")):
                await self._record_error(
                    stage="entry_gate",
                    error_message="entry_attempt_rate_limited",
                    symbol=decision.get("symbol"),
                    error_code="entry_attempt_rate_limited",
                )
                return
            spread_reject = self._check_entry_spread_limits(decision)
            if spread_reject:
                await self._record_error(
                    stage="entry_gate",
                    error_message=spread_reject,
                    symbol=decision.get("symbol"),
                    error_code="entry_spread_blocked",
                )
                return
            freshness_reject = self._check_entry_freshness_limits(decision.get("symbol"))
            if freshness_reject:
                await self._record_error(
                    stage="entry_gate",
                    error_message=freshness_reject,
                    symbol=decision.get("symbol"),
                    error_code="entry_stale_data_blocked",
                )
                return
        
        log_info(
            "execution_intent_start",
            symbol=decision.get("symbol"),
            bot_id=self.bot_id,
            side=signal.get("side"),
            size=signal.get("size"),
            replace_position=is_replace_signal,
        )
        client_order_id = build_client_order_id(
            self.bot_id,
            decision_id,
            decision.get("symbol"),
            signal.get("side"),
            signal.get("size"),
        )
        if await self._intent_exists(client_order_id):
            log_warning("execution_worker_intent_exists", client_order_id=client_order_id)
            await self._record_error(
                stage="dedupe_db",
                error_message="intent_exists",
                symbol=decision.get("symbol"),
                client_order_id=client_order_id,
                error_code="intent_exists",
            )
            return
        if not await self._mark_idempotent(client_order_id):
            log_warning("execution_worker_duplicate_intent", client_order_id=client_order_id)
            return
        # DEBUG: Log signal SL/TP before creating intent
        signal_sl = signal.get("stop_loss")
        signal_tp = signal.get("take_profit")
        log_info(
            "execution_worker_intent_sltp_debug",
            symbol=decision.get("symbol"),
            signal_has_sl=signal_sl is not None,
            signal_has_tp=signal_tp is not None,
            signal_sl=signal_sl,
            signal_tp=signal_tp,
            strategy=signal.get("strategy_id"),
        )
        decision_execution_policy = decision.get("execution_policy") or {}
        policy_mode = str(decision_execution_policy.get("mode") or "").strip().lower()
        if policy_mode and policy_mode not in {"maker_first", "taker_only"}:
            await self._record_error(
                stage="entry_gate",
                error_message=f"unsupported_execution_policy:{policy_mode}",
                symbol=decision.get("symbol"),
                error_code="unsupported_execution_policy",
                payload={"execution_policy": decision_execution_policy},
            )
            return
        execution_policy = "market"
        execution_cohort = "baseline_market"
        if policy_mode == "maker_first":
            execution_policy = "maker_first"
            execution_cohort = "maker_first"
        elif policy_mode == "taker_only":
            execution_policy = "market"
            execution_cohort = "taker_only"
        intent = ExecutionIntent(
            symbol=decision.get("symbol"),
            side=signal.get("side"),
            size=signal.get("size"),
            entry_price=signal.get("entry_price"),
            stop_loss=signal_sl,
            take_profit=signal_tp,
            strategy_id=signal.get("strategy_id"),
            profile_id=signal.get("profile_id"),
            client_order_id=client_order_id,
            decision_id=decision_id,
            prediction_confidence=signal.get("prediction_confidence") or decision.get("prediction_confidence"),
            prediction_direction=(
                (decision.get("prediction") or {}).get("direction")
                or signal.get("prediction_direction")
            ),
            prediction_source=(
                (decision.get("prediction") or {}).get("source")
                or (decision.get("prediction") or {}).get("provider")
                or signal.get("prediction_source")
            ),
            entry_p_hat=signal.get("p_hat"),
            entry_p_hat_source=signal.get("p_hat_source"),
            reduce_only=signal.get("reduce_only", False),
            is_exit_signal=signal.get("is_exit_signal", False),
            # Time budget parameters (MFT scalping)
            expected_horizon_sec=signal.get("expected_horizon_sec"),
            time_to_work_sec=signal.get("time_to_work_sec"),
            max_hold_sec=signal.get("max_hold_sec") or signal.get("max_hold_time_seconds"),
            mfe_min_bps=signal.get("mfe_min_bps"),
            exit_reason=signal.get("meta_reason"),
            # Prediction context (Bug 8 fix)
            model_side=signal.get("model_side") or (decision.get("model_direction_alignment") or {}).get("model_side"),
            p_up=(decision.get("prediction") or {}).get("p_up"),
            p_down=(decision.get("prediction") or {}).get("p_down"),
            p_flat=(decision.get("prediction") or {}).get("p_flat"),
            execution_policy=execution_policy,
            execution_cohort=execution_cohort,
            execution_experiment_id=(self.config.execution_experiment_id or None),
        )
        if is_entry_signal and execution_policy == "maker_first":
            maker_plan = await self._build_entry_execution_plan(decision, signal)
            if maker_plan:
                new_limit = maker_plan.get("limit_price")
                # Rebase SL/TP relative to the limit price when it differs from
                # the original entry price.  The signal's SL/TP are computed from
                # mid price, but the limit order sits at best-bid/ask which can be
                # on the other side of the SL — causing Bybit to reject the order.
                adjusted_sl = intent.stop_loss
                adjusted_tp = intent.take_profit
                original_entry = intent.entry_price
                if new_limit and original_entry and original_entry > 0:
                    delta = new_limit - original_entry
                    if adjusted_sl is not None:
                        adjusted_sl = adjusted_sl + delta
                    if adjusted_tp is not None:
                        adjusted_tp = adjusted_tp + delta
                intent = replace(
                    intent,
                    order_type=maker_plan.get("order_type", intent.order_type),
                    limit_price=new_limit,
                    post_only=bool(maker_plan.get("post_only", False)),
                    time_in_force=maker_plan.get("time_in_force"),
                    mid_at_send=maker_plan.get("mid_at_send"),
                    expected_price_at_send=maker_plan.get("expected_price_at_send"),
                    send_ts=time.time(),
                    execution_policy="maker_first",
                    execution_cohort="maker_first",
                    stop_loss=adjusted_sl,
                    take_profit=adjusted_tp,
                )
                log_info(
                    "execution_worker_entry_plan",
                    symbol=intent.symbol,
                    side=intent.side,
                    order_type=intent.order_type,
                    limit_price=intent.limit_price,
                    post_only=intent.post_only,
                    fill_window_ms=self.config.entry_maker_fill_window_ms,
                )
        elif is_entry_signal and policy_mode == "taker_only":
            log_info(
                "execution_worker_entry_policy_forced_taker",
                symbol=decision.get("symbol"),
                side=signal.get("side"),
                reason=decision_execution_policy.get("reason"),
            )
        # Extract snapshot metrics for post-trade analysis
        snapshot_metrics = _extract_snapshot_metrics(decision)
        await self._record_intent(
            intent=intent,
            status="created",
            decision_id=decision_id,
            snapshot_metrics=snapshot_metrics,
        )
        
        # Mark symbol as in-flight to prevent concurrent orders
        if symbol:
            self._in_flight_symbols.add(symbol)
        if is_entry_signal and symbol:
            self._record_entry_attempt(symbol)
        
        executed_ok = False
        try:
            executed_ok = await self._execute_with_retry(intent, decision.get("timestamp"))
        finally:
            # Clear in-flight status. Entry cooldown should only start after a
            # real successful execution path, not after every failed/no-op
            # attempt, otherwise accepted decisions self-throttle indefinitely.
            if symbol:
                self._in_flight_symbols.discard(symbol)
                if is_entry_signal and executed_ok:
                    self._last_order_time[symbol] = time.time()

    async def _mark_idempotent(self, client_order_id: Optional[str]) -> bool:
        try:
            return await self.idempotency_store.claim(client_order_id)
        except Exception as exc:
            log_warning("execution_worker_dedupe_failed", error=str(exc))
        return True

    async def _find_local_position(self, symbol: Optional[str]) -> Optional[dict]:
        if not symbol:
            return None
        positions = await self.execution_manager.position_manager.list_open_positions()
        for pos in positions:
            if pos.symbol == symbol:
                return {"side": (pos.side or "").lower(), "size": abs(float(pos.size or 0.0))}
        return None

    async def _find_exchange_position(self, symbol: Optional[str]) -> Optional[dict]:
        if not symbol:
            return None
        client = getattr(self.execution_manager, "exchange_client", None)
        fetcher = getattr(client, "fetch_positions", None)
        if fetcher is None:
            return None

        normalized_target = normalize_exchange_symbol(self.exchange, symbol)
        exchange_positions = await fetcher()
        for raw in exchange_positions or []:
            raw_symbol = raw.get("symbol") or raw.get("instId") or raw.get("market")
            normalized = normalize_exchange_symbol(self.exchange, raw_symbol)
            if normalized != normalized_target:
                continue
            size_val = _safe_float(raw.get("size"))
            if size_val is None:
                size_val = _safe_float(raw.get("contracts"))
            if size_val is None:
                size_val = _safe_float(raw.get("positionAmt"))
            if size_val is None:
                size_val = _safe_float(raw.get("qty"))
            if size_val is None:
                continue
            if abs(size_val) <= 0:
                continue
            side_raw = (raw.get("side") or "").lower()
            if side_raw not in {"long", "short"}:
                side_raw = "short" if size_val < 0 else "long"
            return {"side": side_raw, "size": abs(float(size_val))}
        return None

    async def _resolve_reference_price(self, symbol: Optional[str], signal: dict) -> Optional[float]:
        direct = _safe_float(signal.get("entry_price"))
        if direct is not None and direct > 0:
            return direct
        if symbol:
            exchange_client = getattr(self.execution_manager, "exchange_client", None)
            reference_prices = getattr(exchange_client, "reference_prices", None)
            if reference_prices is None and hasattr(exchange_client, "_inner"):
                reference_prices = getattr(getattr(exchange_client, "_inner", None), "reference_prices", None)
            if reference_prices and hasattr(reference_prices, "get_reference_price"):
                val = _safe_float(reference_prices.get_reference_price(symbol))
                if val is not None and val > 0:
                    return val
        return None

    async def _normalize_entry_size(self, symbol: str, decision: dict, signal: dict) -> None:
        raw_size = _safe_float(signal.get("size"))
        if raw_size is None or raw_size <= 0:
            return

        entry_price = _safe_float(signal.get("entry_price"))
        if entry_price is None or entry_price <= 0:
            entry_price = await self._resolve_reference_price(symbol, signal)
        if entry_price is None or entry_price <= 0:
            return

        size_usd = (
            _safe_float(signal.get("size_usd"))
            or _safe_float(decision.get("size_usd"))
            or _safe_float((signal.get("sizing_context") or {}).get("size_usd"))
        )
        implied_notional = raw_size * entry_price

        # Upstream can emit USD size in `size` for some paths; normalize to quantity.
        if size_usd and size_usd > 0 and implied_notional > max(size_usd * 4.0, 5000.0):
            normalized_size = size_usd / entry_price
            if normalized_size > 0:
                original_size = raw_size
                signal["size"] = normalized_size
                signal["size_usd"] = size_usd
                raw_size = normalized_size
                implied_notional = raw_size * entry_price
                log_warning(
                    "execution_worker_size_normalized_from_usd",
                    symbol=symbol,
                    original_size=original_size,
                    normalized_size=normalized_size,
                    size_usd=size_usd,
                    entry_price=entry_price,
                )

        if self.config.hard_max_order_notional_usd > 0 and implied_notional > self.config.hard_max_order_notional_usd:
            capped_size = self.config.hard_max_order_notional_usd / entry_price
            if capped_size > 0:
                signal["size"] = capped_size
                log_warning(
                    "execution_worker_size_capped_by_notional",
                    symbol=symbol,
                    original_notional=implied_notional,
                    hard_max_order_notional_usd=self.config.hard_max_order_notional_usd,
                    capped_size=capped_size,
                )

    async def _build_entry_execution_plan(self, decision: dict, signal: dict) -> Optional[dict]:
        mode = str(self.config.entry_execution_mode or "market").lower()
        auto_modes = {"auto", "dynamic"}
        maker_modes = {"maker_post_only", "limit", "post_only_limit", "maker_limit"} | auto_modes
        if mode not in maker_modes:
            return None

        # Dynamic maker/taker selection to improve fill rates.
        # Returning None here falls back to baseline market execution.
        if mode in auto_modes:
            risk_context = decision.get("risk_context") or {}
            spread_bps = _safe_float(risk_context.get("spread_bps"))
            expected_edge_bps = _safe_float(signal.get("expected_edge_bps"))
            cost_estimate_bps = _safe_float(signal.get("cost_estimate_bps"))
            time_to_work_sec = _safe_float(signal.get("time_to_work_sec"))

            # If the setup is time-sensitive, prefer immediate fill.
            if time_to_work_sec is not None and time_to_work_sec <= float(self.config.entry_auto_force_market_ttw_sec):
                return None

            # If edge massively dominates estimated costs, don't miss the trade.
            if (
                expected_edge_bps is not None
                and cost_estimate_bps is not None
                and cost_estimate_bps > 0
                and (expected_edge_bps / cost_estimate_bps) >= float(self.config.entry_auto_taker_edge_multiple)
            ):
                return None

            # If the market is very tight, maker advantage is small; prefer fill certainty.
            if (
                spread_bps is not None
                and spread_bps <= float(self.config.entry_auto_taker_max_spread_bps)
            ):
                return None

        symbol = decision.get("symbol")
        if self.config.entry_maker_enable_symbols and symbol not in self.config.entry_maker_enable_symbols:
            return None
        bid, ask, _ = self._read_best_bid_ask(symbol, decision)
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return None
        side = str(signal.get("side") or "").lower()
        mid = (bid + ask) / 2.0
        limit_price = self._derive_maker_limit_price(
            side=side,
            bid=bid,
            ask=ask,
            offset_ticks=int(self.config.entry_maker_price_offset_ticks),
        )
        return {
            "order_type": "limit",
            "post_only": True,
            "time_in_force": "GTC",
            "limit_price": limit_price,
            "mid_at_send": mid,
            "expected_price_at_send": limit_price,
        }

    def _read_best_bid_ask(
        self,
        symbol: Optional[str],
        decision: Optional[dict] = None,
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        risk_context = ((decision or {}).get("risk_context") or {}) if isinstance(decision, dict) else {}
        bid = _safe_float(risk_context.get("best_bid") or risk_context.get("bid"))
        ask = _safe_float(risk_context.get("best_ask") or risk_context.get("ask"))
        if (bid is None or ask is None) and symbol:
            exchange_client = getattr(self.execution_manager, "exchange_client", None)
            reference_prices = getattr(exchange_client, "reference_prices", None)
            if reference_prices is None and hasattr(exchange_client, "_inner"):
                reference_prices = getattr(getattr(exchange_client, "_inner", None), "reference_prices", None)
            if reference_prices and hasattr(reference_prices, "get_orderbook_with_ts"):
                result = reference_prices.get_orderbook_with_ts(symbol)
                if result:
                    book = result[0]
                    if isinstance(book, dict):
                        bids = book.get("bids") or []
                        asks = book.get("asks") or []
                        if bids and isinstance(bids[0], (list, tuple)) and len(bids[0]) >= 1:
                            bid = bid or _safe_float(bids[0][0])
                        if asks and isinstance(asks[0], (list, tuple)) and len(asks[0]) >= 1:
                            ask = ask or _safe_float(asks[0][0])
        spread_bps = None
        if bid is not None and ask is not None:
            mid = (bid + ask) / 2.0
            if mid > 0:
                spread_bps = ((ask - bid) / mid) * 10000.0
        return bid, ask, spread_bps

    def _allow_entry_by_skip_cooldown(self, symbol: Optional[str], side: Optional[str]) -> bool:
        if not symbol:
            return True
        key = f"{symbol}:{(side or '').lower()}"
        until = self._entry_skip_until.get(key, 0.0)
        return time.time() >= until

    def _activate_skip_cooldown(self, symbol: Optional[str], side: Optional[str]) -> None:
        if not symbol:
            return
        key = f"{symbol}:{(side or '').lower()}"
        self._entry_skip_until[key] = time.time() + max(0.0, self.config.entry_maker_skip_cooldown_ms / 1000.0)

    def _allow_entry_after_stop_out(self, symbol: Optional[str]) -> bool:
        if not symbol:
            return True
        until = self._stop_out_skip_until.get(symbol.upper(), 0.0)
        return time.time() >= until

    def _record_stop_out_exit(self, decision: dict, signal: dict) -> None:
        is_exit_signal = bool(signal.get("is_exit_signal", False) or signal.get("reduce_only", False))
        if not is_exit_signal:
            return
        symbol = str(decision.get("symbol") or "").strip().upper()
        if not symbol:
            return
        reason_blob = " ".join(
            str(value or "").lower()
            for value in (
                signal.get("reason"),
                signal.get("exit_reason"),
                signal.get("meta_reason"),
                decision.get("reason"),
                decision.get("exit_reason"),
            )
        )
        if "stop_loss" not in reason_blob and "stop-loss" not in reason_blob and "stop_out" not in reason_blob:
            return
        cooldown_sec = max(0.0, self.config.entry_stop_out_cooldown_ms / 1000.0)
        if cooldown_sec <= 0:
            return
        self._stop_out_skip_until[symbol] = time.time() + cooldown_sec

    def _record_entry_attempt(self, symbol: str) -> None:
        now = time.time()
        attempts = self._entry_attempts.setdefault(symbol, [])
        attempts.append(now)
        cutoff = now - 60.0
        self._entry_attempts[symbol] = [ts for ts in attempts if ts >= cutoff]

    def _allow_entry_attempt_rate(self, symbol: Optional[str]) -> bool:
        if not symbol:
            return True
        if self.config.entry_max_attempts_per_symbol_per_min <= 0:
            return True
        attempts = self._entry_attempts.get(symbol, [])
        now = time.time()
        cutoff = now - 60.0
        attempts = [ts for ts in attempts if ts >= cutoff]
        self._entry_attempts[symbol] = attempts
        return len(attempts) < self.config.entry_max_attempts_per_symbol_per_min

    def _check_entry_spread_limits(self, decision: dict) -> Optional[str]:
        if self.config.entry_max_spread_bps <= 0 and self.config.entry_max_spread_ticks <= 0:
            return None
        risk_context = decision.get("risk_context") or {}
        spread_bps = _safe_float(risk_context.get("spread_bps"))
        spread_ticks = _safe_float(risk_context.get("spread_ticks"))
        if (
            self.config.entry_max_spread_bps > 0
            and spread_bps is not None
            and spread_bps > self.config.entry_max_spread_bps
        ):
            return f"spread_bps_too_wide:{spread_bps:.3f}>{self.config.entry_max_spread_bps:.3f}"
        if (
            self.config.entry_max_spread_ticks > 0
            and spread_ticks is not None
            and spread_ticks > self.config.entry_max_spread_ticks
        ):
            return f"spread_ticks_too_wide:{spread_ticks:.2f}>{self.config.entry_max_spread_ticks}"
        return None

    def _check_entry_freshness_limits(self, symbol: Optional[str]) -> Optional[str]:
        if not symbol:
            return None
        exchange_client = getattr(self.execution_manager, "exchange_client", None)
        reference_prices = getattr(exchange_client, "reference_prices", None)
        if reference_prices is None and hasattr(exchange_client, "_inner"):
            reference_prices = getattr(getattr(exchange_client, "_inner", None), "reference_prices", None)
        if not reference_prices:
            return None
        now = time.time()
        book_age_ms: Optional[float] = None
        if (
            self.config.entry_max_orderbook_age_ms > 0
            and hasattr(reference_prices, "get_orderbook_with_ts")
        ):
            book_result = reference_prices.get_orderbook_with_ts(symbol)
            if not book_result:
                return "orderbook_missing"
            _, book_ts = book_result
            book_age_ms = (now - float(book_ts)) * 1000.0
            if book_age_ms > self.config.entry_max_orderbook_age_ms:
                return f"orderbook_stale:{book_age_ms:.0f}ms>{self.config.entry_max_orderbook_age_ms}ms"
        if (
            self.config.entry_max_reference_age_ms > 0
            and hasattr(reference_prices, "get_reference_price_with_ts")
        ):
            ref_result = reference_prices.get_reference_price_with_ts(symbol)
            if not ref_result:
                return "reference_price_missing"
            _, ref_ts = ref_result
            ref_age_ms = (now - float(ref_ts)) * 1000.0
            if (
                (self.config.market_type or "").lower() == "spot"
                and book_age_ms is not None
                and book_age_ms <= self.config.entry_max_orderbook_age_ms
            ):
                return None
            if ref_age_ms > self.config.entry_max_reference_age_ms:
                return f"reference_price_stale:{ref_age_ms:.0f}ms>{self.config.entry_max_reference_age_ms}ms"
        return None

    async def _mark_exit_idempotent(self, symbol: str, event_id: Optional[str] = None) -> bool:
        try:
            # Dedupe should only collapse retries of the SAME decision event.
            # If event_id is missing, fail open to avoid suppressing distinct exits.
            if not event_id:
                log_warning("execution_worker_exit_dedupe_missing_event_id", symbol=symbol)
                return True
            key = f"exit:{symbol}:{event_id}"
            return await self._exit_idempotency_store.claim(key)
        except Exception as exc:
            log_warning("execution_worker_exit_dedupe_failed", symbol=symbol, error=str(exc))
            # Fail open to avoid blocking safety exits if dedupe fails
            return True

    async def _execute_with_retry(self, intent: ExecutionIntent, timestamp: Optional[float]) -> bool:
        if self._is_maker_entry_intent(intent):
            return await self._execute_maker_entry(intent, timestamp)
        attempt = 0
        last_failure_reason: Optional[str] = None
        while True:
            try:
                status = await self.execution_manager.execute_intent(intent)
            except Exception as exc:
                error_message = str(exc)
                error_code = _classify_error(error_message)
                await self._record_error(
                    stage="execute",
                    error_message=error_message,
                    symbol=intent.symbol,
                    client_order_id=intent.client_order_id,
                    error_code=error_code,
                )
                status = OrderStatus(order_id=None, status="failed")
                # Record intent as failed immediately when execution raises an exception
                await self._record_intent(
                    intent=intent,
                    status="failed",
                    order_id=None,
                    last_error=error_code or "execution_exception",
                )
                await self._emit_status(intent, "failed", attempt)
                await self._write_status_snapshot(intent.symbol, "failed", attempt, error_code or "execution_exception", timestamp, None)
                return False
            status_reason = (status.reason or "").strip() or None
            if status_reason:
                last_failure_reason = status_reason
            if (
                status_reason == "exit_no_position"
                and (intent.reduce_only or intent.is_exit_signal)
            ):
                self._exit_no_position_until[intent.symbol] = time.time() + max(
                    0.0, float(self.config.exit_no_position_cooldown_sec)
                )
                await self._record_intent(
                    intent=intent,
                    status="canceled",
                    order_id=status.order_id,
                    last_error=status_reason,
                )
                await self._emit_status(intent, "canceled", attempt)
                await self._write_status_snapshot(
                    intent.symbol,
                    "canceled",
                    attempt,
                    status_reason,
                    timestamp,
                    status.order_id,
                )
                return True
            if _is_terminal_spot_exit_balance_miss(
                status_reason,
                intent=intent,
                market_type=self.config.market_type,
            ):
                self._exit_no_position_until[intent.symbol] = time.time() + max(
                    0.0, float(self.config.exit_no_position_cooldown_sec)
                )
                await self._record_intent(
                    intent=intent,
                    status="canceled",
                    order_id=status.order_id,
                    last_error=status_reason,
                )
                await self._emit_status(intent, "canceled", attempt)
                await self._write_status_snapshot(
                    intent.symbol,
                    "canceled",
                    attempt,
                    status_reason,
                    timestamp,
                    status.order_id,
                )
                await self._reconcile()
                return True
            # Only record as "submitted" if we got here without exception
            await self._record_intent(
                intent=intent,
                status="submitted",
                order_id=status.order_id,
            )
            if self._is_filled(status):
                await self._record_intent(
                    intent=intent,
                    status="filled",
                    order_id=status.order_id,
                )
                await self._write_status_snapshot(intent.symbol, status.status, attempt, None, timestamp, status.order_id)
                return True
            if self._is_pending(status):
                resolved = await self._poll_status(intent, status, attempt, timestamp)
                if resolved:
                    return True
                await self._emit_status(intent, "failed", attempt)
                await self._write_status_snapshot(intent.symbol, "failed", attempt, "status_poll_failed", timestamp, status.order_id)
                await self._record_intent(
                    intent=intent,
                    status="failed",
                    order_id=status.order_id,
                    last_error="status_poll_failed",
                )
                await self._record_error(
                    stage="status_poll",
                    error_message="status_poll_failed",
                    symbol=intent.symbol,
                    order_id=status.order_id,
                    client_order_id=intent.client_order_id,
                    payload={"attempt": attempt},
                )
                await self._reconcile()
                return False
            attempt += 1
            if attempt > self.config.max_retries:
                final_error = last_failure_reason or status_reason or "execution_failed"
                await self._emit_status(intent, "failed", attempt)
                await self._write_status_snapshot(intent.symbol, "failed", attempt, final_error, timestamp, status.order_id)
                await self._record_intent(
                    intent=intent,
                    status="failed",
                    order_id=status.order_id,
                    last_error=final_error,
                )
                await self._record_error(
                    stage="execute",
                    error_message=final_error,
                    symbol=intent.symbol,
                    order_id=status.order_id,
                    client_order_id=intent.client_order_id,
                    error_code=_classify_error(final_error),
                    payload={"attempt": attempt, "status": status.status, "reason": status_reason},
                )
                await self._reconcile()
                return False
            await self._emit_status(intent, "retrying", attempt)
            await self._write_status_snapshot(intent.symbol, "retrying", attempt, None, timestamp, status.order_id)
            await self._backoff_sleep(attempt)

    async def _execute_maker_entry(self, intent: ExecutionIntent, timestamp: Optional[float]) -> bool:
        max_attempts = max(1, int(self.config.entry_maker_max_reposts) + 1)
        root_client_order_id = intent.root_client_order_id or intent.client_order_id
        if root_client_order_id and intent.root_client_order_id != root_client_order_id:
            intent = replace(intent, root_client_order_id=root_client_order_id)
        post_only_reject_count = int(intent.post_only_reject_count or 0)
        cancel_after_timeout_count = int(intent.cancel_after_timeout_count or 0)
        for maker_attempt in range(max_attempts):
            attempt_client_order_id = (
                f"{root_client_order_id}:m{maker_attempt}" if root_client_order_id else None
            )
            attempt_intent = replace(
                intent,
                client_order_id=attempt_client_order_id,
                send_ts=time.time(),
                post_only_reject_count=post_only_reject_count,
                cancel_after_timeout_count=cancel_after_timeout_count,
            )
            try:
                status = await self.execution_manager.execute_intent(attempt_intent)
            except Exception as exc:
                error_message = str(exc)
                post_only_reject = self._is_post_only_reject(error_message)
                await self._record_error(
                    stage="execute_maker",
                    error_message=error_message,
                    symbol=attempt_intent.symbol,
                    client_order_id=attempt_intent.client_order_id,
                    error_code="maker_post_only_reject" if post_only_reject else _classify_error(error_message),
                    payload={"maker_attempt": maker_attempt},
                )
                if post_only_reject and maker_attempt + 1 < max_attempts:
                    post_only_reject_count += 1
                    await self._backoff_sleep(1)
                    refreshed = await self._refresh_maker_intent_price(intent)
                    if refreshed:
                        intent = replace(
                            refreshed,
                            post_only_reject_count=post_only_reject_count,
                            cancel_after_timeout_count=cancel_after_timeout_count,
                        )
                    continue
                self._activate_skip_cooldown(intent.symbol, intent.side)
                return False

            await self._record_intent(
                intent=attempt_intent,
                status="submitted",
                order_id=status.order_id,
                recorded_client_order_id=root_client_order_id,
                snapshot_metrics={
                    "order_type": attempt_intent.order_type,
                    "post_only": attempt_intent.post_only,
                    "limit_price": attempt_intent.limit_price,
                    "mid_at_send": attempt_intent.mid_at_send,
                    "expected_price_at_send": attempt_intent.expected_price_at_send,
                    "send_ts": attempt_intent.send_ts,
                    "maker_attempt": maker_attempt,
                    "root_client_order_id": root_client_order_id,
                    "attempt_client_order_id": attempt_client_order_id,
                },
            )

            if self._is_filled(status):
                await self._record_intent(
                    intent=attempt_intent,
                    status="filled",
                    order_id=status.order_id,
                    recorded_client_order_id=root_client_order_id,
                )
                return True

            # Wait only maker fill window, then cancel.
            resolved = await self._poll_status_window(
                attempt_intent,
                status,
                maker_attempt,
                timestamp,
                window_ms=max(50, int(self.config.entry_maker_fill_window_ms)),
            )
            if resolved:
                return True

            cancel = await self.execution_manager.cancel_order(
                order_id=status.order_id,
                client_order_id=attempt_intent.client_order_id,
                symbol=attempt_intent.symbol,
            )
            await self._record_error(
                stage="maker_cancel",
                error_message=cancel.message,
                symbol=attempt_intent.symbol,
                order_id=status.order_id,
                client_order_id=attempt_intent.client_order_id,
                error_code="maker_unfilled_cancel",
                payload={"maker_attempt": maker_attempt},
            )
            cancel_after_timeout_count += 1

            # Handle cancel/fill race: require terminal confirmation after cancel.
            terminal = await self._wait_for_terminal_after_cancel(attempt_intent, status.order_id)
            if terminal is None:
                # Some venues can lag order status updates right after cancel acknowledgement.
                # Run one reconcile + repoll cycle before declaring this attempt unfilled.
                await self._reconcile()
                terminal = await self._wait_for_terminal_after_cancel(attempt_intent, status.order_id)
            if terminal and self._is_filled(terminal):
                await self._record_intent(
                    intent=attempt_intent,
                    status="filled",
                    order_id=terminal.order_id or status.order_id,
                    recorded_client_order_id=root_client_order_id,
                )
                return True
            if terminal and self._partial_fill_accepted(terminal):
                synthesized = OrderStatus(
                    order_id=terminal.order_id or status.order_id,
                    status="filled",
                    fill_price=terminal.fill_price,
                    fee_usd=terminal.fee_usd,
                    filled_size=terminal.filled_size,
                    remaining_size=terminal.remaining_size,
                    reference_price=terminal.reference_price,
                    timestamp=terminal.timestamp or time.time(),
                    source=terminal.source or "rest",
                    reason="partial_fill_accepted",
                )
                await self.execution_manager.record_order_status(attempt_intent, synthesized)
                await self._record_intent(
                    intent=attempt_intent,
                    status="filled",
                    order_id=synthesized.order_id,
                    last_error="partial_fill_accepted",
                    recorded_client_order_id=root_client_order_id,
                )
                return True

            if maker_attempt + 1 >= max_attempts:
                if self.config.entry_maker_fallback_to_market:
                    await self._record_intent(
                        intent=attempt_intent,
                        status="canceled",
                        order_id=status.order_id,
                        last_error="maker_unfilled_timeout_fallback_market",
                        recorded_client_order_id=root_client_order_id,
                    )
                    fallback_client_order_id = (
                        f"{root_client_order_id}:f" if root_client_order_id else None
                    )
                    fallback_intent = replace(
                        intent,
                        client_order_id=fallback_client_order_id,
                        post_only=False,
                        order_type="market",
                        limit_price=None,
                        time_in_force=None,
                        expected_price_at_send=None,
                        execution_policy="maker_then_market_fallback",
                        execution_cohort="maker_then_market_fallback",
                        send_ts=time.time(),
                    )
                    await self._record_error(
                        stage="maker_fallback",
                        error_message="maker_unfilled_timeout_fallback_market",
                        symbol=fallback_intent.symbol,
                        order_id=status.order_id,
                        client_order_id=fallback_intent.client_order_id,
                        error_code="maker_unfilled_timeout_fallback_market",
                        payload={"maker_attempt": maker_attempt},
                    )
                    # Reuse normal execution path for market fallback, including retries/telemetry.
                    return await self._execute_with_retry(fallback_intent, timestamp)
                self._activate_skip_cooldown(intent.symbol, intent.side)
                await self._record_intent(
                    intent=attempt_intent,
                    status="failed",
                    order_id=status.order_id,
                    last_error="maker_unfilled_timeout",
                    recorded_client_order_id=root_client_order_id,
                )
                return False

            refreshed = await self._refresh_maker_intent_price(intent)
            if refreshed:
                intent = replace(
                    refreshed,
                    post_only_reject_count=post_only_reject_count,
                    cancel_after_timeout_count=cancel_after_timeout_count,
                )

        self._activate_skip_cooldown(intent.symbol, intent.side)
        return False

    async def _emit_status(self, intent: ExecutionIntent, status: str, attempt: int) -> None:
        if not (self.telemetry and self.telemetry_context):
            return
        reason = "execution_status"
        if status == "retrying":
            reason = "execution_retry"
        elif status == "failed":
            reason = "execution_failed"
        payload = order_payload(
            side=intent.side,
            size=intent.size,
            status=status,
            reason=reason,
            slippage_bps=None,
            fee_usd=None,
        )
        payload["attempt"] = attempt
        await self.telemetry.publish_order(
            ctx=self.telemetry_context,
            symbol=intent.symbol,
            payload=payload,
        )

    async def _write_status_snapshot(
        self,
        symbol: str,
        status: str,
        attempt: int,
        error: Optional[str],
        timestamp: Optional[float],
        order_id: Optional[str],
    ) -> None:
        key = f"quantgambit:{self.bot_id}:execution:{symbol}:latest"
        snapshot = {
            "symbol": symbol,
            "status": status,
            "attempt": attempt,
            "error": error,
            "timestamp": timestamp or time.time(),
            "order_id": order_id,
        }
        await self.snapshots.write(key, snapshot)

    async def _backoff_sleep(self, attempt: int) -> None:
        delay = min(self.config.max_backoff_sec, self.config.base_backoff_sec * (2 ** (attempt - 1)))
        if delay > 0:
            await asyncio.sleep(delay)

    async def _reconcile(self) -> None:
        reconciler = getattr(self.execution_manager, "reconciler", None)
        if reconciler and hasattr(reconciler, "reconcile"):
            await reconciler.reconcile()

    def _is_maker_entry_intent(self, intent: ExecutionIntent) -> bool:
        return (
            not intent.reduce_only
            and not intent.is_exit_signal
            and str(intent.order_type or "").lower() == "limit"
            and bool(intent.post_only)
            and intent.limit_price is not None
        )

    def _is_reference_price_fresh(self, symbol: Optional[str]) -> bool:
        if not symbol:
            return True
        exchange_client = getattr(self.execution_manager, "exchange_client", None)
        reference_prices = getattr(exchange_client, "reference_prices", None)
        if reference_prices is None and hasattr(exchange_client, "_inner"):
            reference_prices = getattr(getattr(exchange_client, "_inner", None), "reference_prices", None)
        if not reference_prices:
            return True
        if (
            (self.config.market_type or "").lower() == "spot"
            and self._is_orderbook_fresh(symbol)
        ):
            return True
        if not hasattr(reference_prices, "get_reference_price_with_ts"):
            return True
        result = reference_prices.get_reference_price_with_ts(symbol)
        if not result:
            return False
        _, ts = result
        age = time.time() - float(ts)
        return age <= self.config.max_reference_price_age_sec

    def _is_orderbook_fresh(self, symbol: Optional[str]) -> bool:
        if not symbol:
            return True
        exchange_client = getattr(self.execution_manager, "exchange_client", None)
        reference_prices = getattr(exchange_client, "reference_prices", None)
        if reference_prices is None and hasattr(exchange_client, "_inner"):
            reference_prices = getattr(getattr(exchange_client, "_inner", None), "reference_prices", None)
        if not reference_prices or not hasattr(reference_prices, "get_orderbook_with_ts"):
            return True
        result = reference_prices.get_orderbook_with_ts(symbol)
        if not result:
            return False
        _, ts = result
        age = time.time() - float(ts)
        return age <= self.config.max_orderbook_age_sec

    async def _poll_status(
        self,
        intent: ExecutionIntent,
        initial_status: OrderStatus,
        attempt: int,
        timestamp: Optional[float],
    ) -> bool:
        order_id = initial_status.order_id
        if not order_id and intent.client_order_id and hasattr(self.execution_manager, "poll_order_status_by_client_id"):
            order_id = intent.client_order_id
        order_store = getattr(self.execution_manager, "order_store", None)

        async def _check_ws_status() -> bool:
            if not order_store or not hasattr(order_store, "get"):
                return False
            record = order_store.get(initial_status.order_id, intent.client_order_id)
            if not record or not record.history:
                return False
            last = record.history[-1]
            if last.source != "ws":
                return False
            normalized_record = normalize_order_status(record.status)
            normalized_initial = normalize_order_status(initial_status.status)
            if normalized_record != normalized_initial:
                await self._emit_guardrail(
                    {
                        "type": "order_status_ws_update",
                        "symbol": intent.symbol,
                        "order_id": record.order_id,
                        "client_order_id": record.client_order_id,
                        "status": normalized_record,
                        "source": "ws",
                    }
                )
                await self._write_status_snapshot(
                    intent.symbol,
                    normalized_record,
                    attempt,
                    None,
                    last.timestamp,
                    record.order_id,
                )
            if is_terminal_status(normalized_record):
                await self._emit_guardrail(
                    {
                        "type": "order_status_ws_resolved",
                        "symbol": intent.symbol,
                        "order_id": record.order_id,
                        "client_order_id": record.client_order_id,
                        "status": normalized_record,
                        "source": "ws",
                    }
                )
                return True
            return False

        if await _check_ws_status():
            return True
        await self._emit_guardrail(
            {
                "type": "order_status_rest_poll",
                "symbol": intent.symbol,
                "order_id": initial_status.order_id,
                "client_order_id": intent.client_order_id,
                "attempt": attempt,
                "poll_attempts": self.config.status_poll_attempts,
                "source": "rest",
                "reason": "ws_gap_rest_poll",
            }
        )
        for poll_attempt in range(self.config.status_poll_attempts):
            await asyncio.sleep(self.config.status_poll_interval_sec)
            if await _check_ws_status():
                return True
            if initial_status.order_id:
                status = await self.execution_manager.poll_order_status(order_id, intent.symbol)
            else:
                status = await self.execution_manager.poll_order_status_by_client_id(order_id, intent.symbol)
            if not status:
                continue
            normalized = normalize_order_status(status.status)
            resolved_status = OrderStatus(
                order_id=status.order_id,
                status=normalized,
                fill_price=status.fill_price,
                fee_usd=status.fee_usd,
                filled_size=status.filled_size,
                remaining_size=status.remaining_size,
                reference_price=status.reference_price,
                timestamp=time.time(),
                source="rest",
            )
            if is_open_status(normalized):
                await self.execution_manager.record_order_status(intent, resolved_status)
                await self._write_status_snapshot(
                    intent.symbol,
                    resolved_status.status,
                    attempt,
                    None,
                    timestamp,
                    resolved_status.order_id,
                )
                continue
            resolved = await self.execution_manager.record_order_status(intent, resolved_status)
            await self._write_status_snapshot(
                intent.symbol,
                resolved_status.status,
                attempt,
                None,
                timestamp,
                resolved_status.order_id,
            )
            await self._record_intent(
                intent=intent,
                status="submitted" if not is_terminal_status(normalized) else normalized,
                order_id=resolved_status.order_id,
            )
            return resolved or is_terminal_status(normalized)
        await self._emit_guardrail(
            {
                "type": "order_status_poll_failed",
                "symbol": intent.symbol,
                "order_id": initial_status.order_id,
                "client_order_id": intent.client_order_id,
                "attempt": attempt,
                "poll_attempts": self.config.status_poll_attempts,
                "source": "rest",
                "reason": "ws_gap_poll_failed",
            }
        )
        return False

    async def _poll_status_window(
        self,
        intent: ExecutionIntent,
        initial_status: OrderStatus,
        attempt: int,
        timestamp: Optional[float],
        window_ms: int,
    ) -> bool:
        order_id = initial_status.order_id or intent.client_order_id
        if not order_id:
            return False
        end_at = time.time() + max(0.05, window_ms / 1000.0)
        while time.time() < end_at:
            await asyncio.sleep(max(0.05, self.config.status_poll_interval_sec))
            status = await self.execution_manager.poll_order_status(order_id, intent.symbol) if initial_status.order_id else await self.execution_manager.poll_order_status_by_client_id(order_id, intent.symbol)
            if not status:
                continue
            normalized = normalize_order_status(status.status)
            resolved_status = OrderStatus(
                order_id=status.order_id,
                status=normalized,
                fill_price=status.fill_price,
                fee_usd=status.fee_usd,
                filled_size=status.filled_size,
                remaining_size=status.remaining_size,
                reference_price=status.reference_price,
                timestamp=time.time(),
                source="rest",
            )
            if is_open_status(normalized):
                await self.execution_manager.record_order_status(intent, resolved_status)
                continue
            resolved = await self.execution_manager.record_order_status(intent, resolved_status)
            await self._write_status_snapshot(
                intent.symbol,
                resolved_status.status,
                attempt,
                None,
                timestamp,
                resolved_status.order_id,
            )
            await self._record_intent(
                intent=intent,
                status="submitted" if not is_terminal_status(normalized) else normalized,
                order_id=resolved_status.order_id,
                recorded_client_order_id=(intent.root_client_order_id or intent.client_order_id),
            )
            return bool(resolved or is_terminal_status(normalized))
        return False

    async def _wait_for_terminal_after_cancel(
        self,
        intent: ExecutionIntent,
        order_id: Optional[str],
    ) -> Optional[OrderStatus]:
        lookup_id = order_id or intent.client_order_id
        if not lookup_id:
            return None
        for _ in range(max(2, self.config.status_poll_attempts)):
            await asyncio.sleep(max(0.05, self.config.status_poll_interval_sec))
            status = await self.execution_manager.poll_order_status(lookup_id, intent.symbol) if order_id else await self.execution_manager.poll_order_status_by_client_id(lookup_id, intent.symbol)
            if not status:
                continue
            normalized = normalize_order_status(status.status)
            if is_terminal_status(normalized):
                return status
        return None

    async def _refresh_maker_intent_price(self, intent: ExecutionIntent) -> Optional[ExecutionIntent]:
        bid, ask, _ = self._read_best_bid_ask(intent.symbol)
        if bid is None or ask is None:
            return None
        side = str(intent.side or "").lower()
        limit_price = self._derive_maker_limit_price(
            side=side,
            bid=bid,
            ask=ask,
            offset_ticks=int(self.config.entry_maker_price_offset_ticks),
        )
        # Rebase SL/TP to track the new limit price
        adjusted_sl = intent.stop_loss
        adjusted_tp = intent.take_profit
        old_limit = intent.limit_price
        if old_limit and old_limit > 0 and limit_price:
            delta = limit_price - old_limit
            if adjusted_sl is not None:
                adjusted_sl = adjusted_sl + delta
            if adjusted_tp is not None:
                adjusted_tp = adjusted_tp + delta
        return replace(
            intent,
            limit_price=limit_price,
            mid_at_send=(bid + ask) / 2.0 if bid > 0 and ask > 0 else intent.mid_at_send,
            expected_price_at_send=limit_price,
            stop_loss=adjusted_sl,
            take_profit=adjusted_tp,
        )

    def _is_post_only_reject(self, message: str) -> bool:
        lowered = (message or "").lower()
        return "post only" in lowered or "post-only" in lowered or "would take" in lowered or "maker" in lowered

    def _partial_fill_accepted(self, status: OrderStatus) -> bool:
        if not self.config.entry_partial_accept:
            return False
        filled_size = _safe_float(status.filled_size)
        fill_price = _safe_float(status.fill_price) or _safe_float(status.reference_price)
        if not filled_size or filled_size <= 0 or not fill_price or fill_price <= 0:
            return False
        filled_notional = filled_size * fill_price
        return filled_notional >= max(0.0, self.config.entry_min_fill_notional_usd)

    def _derive_maker_limit_price(
        self,
        side: str,
        bid: float,
        ask: float,
        offset_ticks: int,
    ) -> float:
        """
        Build a post-only maker price near touch.

        `offset_ticks` nudges price toward the spread interior:
        - buy/long: bid + offset*tick (capped below ask)
        - sell/short: ask - offset*tick (capped above bid)
        """
        if side in {"buy", "long"}:
            touch = bid
            contra = ask
            direction = 1.0
        else:
            touch = ask
            contra = bid
            direction = -1.0

        if offset_ticks <= 0:
            return touch

        spread = max(0.0, ask - bid)
        if spread <= 0.0:
            return touch

        # Infer a conservative tick from displayed precision and spread.
        tick = self._infer_price_tick_size(bid, ask)
        if tick <= 0.0:
            return touch

        target = touch + (direction * float(offset_ticks) * tick)
        if side in {"buy", "long"}:
            max_maker = max(bid, contra - tick)
            return min(target, max_maker)
        min_maker = min(ask, contra + tick)
        return max(target, min_maker)

    def _infer_price_tick_size(self, bid: float, ask: float) -> float:
        candidates = []
        spread = abs(ask - bid)
        if spread > 0:
            candidates.append(spread)
        for price in (bid, ask):
            txt = f"{price:.12f}".rstrip("0")
            if "." not in txt:
                continue
            decimals = len(txt.split(".", 1)[1])
            if decimals > 0:
                candidates.append(10.0 ** (-decimals))
        positives = [v for v in candidates if v > 0]
        return min(positives) if positives else 0.0

    async def _record_intent(
        self,
        intent: ExecutionIntent,
        status: str,
        decision_id: Optional[str] = None,
        order_id: Optional[str] = None,
        last_error: Optional[str] = None,
        snapshot_metrics: Optional[dict] = None,
        recorded_client_order_id: Optional[str] = None,
    ) -> None:
        order_store = getattr(self.execution_manager, "order_store", None)
        if not order_store or not hasattr(order_store, "record_intent"):
            return
        effective_client_order_id = recorded_client_order_id or intent.client_order_id
        if not effective_client_order_id:
            return
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        submitted_at = created_at if status == "submitted" else None
        metrics = dict(snapshot_metrics or {})
        if intent.execution_policy is not None:
            metrics["execution_policy"] = intent.execution_policy
        if intent.execution_cohort is not None:
            metrics["execution_cohort"] = intent.execution_cohort
        if intent.execution_experiment_id is not None:
            metrics["execution_experiment_id"] = intent.execution_experiment_id
        await order_store.record_intent(
            intent_id=str(uuid.uuid4()),
            symbol=intent.symbol,
            side=intent.side,
            size=float(intent.size or 0.0),
            client_order_id=effective_client_order_id,
            status=status,
            decision_id=decision_id,
            entry_price=intent.entry_price,
            stop_loss=intent.stop_loss,
            take_profit=intent.take_profit,
            strategy_id=intent.strategy_id,
            profile_id=intent.profile_id,
            order_id=order_id,
            last_error=last_error,
            created_at=created_at,
            submitted_at=submitted_at,
            snapshot_metrics=metrics or None,
        )

    async def _record_error(
        self,
        stage: str,
        error_message: str,
        symbol: Optional[str] = None,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        error_code: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> None:
        order_store = getattr(self.execution_manager, "order_store", None)
        if order_store and hasattr(order_store, "record_error"):
            await order_store.record_error(
                stage=stage,
                error_message=error_message,
                error_code=error_code,
                symbol=symbol,
                order_id=order_id,
                client_order_id=client_order_id,
                payload=payload,
            )
        if self.telemetry and self.telemetry_context:
            guardrail_payload = {
                "type": "order_error",
                "stage": stage,
                "error_code": error_code,
                "error_message": error_message,
                "symbol": symbol,
                "order_id": order_id,
                "client_order_id": client_order_id,
            }
            if payload:
                guardrail_payload["payload"] = payload
            await self.telemetry.publish_guardrail(self.telemetry_context, guardrail_payload)

    async def _emit_guardrail(self, payload: dict) -> None:
        if not (self.telemetry and self.telemetry_context):
            return
        await self.telemetry.publish_guardrail(self.telemetry_context, payload)

    async def _intent_exists(self, client_order_id: Optional[str]) -> bool:
        if not client_order_id:
            return False
        order_store = getattr(self.execution_manager, "order_store", None)
        if not order_store or not hasattr(order_store, "load_intent_by_client_order_id"):
            return False
        try:
            record = await order_store.load_intent_by_client_order_id(client_order_id)
        except Exception as exc:
            await self._record_error(
                stage="dedupe_db",
                error_message=str(exc),
                client_order_id=client_order_id,
                error_code="intent_lookup_failed",
            )
            return False
        if not record:
            return False
        status = record.get("status")
        return status in {"created", "submitted"}

    @staticmethod
    def _is_filled(status: OrderStatus) -> bool:
        return (status.status or "").lower() in {"filled", "complete", "done"}

    @staticmethod
    def _is_pending(status: OrderStatus) -> bool:
        return is_open_status(status.status)


def _classify_error(message: str) -> str:
    if not message:
        return "unknown"
    lowered = message.lower()
    if "timeout" in lowered:
        return "timeout"
    if "rate" in lowered and "limit" in lowered:
        return "rate_limited"
    if "insufficient" in lowered or "margin" in lowered:
        return "insufficient_margin"
    if "invalid" in lowered or "bad request" in lowered:
        return "invalid_params"
    if "auth" in lowered or "signature" in lowered:
        return "auth_failed"
    return "unknown"


def _is_terminal_spot_exit_balance_miss(
    reason: Optional[str],
    *,
    intent: ExecutionIntent,
    market_type: str,
) -> bool:
    if not (intent.reduce_only or intent.is_exit_signal):
        return False
    if str(market_type or "").lower() != "spot":
        return False
    lowered = str(reason or "").lower()
    if not lowered:
        return False
    return (
        "spot_exit_no_free_balance" in lowered
        or ("170131" in lowered and "insufficient balance" in lowered)
        or ("exchange_error:" in lowered and "insufficient balance" in lowered)
    )


def _safe_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_opposite_position(signal_side: Optional[str], existing_side: Optional[str]) -> bool:
    if not signal_side or not existing_side:
        return False
    signal_normalized = str(signal_side).lower()
    existing_normalized = str(existing_side).lower()
    if signal_normalized in {"buy", "long"}:
        return existing_normalized in {"sell", "short"}
    if signal_normalized in {"sell", "short"}:
        return existing_normalized in {"buy", "long"}
    return False


def _extract_snapshot_metrics(decision: dict) -> Optional[dict]:
    """
    Extract market conditions at entry time for post-trade analysis.
    
    This allows answering questions like:
    - "Did we enter shorts when orderflow was +0.8?" 
    - "What was the spread when we entered?"
    - "Were we trading into adverse orderflow?"
    - "What session was active when this profile was selected?" (US-3, AC3.3)
    - "What were the top scoring profiles?"
    
    Returns dict with key metrics or None if no data available.
    """
    risk_context = decision.get("risk_context") or {}
    signal = decision.get("signal") or {}
    
    # Collect all relevant metrics
    metrics: dict = {}
    
    # Price data
    if decision.get("timestamp"):
        metrics["decision_timestamp"] = decision["timestamp"]
    
    # Orderflow (critical for post-trade analysis)
    for key in ("orderflow_imbalance", "imb_1s", "imb_5s", "imb_30s", "orderflow_persistence_sec"):
        val = risk_context.get(key)
        if val is not None:
            metrics[key] = val
    
    # Spread and depth
    for key in ("spread_bps", "bid_depth_usd", "ask_depth_usd", "depth_imbalance"):
        val = risk_context.get(key)
        if val is not None:
            metrics[key] = val
    
    # Regime info
    for key in ("volatility_regime", "vol_regime_score", "trend_direction", "trend_strength", 
                "market_regime", "regime_confidence", "risk_mode", "risk_scale"):
        val = risk_context.get(key)
        if val is not None:
            metrics[key] = val
    
    # Price levels
    for key in ("price", "bid", "ask", "poc_price", "vah_price", "val_price", "position_in_value"):
        val = risk_context.get(key)
        if val is not None:
            metrics[key] = val
    
    # Feed staleness (how fresh was our data?)
    feed_staleness = risk_context.get("feed_staleness")
    if feed_staleness:
        metrics["feed_staleness"] = feed_staleness
    
    # Signal-specific info
    if signal.get("prediction_confidence") is not None:
        metrics["prediction_confidence"] = signal["prediction_confidence"]
    if signal.get("meta_reason"):
        metrics["entry_reason"] = signal["meta_reason"]
    if signal.get("p_hat") is not None:
        metrics["entry_p_hat"] = signal.get("p_hat")
    if signal.get("p_hat_source") is not None:
        metrics["entry_p_hat_source"] = signal.get("p_hat_source")

    # Prediction payload (for model evaluation / accuracy tracking)
    prediction = decision.get("prediction") or {}
    if isinstance(prediction, dict):
        for key in ("direction", "confidence", "source", "reject"):
            if prediction.get(key) is not None:
                metrics[f"prediction_{key}"] = prediction.get(key)
        for key in ("provider", "expert_id", "expert_routed", "calibration_applied", "p_up", "p_down", "p_flat", "margin", "entropy"):
            if prediction.get(key) is not None:
                metrics[f"prediction_{key}"] = prediction.get(key)
        # Preserve compact nested prediction block for future cohort analysis.
        nested = {}
        for key in (
            "direction",
            "confidence",
            "source",
            "provider",
            "reject",
            "reason",
            "expert_id",
            "expert_routed",
            "calibration_applied",
            "p_up",
            "p_down",
            "p_flat",
            "margin",
            "entropy",
        ):
            if prediction.get(key) is not None:
                nested[key] = prediction.get(key)
        if nested:
            metrics["prediction"] = nested
    # Backfill from flat decision/signal fields when prediction dict is sparse.
    if metrics.get("prediction_source") is None:
        src = decision.get("prediction_source") or signal.get("prediction_source")
        if src is not None:
            metrics["prediction_source"] = src
    if metrics.get("prediction_direction") is None:
        direction = decision.get("prediction_direction") or signal.get("prediction_direction")
        if direction is not None:
            metrics["prediction_direction"] = direction
    if metrics.get("prediction_confidence") is None:
        conf = decision.get("prediction_confidence") or signal.get("prediction_confidence")
        if conf is not None:
            metrics["prediction_confidence"] = conf
    
    # Profile selection metadata (US-3, AC3.3)
    # Allows post-trade analysis of profile selection decisions
    profile_selection = decision.get("profile_selection_metadata")
    if profile_selection:
        # Include session info for debugging session mismatch bugs
        if profile_selection.get("session"):
            metrics["profile_session"] = profile_selection["session"]
        if profile_selection.get("hour_utc") is not None:
            metrics["profile_hour_utc"] = profile_selection["hour_utc"]
        if profile_selection.get("selected_profile"):
            metrics["profile_selected"] = profile_selection["selected_profile"]
        if profile_selection.get("rejection_count") is not None:
            metrics["profile_rejection_count"] = profile_selection["rejection_count"]
        if profile_selection.get("total_profiles_evaluated") is not None:
            metrics["profile_total_evaluated"] = profile_selection["total_profiles_evaluated"]
        # Store top scores summary (limited to avoid bloating storage)
        top_scores = profile_selection.get("top_scores")
        if top_scores:
            metrics["profile_top_scores"] = top_scores[:3]  # Limit to top 3
    
    return metrics if metrics else None
