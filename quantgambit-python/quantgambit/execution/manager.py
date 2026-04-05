"""Execution manager interface for exchange and position actions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import os
import time
import uuid
from typing import Callable, Dict, List, Optional

from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.observability.schemas import order_payload
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.execution.order_statuses import normalize_order_status
from quantgambit.execution.symbols import normalize_exchange_symbol
from quantgambit.storage.redis_snapshots import RedisSnapshotReader


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    side: str  # long | short
    size: float
    # Stable attribution keys (for post-trade analysis + determinism across restarts)
    entry_client_order_id: Optional[str] = None
    entry_decision_id: Optional[str] = None
    execution_policy: Optional[str] = None
    execution_cohort: Optional[str] = None
    execution_experiment_id: Optional[str] = None
    reference_price: Optional[float] = None
    entry_price: Optional[float] = None
    entry_fee_usd: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: Optional[float] = None
    prediction_confidence: Optional[float] = None
    prediction_direction: Optional[str] = None
    prediction_source: Optional[str] = None
    entry_p_hat: Optional[float] = None
    entry_p_hat_source: Optional[str] = None
    strategy_id: Optional[str] = None
    profile_id: Optional[str] = None
    # MFE/MAE tracking (Maximum Favorable/Adverse Excursion)
    mfe_price: Optional[float] = None  # Best price reached (highest for long, lowest for short)
    mae_price: Optional[float] = None  # Worst price reached (lowest for long, highest for short)
    mfe_pct: Optional[float] = None  # MFE as percentage from entry
    mae_pct: Optional[float] = None  # MAE as percentage from entry
    # Signal strength at entry
    entry_signal_strength: Optional[str] = None  # weak/moderate/strong
    entry_signal_confidence: Optional[float] = None  # 0.0-1.0
    entry_confirmation_count: Optional[int] = None  # Number of confirmations
    # Time budget parameters (MFT scalping)
    expected_horizon_sec: Optional[float] = None  # How long signal is expected to be valid
    time_to_work_sec: Optional[float] = None  # T_work: time to first progress
    max_hold_sec: Optional[float] = None  # Max hold time before stale exit
    mfe_min_bps: Optional[float] = None  # Min favorable excursion expected quickly
    # Prediction context (Bug 8 fix — full traceability from prediction to trade outcome)
    model_side: Optional[str] = None  # "long" | "short" | None
    p_up: Optional[float] = None  # Raw probability of "up" class
    p_down: Optional[float] = None  # Raw probability of "down" class
    p_flat: Optional[float] = None  # Raw probability of "flat" class


@dataclass(frozen=True)
class OrderStatus:
    order_id: Optional[str]
    status: str
    fill_price: Optional[float] = None
    fee_usd: Optional[float] = None
    filled_size: Optional[float] = None
    remaining_size: Optional[float] = None
    reference_price: Optional[float] = None
    timestamp: Optional[float] = None
    source: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class ExecutionIntent:
    symbol: str
    side: str
    size: float
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy_id: Optional[str] = None
    profile_id: Optional[str] = None
    client_order_id: Optional[str] = None
    root_client_order_id: Optional[str] = None
    decision_id: Optional[str] = None
    execution_policy: Optional[str] = None
    execution_cohort: Optional[str] = None
    execution_experiment_id: Optional[str] = None
    prediction_confidence: Optional[float] = None
    prediction_direction: Optional[str] = None
    prediction_source: Optional[str] = None
    entry_p_hat: Optional[float] = None
    entry_p_hat_source: Optional[str] = None
    reduce_only: bool = False  # True for exit/close signals
    is_exit_signal: bool = False  # True when closing an existing position
    # Signal strength at entry (for telemetry)
    signal_strength: Optional[str] = None  # weak/moderate/strong
    signal_confidence: Optional[float] = None  # 0.0-1.0
    confirmation_count: Optional[int] = None  # Number of confirmations
    # Time budget parameters (MFT scalping)
    expected_horizon_sec: Optional[float] = None  # How long signal is expected to be valid
    time_to_work_sec: Optional[float] = None  # T_work: time to first progress
    max_hold_sec: Optional[float] = None  # Max hold time before stale exit
    mfe_min_bps: Optional[float] = None  # Min favorable excursion expected quickly
    # Provenance for close intents emitted by the signal pipeline.
    exit_reason: Optional[str] = None
    # Prediction context (Bug 8 fix — full traceability)
    model_side: Optional[str] = None  # "long" | "short" | None
    p_up: Optional[float] = None  # Raw probability of "up" class
    p_down: Optional[float] = None  # Raw probability of "down" class
    p_flat: Optional[float] = None  # Raw probability of "flat" class
    # Entry execution controls
    order_type: str = "market"  # market|limit
    limit_price: Optional[float] = None
    post_only: bool = False
    time_in_force: Optional[str] = None
    # Entry telemetry primitives
    mid_at_send: Optional[float] = None
    expected_price_at_send: Optional[float] = None
    send_ts: Optional[float] = None
    ack_ts: Optional[float] = None
    first_fill_ts: Optional[float] = None
    final_fill_ts: Optional[float] = None
    post_only_reject_count: int = 0
    cancel_after_timeout_count: int = 0


@dataclass
class FlattenResult:
    status: str
    message: str


def _logical_client_order_id(intent: ExecutionIntent) -> Optional[str]:
    """Root lineage id used for attribution/persistence across maker retries."""
    return intent.root_client_order_id or intent.client_order_id


@dataclass
class RiskOverrideResult:
    status: str
    message: str


@dataclass
class ReloadResult:
    status: str
    message: str


@dataclass
class FailoverResult:
    status: str
    message: str


@dataclass
class OrderActionResult:
    status: str
    message: str


class ExchangeClient:
    """Exchange adapter interface for execution actions."""

    async def close_position(
        self,
        symbol: str,
        side: str,
        size: float,
        client_order_id: Optional[str] = None,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        post_only: bool = False,
        time_in_force: Optional[str] = None,
    ) -> OrderStatus:
        raise NotImplementedError

    async def open_position(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        post_only: bool = False,
        time_in_force: Optional[str] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> OrderStatus:
        raise NotImplementedError

    async def place_protective_orders(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> bool:
        raise NotImplementedError

    async def fetch_order_status(self, order_id: str, symbol: str) -> Optional[OrderStatus]:
        raise NotImplementedError

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Optional[OrderStatus]:
        raise NotImplementedError

    async def cancel_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
    ) -> OrderStatus:
        # Never crash runtime if an adapter doesn't implement cancel; surface a
        # deterministic rejected status so caller can continue safely.
        return OrderStatus(
            order_id=order_id or client_order_id,
            status="rejected",
            reason="cancel_not_supported",
        )

    async def replace_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
        price: Optional[float],
        size: Optional[float],
    ) -> OrderStatus:
        return OrderStatus(
            order_id=order_id or client_order_id,
            status="rejected",
            reason="replace_not_supported",
        )


class PositionManager:
    """Position manager interface for tracking/closing positions."""

    async def list_open_positions(self) -> List[PositionSnapshot]:
        raise NotImplementedError

    async def upsert_position(self, snapshot: PositionSnapshot, accumulate: bool = True) -> None:
        """Insert or update a position.
        
        If accumulate=True (default), adds to existing position on same side.
        If accumulate=False, replaces position entirely.
        """
        raise NotImplementedError

    async def mark_closing(self, symbol: str, reason: str) -> None:
        raise NotImplementedError

    async def finalize_close(self, symbol: str) -> None:
        raise NotImplementedError

    def update_mfe_mae(self, symbol: str, current_price: float) -> None:
        """Update MFE/MAE for a position based on current price.
        
        Should be called on each price tick to track maximum favorable
        and adverse excursions during the trade.
        """
        pass  # Default no-op for backward compatibility


class RiskManager:
    """Risk manager interface for applying overrides."""

    async def apply_overrides(
        self,
        overrides: Dict[str, float],
        ttl_seconds: int,
        scope: Optional[Dict[str, str]] = None,
    ) -> bool:
        raise NotImplementedError


class ExchangeRouter:
    """Exchange router interface for manual failover."""

    async def switch_to_secondary(self) -> bool:
        raise NotImplementedError

    async def switch_to_primary(self) -> bool:
        raise NotImplementedError


class ExchangeReconciler:
    """Reconcile positions/balances after exchange switch."""

    async def reconcile(self) -> bool:
        raise NotImplementedError


class ExecutionManager:
    """Abstract execution manager for control-plane actions."""

    async def execute_intent(self, intent: ExecutionIntent) -> OrderStatus:
        raise NotImplementedError

    async def record_order_status(self, intent: ExecutionIntent, status: OrderStatus) -> bool:
        raise NotImplementedError

    async def poll_order_status(self, order_id: str, symbol: str) -> Optional[OrderStatus]:
        raise NotImplementedError

    async def poll_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Optional[OrderStatus]:
        raise NotImplementedError

    async def flatten_positions(self, symbol: Optional[str] = None) -> FlattenResult:
        raise NotImplementedError

    async def apply_risk_override(
        self,
        overrides: Dict[str, float],
        ttl_seconds: int,
        scope: Optional[Dict[str, str]] = None,
    ) -> RiskOverrideResult:
        raise NotImplementedError

    async def reload_config(self) -> ReloadResult:
        raise NotImplementedError

    async def execute_failover(self) -> FailoverResult:
        raise NotImplementedError

    async def execute_recovery(self) -> FailoverResult:
        raise NotImplementedError

    async def cancel_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
    ) -> OrderActionResult:
        raise NotImplementedError

    async def replace_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
        price: Optional[float],
        size: Optional[float],
    ) -> OrderActionResult:
        raise NotImplementedError


class RealExecutionManager(ExecutionManager):
    """Concrete execution manager using exchange + position manager interfaces."""

    def __init__(
        self,
        exchange_client: ExchangeClient,
        position_manager: PositionManager,
        risk_manager: Optional[RiskManager] = None,
        exchange_router: Optional[ExchangeRouter] = None,
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        reconciler: Optional[ExchangeReconciler] = None,
        order_store: Optional[InMemoryOrderStore] = None,
        snapshot_reader: Optional[RedisSnapshotReader] = None,
        profile_feedback: Optional[Callable[[str, str, float], None]] = None,
        reference_prices=None,
    ):
        self.exchange_client = exchange_client
        self.position_manager = position_manager
        self.risk_manager = risk_manager
        self.exchange_router = exchange_router
        self.primary_exchange: Optional[str] = None
        self.secondary_exchange: Optional[str] = None
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.reconciler = reconciler
        self.order_store = order_store
        self.snapshot_reader = snapshot_reader
        self.profile_feedback = profile_feedback
        self.reference_prices = reference_prices

    def set_failover_targets(self, primary_exchange: Optional[str], secondary_exchange: Optional[str]) -> None:
        self.primary_exchange = primary_exchange
        self.secondary_exchange = secondary_exchange

    async def flatten_positions(self, symbol: Optional[str] = None) -> FlattenResult:
        positions = await self.position_manager.list_open_positions()
        if symbol:
            positions = [pos for pos in positions if pos.symbol == symbol]

        if not positions:
            return FlattenResult(status="executed", message="no_positions")

        failures = 0
        for pos in positions:
            await self.position_manager.mark_closing(pos.symbol, reason="manual_flatten")
            status = await self.exchange_client.close_position(pos.symbol, pos.side, pos.size)
            if _is_filled(status.status):
                exit_timestamp = status.timestamp or time.time()
                size_for_pnl = status.filled_size or pos.size
                exit_price = status.fill_price
                exit_fee_usd = status.fee_usd
                reconciled = await _reconcile_close_from_exchange(
                    exchange_client=self.exchange_client,
                    symbol=pos.symbol,
                    order_id=status.order_id,
                    client_order_id=None,
                    exit_timestamp=exit_timestamp,
                )
                if reconciled:
                    exit_price = reconciled.get("avg_price") or exit_price
                    exit_fee_usd = reconciled.get("total_fees_usd") if reconciled.get("total_fees_usd") is not None else exit_fee_usd
                    size_for_pnl = reconciled.get("total_qty") or size_for_pnl
                    exit_timestamp = reconciled.get("exit_timestamp") or exit_timestamp
                gross_pnl, net_pnl, net_pnl_pct, total_fees = _compute_pnl_breakdown(
                    pos.entry_price,
                    exit_price,
                    size_for_pnl,
                    pos.side,
                    entry_fee_usd=pos.entry_fee_usd,
                    exit_fee_usd=exit_fee_usd,
                )
                self._record_profile_feedback(pos.profile_id, pos.symbol, net_pnl)
                hold_time_sec = (exit_timestamp - pos.opened_at) if pos.opened_at else None
                await self._record_order(
                    symbol=pos.symbol,
                    side=_exit_side(pos.side),
                    size=pos.size,
                    status=status.status,
                    order_id=status.order_id,
                    client_order_id=None,
                    reason="manual_flatten",
                    fill_price=exit_price,
                    fee_usd=exit_fee_usd,
                    filled_size=size_for_pnl,
                    remaining_size=status.remaining_size,
                    source=status.source or "local",
                    event_type="manual_flatten",
                    reference_price=pos.reference_price or status.reference_price,
                )
                await self.position_manager.finalize_close(pos.symbol)
                await self._cleanup_protective_orders(pos.symbol)
                await self._emit_order_event(
                    symbol=pos.symbol,
                    side=_exit_side(pos.side),
                    size=size_for_pnl,
                    status=status.status,
                    reason="manual_flatten",
                    reference_price=pos.reference_price or status.reference_price,
                    fill_price=exit_price,
                    fee_usd=exit_fee_usd,
                    entry_fee_usd=pos.entry_fee_usd,
                    total_fees_usd=total_fees,
                    order_id=status.order_id,
                    client_order_id=None,
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
                    hold_time_sec=hold_time_sec,
                    prediction_confidence=pos.prediction_confidence,
                    prediction_direction=pos.prediction_direction,
                    prediction_source=pos.prediction_source,
                    entry_p_hat=pos.entry_p_hat,
                    entry_p_hat_source=pos.entry_p_hat_source,
                    model_side=pos.model_side,
                    p_up=pos.p_up,
                    p_down=pos.p_down,
                    p_flat=pos.p_flat,
                )
                await self._emit_position_closed(
                    symbol=pos.symbol,
                    side=pos.side,
                    size=size_for_pnl,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    realized_pnl=net_pnl,
                    realized_pnl_pct=net_pnl_pct,
                    fee_usd=exit_fee_usd,
                    entry_client_order_id=pos.entry_client_order_id,
                    entry_decision_id=pos.entry_decision_id,
                    execution_policy=pos.execution_policy,
                    execution_cohort=pos.execution_cohort,
                    execution_experiment_id=pos.execution_experiment_id,
                    entry_fee_usd=pos.entry_fee_usd,
                    total_fees_usd=total_fees,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    hold_time_sec=hold_time_sec,
                    entry_timestamp=pos.opened_at,
                    close_reason="manual_flatten",
                    order_id=status.order_id,
                    strategy_id=pos.strategy_id,
                    profile_id=pos.profile_id,
                    mfe_pct=pos.mfe_pct,
                    mae_pct=pos.mae_pct,
                    signal_strength=pos.entry_signal_strength,
                    signal_confidence=pos.entry_signal_confidence,
                    prediction_confidence=pos.prediction_confidence,
                    prediction_direction=pos.prediction_direction,
                    prediction_source=pos.prediction_source,
                    entry_p_hat=pos.entry_p_hat,
                    entry_p_hat_source=pos.entry_p_hat_source,
                    entry_reference_price=pos.reference_price,
                    exit_reference_price=pos.reference_price or status.reference_price,
                )
            else:
                failures += 1
                await self._record_order(
                    symbol=pos.symbol,
                    side=_exit_side(pos.side),
                    size=pos.size,
                    status=status.status,
                    order_id=status.order_id,
                    client_order_id=None,
                    reason="manual_flatten",
                    fill_price=status.fill_price,
                    fee_usd=status.fee_usd,
                    filled_size=status.filled_size,
                    remaining_size=status.remaining_size,
                    source=status.source or "local",
                    event_type="manual_flatten",
                    reference_price=pos.reference_price or status.reference_price,
                )
                await self._emit_order_event(
                    symbol=pos.symbol,
                    side=_exit_side(pos.side),
                    size=pos.size,
                    status=status.status,
                    reason="manual_flatten",
                    reference_price=pos.reference_price or status.reference_price,
                    fill_price=status.fill_price,
                    fee_usd=status.fee_usd,
                    order_id=status.order_id,
                    client_order_id=None,
                    position_effect="close",
                    entry_price=pos.entry_price,
                    exit_price=status.fill_price,
                    entry_timestamp=pos.opened_at,
                    prediction_confidence=pos.prediction_confidence,
                    prediction_direction=pos.prediction_direction,
                    prediction_source=pos.prediction_source,
                    entry_p_hat=pos.entry_p_hat,
                    entry_p_hat_source=pos.entry_p_hat_source,
                    model_side=pos.model_side,
                    p_up=pos.p_up,
                    p_down=pos.p_down,
                    p_flat=pos.p_flat,
                )

        if failures:
            return FlattenResult(status="failed", message=f"flatten_failed:{failures}")
        await self._emit_positions_snapshot()
        return FlattenResult(status="executed", message="flatten_complete")

    async def _resolve_exit_position(self, symbol: str) -> Optional[PositionSnapshot]:
        """Resolve the current position for an exit intent.

        Preference order:
        1) Local position manager
        2) Exchange fetch_positions() with symbol normalization
        """
        position = await _find_open_position(self.position_manager, symbol)
        if position:
            return position
        if not self.exchange_client or not hasattr(self.exchange_client, "fetch_positions"):
            return None
        market_type = getattr(self.exchange_client, "market_type", None)
        normalized_target_symbol = normalize_exchange_symbol(
            getattr(self.exchange_client, "exchange", "") or "",
            symbol,
            market_type=market_type,
        ) or symbol
        try:
            exchange_positions = await self.exchange_client.fetch_positions()
        except Exception as exc:
            log_warning("exit_position_fetch_failed", symbol=symbol, error=str(exc))
            return None
        if not exchange_positions:
            return None
        for pos in exchange_positions:
            raw_symbol = pos.get("symbol") or ""
            normalized = normalize_exchange_symbol(
                getattr(self.exchange_client, "exchange", "") or "",
                raw_symbol,
                market_type=market_type,
            )
            if normalized != normalized_target_symbol:
                continue
            raw_size = pos.get("contracts", None)
            if raw_size is None:
                raw_size = pos.get("size", None)
            if raw_size is None:
                raw_size = pos.get("positionAmt", None)
            try:
                size_val = float(raw_size or 0)
            except (TypeError, ValueError):
                size_val = 0.0
            if size_val == 0:
                continue
            side = (pos.get("side") or ("short" if size_val < 0 else "long")).lower()
            size_abs = abs(size_val)
            entry_price = None
            try:
                entry_price = float(pos.get("entryPrice") or pos.get("entry_price") or 0) or None
            except (TypeError, ValueError):
                entry_price = None
            opened_at = None
            try:
                ts = pos.get("timestamp") or pos.get("updatedTime") or pos.get("createdTime")
                if ts:
                    opened_at = float(ts) / 1000.0 if float(ts) > 1e12 else float(ts)
            except Exception:
                opened_at = None
            snapshot = PositionSnapshot(
                symbol=normalized,
                side=side,
                size=size_abs,
                reference_price=entry_price,
                entry_price=entry_price,
                stop_loss=pos.get("stopLoss") or pos.get("stop_loss") or pos.get("sl") or pos.get("slPrice"),
                take_profit=pos.get("takeProfit") or pos.get("take_profit") or pos.get("tp") or pos.get("tpPrice"),
                opened_at=opened_at,
            )
            await self.position_manager.upsert_position(snapshot, accumulate=False)
            log_info("exit_position_hydrated_from_exchange", symbol=normalized, size=size_abs, side=side)
            return snapshot
        return None

    async def execute_intent(self, intent: ExecutionIntent) -> OrderStatus:
        # Capture submission time BEFORE calling exchange for latency tracking
        submitted_at = time.time()
        resolved_exit_position: Optional[PositionSnapshot] = None
        effective_size = intent.size
        try:
            # For exit signals (reduce_only), use close_position instead of open_position
            if intent.reduce_only or intent.is_exit_signal:
                resolved_exit_position = await self._resolve_exit_position(intent.symbol)
                if not resolved_exit_position:
                    log_warning(
                        "exit_signal_no_position",
                        symbol=intent.symbol,
                        side=intent.side,
                    )
                    return OrderStatus(
                        order_id=None,
                        status="rejected",
                        fill_price=None,
                        fee_usd=None,
                        reason="exit_no_position",
                    )
                exit_size = resolved_exit_position.size
                if intent.size and intent.size > 0:
                    exit_size = min(intent.size, resolved_exit_position.size)
                if exit_size <= 0:
                    log_warning("exit_signal_zero_size", symbol=intent.symbol, size=exit_size)
                    return OrderStatus(
                        order_id=None,
                        status="rejected",
                        fill_price=None,
                        fee_usd=None,
                        reason="exit_zero_size",
                    )
                effective_size = exit_size
                # Determine the position side we're closing
                # If intent.side is "sell", we're closing a "long" position
                # If intent.side is "buy", we're closing a "short" position
                position_side = resolved_exit_position.side or ("long" if intent.side == "sell" else "short")
                
                log_info(
                    "execute_exit_intent",
                    symbol=intent.symbol,
                    intent_side=intent.side,
                    position_side=position_side,
                    size=effective_size,
                    reduce_only=intent.reduce_only,
                )
                
                status = await self.exchange_client.close_position(
                    intent.symbol,
                    position_side,
                    effective_size,
                    client_order_id=intent.client_order_id,
                )
            else:
                effective_size = intent.size
                try:
                    status = await self.exchange_client.open_position(
                        intent.symbol,
                        intent.side,
                        intent.size,
                        order_type=intent.order_type,
                        limit_price=intent.limit_price,
                        post_only=intent.post_only,
                        time_in_force=intent.time_in_force,
                        stop_loss=intent.stop_loss,
                        take_profit=intent.take_profit,
                        client_order_id=intent.client_order_id,
                    )
                except TypeError:
                    # Backward compatibility for legacy/mock exchange clients.
                    status = await self.exchange_client.open_position(
                        intent.symbol,
                        intent.side,
                        intent.size,
                        stop_loss=intent.stop_loss,
                        take_profit=intent.take_profit,
                        client_order_id=intent.client_order_id,
                    )
        except Exception as exc:
            # If exchange raises an exception, return rejected status
            # This ensures the intent gets marked as failed, not left in "submitted" state
            error_str = str(exc)
            log_warning(
                "execute_intent_exception",
                symbol=intent.symbol,
                error=error_str,
                error_type=type(exc).__name__,
                is_exit=intent.reduce_only or intent.is_exit_signal,
            )
            
            # Handle "position is zero" errors - clear stale local position state
            # Common exchange errors:
            # - Bybit 110017: "current position is zero, cannot fix reduce-only order qty"
            # - OKX: Similar "position not found" errors
            is_no_position_error = (
                "110017" in error_str or 
                "position is zero" in error_str.lower() or
                "position not found" in error_str.lower() or
                "no position" in error_str.lower()
            )
            
            if is_no_position_error and (intent.reduce_only or intent.is_exit_signal):
                # Clear the stale position from local state
                log_warning(
                    "stale_position_cleared",
                    symbol=intent.symbol,
                    reason="exchange_says_no_position",
                    error=error_str[:200],
                )
                try:
                    await self.position_manager.finalize_close(intent.symbol)
                except Exception as clear_exc:
                    log_warning("position_clear_failed", symbol=intent.symbol, error=str(clear_exc))
            
            status = OrderStatus(
                order_id=None,
                status="rejected",
                fill_price=None,
                fee_usd=None,
                reason=f"exchange_error: {error_str[:500]}",
            )
        ack_ts = time.time()
        if intent.ack_ts is None:
            intent = replace(intent, ack_ts=ack_ts)
        if _is_filled(status.status):
            fill_ts = status.timestamp or ack_ts
            if intent.first_fill_ts is None:
                intent = replace(intent, first_fill_ts=fill_ts)
            if intent.final_fill_ts is None:
                intent = replace(intent, final_fill_ts=fill_ts)
        fill_price = status.fill_price
        fee_usd = status.fee_usd
        filled_size = status.filled_size
        if _is_filled(status.status):
            reconciled = await _reconcile_execution_from_exchange(
                exchange_client=self.exchange_client,
                symbol=intent.symbol,
                order_id=status.order_id,
                client_order_id=intent.client_order_id,
                timestamp=status.timestamp,
            )
            if reconciled:
                fill_price = reconciled.get("avg_price") or fill_price
                fee_usd = reconciled.get("total_fees_usd") if reconciled.get("total_fees_usd") is not None else fee_usd
                filled_size = reconciled.get("total_qty") or filled_size
                status = OrderStatus(
                    order_id=status.order_id,
                    status=status.status,
                    fill_price=fill_price,
                    fee_usd=fee_usd,
                    filled_size=filled_size,
                    remaining_size=status.remaining_size,
                    reference_price=status.reference_price,
                    timestamp=status.timestamp,
                    source=status.source,
                    reason=status.reason,
                )
        await self._record_order(
            symbol=intent.symbol,
            side=intent.side,
            size=filled_size or effective_size,
            status=status.status,
            order_id=status.order_id,
            client_order_id=intent.client_order_id,
            reason=status.reason or "execution_intent",
            fill_price=fill_price,
            fee_usd=fee_usd,
            filled_size=filled_size,
            remaining_size=status.remaining_size,
            source=status.source or "local",
            event_type="execution_intent",
            reference_price=intent.entry_price or status.reference_price,
            submitted_at_override=submitted_at,
        )
        
        # Handle "rejected" status with "position is zero" error (from guards.py circuit breaker)
        # This indicates the exchange has no position but we think we do - clear stale local state
        if status.status == "rejected" and status.reason and (intent.reduce_only or intent.is_exit_signal):
            reason_str = status.reason.lower()
            is_no_position_error = (
                "110017" in reason_str or
                "position is zero" in reason_str or
                "position not found" in reason_str or
                "no position" in reason_str or
                "don't have any positions" in reason_str
            )
            if is_no_position_error:
                log_warning(
                    "stale_position_cleared_from_rejected",
                    symbol=intent.symbol,
                    reason="exchange_says_no_position",
                    status_reason=status.reason[:200] if status.reason else None,
                )
                try:
                    await self.position_manager.finalize_close(intent.symbol)
                except Exception as clear_exc:
                    log_warning("position_clear_failed", symbol=intent.symbol, error=str(clear_exc))
        
        if _is_filled(status.status):
            # Handle exit signals differently - close position instead of opening
            if intent.reduce_only or intent.is_exit_signal:
                # This is an exit signal - close the position
                position_side = "long" if intent.side == "sell" else "short"
                position = resolved_exit_position or await _find_open_position(self.position_manager, intent.symbol)
                
                if position:
                    exit_timestamp = status.timestamp or time.time()
                    size_for_pnl = status.filled_size or intent.size or position.size
                    exit_price = status.fill_price
                    exit_fee_usd = status.fee_usd
                    reconciled = await _reconcile_close_from_exchange(
                        exchange_client=self.exchange_client,
                        symbol=intent.symbol,
                        order_id=status.order_id,
                        client_order_id=intent.client_order_id,
                        exit_timestamp=exit_timestamp,
                    )
                    if reconciled:
                        exit_price = reconciled.get("avg_price") or exit_price
                        exit_fee_usd = reconciled.get("total_fees_usd") if reconciled.get("total_fees_usd") is not None else exit_fee_usd
                        size_for_pnl = reconciled.get("total_qty") or size_for_pnl
                        exit_timestamp = reconciled.get("exit_timestamp") or exit_timestamp
                    await self._record_order(
                        symbol=intent.symbol,
                        side=intent.side,
                        size=size_for_pnl,
                        status=status.status,
                        order_id=status.order_id,
                        client_order_id=intent.client_order_id,
                        reason="exchange_reconcile",
                        fill_price=exit_price,
                        fee_usd=exit_fee_usd,
                        filled_size=size_for_pnl,
                        remaining_size=status.remaining_size,
                        timestamp=exit_timestamp,
                        source="exchange_reconcile",
                        event_type="exchange_reconcile",
                        reference_price=position.reference_price or status.reference_price,
                    )
                    gross_pnl, net_pnl, net_pnl_pct, total_fees = _compute_pnl_breakdown(
                        position.entry_price,
                        exit_price,
                        size_for_pnl,
                        position.side,
                        entry_fee_usd=position.entry_fee_usd,
                        exit_fee_usd=exit_fee_usd,
                    )
                    hold_time_sec = (exit_timestamp - position.opened_at) if position.opened_at else None
                    exit_reason = str(intent.exit_reason or "strategic_exit")
                    entry_coid = str(position.entry_client_order_id or "")
                    entry_post_only = ":m" in entry_coid
                    
                    await self.position_manager.finalize_close(intent.symbol)
                    await self._emit_order_event(
                        symbol=intent.symbol,
                        side=intent.side,
                        size=size_for_pnl,
                        status=status.status,
                        reason=exit_reason,
                        reference_price=status.reference_price,
                        fill_price=exit_price,
                        fee_usd=exit_fee_usd,
                        entry_fee_usd=position.entry_fee_usd,
                        total_fees_usd=total_fees,
                        order_id=status.order_id,
                        client_order_id=intent.client_order_id,
                        position_effect="close",
                        realized_pnl=net_pnl,
                        realized_pnl_pct=net_pnl_pct,
                        gross_pnl=gross_pnl,
                        net_pnl=net_pnl,
                        filled_size=size_for_pnl,
                        hold_time_sec=hold_time_sec,
                        entry_price=position.entry_price,
                        exit_price=exit_price,
                        entry_timestamp=position.opened_at,
                        # MFE/MAE telemetry
                        mfe_pct=position.mfe_pct,
                        mae_pct=position.mae_pct,
                        entry_client_order_id=position.entry_client_order_id,
                        entry_order_type="limit" if entry_post_only else "market",
                        entry_post_only=entry_post_only,
                        order_type=intent.order_type,
                        post_only=intent.post_only,
                        prediction_confidence=position.prediction_confidence,
                        prediction_direction=position.prediction_direction,
                        prediction_source=position.prediction_source,
                        entry_p_hat=position.entry_p_hat,
                        entry_p_hat_source=position.entry_p_hat_source,
                        model_side=position.model_side,
                        p_up=position.p_up,
                        p_down=position.p_down,
                        p_flat=position.p_flat,
                    )
                    await self._emit_position_closed(
                        symbol=intent.symbol,
                        side=position.side,
                        size=size_for_pnl,
                        entry_price=position.entry_price,
                        exit_price=exit_price,
                        realized_pnl=net_pnl,
                        realized_pnl_pct=net_pnl_pct,
                        fee_usd=exit_fee_usd,
                        entry_client_order_id=position.entry_client_order_id,
                        entry_decision_id=position.entry_decision_id,
                        execution_policy=position.execution_policy,
                        execution_cohort=position.execution_cohort,
                        execution_experiment_id=position.execution_experiment_id,
                        entry_fee_usd=position.entry_fee_usd,
                        total_fees_usd=total_fees,
                        gross_pnl=gross_pnl,
                        net_pnl=net_pnl,
                        hold_time_sec=hold_time_sec,
                        entry_timestamp=position.opened_at,
                        close_reason=exit_reason,
                        order_id=status.order_id,
                        strategy_id=position.strategy_id,
                        profile_id=position.profile_id,
                        mfe_pct=position.mfe_pct,
                        mae_pct=position.mae_pct,
                        signal_strength=position.entry_signal_strength,
                        signal_confidence=position.entry_signal_confidence,
                        prediction_confidence=position.prediction_confidence,
                        prediction_direction=position.prediction_direction,
                        prediction_source=position.prediction_source,
                        entry_p_hat=position.entry_p_hat,
                        entry_p_hat_source=position.entry_p_hat_source,
                    )
                    log_info(
                        "position_closed_exit_signal",
                        symbol=intent.symbol,
                        side=position.side,
                        close_reason=exit_reason,
                        realized_pnl=net_pnl,
                        realized_pnl_pct=net_pnl_pct,
                        hold_time_sec=hold_time_sec,
                        mfe_pct=position.mfe_pct,
                        mae_pct=position.mae_pct,
                    )
                else:
                    log_warning(
                        "exit_signal_no_position_after_fill",
                        symbol=intent.symbol,
                        side=intent.side,
                    )
                
                await self._emit_positions_snapshot()
                return status
            
            # Normal entry signal - open position
            entry_price = fill_price or intent.entry_price or status.reference_price
            entry_timestamp = status.timestamp or time.time()
            entry_size = filled_size or intent.size
            await self.position_manager.upsert_position(
                PositionSnapshot(
                    symbol=intent.symbol,
                    side=intent.side,
                    size=entry_size,
                    entry_client_order_id=_logical_client_order_id(intent),
                    entry_decision_id=intent.decision_id,
                    execution_policy=intent.execution_policy,
                    execution_cohort=intent.execution_cohort,
                    execution_experiment_id=intent.execution_experiment_id,
                    reference_price=status.reference_price,
                    entry_price=entry_price,
                    entry_fee_usd=fee_usd,
                    stop_loss=intent.stop_loss,
                    take_profit=intent.take_profit,
                    opened_at=entry_timestamp,
                    prediction_confidence=intent.prediction_confidence,
                    prediction_direction=intent.prediction_direction,
                    prediction_source=intent.prediction_source,
                    entry_p_hat=intent.entry_p_hat,
                    entry_p_hat_source=intent.entry_p_hat_source,
                    strategy_id=intent.strategy_id,
                    profile_id=intent.profile_id,
                    # Signal strength telemetry
                    entry_signal_strength=intent.signal_strength,
                    entry_signal_confidence=intent.signal_confidence,
                    entry_confirmation_count=intent.confirmation_count,
                    # Time budget parameters
                    expected_horizon_sec=intent.expected_horizon_sec,
                    time_to_work_sec=intent.time_to_work_sec,
                    max_hold_sec=intent.max_hold_sec,
                    mfe_min_bps=intent.mfe_min_bps,
                    # Prediction context (Bug 8 fix)
                    model_side=intent.model_side,
                    p_up=intent.p_up,
                    p_down=intent.p_down,
                    p_flat=intent.p_flat,
                )
            )
            await self._emit_position_opened(
                symbol=intent.symbol,
                side=intent.side,
                size=entry_size,
                entry_price=entry_price,
                entry_timestamp=entry_timestamp,
                fee_usd=fee_usd,
                stop_loss=intent.stop_loss,
                take_profit=intent.take_profit,
                order_id=status.order_id,
                client_order_id=_logical_client_order_id(intent),
                decision_id=intent.decision_id,
                strategy_id=intent.strategy_id,
                profile_id=intent.profile_id,
                execution_policy=intent.execution_policy,
                execution_cohort=intent.execution_cohort,
                execution_experiment_id=intent.execution_experiment_id,
                prediction_confidence=intent.prediction_confidence,
                prediction_direction=intent.prediction_direction,
                prediction_source=intent.prediction_source,
                entry_p_hat=intent.entry_p_hat,
                entry_p_hat_source=intent.entry_p_hat_source,
                signal_strength=intent.signal_strength,
                signal_confidence=intent.signal_confidence,
                confirmation_count=intent.confirmation_count,
                entry_reference_price=status.reference_price,
            )
            await self._emit_order_event(
                symbol=intent.symbol,
                side=intent.side,
                size=entry_size,
                status=status.status,
                reason="execution_intent",
                reference_price=status.reference_price,
                fill_price=fill_price,
                fee_usd=fee_usd,
                entry_fee_usd=fee_usd,
                total_fees_usd=fee_usd,
                order_id=status.order_id,
                client_order_id=intent.client_order_id,
                position_effect="open",
                entry_price=entry_price,
                entry_timestamp=entry_timestamp,
                filled_size=filled_size,
                # Signal strength telemetry
                signal_strength=intent.signal_strength,
                signal_confidence=intent.signal_confidence,
                confirmation_count=intent.confirmation_count,
                mid_at_send=intent.mid_at_send,
                expected_price_at_send=intent.expected_price_at_send,
                send_ts=intent.send_ts,
                ack_ts=intent.ack_ts,
                first_fill_ts=intent.first_fill_ts,
                final_fill_ts=intent.final_fill_ts,
                post_only_reject_count=intent.post_only_reject_count,
                cancel_after_timeout_count=intent.cancel_after_timeout_count,
                order_type=intent.order_type,
                post_only=intent.post_only,
            )
            await self._emit_positions_snapshot()
            await self._place_protective_orders(intent, filled_size=filled_size)
            return status
        if _is_rejected(status.status):
            await self._emit_order_event(
                symbol=intent.symbol,
                side=intent.side,
                size=intent.size,
                status=status.status,
                reason="execution_intent",
                reference_price=status.reference_price,
                fill_price=status.fill_price,
                fee_usd=status.fee_usd,
                order_id=status.order_id,
                client_order_id=intent.client_order_id,
                mid_at_send=intent.mid_at_send,
                expected_price_at_send=intent.expected_price_at_send,
                send_ts=intent.send_ts,
                ack_ts=intent.ack_ts,
                post_only_reject_count=intent.post_only_reject_count,
                cancel_after_timeout_count=intent.cancel_after_timeout_count,
                order_type=intent.order_type,
                post_only=intent.post_only,
            )
            return status
        await self._emit_order_event(
            symbol=intent.symbol,
            side=intent.side,
            size=intent.size,
            status=status.status,
            reason="execution_pending",
            reference_price=status.reference_price,
            fill_price=status.fill_price,
            fee_usd=status.fee_usd,
            order_id=status.order_id,
            client_order_id=intent.client_order_id,
            mid_at_send=intent.mid_at_send,
            expected_price_at_send=intent.expected_price_at_send,
            send_ts=intent.send_ts,
            ack_ts=intent.ack_ts,
            post_only_reject_count=intent.post_only_reject_count,
            cancel_after_timeout_count=intent.cancel_after_timeout_count,
            order_type=intent.order_type,
            post_only=intent.post_only,
        )
        return status

    async def _place_protective_orders(self, intent: ExecutionIntent, filled_size: Optional[float] = None) -> None:
        if not intent.stop_loss and not intent.take_profit:
            return
        if not hasattr(self.exchange_client, "place_protective_orders"):
            return
        protective_size = filled_size or intent.size
        if not protective_size or protective_size <= 0:
            return
        try:
            await self._cleanup_protective_orders(intent.symbol)
            await self.exchange_client.place_protective_orders(
                intent.symbol,
                intent.side,
                protective_size,
                stop_loss=intent.stop_loss,
                take_profit=intent.take_profit,
                client_order_id=intent.client_order_id,
            )
        except Exception as exc:
            log_warning(
                "protective_orders_failed",
                symbol=intent.symbol,
                error=str(exc),
            )

    async def record_order_status(self, intent: ExecutionIntent, status: OrderStatus) -> bool:
        if self.order_store and not self.order_store.should_accept_update(
            status.order_id,
            intent.client_order_id,
            status.status,
            timestamp=status.timestamp,
            source=status.source,
        ):
            log_warning(
                "order_status_rejected",
                order_id=status.order_id,
                client_order_id=intent.client_order_id,
                status=status.status,
                source=status.source,
            )
            return False
        reason = status.reason or "execution_update"
        fill_price = status.fill_price
        fee_usd = status.fee_usd
        filled_size = status.filled_size
        if _is_filled(status.status):
            reconciled = await _reconcile_execution_from_exchange(
                exchange_client=self.exchange_client,
                symbol=intent.symbol,
                order_id=status.order_id,
                client_order_id=intent.client_order_id,
                timestamp=status.timestamp,
            )
            if reconciled:
                fill_price = reconciled.get("avg_price") or fill_price
                fee_usd = reconciled.get("total_fees_usd") if reconciled.get("total_fees_usd") is not None else fee_usd
                filled_size = reconciled.get("total_qty") or filled_size
        await self._record_order(
            symbol=intent.symbol,
            side=intent.side,
            size=filled_size or intent.size,
            status=status.status,
            order_id=status.order_id,
            client_order_id=intent.client_order_id,
            reason=reason,
            fill_price=fill_price,
            fee_usd=fee_usd,
            filled_size=filled_size,
            remaining_size=status.remaining_size,
            timestamp=status.timestamp,
            source=status.source,
            event_type="execution_update",
            reference_price=intent.entry_price or status.reference_price,
        )
        # SYNC: Update order_intents to match order_states status
        if self.order_store and hasattr(self.order_store, "record_intent"):
            await self.order_store.record_intent(
                intent_id=str(uuid.uuid4()),  # Use new intent_id for tracking
                symbol=intent.symbol,
                side=intent.side,
                size=float(intent.size or 0.0),
                client_order_id=intent.client_order_id,
                status=status.status,  # Sync status from order_states
                order_id=status.order_id,
                last_error=status.reason if status.status in ("failed", "rejected", "canceled") else None,
            )
        if _is_filled(status.status):
            entry_price = fill_price or intent.entry_price or status.reference_price
            entry_timestamp = status.timestamp or time.time()
            position = await _find_open_position(self.position_manager, intent.symbol)
            if position and _is_exit_for_position(intent.side, position.side):
                exit_timestamp = status.timestamp or time.time()
                size_for_pnl = filled_size or intent.size or position.size
                exit_price = fill_price
                exit_fee_usd = fee_usd
                reconciled = await _reconcile_close_from_exchange(
                    exchange_client=self.exchange_client,
                    symbol=intent.symbol,
                    order_id=status.order_id,
                    client_order_id=intent.client_order_id,
                    exit_timestamp=exit_timestamp,
                )
                if reconciled:
                    exit_price = reconciled.get("avg_price") or exit_price
                    exit_fee_usd = reconciled.get("total_fees_usd") if reconciled.get("total_fees_usd") is not None else exit_fee_usd
                    size_for_pnl = reconciled.get("total_qty") or size_for_pnl
                    exit_timestamp = reconciled.get("exit_timestamp") or exit_timestamp
                await self._record_order(
                    symbol=intent.symbol,
                    side=intent.side,
                    size=size_for_pnl,
                    status=status.status,
                    order_id=status.order_id,
                    client_order_id=intent.client_order_id,
                    reason="exchange_reconcile",
                    fill_price=exit_price,
                    fee_usd=exit_fee_usd,
                    filled_size=size_for_pnl,
                    remaining_size=status.remaining_size,
                    timestamp=exit_timestamp,
                    source="exchange_reconcile",
                    event_type="exchange_reconcile",
                    reference_price=position.reference_price or status.reference_price,
                )
                gross_pnl, net_pnl, net_pnl_pct, total_fees = _compute_pnl_breakdown(
                    position.entry_price,
                    exit_price,
                    size_for_pnl,
                    position.side,
                    entry_fee_usd=position.entry_fee_usd,
                    exit_fee_usd=exit_fee_usd,
                )
                profile_id = position.profile_id or intent.profile_id
                self._record_profile_feedback(profile_id, intent.symbol, net_pnl)
                hold_time_sec = (exit_timestamp - position.opened_at) if position.opened_at else None
                entry_coid = str(position.entry_client_order_id or "")
                entry_post_only = ":m" in entry_coid
                await self.position_manager.finalize_close(intent.symbol)
                await self._cleanup_protective_orders(intent.symbol)
                await self._emit_order_event(
                    symbol=intent.symbol,
                    side=intent.side,
                    size=size_for_pnl or intent.size,
                    status=status.status,
                    reason=reason,
                    reference_price=position.reference_price or status.reference_price,
                    fill_price=exit_price,
                    fee_usd=exit_fee_usd,
                    entry_fee_usd=position.entry_fee_usd,
                    total_fees_usd=total_fees,
                    order_id=status.order_id,
                    client_order_id=intent.client_order_id,
                    position_effect="close",
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    realized_pnl=net_pnl,
                    realized_pnl_pct=net_pnl_pct,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    filled_size=size_for_pnl,
                    entry_timestamp=position.opened_at,
                    exit_timestamp=exit_timestamp,
                    hold_time_sec=hold_time_sec,
                    entry_client_order_id=position.entry_client_order_id,
                    entry_order_type="limit" if entry_post_only else "market",
                    entry_post_only=entry_post_only,
                    order_type=intent.order_type,
                    post_only=intent.post_only,
                    prediction_confidence=position.prediction_confidence,
                    prediction_direction=position.prediction_direction,
                    prediction_source=position.prediction_source,
                    entry_p_hat=position.entry_p_hat,
                    entry_p_hat_source=position.entry_p_hat_source,
                    model_side=position.model_side,
                    p_up=position.p_up,
                    p_down=position.p_down,
                    p_flat=position.p_flat,
                )
                # Emit position lifecycle event - single source of truth for PnL
                await self._emit_position_closed(
                    symbol=intent.symbol,
                    side=position.side,
                    size=size_for_pnl or intent.size,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    realized_pnl=net_pnl,
                    realized_pnl_pct=net_pnl_pct,
                    fee_usd=exit_fee_usd,
                    entry_client_order_id=position.entry_client_order_id,
                    entry_decision_id=position.entry_decision_id,
                    execution_policy=position.execution_policy,
                    execution_cohort=position.execution_cohort,
                    execution_experiment_id=position.execution_experiment_id,
                    entry_fee_usd=position.entry_fee_usd,
                    total_fees_usd=total_fees,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    hold_time_sec=hold_time_sec,
                    close_order_id=status.order_id,
                    closed_by="trading_signal",
                    strategy_id=intent.strategy_id,
                    profile_id=profile_id,
                    entry_timestamp=position.opened_at,
                    prediction_confidence=position.prediction_confidence,
                    prediction_direction=position.prediction_direction,
                    prediction_source=position.prediction_source,
                    entry_p_hat=position.entry_p_hat,
                    entry_p_hat_source=position.entry_p_hat_source,
                    mfe_pct=position.mfe_pct,
                    mae_pct=position.mae_pct,
                    entry_reference_price=position.reference_price,
                    exit_reference_price=position.reference_price or status.reference_price,
                )
                await self._emit_positions_snapshot()
                return True
            # Guard: do not create a new position from an exit/close fill.
            # This prevents phantom positions when the order-update WS
            # processes a close fill after the position guard already
            # finalized the position (race condition).
            norm_side = (intent.side or "").lower()
            market_type = getattr(self.exchange_client, "market_type", "perp")
            is_exit_fill = (
                intent.reduce_only
                or intent.is_exit_signal
                or (market_type == "spot" and norm_side in {"sell", "short"})
            )
            if is_exit_fill:
                log_warning(
                    "record_order_status_orphan_exit_fill",
                    symbol=intent.symbol,
                    side=intent.side,
                    size=filled_size or intent.size,
                    reason="exit_fill_no_position_to_close",
                )
                await self._cleanup_protective_orders(intent.symbol)
                await self._emit_positions_snapshot()
                return True
            await self.position_manager.upsert_position(
                PositionSnapshot(
                    symbol=intent.symbol,
                    side=intent.side,
                    size=filled_size or intent.size,
                    entry_client_order_id=_logical_client_order_id(intent),
                    entry_decision_id=intent.decision_id,
                    execution_policy=intent.execution_policy,
                    execution_cohort=intent.execution_cohort,
                    execution_experiment_id=intent.execution_experiment_id,
                    reference_price=status.reference_price,
                    entry_price=entry_price,
                    entry_fee_usd=status.fee_usd,
                    stop_loss=intent.stop_loss,
                    take_profit=intent.take_profit,
                    opened_at=entry_timestamp,
                    prediction_confidence=intent.prediction_confidence,
                    prediction_direction=intent.prediction_direction,
                    prediction_source=intent.prediction_source,
                    entry_p_hat=intent.entry_p_hat,
                    entry_p_hat_source=intent.entry_p_hat_source,
                    strategy_id=intent.strategy_id,
                    profile_id=intent.profile_id,
                    # Signal strength telemetry
                    entry_signal_strength=intent.signal_strength,
                    entry_signal_confidence=intent.signal_confidence,
                    entry_confirmation_count=intent.confirmation_count,
                    # Time budget parameters
                    expected_horizon_sec=intent.expected_horizon_sec,
                    time_to_work_sec=intent.time_to_work_sec,
                    max_hold_sec=intent.max_hold_sec,
                    mfe_min_bps=intent.mfe_min_bps,
                    # Prediction context (Bug 8 fix)
                    model_side=intent.model_side,
                    p_up=intent.p_up,
                    p_down=intent.p_down,
                    p_flat=intent.p_flat,
                )
            )
            await self._emit_order_event(
                symbol=intent.symbol,
                side=intent.side,
                size=intent.size,
                status=status.status,
                reason=reason,
                reference_price=status.reference_price,
                fill_price=status.fill_price,
                fee_usd=status.fee_usd,
                entry_fee_usd=status.fee_usd,
                total_fees_usd=status.fee_usd,
                order_id=status.order_id,
                client_order_id=intent.client_order_id,
                position_effect="open",
                entry_price=entry_price,
                entry_timestamp=entry_timestamp,
                filled_size=status.filled_size,
                mid_at_send=intent.mid_at_send,
                expected_price_at_send=intent.expected_price_at_send,
                send_ts=intent.send_ts,
                ack_ts=intent.ack_ts,
                first_fill_ts=intent.first_fill_ts,
                final_fill_ts=intent.final_fill_ts,
                post_only_reject_count=intent.post_only_reject_count,
                cancel_after_timeout_count=intent.cancel_after_timeout_count,
                order_type=intent.order_type,
                post_only=intent.post_only,
            )
            await self._emit_positions_snapshot()
            return True
        if _is_partial(status.status):
            await self._emit_order_event(
                symbol=intent.symbol,
                side=intent.side,
                size=intent.size,
                status=status.status,
                reason=status.reason or "execution_partial",
                reference_price=status.reference_price,
                fill_price=status.fill_price,
                fee_usd=status.fee_usd,
                order_id=status.order_id,
                client_order_id=intent.client_order_id,
            )
            return False
        if _is_rejected(status.status):
            await self._emit_order_event(
                symbol=intent.symbol,
                side=intent.side,
                size=intent.size,
                status=status.status,
                reason=reason,
                reference_price=status.reference_price,
                fill_price=status.fill_price,
                fee_usd=status.fee_usd,
                order_id=status.order_id,
                client_order_id=intent.client_order_id,
                mid_at_send=intent.mid_at_send,
                expected_price_at_send=intent.expected_price_at_send,
                send_ts=intent.send_ts,
                ack_ts=intent.ack_ts,
                post_only_reject_count=intent.post_only_reject_count,
                cancel_after_timeout_count=intent.cancel_after_timeout_count,
                order_type=intent.order_type,
                post_only=intent.post_only,
            )
            return False
        await self._emit_order_event(
            symbol=intent.symbol,
            side=intent.side,
            size=intent.size,
            status=status.status,
            reason=reason,
            reference_price=status.reference_price,
            fill_price=status.fill_price,
            fee_usd=status.fee_usd,
            order_id=status.order_id,
            client_order_id=intent.client_order_id,
            mid_at_send=intent.mid_at_send,
            expected_price_at_send=intent.expected_price_at_send,
            send_ts=intent.send_ts,
            ack_ts=intent.ack_ts,
            post_only_reject_count=intent.post_only_reject_count,
            cancel_after_timeout_count=intent.cancel_after_timeout_count,
            order_type=intent.order_type,
            post_only=intent.post_only,
        )
        return True

    async def _cleanup_protective_orders(self, symbol: str) -> None:
        if not self.order_store or not hasattr(self.order_store, "list_orders"):
            return
        try:
            records = self.order_store.list_orders()
        except Exception:
            return
        cleanup_ts = time.time()
        for record in records:
            client_order_id = str(record.client_order_id or "")
            if not client_order_id:
                continue
            lowered = client_order_id.lower()
            if not (
                lowered.endswith(":sl")
                or lowered.endswith(":tp")
                or lowered.endswith(":tpl")
                or lowered.endswith(":tpsl")
            ):
                continue
            if normalize_order_status(record.status) not in {"open", "submitted", "pending"}:
                continue
            if normalize_exchange_symbol(None, record.symbol) != normalize_exchange_symbol(None, symbol):
                continue
            exchange_status: Optional[OrderStatus] = None
            try:
                exchange_status = await self.exchange_client.cancel_order(
                    record.order_id,
                    record.client_order_id,
                    record.symbol,
                )
            except Exception as exc:
                log_warning(
                    "protective_order_cancel_failed",
                    symbol=record.symbol,
                    order_id=record.order_id,
                    client_order_id=record.client_order_id,
                    error=str(exc),
                )
            await self.order_store.record(
                symbol=record.symbol,
                side=record.side,
                size=record.size,
                status=(exchange_status.status if exchange_status else "canceled"),
                order_id=(exchange_status.order_id if exchange_status and exchange_status.order_id else record.order_id),
                client_order_id=record.client_order_id,
                reason=(exchange_status.reason if exchange_status and exchange_status.reason else "position_closed_protection_cleanup"),
                remaining_size=0.0,
                timestamp=cleanup_ts,
                source=(exchange_status.source if exchange_status and exchange_status.source else "local"),
                event_type="protection_cleanup",
                persist=True,
            )
            if hasattr(self.order_store, "record_intent"):
                terminal_status = exchange_status.status if exchange_status else "canceled"
                terminal_reason = (
                    exchange_status.reason
                    if exchange_status and exchange_status.reason
                    else "position_closed_protection_cleanup"
                )
                await self.order_store.record_intent(
                    intent_id=str(uuid.uuid4()),
                    symbol=record.symbol,
                    side=record.side,
                    size=float(record.size or 0.0),
                    client_order_id=record.client_order_id,
                    status=terminal_status,
                    order_id=(
                        exchange_status.order_id
                        if exchange_status and exchange_status.order_id
                        else record.order_id
                    ),
                    last_error=terminal_reason,
                )

    async def poll_order_status(self, order_id: str, symbol: str) -> Optional[OrderStatus]:
        return await self.exchange_client.fetch_order_status(order_id, symbol)

    async def poll_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Optional[OrderStatus]:
        if not hasattr(self.exchange_client, "fetch_order_status_by_client_id"):
            return None
        return await self.exchange_client.fetch_order_status_by_client_id(client_order_id, symbol)

    def _record_profile_feedback(self, profile_id: Optional[str], symbol: Optional[str], pnl: Optional[float]) -> None:
        if not profile_id or not symbol or pnl is None:
            return
        if not self.profile_feedback:
            return
        try:
            self.profile_feedback(profile_id, symbol, pnl)
        except Exception as exc:
            log_warning(
                "profile_feedback_failed",
                profile_id=profile_id,
                symbol=symbol,
                error=str(exc),
            )

    async def apply_risk_override(
        self,
        overrides: Dict[str, float],
        ttl_seconds: int,
        scope: Optional[Dict[str, str]] = None,
    ) -> RiskOverrideResult:
        if not self.risk_manager:
            return RiskOverrideResult(status="rejected", message="risk_manager_unavailable")
        success = await self.risk_manager.apply_overrides(overrides, ttl_seconds, scope=scope)
        if not success:
            return RiskOverrideResult(status="failed", message="risk_override_failed")
        return RiskOverrideResult(status="executed", message="risk_override_applied")

    async def reload_config(self) -> ReloadResult:
        # Wire to config loader if available; return accepted for now.
        return ReloadResult(status="accepted", message="reload_enqueued")

    async def execute_failover(self) -> FailoverResult:
        if not self.exchange_router:
            return FailoverResult(status="rejected", message="exchange_router_unavailable")
        if self.primary_exchange and self.secondary_exchange and hasattr(self.exchange_router, "state"):
            try:
                self.exchange_router.state.primary_exchange = self.primary_exchange
                self.exchange_router.state.secondary_exchange = self.secondary_exchange
            except Exception:
                pass
        success = await self.exchange_router.switch_to_secondary()
        if not success:
            return FailoverResult(status="failed", message="failover_failed")
        if self.reconciler:
            await self.reconciler.reconcile()
        return FailoverResult(status="executed", message="failover_complete")

    async def execute_recovery(self) -> FailoverResult:
        if not self.exchange_router:
            return FailoverResult(status="rejected", message="exchange_router_unavailable")
        if self.primary_exchange and hasattr(self.exchange_router, "state"):
            try:
                self.exchange_router.state.primary_exchange = self.primary_exchange
            except Exception:
                pass
        success = await self.exchange_router.switch_to_primary()
        if not success:
            return FailoverResult(status="failed", message="recovery_failed")
        if self.reconciler:
            await self.reconciler.reconcile()
        return FailoverResult(status="executed", message="recovery_complete")

    async def cancel_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
    ) -> OrderActionResult:
        if not symbol:
            return OrderActionResult(status="rejected", message="symbol_required")
        status = await self.exchange_client.cancel_order(order_id, client_order_id, symbol)
        if self.order_store:
            await self.order_store.record(
                symbol=symbol,
                side="unknown",
                size=0.0,
                status=status.status,
                order_id=order_id or status.order_id,
                client_order_id=client_order_id,
                reason=status.reason or "manual_cancel",
                fill_price=status.fill_price,
                fee_usd=status.fee_usd,
                filled_size=status.filled_size,
                remaining_size=status.remaining_size,
                timestamp=status.timestamp,
                source=status.source,
                raw_exchange_status=status.status,
                persist=True,
            )
        return OrderActionResult(status=status.status, message="cancel_submitted")

    async def replace_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
        price: Optional[float],
        size: Optional[float],
    ) -> OrderActionResult:
        if not symbol:
            return OrderActionResult(status="rejected", message="symbol_required")
        status = await self.exchange_client.replace_order(
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            price=price,
            size=size,
        )
        if self.order_store:
            await self.order_store.record(
                symbol=symbol,
                side="unknown",
                size=size or 0.0,
                status=status.status,
                order_id=order_id or status.order_id,
                client_order_id=client_order_id,
                reason=status.reason or "manual_replace",
                fill_price=status.fill_price,
                fee_usd=status.fee_usd,
                filled_size=status.filled_size,
                remaining_size=status.remaining_size,
                timestamp=status.timestamp,
                source=status.source,
                raw_exchange_status=status.status,
                persist=True,
            )
        return OrderActionResult(status=status.status, message="replace_submitted")

    async def _emit_order_event(
        self,
        symbol: str,
        side: str,
        size: float,
        status: str,
        reason: str,
        reference_price: Optional[float],
        fill_price: Optional[float],
        fee_usd: Optional[float],
        entry_fee_usd: Optional[float] = None,
        total_fees_usd: Optional[float] = None,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        position_effect: Optional[str] = None,
        entry_price: Optional[float] = None,
        exit_price: Optional[float] = None,
        realized_pnl: Optional[float] = None,
        realized_pnl_pct: Optional[float] = None,
        gross_pnl: Optional[float] = None,
        net_pnl: Optional[float] = None,
        filled_size: Optional[float] = None,
        entry_timestamp: Optional[float] = None,
        exit_timestamp: Optional[float] = None,
        hold_time_sec: Optional[float] = None,
        # Signal strength telemetry (for entries)
        signal_strength: Optional[str] = None,
        signal_confidence: Optional[float] = None,
        confirmation_count: Optional[int] = None,
        # MFE/MAE telemetry (for exits)
        mfe_pct: Optional[float] = None,
        mae_pct: Optional[float] = None,
        # Entry execution telemetry
        mid_at_send: Optional[float] = None,
        expected_price_at_send: Optional[float] = None,
        send_ts: Optional[float] = None,
        ack_ts: Optional[float] = None,
        first_fill_ts: Optional[float] = None,
        final_fill_ts: Optional[float] = None,
        post_only_reject_count: Optional[int] = None,
        cancel_after_timeout_count: Optional[int] = None,
        order_type: Optional[str] = None,
        post_only: Optional[bool] = None,
        entry_client_order_id: Optional[str] = None,
        entry_order_type: Optional[str] = None,
        entry_post_only: Optional[bool] = None,
        execution_policy: Optional[str] = None,
        execution_cohort: Optional[str] = None,
        execution_experiment_id: Optional[str] = None,
        prediction_confidence: Optional[float] = None,
        prediction_direction: Optional[str] = None,
        prediction_source: Optional[str] = None,
        entry_p_hat: Optional[float] = None,
        entry_p_hat_source: Optional[str] = None,
        model_side: Optional[str] = None,
        p_up: Optional[float] = None,
        p_down: Optional[float] = None,
        p_flat: Optional[float] = None,
    ) -> None:
        if not self.telemetry or not self.telemetry_context:
            return
        slippage_bps = None
        if reference_price and fill_price and reference_price > 0:
            slippage_bps = abs((fill_price - reference_price) / reference_price) * 10000.0
        payload = order_payload(
            side=side,
            size=size,
            status=status,
            reason=reason,
            slippage_bps=slippage_bps,
            fee_usd=fee_usd,
            entry_fee_usd=entry_fee_usd,
            total_fees_usd=total_fees_usd,
            fill_price=fill_price,
            order_id=order_id,
            client_order_id=client_order_id,
            position_effect=position_effect,
            entry_price=entry_price,
            exit_price=exit_price,
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            filled_size=filled_size,
            entry_timestamp=entry_timestamp,
            exit_timestamp=exit_timestamp,
            hold_time_sec=hold_time_sec,
        )
        mfe_pct_value = _coerce_float(mfe_pct)
        mae_pct_value = _coerce_float(mae_pct)
        if position_effect == "close":
            # Always emit normalized excursion fields for close events.
            if mfe_pct_value is None:
                mfe_pct_value = 0.0
            if mae_pct_value is None:
                mae_pct_value = 0.0
            payload["mfe_pct"] = float(mfe_pct_value)
            payload["mae_pct"] = float(mae_pct_value)
            payload["mae_abs_pct"] = float(abs(mae_pct_value))
            payload["mfe_bps"] = float(mfe_pct_value * 100.0)
            payload["mae_bps"] = float(mae_pct_value * 100.0)
        # Add signal strength telemetry for entries
        if signal_strength is not None:
            payload["signal_strength"] = signal_strength
        if signal_confidence is not None:
            payload["signal_confidence"] = signal_confidence
        if confirmation_count is not None:
            payload["confirmation_count"] = confirmation_count
        # Preserve explicit excursion telemetry on non-close payloads when provided.
        if position_effect != "close":
            if mfe_pct is not None:
                payload["mfe_pct"] = mfe_pct
            if mae_pct is not None:
                payload["mae_pct"] = mae_pct
        if mid_at_send is not None:
            payload["mid_at_send"] = mid_at_send
        if expected_price_at_send is not None:
            payload["expected_price_at_send"] = expected_price_at_send
        if send_ts is not None:
            payload["send_ts"] = send_ts
        if ack_ts is not None:
            payload["ack_ts"] = ack_ts
        if first_fill_ts is not None:
            payload["first_fill_ts"] = first_fill_ts
        if final_fill_ts is not None:
            payload["final_fill_ts"] = final_fill_ts
        if post_only_reject_count is not None:
            payload["post_only_reject_count"] = int(post_only_reject_count)
        if cancel_after_timeout_count is not None:
            payload["cancel_after_timeout_count"] = int(cancel_after_timeout_count)
        if order_type is not None:
            payload["order_type"] = order_type
        if post_only is not None:
            payload["post_only"] = bool(post_only)
        if entry_client_order_id is not None:
            payload["entry_client_order_id"] = entry_client_order_id
        if entry_order_type is not None:
            payload["entry_order_type"] = entry_order_type
        if entry_post_only is not None:
            payload["entry_post_only"] = bool(entry_post_only)
        inferred_policy = execution_policy
        if inferred_policy is None:
            if (
                bool(entry_post_only)
                or str(entry_order_type or "").lower() == "limit"
                or (entry_client_order_id and ":m" in str(entry_client_order_id))
                or (position_effect == "open" and str(order_type or "").lower() == "limit" and bool(post_only))
            ):
                inferred_policy = "maker_first"
            elif position_effect in {"open", "close"}:
                inferred_policy = "market"
        if inferred_policy is not None:
            payload["execution_policy"] = inferred_policy
            payload["execution_cohort"] = execution_cohort or (
                "maker_first" if inferred_policy == "maker_first" else "baseline_market"
            )
        elif execution_cohort is not None:
            payload["execution_cohort"] = execution_cohort
        experiment_id = execution_experiment_id
        if experiment_id is None:
            env_experiment = (os.getenv("EXECUTION_EXPERIMENT_ID") or "").strip()
            experiment_id = env_experiment or None
        if experiment_id is not None:
            payload["execution_experiment_id"] = experiment_id
        if position_effect == "close":
            size_basis = _coerce_float(filled_size) or _coerce_float(size)
            entry_fee_bps = _compute_fee_bps(entry_fee_usd, entry_price, size_basis)
            exit_fee_bps = _compute_fee_bps(fee_usd, exit_price or fill_price, size_basis)
            total_cost_bps = _sum_cost_bps(entry_fee_bps, exit_fee_bps, None, slippage_bps)
            payload["entry_fee_bps"] = entry_fee_bps
            payload["exit_fee_bps"] = exit_fee_bps
            payload["total_cost_bps"] = total_cost_bps
        if prediction_confidence is not None:
            payload["prediction_confidence"] = prediction_confidence
        if prediction_direction is not None:
            payload["prediction_direction"] = prediction_direction
        if prediction_source is not None:
            payload["prediction_source"] = prediction_source
        if entry_p_hat is not None:
            payload["entry_p_hat"] = entry_p_hat
        if entry_p_hat_source is not None:
            payload["entry_p_hat_source"] = entry_p_hat_source
        if model_side is not None:
            payload["model_side"] = model_side
        if p_up is not None:
            payload["p_up"] = p_up
        if p_down is not None:
            payload["p_down"] = p_down
        if p_flat is not None:
            payload["p_flat"] = p_flat
        await self.telemetry.publish_order(
            ctx=self.telemetry_context,
            symbol=symbol,
            payload=payload,
        )

    async def _record_order(
        self,
        symbol: str,
        side: str,
        size: float,
        status: str,
        order_id: Optional[str],
        client_order_id: Optional[str],
        reason: Optional[str],
        fill_price: Optional[float],
        fee_usd: Optional[float],
        filled_size: Optional[float] = None,
        remaining_size: Optional[float] = None,
        timestamp: Optional[float] = None,
        source: Optional[str] = None,
        event_type: Optional[str] = None,
        reference_price: Optional[float] = None,
        submitted_at_override: Optional[float] = None,
    ) -> None:
        if not self.order_store:
            return
        normalized_status = normalize_order_status(status)
        update_ts = timestamp or time.time()
        exchange = self.telemetry_context.exchange if self.telemetry_context else None
        submitted_at = None
        accepted_at = None
        open_at = None
        filled_at = None
        iso_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(update_ts))
        
        # Always set submitted_at for new orders (local source) regardless of current status
        # This captures when we actually submitted the order
        if (source or "local") == "local" and event_type in {"execution_intent", None}:
            if submitted_at_override:
                submitted_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(submitted_at_override))
            else:
                submitted_at = iso_ts
        
        if normalized_status == "pending":
            if (source or "local") != "local":
                accepted_at = iso_ts
        if normalized_status in {"open", "partially_filled"}:
            open_at = iso_ts
        if normalized_status == "filled":
            filled_at = iso_ts
        
        # Calculate slippage when order is filled
        slippage_bps = None
        if normalized_status == "filled" and fill_price and reference_price and reference_price > 0:
            slippage_bps = abs((fill_price - reference_price) / reference_price) * 10000.0
        
        await self.order_store.record(
            symbol=symbol,
            side=side,
            size=size,
            status=status,
            order_id=order_id,
            client_order_id=client_order_id,
            reason=reason,
            fill_price=fill_price,
            fee_usd=fee_usd,
            filled_size=filled_size,
            remaining_size=remaining_size,
            timestamp=timestamp,
            source=source,
            exchange=exchange,
            submitted_at=submitted_at,
            accepted_at=accepted_at,
            open_at=open_at,
            filled_at=filled_at,
            event_type=event_type,
            slippage_bps=slippage_bps,
        )

    async def _emit_position_closed(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: Optional[float],
        exit_price: Optional[float],
        realized_pnl: Optional[float],
        realized_pnl_pct: Optional[float],
        fee_usd: Optional[float],
        entry_client_order_id: Optional[str] = None,
        entry_decision_id: Optional[str] = None,
        execution_policy: Optional[str] = None,
        execution_cohort: Optional[str] = None,
        execution_experiment_id: Optional[str] = None,
        entry_fee_usd: Optional[float] = None,
        total_fees_usd: Optional[float] = None,
        gross_pnl: Optional[float] = None,
        net_pnl: Optional[float] = None,
        hold_time_sec: Optional[float] = None,
        entry_timestamp: Optional[float] = None,
        close_order_id: Optional[str] = None,
        closed_by: Optional[str] = None,
        close_reason: Optional[str] = None,  # Alias for closed_by
        order_id: Optional[str] = None,  # Alias for close_order_id
        strategy_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        # MFE/MAE telemetry
        mfe_pct: Optional[float] = None,
        mae_pct: Optional[float] = None,
        # Signal strength telemetry
        signal_strength: Optional[str] = None,
        signal_confidence: Optional[float] = None,
        # Prediction telemetry (at entry time)
        prediction_confidence: Optional[float] = None,
        prediction_direction: Optional[str] = None,
        prediction_source: Optional[str] = None,
        entry_p_hat: Optional[float] = None,
        entry_p_hat_source: Optional[str] = None,
        entry_reference_price: Optional[float] = None,
        exit_reference_price: Optional[float] = None,
    ) -> None:
        """Emit position closed event - single source of truth for realized PnL."""
        # Handle parameter aliases
        actual_order_id = close_order_id or order_id
        actual_closed_by = closed_by or close_reason or "unknown"

        # Skip emitting "closed" if we don't have realized PnL or exit price.
        # This prevents null PnL closes from polluting win-rate and PnL metrics.
        if exit_price is None or realized_pnl is None:
            log_warning(
                "position_closed_missing_fill",
                symbol=symbol,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                closed_by=actual_closed_by,
                order_id=actual_order_id,
            )
            return
        
        entry_slippage_bps = _compute_slippage_bps(entry_reference_price, entry_price)
        exit_slippage_bps = _compute_slippage_bps(exit_reference_price, exit_price)
        realized_slippage_bps = None
        if entry_slippage_bps is not None and exit_slippage_bps is not None:
            realized_slippage_bps = entry_slippage_bps + exit_slippage_bps
        elif entry_slippage_bps is not None:
            realized_slippage_bps = entry_slippage_bps
        elif exit_slippage_bps is not None:
            realized_slippage_bps = exit_slippage_bps
        entry_fee_bps = _compute_fee_bps(entry_fee_usd, entry_price, size)
        exit_fee_bps = _compute_fee_bps(fee_usd, exit_price, size)
        spread_cost_bps = _compute_spread_cost_bps(
            side=side,
            entry_reference_price=entry_reference_price,
            entry_fill_price=entry_price,
            exit_reference_price=exit_reference_price,
            exit_fill_price=exit_price,
        )
        total_cost_bps = _sum_cost_bps(
            entry_fee_bps,
            exit_fee_bps,
            entry_slippage_bps,
            exit_slippage_bps,
        )
        if total_cost_bps is None:
            total_cost_bps = 0.0

        payload = {
            "side": side,
            "size": size,
            "status": "closed",
            "entry_price": entry_price,
            "exit_price": exit_price,
            "exit_timestamp": time.time(),
            "entry_timestamp": entry_timestamp,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "fee_usd": fee_usd,
            "entry_fee_usd": entry_fee_usd,
            "total_fees_usd": total_fees_usd,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "hold_time_sec": hold_time_sec,
            "close_order_id": actual_order_id,
            "closed_by": actual_closed_by,
            "strategy_id": strategy_id,
            "profile_id": profile_id,
            "execution_policy": execution_policy,
            "execution_cohort": execution_cohort,
            "execution_experiment_id": execution_experiment_id,
            "entry_reference_price": entry_reference_price,
            "exit_reference_price": exit_reference_price,
            "entry_slippage_bps": entry_slippage_bps,
            "exit_slippage_bps": exit_slippage_bps,
            "realized_slippage_bps": realized_slippage_bps,
            "entry_fee_bps": entry_fee_bps,
            "exit_fee_bps": exit_fee_bps,
            "spread_cost_bps": spread_cost_bps,
            "total_cost_bps": total_cost_bps,
        }
        if self.order_store and hasattr(self.order_store, "record_trade_cost"):
            try:
                notional = _coerce_float(size) * (_coerce_float(entry_price) or _coerce_float(exit_price) or 0.0)
                notional = abs(notional or 0.0)
                fees_total = _coerce_float(total_fees_usd)
                if fees_total is None:
                    fees_total = (_coerce_float(entry_fee_usd) or 0.0) + (_coerce_float(fee_usd) or 0.0)
                total_cost_usd = fees_total
                if total_cost_bps is not None and notional > 0:
                    # Preserve signed economics: maker rebates (negative fees) should reduce total cost.
                    total_cost_usd = (float(total_cost_bps) / 10000.0) * notional
                await self.order_store.record_trade_cost(
                    trade_id=str(actual_order_id or entry_client_order_id or f"{symbol}:{time.time()}"),
                    symbol=symbol,
                    profile_id=profile_id,
                    execution_price=float(_coerce_float(exit_price) or 0.0),
                    decision_mid_price=float(
                        _coerce_float(exit_reference_price)
                        or _coerce_float(entry_reference_price)
                        or _coerce_float(entry_price)
                        or _coerce_float(exit_price)
                        or 0.0
                    ),
                    slippage_bps=float(_coerce_float(realized_slippage_bps) or 0.0),
                    fees=float(fees_total),
                    funding_cost=0.0,
                    total_cost=float(total_cost_usd),
                    order_size=_coerce_float(size),
                    side=side,
                    timestamp=_coerce_iso_timestamp(time.time()),
                    entry_fee_usd=_coerce_float(entry_fee_usd),
                    exit_fee_usd=_coerce_float(fee_usd),
                    entry_fee_bps=_coerce_float(entry_fee_bps),
                    exit_fee_bps=_coerce_float(exit_fee_bps),
                    entry_slippage_bps=_coerce_float(entry_slippage_bps),
                    exit_slippage_bps=_coerce_float(exit_slippage_bps),
                    spread_cost_bps=_coerce_float(spread_cost_bps),
                    adverse_selection_bps=None,
                    total_cost_bps=_coerce_float(total_cost_bps),
                )
            except Exception as exc:
                log_warning("trade_cost_persist_failed", symbol=symbol, error=str(exc))
        # Stable attribution (lets us join without timestamp heuristics)
        if entry_client_order_id is not None:
            payload["entry_client_order_id"] = entry_client_order_id
        if entry_decision_id is not None:
            payload["entry_decision_id"] = entry_decision_id
        # Always emit normalized excursion fields for closed lifecycle events.
        mfe_pct_value = _coerce_float(mfe_pct)
        mae_pct_value = _coerce_float(mae_pct)
        if mfe_pct_value is None:
            mfe_pct_value = 0.0
        if mae_pct_value is None:
            mae_pct_value = 0.0
        payload["mfe_pct"] = float(mfe_pct_value)
        payload["mae_pct"] = float(mae_pct_value)
        payload["mae_abs_pct"] = float(abs(mae_pct_value))
        payload["mfe_bps"] = float(mfe_pct_value * 100.0)
        payload["mae_bps"] = float(mae_pct_value * 100.0)
        # Add signal strength telemetry
        if signal_strength is not None:
            payload["signal_strength"] = signal_strength
        if signal_confidence is not None:
            payload["signal_confidence"] = signal_confidence
        if prediction_confidence is not None:
            payload["prediction_confidence"] = prediction_confidence
        if prediction_direction is not None:
            payload["prediction_direction"] = prediction_direction
        if prediction_source is not None:
            payload["prediction_source"] = prediction_source
        if entry_p_hat is not None:
            payload["entry_p_hat"] = entry_p_hat
        if entry_p_hat_source is not None:
            payload["entry_p_hat_source"] = entry_p_hat_source
        
        if self.telemetry and self.telemetry_context:
            await self.telemetry.publish_position_lifecycle(
                ctx=self.telemetry_context,
                symbol=symbol,
                event_type="closed",
                payload=payload,
            )

    async def _emit_position_opened(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: Optional[float],
        entry_timestamp: Optional[float],
        fee_usd: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
        order_id: Optional[str],
        client_order_id: Optional[str],
        decision_id: Optional[str],
        strategy_id: Optional[str],
        profile_id: Optional[str],
        execution_policy: Optional[str] = None,
        execution_cohort: Optional[str] = None,
        execution_experiment_id: Optional[str] = None,
        prediction_confidence: Optional[float] = None,
        prediction_direction: Optional[str] = None,
        prediction_source: Optional[str] = None,
        entry_p_hat: Optional[float] = None,
        entry_p_hat_source: Optional[str] = None,
        signal_strength: Optional[str] = None,
        signal_confidence: Optional[float] = None,
        confirmation_count: Optional[int] = None,
        entry_reference_price: Optional[float] = None,
    ) -> None:
        if not self.telemetry or not self.telemetry_context:
            return
        entry_slippage_bps = _compute_slippage_bps(entry_reference_price, entry_price)
        payload = {
            "side": side,
            "size": size,
            "status": "open",
            "entry_price": entry_price,
            "entry_timestamp": entry_timestamp,
            "fee_usd": fee_usd,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "order_id": order_id,
            "client_order_id": client_order_id,
            "decision_id": decision_id,
            "strategy_id": strategy_id,
            "profile_id": profile_id,
            "execution_policy": execution_policy,
            "execution_cohort": execution_cohort,
            "execution_experiment_id": execution_experiment_id,
            "entry_reference_price": entry_reference_price,
            "entry_slippage_bps": entry_slippage_bps,
        }
        if signal_strength is not None:
            payload["signal_strength"] = signal_strength
        if signal_confidence is not None:
            payload["signal_confidence"] = signal_confidence
        if confirmation_count is not None:
            payload["confirmation_count"] = confirmation_count
        if prediction_confidence is not None:
            payload["prediction_confidence"] = prediction_confidence
        if prediction_direction is not None:
            payload["prediction_direction"] = prediction_direction
        if prediction_source is not None:
            payload["prediction_source"] = prediction_source
        if entry_p_hat is not None:
            payload["entry_p_hat"] = entry_p_hat
        if entry_p_hat_source is not None:
            payload["entry_p_hat_source"] = entry_p_hat_source
        await self.telemetry.publish_position_lifecycle(
            ctx=self.telemetry_context,
            symbol=symbol,
            event_type="opened",
            payload=payload,
        )

    async def _emit_positions_snapshot(self) -> None:
        if not self.telemetry or not self.telemetry_context:
            return
        positions = await self.position_manager.list_open_positions()
        now = time.time()
        prediction_map = await self._resolve_prediction_confidence([pos.symbol for pos in positions])
        
        # Build position list with current market prices and unrealized PnL
        position_list = []
        for pos in positions:
            size = abs(float(pos.size or 0.0))
            # Get current market price from reference price cache
            current_price = None
            if self.reference_prices and hasattr(self.reference_prices, 'get_reference_price'):
                current_price = self.reference_prices.get_reference_price(pos.symbol)
            mark_price = current_price if current_price is not None else pos.reference_price
            
            # Calculate unrealized PnL
            unrealized_pnl = None
            if pos.entry_price and mark_price and size:
                if pos.side == "long":
                    unrealized_pnl = (mark_price - pos.entry_price) * size
                elif pos.side == "short":
                    unrealized_pnl = (pos.entry_price - mark_price) * size
            
            position_list.append({
                "symbol": pos.symbol,
                "side": pos.side,
                "size": size,
                "entry_client_order_id": pos.entry_client_order_id,
                "entry_decision_id": pos.entry_decision_id,
                "reference_price": mark_price,
                "entry_price": pos.entry_price,
                "entry_fee_usd": pos.entry_fee_usd,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "opened_at": pos.opened_at,
                "age_sec": (now - pos.opened_at) if pos.opened_at else None,
                "guard_status": "protected" if (pos.stop_loss or pos.take_profit) else "unprotected",
                "prediction_confidence": pos.prediction_confidence
                if pos.prediction_confidence is not None
                else prediction_map.get(pos.symbol),
                "prediction_direction": pos.prediction_direction,
                "prediction_source": pos.prediction_source,
                "entry_p_hat": pos.entry_p_hat,
                "entry_p_hat_source": pos.entry_p_hat_source,
                "strategy_id": pos.strategy_id,
                "profile_id": pos.profile_id,
                "expected_horizon_sec": pos.expected_horizon_sec,
                "time_to_work_sec": pos.time_to_work_sec,
                "max_hold_sec": pos.max_hold_sec,
                "mfe_min_bps": pos.mfe_min_bps,
                "unrealized_pnl": unrealized_pnl,
                "model_side": pos.model_side,
                "p_up": pos.p_up,
                "p_down": pos.p_down,
                "p_flat": pos.p_flat,
            })
        
        payload = {
            "positions": position_list,
            "count": len(positions),
        }
        await self.telemetry.publish_positions(self.telemetry_context, payload)

    async def _resolve_prediction_confidence(self, symbols: list[str]) -> dict[str, Optional[float]]:
        if not symbols:
            return {}
        if not self.snapshot_reader or not self.telemetry_context:
            return {}
        tenant_id = self.telemetry_context.tenant_id
        bot_id = self.telemetry_context.bot_id
        latest_key = f"quantgambit:{tenant_id}:{bot_id}:prediction:latest"
        history_key = f"quantgambit:{tenant_id}:{bot_id}:prediction:history"
        mapping: dict[str, Optional[float]] = {}
        latest = await self.snapshot_reader.read(latest_key)
        if latest:
            symbol = latest.get("symbol")
            confidence = _coerce_float(latest.get("confidence"))
            if symbol:
                mapping[symbol] = confidence
        missing = {symbol for symbol in symbols if symbol not in mapping}
        if missing:
            for symbol in list(missing):
                per_symbol_key = f"quantgambit:{tenant_id}:{bot_id}:prediction:{symbol}:latest"
                per_symbol = await self.snapshot_reader.read(per_symbol_key)
                if per_symbol:
                    mapping[symbol] = _coerce_float(per_symbol.get("confidence"))
                    missing.remove(symbol)
        if missing:
            history = await self.snapshot_reader.read_history(history_key, limit=200)
            for item in history:
                symbol = item.get("symbol")
                if not symbol or symbol not in missing:
                    continue
                mapping[symbol] = _coerce_float(item.get("confidence"))
                missing.remove(symbol)
                if not missing:
                    break
        return mapping


def _exit_side(side: str) -> str:
    normalized = (side or "").lower()
    if normalized in {"long", "buy"}:
        return "sell"
    if normalized in {"short", "sell"}:
        return "buy"
    return "sell"


def _is_filled(status: str) -> bool:
    return (status or "").lower() in {"filled", "complete", "done"}


def _is_partial(status: str) -> bool:
    return (status or "").lower() in {"partial", "partially_filled", "partiallyfilled"}


def _is_rejected(status: str) -> bool:
    return (status or "").lower() in {"rejected", "canceled", "cancelled", "expired", "failed"}


def _coerce_float(value: Optional[object]) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_iso_timestamp(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_slippage_bps(
    reference_price: Optional[float],
    fill_price: Optional[float],
) -> Optional[float]:
    ref = _coerce_float(reference_price)
    fill = _coerce_float(fill_price)
    if ref is None or fill is None or ref <= 0:
        return None
    return abs((fill - ref) / ref) * 10000.0


def _compute_fee_bps(
    fee_usd: Optional[float],
    price: Optional[float],
    size: Optional[float],
) -> Optional[float]:
    fee = _coerce_float(fee_usd)
    px = _coerce_float(price)
    qty = _coerce_float(size)
    if fee is None or px is None or qty is None or px <= 0 or qty <= 0:
        return None
    notional = px * qty
    if notional <= 0:
        return None
    # Keep sign: negative maker fees (rebates) produce negative fee bps.
    return fee / notional * 10000.0


def _compute_spread_cost_bps(
    side: Optional[str],
    entry_reference_price: Optional[float],
    entry_fill_price: Optional[float],
    exit_reference_price: Optional[float],
    exit_fill_price: Optional[float],
) -> Optional[float]:
    s = (side or "").lower()
    entry_ref = _coerce_float(entry_reference_price)
    entry_fill = _coerce_float(entry_fill_price)
    exit_ref = _coerce_float(exit_reference_price)
    exit_fill = _coerce_float(exit_fill_price)
    values: list[float] = []
    if entry_ref and entry_ref > 0 and entry_fill is not None:
        if s in {"short", "sell"}:
            values.append((entry_ref - entry_fill) / entry_ref * 10000.0)
        else:
            values.append((entry_fill - entry_ref) / entry_ref * 10000.0)
    if exit_ref and exit_ref > 0 and exit_fill is not None:
        if s in {"short", "sell"}:
            values.append((exit_fill - exit_ref) / exit_ref * 10000.0)
        else:
            values.append((exit_ref - exit_fill) / exit_ref * 10000.0)
    if not values:
        return None
    return sum(values)


def _sum_cost_bps(*values: Optional[float]) -> Optional[float]:
    present = [float(v) for v in values if v is not None]
    if not present:
        return None
    return sum(present)


def _compute_pnl_breakdown(
    entry_price: Optional[float],
    exit_price: Optional[float],
    size: Optional[float],
    side: Optional[str],
    entry_fee_usd: Optional[float] = None,
    exit_fee_usd: Optional[float] = None,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Return (gross_pnl, net_pnl, net_pnl_pct, total_fees_usd)."""
    entry_price = _coerce_float(entry_price)
    exit_price = _coerce_float(exit_price)
    size = _coerce_float(size)
    if entry_price is None or exit_price is None or size is None:
        return None, None, None, None
    if entry_price <= 0 or size <= 0:
        return None, None, None, None
    normalized = (side or "").lower()
    if normalized in {"short", "sell"}:
        gross_pnl = (entry_price - exit_price) * size
    else:
        gross_pnl = (exit_price - entry_price) * size
    total_fees = None
    if entry_fee_usd is not None or exit_fee_usd is not None:
        total_fees = (entry_fee_usd or 0.0) + (exit_fee_usd or 0.0)
    net_pnl = gross_pnl
    if total_fees is not None:
        net_pnl = gross_pnl - total_fees
    net_pnl_pct = (net_pnl / (entry_price * size)) * 100.0
    return gross_pnl, net_pnl, net_pnl_pct, total_fees


def _compute_realized_pnl(
    entry_price: Optional[float],
    exit_price: Optional[float],
    size: Optional[float],
    side: Optional[str],
    fee_usd: Optional[float],
    entry_fee_usd: Optional[float] = None,
) -> tuple[Optional[float], Optional[float]]:
    _, net_pnl, net_pnl_pct, _ = _compute_pnl_breakdown(
        entry_price,
        exit_price,
        size,
        side,
        entry_fee_usd=entry_fee_usd,
        exit_fee_usd=fee_usd,
    )
    return net_pnl, net_pnl_pct


def _coerce_epoch_sec(value: Optional[object]) -> Optional[float]:
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts > 1e12:
        return ts / 1000.0
    return ts


def _extract_trade_order_id(trade: dict) -> Optional[str]:
    info = trade.get("info") if isinstance(trade, dict) else None
    if isinstance(info, dict):
        return (
            info.get("orderId")
            or info.get("order_id")
            or info.get("orderID")
            or info.get("ordId")
        )
    return trade.get("order") or trade.get("orderId")


def _extract_trade_client_order_id(trade: dict) -> Optional[str]:
    info = trade.get("info") if isinstance(trade, dict) else None
    if isinstance(info, dict):
        return (
            info.get("orderLinkId")
            or info.get("clientOrderId")
            or info.get("client_order_id")
        )
    return trade.get("clientOrderId") or trade.get("client_order_id")


def _extract_trade_fee_usd(trade: dict) -> Optional[float]:
    fee = trade.get("fee") if isinstance(trade, dict) else None
    if isinstance(fee, dict):
        return _coerce_float(fee.get("cost") or fee.get("fee"))
    fee_val = trade.get("fee") or trade.get("commission")
    if fee_val is not None:
        return _coerce_float(fee_val)
    info = trade.get("info") if isinstance(trade, dict) else None
    if isinstance(info, dict):
        return _coerce_float(info.get("execFee") or info.get("fee") or info.get("commission"))
    return None


def _aggregate_execution_trades(
    trades: list,
    order_id: Optional[str],
    client_order_id: Optional[str],
) -> Optional[dict]:
    if not trades:
        return None
    matched: list[dict] = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        if order_id or client_order_id:
            trade_order_id = _extract_trade_order_id(trade)
            trade_client_id = _extract_trade_client_order_id(trade)
            if order_id and trade_order_id == order_id:
                matched.append(trade)
                continue
            if client_order_id and trade_client_id == client_order_id:
                matched.append(trade)
                continue
        else:
            matched.append(trade)

    if not matched:
        return None

    total_qty = 0.0
    total_cost = 0.0
    total_price_qty = 0.0
    total_fees = 0.0
    fee_found = False
    latest_ts: Optional[float] = None

    for trade in matched:
        info = trade.get("info") if isinstance(trade, dict) else None
        qty = _coerce_float(
            trade.get("amount")
            or trade.get("qty")
            or trade.get("size")
            or (info.get("execQty") if isinstance(info, dict) else None)
        )
        price = _coerce_float(
            trade.get("price")
            or trade.get("avgPrice")
            or (info.get("execPrice") if isinstance(info, dict) else None)
        )
        cost = _coerce_float(
            trade.get("cost")
            or trade.get("quoteQty")
            or (info.get("execValue") if isinstance(info, dict) else None)
        )
        if cost is None and qty is not None and price is not None:
            cost = qty * price
        if qty is not None:
            total_qty += qty
            if price is not None:
                total_price_qty += qty * price
        if cost is not None:
            total_cost += cost
        fee = _extract_trade_fee_usd(trade)
        if fee is not None:
            fee_found = True
            # Keep sign so maker rebates reduce aggregate fee cost.
            total_fees += fee
        ts = trade.get("timestamp") or trade.get("ts")
        if ts is None and isinstance(info, dict):
            ts = info.get("execTime")
        ts_sec = _coerce_epoch_sec(ts)
        if ts_sec is not None:
            if latest_ts is None or ts_sec > latest_ts:
                latest_ts = ts_sec

    if total_qty <= 0:
        return None
    avg_price = None
    if total_price_qty > 0:
        avg_price = total_price_qty / total_qty
    elif total_cost > 0:
        avg_price = total_cost / total_qty

    return {
        "avg_price": avg_price,
        "total_qty": total_qty,
        "total_fees_usd": total_fees if fee_found else None,
        "exit_timestamp": latest_ts,
        "trade_count": len(matched),
    }


async def _reconcile_close_from_exchange(
    exchange_client: ExchangeClient,
    symbol: str,
    order_id: Optional[str],
    client_order_id: Optional[str],
    exit_timestamp: Optional[float],
) -> Optional[dict]:
    return await _reconcile_execution_from_exchange(
        exchange_client=exchange_client,
        symbol=symbol,
        order_id=order_id,
        client_order_id=client_order_id,
        timestamp=exit_timestamp,
    )


async def _reconcile_execution_from_exchange(
    exchange_client: ExchangeClient,
    symbol: str,
    order_id: Optional[str],
    client_order_id: Optional[str],
    timestamp: Optional[float],
) -> Optional[dict]:
    fetcher = getattr(exchange_client, "fetch_executions", None)
    if fetcher is None:
        return None
    if not order_id and not client_order_id:
        return None
    since_ms = None
    if timestamp:
        since_ms = int(max(timestamp - 120.0, 0) * 1000)
    try:
        normalized_symbol = normalize_exchange_symbol(
            getattr(exchange_client, "exchange", "") or getattr(exchange_client, "exchange_id", "") or "",
            symbol,
        ) or symbol
        trades = await fetcher(
            symbol=normalized_symbol,
            order_id=order_id,
            client_order_id=client_order_id,
            since_ms=since_ms,
            limit=100,
        )
    except Exception as exc:
        log_warning(
            "exchange_exec_fetch_failed",
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
            error=str(exc),
        )
        return None
    summary = _aggregate_execution_trades(trades or [], order_id, client_order_id)
    if summary:
        log_info(
            "exchange_exec_reconciled",
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
            trade_count=summary.get("trade_count"),
            avg_price=summary.get("avg_price"),
            total_qty=summary.get("total_qty"),
            total_fees_usd=summary.get("total_fees_usd"),
        )
    return summary


class NoopExecutionManager(ExecutionManager):
    """Fallback execution manager that only acknowledges requests."""

    def set_failover_targets(self, primary_exchange: Optional[str], secondary_exchange: Optional[str]) -> None:
        return None

    async def flatten_positions(self, symbol: Optional[str] = None) -> FlattenResult:
        target = symbol or "all"
        return FlattenResult(status="accepted", message=f"flatten_enqueued:{target}")

    async def execute_intent(self, intent: ExecutionIntent) -> OrderStatus:
        return OrderStatus(order_id=None, status="filled")

    async def record_order_status(self, intent: ExecutionIntent, status: OrderStatus) -> bool:
        return _is_filled(status.status)

    async def poll_order_status(self, order_id: str, symbol: str) -> Optional[OrderStatus]:
        return None

    async def poll_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Optional[OrderStatus]:
        return None

    async def apply_risk_override(
        self,
        overrides: Dict[str, float],
        ttl_seconds: int,
        scope: Optional[Dict[str, str]] = None,
    ) -> RiskOverrideResult:
        return RiskOverrideResult(status="accepted", message="risk_override_enqueued")

    async def reload_config(self) -> ReloadResult:
        return ReloadResult(status="accepted", message="reload_enqueued")

    async def execute_failover(self) -> FailoverResult:
        return FailoverResult(status="accepted", message="failover_enqueued")

    async def execute_recovery(self) -> FailoverResult:
        return FailoverResult(status="accepted", message="recovery_enqueued")

    async def cancel_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
    ) -> OrderActionResult:
        return OrderActionResult(status="rejected", message="cancel_not_supported")

    async def replace_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
        price: Optional[float],
        size: Optional[float],
    ) -> OrderActionResult:
        return OrderActionResult(status="rejected", message="replace_not_supported")


async def _find_open_position(
    position_manager: PositionManager, symbol: Optional[str]
) -> Optional[PositionSnapshot]:
    if not symbol:
        return None
    positions = await position_manager.list_open_positions()
    for pos in positions:
        if pos.symbol == symbol:
            return pos
    return None


def _is_exit_for_position(order_side: Optional[str], position_side: Optional[str]) -> bool:
    order = (order_side or "").lower()
    position = (position_side or "").lower()
    if position in {"long", "buy"}:
        return order in {"sell", "short"}
    if position in {"short", "sell"}:
        return order in {"buy", "long"}
    return False
