"""Position guard worker enforcing stop/take profit and time-based exits."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Set

from quantgambit.execution.manager import (
    ExchangeClient,
    PositionManager,
    PositionSnapshot,
    _compute_pnl_breakdown,
    _is_filled,
    _reconcile_close_from_exchange,
)
from quantgambit.execution.order_statuses import is_terminal_status as _is_terminal_status
from quantgambit.observability.logger import log_info, log_warning
from quantgambit.observability.schemas import order_payload
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.risk.fee_model import FeeModel, FeeAwareExitCheck
import os
from quantgambit.execution.symbols import normalize_exchange_symbol
from quantgambit.core.risk.kill_switch import KillSwitchTrigger

if TYPE_CHECKING:
    from quantgambit.observability.alerts import AlertsClient
    from quantgambit.execution.idempotency_store import RedisIdempotencyStore
    from quantgambit.storage.redis_snapshots import RedisSnapshotReader


@dataclass
class PositionGuardConfig:
    interval_sec: float = 1.0
    max_position_age_sec: float = 0.0
    trailing_stop_bps: float = 0.0
    # Only activate trailing stop after MFE exceeds this threshold (bps)
    trailing_activation_bps: float = 0.0
    # Minimum hold time before trailing can trigger (sec)
    trailing_min_hold_sec: float = 0.0
    # Breakeven protection activates after MFE exceeds this threshold (bps)
    breakeven_activation_bps: float = 0.0
    # Additional buffer above breakeven before protection triggers (bps)
    breakeven_buffer_bps: float = 0.0
    # Minimum hold time before breakeven can trigger (sec)
    breakeven_min_hold_sec: float = 0.0
    # Profit lock: activate after MFE >= activation bps, exit if PnL retraces below retrace bps
    profit_lock_activation_bps: float = 0.0
    profit_lock_retrace_bps: float = 0.0
    profit_lock_min_hold_sec: float = 0.0
    # Dedupe TTL for guard-initiated closes (prevents duplicate closes)
    close_dedupe_ttl_sec: int = 60
    # Protection verification
    verify_exchange_protection: bool = False
    protection_grace_sec: float = 5.0
    require_protection: bool = False
    require_stop_loss: bool = False
    flatten_all_on_protection_failure: bool = True
    # Continuation gate: defer selected "soft exits" if live edge remains favorable.
    continuation_gate_enabled: bool = True
    continuation_min_confidence: float = 0.70
    continuation_min_pnl_bps: float = 10.0
    continuation_max_prediction_age_sec: float = 20.0
    continuation_max_defer_sec: float = 90.0
    continuation_max_defers: int = 60
    continuation_symbol_min_confidence: Optional[Dict[str, float]] = None
    continuation_symbol_min_pnl_bps: Optional[Dict[str, float]] = None
    continuation_symbol_max_defer_sec: Optional[Dict[str, float]] = None
    # Optional two-stage take-profit exit:
    # 1) try reduce-only limit for a bounded window, then
    # 2) cancel and fallback to market for guaranteed flatten.
    tp_limit_exit_enabled: bool = False
    tp_limit_fill_window_ms: int = 800
    tp_limit_price_buffer_bps: float = 0.5
    tp_limit_poll_interval_ms: int = 150
    tp_limit_time_in_force: str = "GTC"
    tp_limit_exit_reasons: Optional[Set[str]] = None
    # Time-cap governance (soft cap -> reevaluate -> conditional close).
    # Safety exits (SL, kill switch, stale-data emergencies) remain immediate.
    max_age_hard_sec: float = 0.0
    # Backward-compatible defaults: immediate max-age close unless explicitly configured.
    max_age_confirmations: int = 1
    max_age_recheck_sec: float = 45.0
    max_age_extension_sec: float = 0.0
    max_age_max_extensions: int = 0
    min_pnl_bps_to_extend: float = 6.0


# Guard reason to emoji/severity mapping
GUARD_ALERT_CONFIG = {
    "trailing_stop_hit": {"emoji": "📉", "severity": "warning", "label": "Trailing Stop"},
    "stop_loss_hit": {"emoji": "🛑", "severity": "warning", "label": "Stop Loss"},
    "take_profit_hit": {"emoji": "🎯", "severity": "info", "label": "Take Profit"},
    "breakeven_stop_hit": {"emoji": "✅", "severity": "info", "label": "Breakeven Protect"},
    "profit_lock_retrace": {"emoji": "💰", "severity": "info", "label": "Profit Lock"},
    "max_age_exceeded": {"emoji": "⏰", "severity": "warning", "label": "Max Age"},
    "max_age_hard_exceeded": {"emoji": "🚨", "severity": "warning", "label": "Hard Max Age"},
    # Time budget exits (MFT scalping)
    "max_hold_exceeded": {"emoji": "⏱️", "severity": "info", "label": "Max Hold"},
    "time_to_work_fail": {"emoji": "⚡", "severity": "info", "label": "T-Work Fail"},
}


class PositionGuardWorker:
    """Poll positions and enforce guardrails."""

    def __init__(
        self,
        exchange_client: ExchangeClient,
        position_manager: PositionManager,
        config: Optional[PositionGuardConfig] = None,
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        alerts_client: Optional["AlertsClient"] = None,
        tenant_id: str = "",
        bot_id: str = "",
        idempotency_store: Optional["RedisIdempotencyStore"] = None,
        # Fee-aware exit parameters
        fee_model: Optional[FeeModel] = None,
        min_profit_buffer_bps: float = 5.0,
        kill_switch=None,  # PersistentKillSwitch or compatible
        snapshot_reader: Optional["RedisSnapshotReader"] = None,
    ):
        self.exchange_client = exchange_client
        self.position_manager = position_manager
        self.config = config or PositionGuardConfig()
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self._alerts_client = alerts_client
        self._tenant_id = tenant_id
        self._bot_id = bot_id
        self._trailing_peaks: Dict[str, float] = {}
        self._idempotency_store = idempotency_store
        # Track symbols currently being closed to prevent duplicate close attempts
        self._closing_symbols: Set[str] = set()
        # Fee-aware exit configuration
        self._fee_model = fee_model
        self._min_profit_buffer_bps = min_profit_buffer_bps
        self._kill_switch = kill_switch
        self._snapshot_reader = snapshot_reader
        self._continuation_state: Dict[str, Dict[str, Any]] = {}
        self._max_age_state: Dict[str, Dict[str, Any]] = {}
        self._continuation_soft_reasons = {"trailing_stop_hit", "max_hold_exceeded", "time_to_work_fail"}
        self._continuation_time_budget_reasons = {"max_hold_exceeded", "time_to_work_fail"}
        self._tp_limit_reasons = set(
            self.config.tp_limit_exit_reasons
            or {
                "take_profit_hit",
                "profit_lock_retrace",
            }
        )

    async def run(self) -> None:
        log_info("position_guard_start", interval_sec=self.config.interval_sec)
        while True:
            await self._tick()
            await asyncio.sleep(self.config.interval_sec)

    async def _tick(self) -> None:
        now = time.time()
        positions = await self.position_manager.list_open_positions()
        if os.getenv("POSITION_GUARD_TRACE", "false").lower() in {"1", "true", "yes"}:
            log_info("position_guard_tick", position_count=len(positions))
        for pos in positions:
            # Skip if already being closed by another process
            if pos.symbol in self._closing_symbols:
                log_info("position_guard_skip_closing", symbol=pos.symbol, reason="already_closing")
                continue
            
            price = _reference_price(self.exchange_client, pos)
            if price is None:
                continue
            if os.getenv("POSITION_GUARD_TRACE", "false").lower() in {"1", "true", "yes"}:
                hold_time = (now - float(pos.opened_at)) if pos.opened_at else None
                log_info(
                    "position_guard_evaluate",
                    symbol=pos.symbol,
                    side=pos.side,
                    size=pos.size,
                    entry_price=pos.entry_price,
                    mark_price=price,
                    stop_loss=pos.stop_loss,
                    take_profit=pos.take_profit,
                    mfe_pct=pos.mfe_pct,
                    mae_pct=pos.mae_pct,
                    hold_time_sec=round(hold_time, 2) if hold_time is not None else None,
                )
            # Exchange-authoritative protection verification (stop-loss / take-profit).
            # This prevents "tight stops don't protect" situations where SL/TP placement failed silently.
            if self.config.verify_exchange_protection:
                ok = await self._verify_exchange_protection(pos, now)
                if not ok:
                    await self._handle_protection_failure(pos, now)
                    # Once we detect protection failure, we are closing/flattening; skip other checks.
                    continue
            # Update MFE/MAE tracking on each tick
            if hasattr(self.position_manager, "update_mfe_mae"):
                self.position_manager.update_mfe_mae(pos.symbol, price)
            reason = _should_close(
                pos,
                price,
                now,
                self.config,
                self._trailing_peaks,
                self._fee_model,
            )
            # Safety fallback: if max-age is configured and hold time already exceeds it,
            # never allow a silent "no_trigger" pass. This preserves max-age governance
            # guarantees even if upstream reason synthesis regresses.
            if not reason and self.config.max_position_age_sec > 0 and pos.opened_at:
                try:
                    hold_time = now - float(pos.opened_at)
                except (TypeError, ValueError):
                    hold_time = None
                if hold_time is not None and hold_time >= float(self.config.max_position_age_sec):
                    log_warning(
                        "position_guard_max_age_fallback_triggered",
                        symbol=pos.symbol,
                        hold_time_sec=round(hold_time, 3),
                        max_age_sec=float(self.config.max_position_age_sec),
                    )
                    reason = "max_age_exceeded"
            if not reason:
                self._continuation_state.pop(pos.symbol, None)
                self._max_age_state.pop(pos.symbol, None)
                if os.getenv("POSITION_GUARD_TRACE", "false").lower() in {"1", "true", "yes"}:
                    log_info("position_guard_no_close", symbol=pos.symbol, reason="no_trigger")
                continue

            if reason == "max_age_exceeded":
                should_close, final_reason, max_age_meta = await self._evaluate_max_age_governance(
                    pos=pos,
                    price=price,
                    now_ts=now,
                )
                if not should_close:
                    log_info(
                        "position_guard_max_age_deferred",
                        symbol=pos.symbol,
                        **max_age_meta,
                    )
                    continue
                reason = final_reason or reason
            
            # Apply fee-aware gating for certain exit reasons
            fee_check_result = self._apply_fee_check(pos, price, reason)
            if fee_check_result is not None and not fee_check_result.should_allow_exit:
                # Fee check blocked the exit
                log_info(
                    "position_guard_fee_blocked",
                    symbol=pos.symbol,
                    reason=reason,
                    gross_pnl_bps=fee_check_result.gross_pnl_bps,
                    net_pnl_bps=fee_check_result.net_pnl_bps,
                    min_required_bps=fee_check_result.min_required_bps,
                    shortfall_bps=fee_check_result.shortfall_bps,
                )
                continue

            should_defer, defer_meta = await self._should_defer_soft_exit(
                pos=pos,
                reason=reason,
                price=price,
                now_ts=now,
            )
            if should_defer:
                log_info(
                    "position_guard_exit_deferred",
                    symbol=pos.symbol,
                    reason=reason,
                    prediction_direction=defer_meta.get("prediction_direction"),
                    prediction_confidence=defer_meta.get("prediction_confidence"),
                    prediction_age_sec=defer_meta.get("prediction_age_sec"),
                    pnl_bps=defer_meta.get("pnl_bps"),
                    defer_count=defer_meta.get("defer_count"),
                    defer_elapsed_sec=defer_meta.get("defer_elapsed_sec"),
                )
                continue
            
            await self._close_position(pos, reason, fee_check_result)
        if self.telemetry and self.telemetry_context:
            await self.telemetry.publish_health_snapshot(
                ctx=self.telemetry_context,
                payload={
                    "status": "ok",
                    "position_guardian": {
                        "status": "running",
                        "timestamp": now,
                        "config": {
                            "maxAgeSec": float(self.config.max_position_age_sec or 0.0),
                            "hardMaxAgeSec": float(self.config.max_age_hard_sec or 0.0),
                            "maxAgeConfirmations": int(self.config.max_age_confirmations or 1),
                            "maxAgeExtensionSec": float(self.config.max_age_extension_sec or 0.0),
                            "maxAgeMaxExtensions": int(self.config.max_age_max_extensions or 0),
                            "continuationEnabled": bool(self.config.continuation_gate_enabled),
                        },
                    },
                    "services": {
                        "python_engine": {
                            "status": "running",
                            "control": {"status": "running"},
                            "workers": {
                                "data_worker": {"status": "running"},
                                "position_guardian": {"status": "running"},
                            },
                        }
                    },
                },
            )

    async def _verify_exchange_protection(self, pos: PositionSnapshot, now: float) -> bool:
        """Return True if exchange shows the expected protective fields for the position."""
        if not self.config.require_protection:
            return True
        if pos.opened_at and (now - float(pos.opened_at)) < float(self.config.protection_grace_sec or 0.0):
            return True

        expected_sl = pos.stop_loss
        expected_tp = pos.take_profit
        if expected_sl is None and expected_tp is None:
            return False
        if self.config.require_stop_loss and expected_sl is None:
            return False

        fetch_positions = getattr(self.exchange_client, "fetch_positions", None)
        if fetch_positions is None:
            # Can't verify; don't force-close, but log loudly.
            log_warning("position_guard_protection_verify_unavailable", symbol=pos.symbol, reason="fetch_positions_missing")
            return True

        try:
            exchange_positions = await fetch_positions([pos.symbol])
        except Exception as exc:
            log_warning("position_guard_protection_verify_failed", symbol=pos.symbol, error=str(exc))
            return True

        exchange_id = (
            getattr(self.exchange_client, "exchange", None)
            or getattr(self.exchange_client, "exchange_id", None)
            or os.getenv("ACTIVE_EXCHANGE")
            or "bybit"
        )
        wanted = normalize_exchange_symbol(str(exchange_id), pos.symbol) or pos.symbol
        match = None
        for exch_pos in exchange_positions or []:
            sym = exch_pos.get("symbol") if isinstance(exch_pos, dict) else None
            normalized = normalize_exchange_symbol(str(exchange_id), sym)
            if normalized == wanted:
                match = exch_pos
                break
        if not match:
            # If the exchange says we don't have a position, don't force-close (reconcile worker handles).
            return True

        exch_sl = (
            match.get("stopLoss")
            or match.get("stop_loss")
            or match.get("sl")
            or match.get("slPrice")
            or (match.get("info") or {}).get("stopLoss")
        )
        exch_tp = (
            match.get("takeProfit")
            or match.get("take_profit")
            or match.get("tp")
            or match.get("tpPrice")
            or (match.get("info") or {}).get("takeProfit")
        )
        has_sl = exch_sl is not None
        has_tp = exch_tp is not None

        if expected_sl is not None and not has_sl:
            log_warning("position_guard_missing_exchange_stop_loss", symbol=pos.symbol)
            return False
        if expected_tp is not None and not has_tp:
            log_warning("position_guard_missing_exchange_take_profit", symbol=pos.symbol)
            return False
        return True

    async def _handle_protection_failure(self, pos: PositionSnapshot, now: float) -> None:
        """Trigger kill switch and flatten/close when protection is missing."""
        log_warning(
            "position_guard_protection_failure",
            symbol=pos.symbol,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
        )
        if self._kill_switch:
            try:
                if not getattr(self._kill_switch, "is_active", lambda: False)():
                    await self._kill_switch.trigger(
                        KillSwitchTrigger.PROTECTION_FAILURE,
                        message=f"missing_exchange_protection:{pos.symbol}",
                    )
            except Exception as exc:
                log_warning("position_guard_kill_switch_trigger_failed", symbol=pos.symbol, error=str(exc))

        if self.config.flatten_all_on_protection_failure:
            positions = await self.position_manager.list_open_positions()
            for p in positions:
                if p.symbol in self._closing_symbols:
                    continue
                await self._close_position(p, reason="protection_failure", fee_check_result=None)
            return

        await self._close_position(pos, reason="protection_failure", fee_check_result=None)
    
    def _apply_fee_check(
        self,
        pos: PositionSnapshot,
        price: float,
        reason: str,
    ) -> Optional[FeeAwareExitCheck]:
        """Apply fee-aware gating for certain exit reasons.
        
        Fee checks are ONLY applied to trailing-stop exits.

        Rationale: this bot is a scalper; time-based exits (max age / time-to-work)
        and protective exits (breakeven/profit-lock/stop-loss) must not be blocked
        by a fee breakeven check, otherwise positions can be held far longer than
        intended and drift into large losses.
        
        Returns:
            FeeAwareExitCheck if fee model is configured and check was applied,
            None if fee check was bypassed or no fee model configured.
        """
        if self._fee_model is None:
            return None

        # Fee-aware gating is intended to reduce churn on trailing exits only.
        # Everything else is treated as a protective/defensive exit and must be allowed.
        if reason != "trailing_stop_hit":
            log_info(
                "position_guard_fee_bypassed",
                symbol=pos.symbol,
                reason=reason,
                bypass_reason="non_trailing_exit",
            )
            return None
        
        if pos.entry_price is None or pos.size is None or pos.size <= 0:
            return None
        
        side = "long" if _is_long(pos) else "short"
        conservative_price = price
        try:
            slippage_bps = float(os.getenv("POSITION_GUARD_FEE_CHECK_SLIPPAGE_BPS", "2.0"))
        except Exception:
            slippage_bps = 2.0
        if slippage_bps > 0:
            if side == "long":
                # Closing long requires selling; haircut price for conservative fee check.
                conservative_price = price * (1.0 - (slippage_bps / 10000.0))
            else:
                # Closing short requires buying; bump price for conservative fee check.
                conservative_price = price * (1.0 + (slippage_bps / 10000.0))
        
        fee_check = self._fee_model.check_exit_profitability(
            size=pos.size,
            entry_price=pos.entry_price,
            current_price=conservative_price,
            side=side,
            min_profit_buffer_bps=self._min_profit_buffer_bps,
        )
        
        return fee_check

    async def _close_position(
        self,
        pos: PositionSnapshot,
        reason: str,
        fee_check_result: Optional[FeeAwareExitCheck] = None,
    ) -> None:
        # Generate a unique client_order_id for this guard close
        # Retry-safe id strategy:
        # - keep deterministic IDs within a short bucket (idempotent against duplicate ticks),
        # - rotate IDs across buckets so repeated rejected closes are not stuck forever
        #   on the same exchange-level client_order_id.
        dedupe_window_sec = max(1, int(self.config.close_dedupe_ttl_sec or 60))
        retry_bucket = int(time.time() // dedupe_window_sec)
        client_order_id = _build_guard_client_order_id(
            self._bot_id,
            pos.symbol,
            pos.side,
            pos.size,
            reason,
            retry_bucket=retry_bucket,
        )
        
        # Check idempotency to prevent duplicate closes
        if self._idempotency_store:
            try:
                claimed = await self._idempotency_store.claim(client_order_id)
                if not claimed:
                    log_warning(
                        "position_guard_duplicate_close",
                        symbol=pos.symbol,
                        reason=reason,
                        client_order_id=client_order_id,
                    )
                    return
            except Exception as exc:
                log_warning("position_guard_dedupe_failed", error=str(exc), symbol=pos.symbol)
                # Fail closed - don't proceed if dedupe check fails
                return
        
        # Mark symbol as closing to prevent concurrent close attempts
        self._closing_symbols.add(pos.symbol)
        
        try:
            await self.position_manager.mark_closing(pos.symbol, reason=reason)
            status, exit_exec_meta = await self._execute_close_order(
                pos=pos,
                reason=reason,
                client_order_id=client_order_id,
            )
            status_reason = (status.reason or "").lower() if status else ""
            no_position_rejected = (
                status.status == "rejected"
                and (
                    "110017" in status_reason
                    or "position is zero" in status_reason
                    or "position not found" in status_reason
                    or "no position" in status_reason
                )
            )
            if no_position_rejected:
                # Exchange confirms there is no open position; clear stale local state.
                await self.position_manager.finalize_close(pos.symbol)
            exit_timestamp = status.timestamp or time.time()
            size_for_pnl = status.filled_size or pos.size
            is_filled = _is_filled(status.status)
            exit_price = status.fill_price
            exit_fee_usd = status.fee_usd
            gross_pnl = None
            net_pnl = None
            net_pnl_pct = None
            total_fees = None
            hold_time_sec = None
            if is_filled:
                reconciled = await _reconcile_close_from_exchange(
                    exchange_client=self.exchange_client,
                    symbol=pos.symbol,
                    order_id=status.order_id,
                    client_order_id=client_order_id,
                    exit_timestamp=exit_timestamp,
                )
                if reconciled:
                    exit_price = reconciled.get("avg_price") or exit_price
                    exit_fee_usd = reconciled.get("total_fees_usd") if reconciled.get("total_fees_usd") is not None else exit_fee_usd
                    size_for_pnl = reconciled.get("total_qty") or size_for_pnl
                    exit_timestamp = reconciled.get("exit_timestamp") or exit_timestamp
            has_fill_price = exit_price is not None

            # Always emit order telemetry, but only finalize/emit "closed" lifecycle on filled exits.
            if self.telemetry and self.telemetry_context:
                reference_price = _reference_price(self.exchange_client, pos)
                slippage_bps = None
                if reference_price and exit_price and reference_price > 0:
                    slippage_bps = abs((exit_price - reference_price) / reference_price) * 10000.0
                if is_filled and has_fill_price:
                    gross_pnl, net_pnl, net_pnl_pct, total_fees = _compute_pnl_breakdown(
                        pos.entry_price,
                        exit_price,
                        size_for_pnl,
                        pos.side,
                        entry_fee_usd=pos.entry_fee_usd,
                        exit_fee_usd=exit_fee_usd,
                    )
                entry_client_order_id = getattr(pos, "entry_client_order_id", None)
                entry_decision_id = getattr(pos, "entry_decision_id", None)
                if entry_client_order_id is None:
                    resolved_entry_id, resolved_decision_id = await self._resolve_entry_attribution(pos)
                    entry_client_order_id = entry_client_order_id or resolved_entry_id
                    entry_decision_id = entry_decision_id or resolved_decision_id
                entry_client_order_id_text = str(entry_client_order_id or "")
                entry_post_only = ":m" in entry_client_order_id_text
                execution_policy = (
                    getattr(pos, "execution_policy", None)
                    or ("maker_first" if entry_post_only else "market")
                )
                execution_cohort = (
                    getattr(pos, "execution_cohort", None)
                    or ("maker_first" if execution_policy == "maker_first" else "baseline_market")
                )
                execution_experiment_id = (
                    getattr(pos, "execution_experiment_id", None)
                    or (os.getenv("EXECUTION_EXPERIMENT_ID", "").strip() or None)
                )
                entry_fee_bps = None
                exit_fee_bps = None
                total_cost_bps = None
                if pos.entry_price and size_for_pnl and float(pos.entry_price) > 0 and float(size_for_pnl) > 0:
                    notional_entry = float(pos.entry_price) * float(size_for_pnl)
                    if pos.entry_fee_usd is not None:
                        entry_fee_bps = (float(pos.entry_fee_usd) / notional_entry) * 10000.0
                if exit_price and size_for_pnl and float(exit_price) > 0 and float(size_for_pnl) > 0:
                    notional_exit = float(exit_price) * float(size_for_pnl)
                    if exit_fee_usd is not None:
                        exit_fee_bps = (float(exit_fee_usd) / notional_exit) * 10000.0
                cost_parts = [entry_fee_bps, exit_fee_bps, slippage_bps]
                if any(v is not None for v in cost_parts):
                    total_cost_bps = sum(float(v) for v in cost_parts if v is not None)
                order_event = order_payload(
                    side=_exit_side(pos.side),
                    size=size_for_pnl,
                    status=status.status,
                    reason=reason,
                    slippage_bps=slippage_bps,
                    fee_usd=exit_fee_usd,
                    entry_fee_usd=pos.entry_fee_usd,
                    total_fees_usd=total_fees,
                    fill_price=exit_price,
                    order_id=status.order_id,
                    client_order_id=client_order_id,
                    position_effect="close",
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    realized_pnl=net_pnl,
                    realized_pnl_pct=net_pnl_pct,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    filled_size=size_for_pnl,
                    entry_timestamp=pos.opened_at,
                    exit_timestamp=exit_timestamp,
                    hold_time_sec=None,
                )
                order_event["stop_loss"] = pos.stop_loss
                order_event["take_profit"] = pos.take_profit
                if entry_client_order_id is not None:
                    order_event["entry_client_order_id"] = entry_client_order_id
                    order_event["entry_post_only"] = bool(entry_post_only)
                    order_event["entry_order_type"] = "limit" if entry_post_only else "market"
                order_event["execution_policy"] = execution_policy
                order_event["execution_cohort"] = execution_cohort
                if execution_experiment_id is not None:
                    order_event["execution_experiment_id"] = execution_experiment_id
                order_event["entry_fee_bps"] = entry_fee_bps
                order_event["exit_fee_bps"] = exit_fee_bps
                order_event["total_cost_bps"] = total_cost_bps
                order_event["exit_execution_path"] = exit_exec_meta.get("path")
                order_event["exit_tp_limit_attempted"] = bool(exit_exec_meta.get("tp_limit_attempted"))
                order_event["exit_tp_limit_filled"] = bool(exit_exec_meta.get("tp_limit_filled"))
                order_event["exit_tp_limit_timeout_fallback"] = bool(
                    exit_exec_meta.get("tp_limit_timeout_fallback")
                )
                if exit_exec_meta.get("tp_limit_price") is not None:
                    order_event["exit_tp_limit_price"] = exit_exec_meta.get("tp_limit_price")
                # Add MFE/MAE telemetry
                if pos.mfe_pct is not None:
                    order_event["mfe_pct"] = pos.mfe_pct
                if pos.mae_pct is not None:
                    order_event["mae_pct"] = pos.mae_pct
                # Add fee_aware metadata
                if fee_check_result is not None:
                    order_event["fee_aware"] = {
                        "gross_pnl_bps": fee_check_result.gross_pnl_bps,
                        "net_pnl_bps": fee_check_result.net_pnl_bps,
                        "breakeven_bps": fee_check_result.breakeven_bps,
                        "min_required_bps": fee_check_result.min_required_bps,
                        "fee_check_passed": fee_check_result.should_allow_exit,
                        "fee_check_bypassed": False,
                    }
                elif reason in ("stop_loss_hit", "take_profit_hit"):
                    order_event["fee_aware"] = {
                        "fee_check_passed": True,
                        "fee_check_bypassed": True,
                        "bypass_reason": reason,
                    }
                if pos.prediction_confidence is not None:
                    order_event["prediction_confidence"] = pos.prediction_confidence
                if pos.prediction_direction is not None:
                    order_event["prediction_direction"] = pos.prediction_direction
                if pos.prediction_source is not None:
                    order_event["prediction_source"] = pos.prediction_source
                if getattr(pos, "entry_p_hat", None) is not None:
                    order_event["entry_p_hat"] = getattr(pos, "entry_p_hat")
                if getattr(pos, "entry_p_hat_source", None) is not None:
                    order_event["entry_p_hat_source"] = getattr(pos, "entry_p_hat_source")
                if getattr(pos, "model_side", None) is not None:
                    order_event["model_side"] = getattr(pos, "model_side")
                if getattr(pos, "p_up", None) is not None:
                    order_event["p_up"] = getattr(pos, "p_up")
                if getattr(pos, "p_down", None) is not None:
                    order_event["p_down"] = getattr(pos, "p_down")
                if getattr(pos, "p_flat", None) is not None:
                    order_event["p_flat"] = getattr(pos, "p_flat")
                await self.telemetry.publish_order(self.telemetry_context, pos.symbol, order_event)

            # Only finalize and emit position lifecycle if filled with a known fill price.
            if is_filled and has_fill_price:
                gross_pnl, net_pnl, net_pnl_pct, total_fees = _compute_pnl_breakdown(
                    pos.entry_price,
                    exit_price,
                    size_for_pnl,
                    pos.side,
                    entry_fee_usd=pos.entry_fee_usd,
                    exit_fee_usd=exit_fee_usd,
                )
                hold_time_sec = (exit_timestamp - pos.opened_at) if pos.opened_at else None
                await self.position_manager.finalize_close(pos.symbol)
                self._trailing_peaks.pop(f"{pos.symbol}:{(pos.side or '').lower()}", None)
                if self.telemetry and self.telemetry_context:
                    # Emit position lifecycle event - single source of truth for PnL
                    lifecycle_payload = {
                        "side": pos.side,
                        "size": pos.size,
                        "status": "closed",
                        "entry_price": pos.entry_price,
                        "stop_loss": pos.stop_loss,
                        "take_profit": pos.take_profit,
                        "exit_price": exit_price,
                        "exit_timestamp": exit_timestamp,
                        "entry_timestamp": pos.opened_at,
                        "realized_pnl": net_pnl,
                        "realized_pnl_pct": net_pnl_pct,
                        "fee_usd": exit_fee_usd,
                        "entry_fee_usd": pos.entry_fee_usd,
                        "total_fees_usd": total_fees,
                        "gross_pnl": gross_pnl,
                        "net_pnl": net_pnl,
                        "hold_time_sec": hold_time_sec,
                        "close_order_id": status.order_id,
                        "closed_by": f"guardian_{reason}",
                        "strategy_id": pos.strategy_id,
                        "profile_id": pos.profile_id,
                        "execution_policy": execution_policy,
                        "execution_cohort": execution_cohort,
                        "execution_experiment_id": execution_experiment_id,
                        "entry_fee_bps": entry_fee_bps,
                        "exit_fee_bps": exit_fee_bps,
                        "total_cost_bps": total_cost_bps,
                        "exit_execution_path": exit_exec_meta.get("path"),
                        "exit_tp_limit_attempted": bool(exit_exec_meta.get("tp_limit_attempted")),
                        "exit_tp_limit_filled": bool(exit_exec_meta.get("tp_limit_filled")),
                        "exit_tp_limit_timeout_fallback": bool(
                            exit_exec_meta.get("tp_limit_timeout_fallback")
                        ),
                    }
                    if exit_exec_meta.get("tp_limit_price") is not None:
                        lifecycle_payload["exit_tp_limit_price"] = exit_exec_meta.get("tp_limit_price")
                    if getattr(pos, "entry_client_order_id", None) is not None:
                        lifecycle_payload["entry_client_order_id"] = getattr(pos, "entry_client_order_id")
                    elif entry_client_order_id is not None:
                        lifecycle_payload["entry_client_order_id"] = entry_client_order_id
                    if getattr(pos, "entry_decision_id", None) is not None:
                        lifecycle_payload["entry_decision_id"] = getattr(pos, "entry_decision_id")
                    elif entry_decision_id is not None:
                        lifecycle_payload["entry_decision_id"] = entry_decision_id
                    if pos.prediction_confidence is not None:
                        lifecycle_payload["prediction_confidence"] = pos.prediction_confidence
                    if pos.prediction_direction is not None:
                        lifecycle_payload["prediction_direction"] = pos.prediction_direction
                    if pos.prediction_source is not None:
                        lifecycle_payload["prediction_source"] = pos.prediction_source
                    if getattr(pos, "entry_p_hat", None) is not None:
                        lifecycle_payload["entry_p_hat"] = getattr(pos, "entry_p_hat")
                    if getattr(pos, "entry_p_hat_source", None) is not None:
                        lifecycle_payload["entry_p_hat_source"] = getattr(pos, "entry_p_hat_source")
                    # Prediction context fields (unconditional — always present, None when unavailable)
                    lifecycle_payload["model_side"] = pos.model_side
                    lifecycle_payload["p_up"] = pos.p_up
                    lifecycle_payload["p_down"] = pos.p_down
                    lifecycle_payload["p_flat"] = pos.p_flat
                    # Add MFE/MAE and signal strength telemetry
                    if pos.mfe_pct is not None:
                        lifecycle_payload["mfe_pct"] = pos.mfe_pct
                    if pos.mae_pct is not None:
                        lifecycle_payload["mae_pct"] = pos.mae_pct
                    if pos.entry_signal_strength is not None:
                        lifecycle_payload["signal_strength"] = pos.entry_signal_strength
                    if pos.entry_signal_confidence is not None:
                        lifecycle_payload["signal_confidence"] = pos.entry_signal_confidence
                    await self.telemetry.publish_position_lifecycle(
                        ctx=self.telemetry_context,
                        symbol=pos.symbol,
                        event_type="closed",
                        payload=lifecycle_payload,
                    )
            else:
                log_warning(
                    "position_guard_close_unfilled",
                    symbol=pos.symbol,
                    reason=reason,
                    status=status.status,
                    has_fill_price=has_fill_price,
                )
                payload = {
                    "type": "position_guard",
                    "symbol": pos.symbol,
                    "reason": reason,
                    "status": status.status,
                    "client_order_id": client_order_id,
                }
                await self.telemetry.publish_guardrail(self.telemetry_context, payload)
            
            # Send Slack/Discord alert
            await self._send_guard_alert(pos, reason, status.fill_price, net_pnl, net_pnl_pct, hold_time_sec)
            
            log_warning("position_guard_close", symbol=pos.symbol, reason=reason, status=status.status, client_order_id=client_order_id)
        finally:
            # Always clear the closing flag
            self._closing_symbols.discard(pos.symbol)
            self._continuation_state.pop(pos.symbol, None)
            self._max_age_state.pop(pos.symbol, None)

    async def _evaluate_max_age_governance(
        self,
        pos: PositionSnapshot,
        price: float,
        now_ts: float,
    ) -> tuple[bool, Optional[str], dict[str, Any]]:
        """Evaluate soft/hard max-age policy with bounded extensions.

        Returns:
            (should_close, reason_override, meta)
        """
        if (
            self.config.max_position_age_sec <= 0
            or not pos.opened_at
        ):
            return True, "max_age_exceeded", {"policy": "immediate"}

        symbol = str(pos.symbol or "")
        age_sec = max(0.0, now_ts - float(pos.opened_at))
        soft_cap_sec = float(self.config.max_position_age_sec)
        hard_cap_sec = float(self.config.max_age_hard_sec or 0.0)
        extension_sec = max(0.0, float(self.config.max_age_extension_sec or 0.0))
        max_extensions = max(0, int(self.config.max_age_max_extensions or 0))
        recheck_sec = max(1.0, float(self.config.max_age_recheck_sec or 45.0))
        required_confirms = max(1, int(self.config.max_age_confirmations or 1))

        state = self._max_age_state.get(symbol)
        if not state:
            state = {
                "next_soft_deadline_ts": float(pos.opened_at) + soft_cap_sec,
                "last_recheck_ts": 0.0,
                "extensions_used": 0,
                "fail_count": 0,
            }
            self._max_age_state[symbol] = state

        hard_deadline_ts: Optional[float] = None
        if hard_cap_sec > 0:
            hard_deadline_ts = float(pos.opened_at) + hard_cap_sec

        if hard_deadline_ts is not None and now_ts >= hard_deadline_ts:
            return True, "max_age_hard_exceeded", {
                "policy": "hard_cap",
                "age_sec": round(age_sec, 3),
                "hard_cap_sec": round(hard_deadline_ts - float(pos.opened_at), 3),
                "extensions_used": int(state.get("extensions_used") or 0),
            }

        next_soft_deadline_ts = float(state.get("next_soft_deadline_ts") or (float(pos.opened_at) + soft_cap_sec))
        if now_ts < next_soft_deadline_ts:
            return False, None, {
                "policy": "within_extension_window",
                "age_sec": round(age_sec, 3),
                "next_soft_deadline_sec": round(next_soft_deadline_ts - float(pos.opened_at), 3),
                "extensions_used": int(state.get("extensions_used") or 0),
            }

        last_recheck_ts = float(state.get("last_recheck_ts") or 0.0)
        if last_recheck_ts > 0 and (now_ts - last_recheck_ts) < recheck_sec:
            return False, None, {
                "policy": "await_recheck_interval",
                "age_sec": round(age_sec, 3),
                "seconds_until_recheck": round(recheck_sec - (now_ts - last_recheck_ts), 3),
                "extensions_used": int(state.get("extensions_used") or 0),
                "fail_count": int(state.get("fail_count") or 0),
            }
        state["last_recheck_ts"] = now_ts

        can_extend = int(state.get("extensions_used") or 0) < max_extensions and extension_sec > 0
        allow_extension, extension_meta = await self._should_extend_max_age(
            pos=pos,
            price=price,
            now_ts=now_ts,
        )
        if can_extend and allow_extension:
            state["extensions_used"] = int(state.get("extensions_used") or 0) + 1
            state["fail_count"] = 0
            new_deadline = next_soft_deadline_ts + extension_sec
            if hard_deadline_ts is not None:
                new_deadline = min(new_deadline, hard_deadline_ts)
            state["next_soft_deadline_ts"] = new_deadline
            return False, None, {
                "policy": "extension_granted",
                "age_sec": round(age_sec, 3),
                "extensions_used": int(state.get("extensions_used") or 0),
                "next_soft_deadline_sec": round(new_deadline - float(pos.opened_at), 3),
                **extension_meta,
            }

        state["fail_count"] = int(state.get("fail_count") or 0) + 1
        fail_count = int(state["fail_count"])
        if fail_count < required_confirms:
            return False, None, {
                "policy": "pending_confirmation",
                "age_sec": round(age_sec, 3),
                "fail_count": fail_count,
                "required_confirmations": required_confirms,
                "extensions_used": int(state.get("extensions_used") or 0),
                **extension_meta,
            }

        return True, "max_age_exceeded", {
            "policy": "confirmed_close",
            "age_sec": round(age_sec, 3),
            "fail_count": fail_count,
            "required_confirmations": required_confirms,
            "extensions_used": int(state.get("extensions_used") or 0),
            **extension_meta,
        }

    async def _should_extend_max_age(
        self,
        pos: PositionSnapshot,
        price: float,
        now_ts: float,
    ) -> tuple[bool, dict[str, Any]]:
        """Return whether position qualifies for a max-age extension."""
        pnl_bps = _current_pnl_bps(pos, price)
        min_pnl_bps = float(self.config.min_pnl_bps_to_extend or 0.0)
        if pnl_bps is None or pnl_bps < min_pnl_bps:
            return False, {
                "extension_check": "pnl_below_threshold",
                "pnl_bps": round(float(pnl_bps), 3) if pnl_bps is not None else None,
                "min_pnl_bps_to_extend": round(min_pnl_bps, 3),
            }

        prediction = await self._load_live_prediction(pos.symbol)
        if not prediction:
            return False, {
                "extension_check": "prediction_missing",
                "pnl_bps": round(float(pnl_bps), 3),
            }

        # Treat suppressed/blocked payloads as unhealthy for extension decisions.
        pred_status = str(prediction.get("status") or "").lower()
        if pred_status in {"suppressed", "blocked"}:
            return False, {
                "extension_check": "prediction_unhealthy",
                "prediction_status": pred_status,
                "prediction_reason": prediction.get("reason"),
                "pnl_bps": round(float(pnl_bps), 3),
            }

        symbol = str(pos.symbol or "").upper()
        confidence = _as_float(prediction.get("confidence"))
        min_conf = _symbol_float_override(
            symbol,
            self.config.continuation_symbol_min_confidence,
            self.config.continuation_min_confidence,
        )
        if confidence is None or confidence < float(min_conf):
            return False, {
                "extension_check": "confidence_low",
                "prediction_confidence": round(float(confidence), 4) if confidence is not None else None,
                "min_confidence": round(float(min_conf), 4),
                "pnl_bps": round(float(pnl_bps), 3),
            }

        direction = str(prediction.get("direction") or "").lower()
        if direction in {"", "flat", "none"} or not _direction_aligns_position(direction, pos):
            return False, {
                "extension_check": "direction_not_aligned",
                "prediction_direction": direction,
                "pnl_bps": round(float(pnl_bps), 3),
            }

        pred_ts = _as_float(prediction.get("timestamp"))
        pred_age_sec = (now_ts - pred_ts) if pred_ts is not None else None
        max_pred_age = float(self.config.continuation_max_prediction_age_sec)
        if pred_age_sec is None or pred_age_sec > max_pred_age:
            return False, {
                "extension_check": "prediction_stale",
                "prediction_age_sec": round(float(pred_age_sec), 3) if pred_age_sec is not None else None,
                "max_prediction_age_sec": round(max_pred_age, 3),
                "pnl_bps": round(float(pnl_bps), 3),
            }

        return True, {
            "extension_check": "ok",
            "prediction_confidence": round(float(confidence), 4),
            "prediction_direction": direction,
            "prediction_age_sec": round(float(pred_age_sec), 3),
            "pnl_bps": round(float(pnl_bps), 3),
        }

    async def _resolve_entry_attribution(self, pos: PositionSnapshot) -> tuple[Optional[str], Optional[str]]:
        if not self._snapshot_reader or not self._tenant_id or not self._bot_id:
            return None, None
        key = f"quantgambit:{self._tenant_id}:{self._bot_id}:positions:latest"
        try:
            payload = await self._snapshot_reader.read(key)
        except Exception:
            return None, None
        if not isinstance(payload, dict):
            return None, None
        positions = payload.get("positions")
        if not isinstance(positions, list):
            return None, None
        pos_symbol = str(getattr(pos, "symbol", "") or "").upper()
        pos_side = str(getattr(pos, "side", "") or "").lower()
        for row in positions:
            if not isinstance(row, dict):
                continue
            row_symbol = str(row.get("symbol") or "").upper()
            row_side = str(row.get("side") or "").lower()
            if row_symbol != pos_symbol or row_side != pos_side:
                continue
            entry_client_order_id = row.get("entry_client_order_id")
            entry_decision_id = row.get("entry_decision_id")
            if entry_client_order_id:
                return str(entry_client_order_id), str(entry_decision_id) if entry_decision_id else None
        return None, None

    async def _execute_close_order(
        self,
        pos: PositionSnapshot,
        reason: str,
        client_order_id: str,
    ) -> tuple[OrderStatus, Dict[str, Any]]:
        meta: Dict[str, Any] = {
            "path": "market",
            "tp_limit_attempted": False,
            "tp_limit_filled": False,
            "tp_limit_timeout_fallback": False,
            "tp_limit_price": None,
        }
        should_try_tp_limit = (
            self.config.tp_limit_exit_enabled
            and reason in self._tp_limit_reasons
            and not _is_emergency_exit_reason(reason)
            and pos.size is not None
            and float(pos.size) > 0
        )
        if not should_try_tp_limit:
            status = await self.exchange_client.close_position(
                pos.symbol,
                pos.side,
                pos.size,
                client_order_id=client_order_id,
            )
            return status, meta

        limit_price = self._compute_tp_limit_price(pos)
        if limit_price is None or limit_price <= 0:
            status = await self.exchange_client.close_position(
                pos.symbol,
                pos.side,
                pos.size,
                client_order_id=client_order_id,
            )
            return status, meta

        meta["path"] = "tp_limit"
        meta["tp_limit_attempted"] = True
        meta["tp_limit_price"] = limit_price
        limit_client_order_id = f"{client_order_id}:tpl"
        status = await self.exchange_client.close_position(
            pos.symbol,
            pos.side,
            pos.size,
            client_order_id=limit_client_order_id,
            order_type="limit",
            limit_price=limit_price,
            post_only=False,
            time_in_force=(self.config.tp_limit_time_in_force or "GTC"),
        )
        if _is_filled(status.status):
            meta["tp_limit_filled"] = True
            return status, meta

        terminal = await self._poll_terminal_close_status(
            symbol=pos.symbol,
            order_id=status.order_id,
            client_order_id=limit_client_order_id,
            window_ms=max(50, int(self.config.tp_limit_fill_window_ms)),
        )
        if terminal and _is_filled(terminal.status):
            meta["tp_limit_filled"] = True
            return terminal, meta

        meta["tp_limit_timeout_fallback"] = True
        meta["path"] = "tp_limit_fallback_market"
        await self.exchange_client.cancel_order(
            order_id=status.order_id,
            client_order_id=limit_client_order_id,
            symbol=pos.symbol,
        )
        after_cancel = await self._poll_terminal_close_status(
            symbol=pos.symbol,
            order_id=status.order_id,
            client_order_id=limit_client_order_id,
            window_ms=max(100, int(self.config.tp_limit_poll_interval_ms) * 4),
        )
        if after_cancel and _is_filled(after_cancel.status):
            meta["tp_limit_filled"] = True
            meta["path"] = "tp_limit_cancel_fill_race"
            return after_cancel, meta

        market_client_order_id = f"{client_order_id}:mkt"
        market_status = await self.exchange_client.close_position(
            pos.symbol,
            pos.side,
            pos.size,
            client_order_id=market_client_order_id,
        )
        return market_status, meta

    async def _poll_terminal_close_status(
        self,
        symbol: str,
        order_id: Optional[str],
        client_order_id: Optional[str],
        window_ms: int,
    ) -> Optional[OrderStatus]:
        end_at = time.time() + max(0.05, float(window_ms) / 1000.0)
        sleep_sec = max(0.05, float(self.config.tp_limit_poll_interval_ms) / 1000.0)
        while time.time() < end_at:
            await asyncio.sleep(sleep_sec)
            status: Optional[OrderStatus] = None
            if order_id:
                status = await self.exchange_client.fetch_order_status(order_id, symbol)
            if status is None and client_order_id and hasattr(self.exchange_client, "fetch_order_status_by_client_id"):
                status = await self.exchange_client.fetch_order_status_by_client_id(client_order_id, symbol)
            if status and _is_terminal_status(status.status):
                return status
        return None

    def _compute_tp_limit_price(self, pos: PositionSnapshot) -> Optional[float]:
        bid, ask = _best_bid_ask(self.exchange_client, pos.symbol)
        buffer_bps = max(0.0, float(self.config.tp_limit_price_buffer_bps or 0.0))
        if _is_long(pos):
            base = bid if bid is not None and bid > 0 else _reference_price(self.exchange_client, pos)
            if base is None or base <= 0:
                return None
            return base * (1.0 - (buffer_bps / 10000.0))
        base = ask if ask is not None and ask > 0 else _reference_price(self.exchange_client, pos)
        if base is None or base <= 0:
            return None
        return base * (1.0 + (buffer_bps / 10000.0))

    async def _should_defer_soft_exit(
        self,
        pos: PositionSnapshot,
        reason: str,
        price: float,
        now_ts: float,
    ) -> tuple[bool, dict[str, Any]]:
        if not self.config.continuation_gate_enabled:
            return False, {}
        if reason not in self._continuation_soft_reasons:
            return False, {}
        if pos.entry_price is None or pos.entry_price <= 0:
            return False, {}
        pnl_bps = _current_pnl_bps(pos, price)
        symbol = str(pos.symbol or "").upper()
        min_pnl_bps = _symbol_float_override(
            symbol,
            self.config.continuation_symbol_min_pnl_bps,
            self.config.continuation_min_pnl_bps,
        )
        fee_shortfall_bps: Optional[float] = None
        # For time-budget exits, allow a bounded defer window when the trade is gross-positive
        # but still below fee+buffer breakeven. This helps avoid scratching winners too early.
        if (
            reason in self._continuation_time_budget_reasons
            and self._fee_model is not None
            and pos.entry_price is not None
            and pos.entry_price > 0
            and pos.size is not None
            and pos.size > 0
            and pnl_bps is not None
            and pnl_bps > 0.0
        ):
            fee_check = self._fee_model.check_exit_profitability(
                size=pos.size,
                entry_price=pos.entry_price,
                current_price=price,
                side="long" if _is_long(pos) else "short",
                min_profit_buffer_bps=self._min_profit_buffer_bps,
            )
            if fee_check is not None and not fee_check.should_allow_exit:
                fee_shortfall_bps = fee_check.shortfall_bps
                min_pnl_bps = min(float(min_pnl_bps), 0.0)
        if pnl_bps is None or pnl_bps < float(min_pnl_bps):
            return False, {}
        prediction = await self._load_live_prediction(pos.symbol)
        if not prediction:
            return False, {}
        confidence = _as_float(prediction.get("confidence"))
        min_conf = _symbol_float_override(
            symbol,
            self.config.continuation_symbol_min_confidence,
            self.config.continuation_min_confidence,
        )
        if confidence is None or confidence < float(min_conf):
            return False, {}
        direction = str(prediction.get("direction") or "").lower()
        if direction in {"", "flat", "none"}:
            return False, {}
        if not _direction_aligns_position(direction, pos):
            return False, {}
        pred_ts = _as_float(prediction.get("timestamp"))
        pred_age_sec = (now_ts - pred_ts) if pred_ts is not None else None
        if pred_age_sec is None or pred_age_sec > float(self.config.continuation_max_prediction_age_sec):
            return False, {}

        state = self._continuation_state.get(pos.symbol)
        if not state or str(state.get("reason")) != str(reason):
            state = {"first_ts": now_ts, "count": 0, "reason": reason}
            self._continuation_state[pos.symbol] = state
        elapsed = max(0.0, now_ts - float(state.get("first_ts") or now_ts))
        count = int(state.get("count") or 0)
        max_defer_sec = _symbol_float_override(
            symbol,
            self.config.continuation_symbol_max_defer_sec,
            self.config.continuation_max_defer_sec,
        )
        if elapsed >= float(max_defer_sec):
            return False, {}
        if count >= int(self.config.continuation_max_defers):
            return False, {}

        state["count"] = count + 1
        return True, {
            "prediction_direction": direction,
            "prediction_confidence": round(float(confidence), 4),
            "prediction_age_sec": round(float(pred_age_sec), 3),
            "pnl_bps": round(float(pnl_bps), 3),
            "fee_shortfall_bps": round(float(fee_shortfall_bps), 3) if fee_shortfall_bps is not None else None,
            "defer_count": int(state["count"]),
            "defer_elapsed_sec": round(float(elapsed), 3),
        }

    async def _load_live_prediction(self, symbol: str) -> Optional[dict[str, Any]]:
        if self._snapshot_reader is None or not self._tenant_id or not self._bot_id:
            return None
        per_symbol_key = f"quantgambit:{self._tenant_id}:{self._bot_id}:prediction:{symbol}:latest"
        latest_key = f"quantgambit:{self._tenant_id}:{self._bot_id}:prediction:latest"
        payload = await self._snapshot_reader.read(per_symbol_key)
        if isinstance(payload, dict):
            return payload
        payload = await self._snapshot_reader.read(latest_key)
        if isinstance(payload, dict) and str(payload.get("symbol") or "").upper() == str(symbol).upper():
            return payload
        return None
    
    async def _send_guard_alert(
        self,
        pos: PositionSnapshot,
        reason: str,
        exit_price: Optional[float],
        realized_pnl: Optional[float],
        realized_pnl_pct: Optional[float],
        hold_time_sec: Optional[float],
    ) -> None:
        """Send Slack/Discord alert for guard trigger."""
        if not self._alerts_client:
            return
        
        try:
            config = GUARD_ALERT_CONFIG.get(reason, {"emoji": "⚠️", "severity": "warning", "label": reason})
            emoji = config["emoji"]
            severity = config["severity"]
            label = config["label"]
            
            # PnL formatting
            pnl_emoji = "🟢" if (realized_pnl or 0) > 0 else "🔴"
            pnl_str = f"${realized_pnl:.2f}" if realized_pnl is not None else "N/A"
            pnl_pct_str = f"{realized_pnl_pct:.2f}%" if realized_pnl_pct is not None else "N/A"
            hold_time_str = f"{hold_time_sec:.0f}s" if hold_time_sec is not None else "N/A"
            
            entry_str = f"${pos.entry_price:.2f}" if pos.entry_price else "N/A"
            exit_str = f"${exit_price:.2f}" if exit_price else "N/A"
            
            message = f"""
{emoji} **{label} Triggered**

• **Symbol:** `{pos.symbol}`
• **Side:** {pos.side}
• **Entry:** {entry_str}
• **Exit:** {exit_str}
• **P&L:** {pnl_emoji} {pnl_str} ({pnl_pct_str})
• **Hold Time:** {hold_time_str}
""".strip()
            
            await self._alerts_client.send(
                alert_type="guard_trigger",
                message=message,
                metadata={
                    "tenant_id": self._tenant_id,
                    "bot_id": self._bot_id,
                    "symbol": pos.symbol,
                    "reason": reason,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "exit_price": exit_price,
                    "realized_pnl": realized_pnl,
                    "realized_pnl_pct": realized_pnl_pct,
                    "hold_time_sec": hold_time_sec,
                },
                severity=severity,
            )
        except Exception as e:
            # Alert failure should never crash the guard worker
            log_warning("guard_alert_failed", error=str(e), symbol=pos.symbol, reason=reason)


def _reference_price(exchange_client: ExchangeClient, pos: PositionSnapshot) -> Optional[float]:
    provider = getattr(exchange_client, "reference_prices", None)
    if provider is None and hasattr(exchange_client, "_inner"):
        provider = getattr(exchange_client, "_inner", None)
        provider = getattr(provider, "reference_prices", None)
    if provider and hasattr(provider, "get_reference_price"):
        price = provider.get_reference_price(pos.symbol)
        if price is not None:
            return price
    return pos.reference_price


def _best_bid_ask(exchange_client: ExchangeClient, symbol: str) -> tuple[Optional[float], Optional[float]]:
    provider = getattr(exchange_client, "reference_prices", None)
    if provider is None and hasattr(exchange_client, "_inner"):
        provider = getattr(exchange_client, "_inner", None)
        provider = getattr(provider, "reference_prices", None)
    if provider and hasattr(provider, "get_orderbook_with_ts"):
        result = provider.get_orderbook_with_ts(symbol)
        book = result[0] if isinstance(result, tuple) and result else result
        if isinstance(book, dict):
            bids = book.get("bids") or []
            asks = book.get("asks") or []
            try:
                best_bid = float(bids[0][0]) if bids else None
            except (TypeError, ValueError, IndexError):
                best_bid = None
            try:
                best_ask = float(asks[0][0]) if asks else None
            except (TypeError, ValueError, IndexError):
                best_ask = None
            return best_bid, best_ask
    return None, None


def _should_close(
    pos: PositionSnapshot,
    price: float,
    now_ts: float,
    config: PositionGuardConfig,
    trailing_peaks: Dict[str, float],
    fee_model: Optional[FeeModel] = None,
) -> Optional[str]:
    entry_price = pos.entry_price
    pnl_bps: Optional[float] = None
    hold_time_sec: Optional[float] = None
    if pos.opened_at:
        # Use the injected tick time from the worker loop; do not call time.time() here.
        hold_time_sec = now_ts - pos.opened_at
    if entry_price is not None and entry_price > 0:
        if _is_long(pos):
            pnl_bps = (price - entry_price) / entry_price * 10000.0
        else:
            pnl_bps = (entry_price - price) / entry_price * 10000.0
    mfe_bps = pnl_bps
    if pos.mfe_pct is not None:
        mfe_bps = pos.mfe_pct * 100.0

    # --- Safety: Stop Loss ---
    if pos.stop_loss is not None:
        if _is_long(pos) and price <= pos.stop_loss:
            return "stop_loss_hit"
        if _is_short(pos) and price >= pos.stop_loss:
            return "stop_loss_hit"
    
    # --- Safety: Take Profit ---
    if pos.take_profit is not None:
        if _is_long(pos) and price >= pos.take_profit:
            return "take_profit_hit"
        if _is_short(pos) and price <= pos.take_profit:
            return "take_profit_hit"

    # --- Profit Protection: Breakeven Stop (after MFE threshold) ---
    if (
        config.breakeven_activation_bps > 0
        and entry_price is not None
        and mfe_bps is not None
        and mfe_bps >= config.breakeven_activation_bps
    ):
        if (
            config.breakeven_min_hold_sec > 0
            and hold_time_sec is not None
            and hold_time_sec < config.breakeven_min_hold_sec
        ):
            return None
        stop_price = _compute_breakeven_stop_price(
            pos, fee_model, config.breakeven_buffer_bps
        )
        if stop_price is not None:
            if _is_long(pos) and price <= stop_price:
                return "breakeven_stop_hit"
            if _is_short(pos) and price >= stop_price:
                return "breakeven_stop_hit"

    # --- Profit Protection: Lock gains if trade retraces after sufficient MFE ---
    if (
        config.profit_lock_activation_bps > 0
        and config.profit_lock_retrace_bps >= 0
        and mfe_bps is not None
        and pnl_bps is not None
        and mfe_bps >= config.profit_lock_activation_bps
    ):
        if (
            config.profit_lock_min_hold_sec > 0
            and hold_time_sec is not None
            and hold_time_sec < config.profit_lock_min_hold_sec
        ):
            return None
        if pnl_bps <= config.profit_lock_retrace_bps:
            return "profit_lock_retrace"

    # --- Profit Protection: Trailing Stop ---
    if config.trailing_stop_bps > 0:
        if (
            config.trailing_min_hold_sec > 0
            and hold_time_sec is not None
            and hold_time_sec < config.trailing_min_hold_sec
        ):
            return None
        if config.trailing_activation_bps <= 0 or (
            mfe_bps is not None and mfe_bps >= config.trailing_activation_bps
        ):
            return _check_trailing_stop(pos, price, config.trailing_stop_bps, trailing_peaks)

    # --- Time Budget: Max Hold (from position) ---
    # Position-specific max_hold_sec takes precedence over global config
    if pos.max_hold_sec is not None and pos.max_hold_sec > 0 and pos.opened_at:
        hold_time = hold_time_sec if hold_time_sec is not None else now_ts - pos.opened_at
        if hold_time >= pos.max_hold_sec:
            return "max_hold_exceeded"
    
    # --- Time Budget: Time-to-Work Check ---
    # If T_work has passed and MFE hasn't reached minimum, scratch the trade
    if pos.time_to_work_sec is not None and pos.mfe_min_bps is not None and pos.opened_at:
        hold_time = hold_time_sec if hold_time_sec is not None else now_ts - pos.opened_at
        if hold_time >= pos.time_to_work_sec:
            # Check if MFE has reached minimum
            # mfe_pct is in percentage, mfe_min_bps is in basis points
            mfe_achieved_bps = (pos.mfe_pct or 0.0) * 100.0  # Convert % to bps
            if mfe_achieved_bps < pos.mfe_min_bps:
                return "time_to_work_fail"
    
    # --- Legacy: Global Max Age (config-based) ---
    if config.max_position_age_sec > 0 and pos.opened_at:
        hold_time = hold_time_sec if hold_time_sec is not None else now_ts - pos.opened_at
        if hold_time >= config.max_position_age_sec:
            return "max_age_exceeded"
    
    return None


def _check_trailing_stop(
    pos: PositionSnapshot,
    price: float,
    trailing_bps: float,
    trailing_peaks: Dict[str, float],
) -> Optional[str]:
    if trailing_bps <= 0:
        return None
    key = f"{pos.symbol}:{(pos.side or '').lower()}"
    if _is_long(pos):
        peak = trailing_peaks.get(key, price)
        if price > peak:
            trailing_peaks[key] = price
            return None
        trigger = peak * (1 - trailing_bps / 10000.0)
        if price <= trigger:
            return "trailing_stop_hit"
    else:
        trough = trailing_peaks.get(key, price)
        if price < trough:
            trailing_peaks[key] = price
            return None
        trigger = trough * (1 + trailing_bps / 10000.0)
        if price >= trigger:
            return "trailing_stop_hit"
    return None


def _is_emergency_exit_reason(reason: Optional[str]) -> bool:
    text = str(reason or "").strip().lower()
    if not text:
        return False
    if text in {"stop_loss_hit", "max_age_hard_exceeded"}:
        return True
    return any(token in text for token in ("emergency", "critical", "liquidation", "safety_exit", "risk"))


def _compute_breakeven_stop_price(
    pos: PositionSnapshot,
    fee_model: Optional[FeeModel],
    buffer_bps: float,
) -> Optional[float]:
    entry_price = pos.entry_price
    size = pos.size
    if entry_price is None or entry_price <= 0 or size is None or size <= 0:
        return None
    side = "long" if _is_long(pos) else "short"
    breakeven_bps = 0.0
    if fee_model is not None:
        breakeven = fee_model.calculate_breakeven(
            size=size,
            entry_price=entry_price,
            side=side,
        )
        if breakeven is not None:
            breakeven_bps = breakeven.breakeven_bps
    total_bps = max(0.0, breakeven_bps + max(0.0, buffer_bps))
    if side == "long":
        return entry_price * (1 + total_bps / 10000.0)
    return entry_price * (1 - total_bps / 10000.0)


def _is_long(pos: PositionSnapshot) -> bool:
    return (pos.side or "").lower() in {"long", "buy"}


def _is_short(pos: PositionSnapshot) -> bool:
    return (pos.side or "").lower() in {"short", "sell"}


def _exit_side(side: Optional[str]) -> str:
    normalized = (side or "").lower()
    if normalized in {"long", "buy"}:
        return "sell"
    if normalized in {"short", "sell"}:
        return "buy"
    return "sell"


def _build_guard_client_order_id(
    bot_id: str,
    symbol: str,
    side: Optional[str],
    size: float,
    reason: str,
    retry_bucket: Optional[int] = None,
) -> str:
    """Build a unique client_order_id for guard-initiated closes.
    
    Uses a hash of bot_id, symbol, side, size, reason, and optional retry bucket.
    This keeps IDs deterministic within a short dedupe window, but allows retries
    to rotate IDs across windows when an exchange keeps rejecting a prior close ID.
    """
    bucket = str(retry_bucket) if retry_bucket is not None else "static"
    base = f"guard:{bot_id}:{symbol}:{side}:{size}:{reason}:{bucket}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()
    return f"qg-guard-{digest[:16]}"


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _current_pnl_bps(pos: PositionSnapshot, price: float) -> Optional[float]:
    entry_price = pos.entry_price
    if entry_price is None or entry_price <= 0:
        return None
    if _is_long(pos):
        return (price - entry_price) / entry_price * 10000.0
    return (entry_price - price) / entry_price * 10000.0


def _direction_aligns_position(direction: str, pos: PositionSnapshot) -> bool:
    d = (direction or "").lower()
    if _is_long(pos):
        return d in {"up", "long", "buy"}
    if _is_short(pos):
        return d in {"down", "short", "sell"}
    return False


def _symbol_float_override(
    symbol: str,
    overrides: Optional[Dict[str, float]],
    default_value: float,
) -> float:
    if not overrides:
        return float(default_value)
    value = overrides.get(str(symbol or "").upper())
    if value is None:
        return float(default_value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default_value)
