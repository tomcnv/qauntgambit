"""Risk and sizing worker."""

from __future__ import annotations

import uuid
import os
from dataclasses import dataclass, replace
import time
from typing import Optional, TYPE_CHECKING

from quantgambit.observability.logger import log_warning, log_info
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.risk.validator import DeepTraderRiskValidator
from quantgambit.execution.manager import PositionSnapshot
from quantgambit.risk.overrides import RiskOverrideStore
from quantgambit.storage.redis_streams import (
    Event,
    RedisStreamsClient,
    decode_and_validate_event,
    Command,
    command_stream_name,
)
from quantgambit.ingest.time_utils import sec_to_us
from quantgambit.core.risk.kill_switch import KillSwitchTrigger

if TYPE_CHECKING:
    from quantgambit.core.latency import LatencyTracker


@dataclass
class RiskWorkerConfig:
    source_stream: str = "events:decisions"
    output_stream: str = "events:risk_decisions"
    consumer_group: str = "quantgambit_risk"
    consumer_name: str = "risk_worker"
    block_ms: int = 1000
    account_equity: float = 100000.0
    risk_per_trade_pct: float = 0.05  # Increased for OKX testnet to meet minimum order sizes
    trading_enabled: bool = True
    min_position_size_usd: float = 50.0  # Increased to meet OKX perpetual minimums
    max_positions: int = 4
    max_positions_per_symbol: int = 1
    max_total_exposure_pct: float = 0.50
    max_exposure_per_symbol_pct: float = 0.20
    max_long_exposure_pct: float = 0.0
    max_short_exposure_pct: float = 0.0
    max_net_exposure_pct: float = 0.0
    max_exposure_per_strategy_pct: float = 0.0
    max_positions_per_strategy: int = 0
    max_daily_loss_pct: float = 0.05
    max_consecutive_losses: int = 3
    max_drawdown_pct: float = 0.10
    max_position_size_usd: Optional[float] = None
    max_leverage: Optional[float] = None
    max_notional_per_symbol: Optional[float] = None
    max_notional_total: Optional[float] = None
    max_reference_price_age_sec: float = 5.0
    include_pending_intents: bool = True
    allow_position_replacement: bool = False
    replace_opposite_only: bool = True
    replace_min_edge_bps: float = 0.0
    replace_min_confidence: float = 0.0
    replace_min_hold_sec: float = 0.0
    # When hard account guardrails are breached, trigger persistent kill switch + flatten.
    trigger_kill_switch_on_guardrail: bool = True
    flatten_on_guardrail: bool = True


class RiskWorker:
    """Consumes decisions, applies risk checks, and emits sized intents."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        state_manager: InMemoryStateManager,
        bot_id: str,
        exchange: str,
        tenant_id: Optional[str] = None,
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        price_provider=None,
        config: Optional[RiskWorkerConfig] = None,
        override_store: Optional[RiskOverrideStore] = None,
        order_store=None,
        snapshot_writer=None,
        snapshot_key: Optional[str] = None,
        latency_tracker: Optional["LatencyTracker"] = None,
        kill_switch=None,  # PersistentKillSwitch or compatible
    ):
        self.redis = redis_client
        self.state_manager = state_manager
        self.bot_id = bot_id
        self.exchange = exchange
        self.tenant_id = tenant_id
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.price_provider = price_provider
        self.config = config or RiskWorkerConfig()
        self.validator = DeepTraderRiskValidator()
        self.override_store = override_store
        self.order_store = order_store
        self.snapshot_writer = snapshot_writer
        self.snapshot_key = snapshot_key
        self._latency_tracker = latency_tracker
        self._kill_switch = kill_switch
        self._flatten_sent = False
        self._persist_positions = os.getenv("RISK_PERSIST_POSITIONS", "").lower() in {"1", "true", "yes"}
        self._positions_snapshot_interval = float(os.getenv("RISK_POSITIONS_SNAPSHOT_INTERVAL_SEC", "2.0"))
        self._last_positions_snapshot = 0.0

    async def run(self) -> None:
        log_info("risk_worker_start", source=self.config.source_stream, output=self.config.output_stream)
        await self.redis.create_group(self.config.source_stream, self.config.consumer_group)
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
            latency_start = self._latency_tracker.start_timer("risk_worker")
        
        try:
            await self._handle_message_inner(payload)
        finally:
            # End latency tracking
            if self._latency_tracker and latency_start is not None:
                self._latency_tracker.end_timer("risk_worker", latency_start)

    async def _handle_message_inner(self, payload: dict) -> None:
        try:
            event = decode_and_validate_event(payload)
        except Exception as exc:
            log_warning("risk_worker_invalid_event", error=str(exc))
            return
        if event.get("event_type") != "decision":
            return
        decision = event.get("payload") or {}
        if decision.get("decision") != "accepted":
            return
        signal = decision.get("signal") or {}
        if not signal:
            log_warning("risk_worker_missing_signal", symbol=decision.get("symbol"))
            return
        
        # Exit signals bypass position count checks - they REDUCE exposure, not increase it
        is_exit_signal = signal.get("is_exit_signal", False) or signal.get("reduce_only", False)
        if is_exit_signal:
            log_info(
                "risk_worker_exit_bypass",
                symbol=decision.get("symbol"),
                side=signal.get("side"),
                reason="exit_signal_passthrough",
            )
            # Pass exit signals directly to execution without position count checks
            # Use "accepted" status for compatibility with execution worker
            await self._publish_risk_decision(
                decision.get("symbol"),
                {
                    "symbol": decision.get("symbol"),
                    "timestamp": decision.get("timestamp"),
                    "status": "accepted",  # Execution worker expects "accepted" not "approved"
                    "signal": signal,
                    "exit_passthrough": True,
                },
            )
            return
        
        positions = await self._load_positions_for_risk()
        await self._maybe_publish_positions_snapshot(positions)
        account_state = self.state_manager.get_account_state()
        overrides = self._get_overrides(symbol=decision.get("symbol"))
        effective_config = _apply_overrides(self.config, overrides)
        pending_positions = await self._load_pending_positions(effective_config)
        all_positions = positions + pending_positions
        if not effective_config.trading_enabled:
            await self._emit_guardrail(
                decision.get("symbol"),
                "trading_disabled",
                {"overrides": overrides or None},
            )
            await self._publish_risk_decision(
                decision.get("symbol"),
                {
                    "symbol": decision.get("symbol"),
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "risk_override_disabled",
                    "signal": signal,
                },
            )
            return
        real_account_equity = account_state.equity or effective_config.account_equity
        deployable_capital = real_account_equity
        if effective_config.account_equity > 0:
            deployable_capital = min(real_account_equity, effective_config.account_equity)
        if account_state.peak_balance <= 0:
            account_state.peak_balance = real_account_equity
        guardrail_reason = _check_account_guardrails(account_state, real_account_equity, effective_config)
        if guardrail_reason:
            await self._maybe_trigger_kill_switch_and_flatten(guardrail_reason, symbol=decision.get("symbol"))
            await self._emit_guardrail(
                decision.get("symbol"),
                guardrail_reason,
                {
                    "account_equity": real_account_equity,
                    "deployable_capital": deployable_capital,
                },
            )
            await self._publish_risk_decision(
                decision.get("symbol"),
                {
                    "symbol": decision.get("symbol"),
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": guardrail_reason,
                    "signal": signal,
                },
            )
            return
        exposure = _portfolio_exposure(
            all_positions,
            self.price_provider,
            max_age_sec=effective_config.max_reference_price_age_sec,
        )
        sizing_equity = deployable_capital
        self._debug_state(real_account_equity, all_positions, exposure)
        total_exposure_pct = (exposure["total_usd"] / sizing_equity) if sizing_equity else 0.0
        long_exposure_pct = (exposure["long_usd"] / sizing_equity) if sizing_equity else 0.0
        short_exposure_pct = (exposure["short_usd"] / sizing_equity) if sizing_equity else 0.0
        net_exposure_pct = (exposure["net_usd"] / sizing_equity * 100.0) if sizing_equity else 0.0
        symbol = decision.get("symbol")
        side = _normalize_signal_side(signal.get("side"))
        strategy_id = signal.get("strategy_id")
        symbol_position_count = _count_positions(all_positions, symbol)
        symbol_positions = [pos for pos in all_positions if pos.symbol == symbol]
        if symbol_position_count >= effective_config.max_positions_per_symbol:
            replace_payload = _evaluate_replacement(
                decision=decision,
                signal=signal,
                positions=symbol_positions,
                config=effective_config,
            )
            if replace_payload:
                signal["replace_position"] = True
                signal["replace_reason"] = replace_payload["reason"]
                signal["replace_existing_side"] = replace_payload["existing_side"]
                signal["replace_existing_size"] = replace_payload["existing_size"]
                if replace_payload.get("expected_edge_bps") is not None:
                    signal["replace_expected_edge_bps"] = replace_payload["expected_edge_bps"]
                if replace_payload.get("signal_confidence") is not None:
                    signal["replace_signal_confidence"] = replace_payload["signal_confidence"]
                log_info(
                    "risk_worker_replace_allowed",
                    symbol=symbol,
                    existing_side=replace_payload["existing_side"],
                    new_side=side,
                    reason=replace_payload["reason"],
                )
            else:
                await self._emit_guardrail(symbol, "max_positions_per_symbol_exceeded", None)
                await self._publish_risk_decision(
                    symbol,
                    {
                        "symbol": symbol,
                        "timestamp": decision.get("timestamp"),
                        "status": "rejected",
                        "rejection_reason": "max_positions_per_symbol_exceeded",
                        "signal": signal,
                    },
                )
                return
        if len(all_positions) >= effective_config.max_positions:
            await self._emit_guardrail(symbol, "max_positions_exceeded", None)
            await self._publish_risk_decision(
                decision.get("symbol"),
                {
                    "symbol": decision.get("symbol"),
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "max_positions_exceeded",
                    "signal": signal,
                },
            )
            return
        if effective_config.max_positions_per_strategy > 0 and strategy_id:
            strategy_count = _count_positions_for_strategy(all_positions, strategy_id)
            if strategy_count >= effective_config.max_positions_per_strategy:
                await self._emit_guardrail(strategy_id, "max_positions_per_strategy_exceeded", None)
                await self._publish_risk_decision(
                    decision.get("symbol"),
                    {
                        "symbol": decision.get("symbol"),
                        "timestamp": decision.get("timestamp"),
                        "status": "rejected",
                        "rejection_reason": "max_positions_per_strategy_exceeded",
                        "signal": signal,
                    },
                )
                return
        if total_exposure_pct >= effective_config.max_total_exposure_pct:
            await self._emit_guardrail(
                symbol,
                "max_total_exposure_exceeded",
                {"total_exposure_pct": total_exposure_pct},
            )
            await self._snapshot_rejection(
                decision,
                signal,
                exposure,
                real_account_equity,
                deployable_capital,
                total_exposure_pct,
                strategy_id,
                effective_config,
                reason="max_total_exposure_exceeded",
            )
            await self._publish_risk_decision(
                decision.get("symbol"),
                {
                    "symbol": decision.get("symbol"),
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "max_total_exposure_exceeded",
                    "signal": signal,
                },
            )
            return
        if effective_config.max_exposure_per_strategy_pct > 0 and strategy_id:
            strategy_usd = exposure["per_strategy"].get(strategy_id, 0.0)
            strategy_pct = (strategy_usd / sizing_equity) if sizing_equity else 0.0
            if strategy_pct >= effective_config.max_exposure_per_strategy_pct:
                await self._emit_guardrail(
                    strategy_id,
                    "max_exposure_per_strategy_exceeded",
                    {"strategy_exposure_pct": strategy_pct},
                )
                await self._publish_risk_decision(
                    decision.get("symbol"),
                    {
                        "symbol": decision.get("symbol"),
                        "timestamp": decision.get("timestamp"),
                        "status": "rejected",
                        "rejection_reason": "max_exposure_per_strategy_exceeded",
                        "signal": signal,
                    },
                )
                return
        if (
            effective_config.max_long_exposure_pct > 0
            and side == "long"
            and long_exposure_pct >= effective_config.max_long_exposure_pct
        ):
            await self._emit_guardrail(
                symbol,
                "max_long_exposure_exceeded",
                {"long_exposure_pct": long_exposure_pct},
            )
            await self._publish_risk_decision(
                symbol,
                {
                    "symbol": symbol,
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "max_long_exposure_exceeded",
                    "signal": signal,
                },
            )
            return
        if (
            effective_config.max_short_exposure_pct > 0
            and side == "short"
            and short_exposure_pct >= effective_config.max_short_exposure_pct
        ):
            await self._emit_guardrail(
                symbol,
                "max_short_exposure_exceeded",
                {"short_exposure_pct": short_exposure_pct},
            )
            await self._publish_risk_decision(
                symbol,
                {
                    "symbol": symbol,
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "max_short_exposure_exceeded",
                    "signal": signal,
                },
            )
            return
        if effective_config.max_net_exposure_pct > 0 and side:
            if side == "long" and net_exposure_pct >= effective_config.max_net_exposure_pct:
                await self._emit_guardrail(
                    symbol,
                    "max_net_exposure_exceeded",
                    {"net_exposure_pct": net_exposure_pct},
                )
                await self._publish_risk_decision(
                    symbol,
                    {
                        "symbol": symbol,
                        "timestamp": decision.get("timestamp"),
                        "status": "rejected",
                        "rejection_reason": "max_net_exposure_exceeded",
                        "signal": signal,
                    },
                )
                return
            if side == "short" and net_exposure_pct <= -effective_config.max_net_exposure_pct:
                await self._emit_guardrail(
                    symbol,
                    "max_net_exposure_exceeded",
                    {"net_exposure_pct": net_exposure_pct},
                )
                await self._publish_risk_decision(
                    symbol,
                    {
                        "symbol": symbol,
                        "timestamp": decision.get("timestamp"),
                        "status": "rejected",
                        "rejection_reason": "max_net_exposure_exceeded",
                        "signal": signal,
                    },
                )
                return
        price, price_reason = _resolve_price_with_reason(
            signal.get("entry_price"),
            decision.get("symbol"),
            self.price_provider,
            effective_config.max_reference_price_age_sec,
        )
        if price is None:
            await self._publish_risk_decision(
                decision.get("symbol"),
                {
                    "symbol": decision.get("symbol"),
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": price_reason or "missing_price",
                    "signal": signal,
                },
            )
            return
        remaining_total_usd = max(
            0.0, effective_config.max_total_exposure_pct * sizing_equity - exposure["total_usd"]
        )
        remaining_symbol_usd = None
        if symbol:
            current_symbol_usd = exposure["per_symbol"].get(symbol, 0.0)
            remaining_symbol_usd = max(
                0.0, effective_config.max_exposure_per_symbol_pct * sizing_equity - current_symbol_usd
            )
        remaining_side_usd = None
        if side == "long" and effective_config.max_long_exposure_pct > 0:
            remaining_side_usd = max(
                0.0, effective_config.max_long_exposure_pct * sizing_equity - exposure["long_usd"]
            )
        if side == "short" and effective_config.max_short_exposure_pct > 0:
            remaining_side_usd = max(
                0.0, effective_config.max_short_exposure_pct * sizing_equity - exposure["short_usd"]
            )
        remaining_net_usd = None
        if effective_config.max_net_exposure_pct > 0 and side:
            net_limit_usd = effective_config.max_net_exposure_pct * sizing_equity
            if side == "long" and exposure["net_usd"] >= 0:
                remaining_net_usd = max(0.0, net_limit_usd - exposure["net_usd"])
            if side == "short" and exposure["net_usd"] <= 0:
                remaining_net_usd = max(0.0, net_limit_usd - abs(exposure["net_usd"]))
        if remaining_total_usd <= 0:
            await self._emit_guardrail(symbol, "max_total_exposure_exceeded", None)
            await self._publish_risk_decision(
                symbol,
                {
                    "symbol": symbol,
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "max_total_exposure_exceeded",
                    "signal": signal,
                },
            )
            return
        if remaining_symbol_usd is not None and remaining_symbol_usd <= 0:
            await self._emit_guardrail(symbol, "max_exposure_per_symbol_exceeded", None)
            await self._publish_risk_decision(
                symbol,
                {
                    "symbol": symbol,
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "max_exposure_per_symbol_exceeded",
                    "signal": signal,
                },
            )
            return
        if remaining_side_usd is not None and remaining_side_usd <= 0:
            reason = "max_long_exposure_exceeded" if side == "long" else "max_short_exposure_exceeded"
            await self._emit_guardrail(symbol, reason, None)
            await self._publish_risk_decision(
                symbol,
                {
                    "symbol": symbol,
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": reason,
                    "signal": signal,
                },
            )
            return
        if remaining_net_usd is not None and remaining_net_usd <= 0:
            await self._emit_guardrail(symbol, "max_net_exposure_exceeded", None)
            await self._publish_risk_decision(
                symbol,
                {
                    "symbol": symbol,
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "max_net_exposure_exceeded",
                    "signal": signal,
                },
            )
            return
        remaining_strategy_usd = None
        if effective_config.max_exposure_per_strategy_pct > 0 and strategy_id:
            current_strategy_usd = exposure["per_strategy"].get(strategy_id, 0.0)
            remaining_strategy_usd = max(
                0.0,
                effective_config.max_exposure_per_strategy_pct * sizing_equity
                - current_strategy_usd,
            )
        if remaining_strategy_usd is not None and remaining_strategy_usd <= 0:
            await self._emit_guardrail(strategy_id, "max_exposure_per_strategy_exceeded", None)
            await self._publish_risk_decision(
                symbol,
                {
                    "symbol": symbol,
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "max_exposure_per_strategy_exceeded",
                    "signal": signal,
                },
            )
            return
        risk_budget_usd = sizing_equity * effective_config.risk_per_trade_pct
        risk_budget_usd *= _portfolio_heat_scale(total_exposure_pct, effective_config.max_total_exposure_pct)
        risk_context = decision.get("risk_context") or {}
        risk_multiplier = _risk_context_multiplier(risk_context)
        risk_budget_usd *= risk_multiplier
        risk_budget_usd = min(risk_budget_usd, remaining_total_usd)
        if remaining_symbol_usd is not None:
            risk_budget_usd = min(risk_budget_usd, remaining_symbol_usd)
        if remaining_side_usd is not None:
            risk_budget_usd = min(risk_budget_usd, remaining_side_usd)
        if remaining_net_usd is not None:
            risk_budget_usd = min(risk_budget_usd, remaining_net_usd)
        if remaining_strategy_usd is not None:
            risk_budget_usd = min(risk_budget_usd, remaining_strategy_usd)
        risk_units = _calculate_size_units_from_budget(
            risk_budget_usd,
            price,
            signal.get("stop_loss"),
        )
        # Apply absolute notional and leverage constraints
        max_notional_total = effective_config.max_notional_total
        max_notional_symbol = effective_config.max_notional_per_symbol
        exposure_per_symbol = exposure["per_symbol"].get(symbol, 0.0) if symbol else 0.0
        if max_notional_total is not None:
            max_notional_total = max(0.0, float(max_notional_total) - exposure["total_usd"])
        if max_notional_symbol is not None:
            max_notional_symbol = max(0.0, float(max_notional_symbol) - exposure_per_symbol)
        leverage_cap_units = None
        if effective_config.max_leverage and effective_config.max_leverage > 0 and sizing_equity > 0:
            leverage_notional_cap = sizing_equity * effective_config.max_leverage
            leverage_cap_units = max(0.0, leverage_notional_cap / price if price > 0 else 0.0)
        # Spot: force leverage=1 regardless of config
        if os.getenv("MARKET_TYPE", "perp").lower() == "spot" and sizing_equity > 0:
            spot_cap = max(0.0, sizing_equity / price if price > 0 else 0.0)
            leverage_cap_units = min(leverage_cap_units, spot_cap) if leverage_cap_units is not None else spot_cap
        max_exposure_usd = remaining_total_usd
        if remaining_symbol_usd is not None:
            max_exposure_usd = min(max_exposure_usd, remaining_symbol_usd)
        if remaining_side_usd is not None:
            max_exposure_usd = min(max_exposure_usd, remaining_side_usd)
        if remaining_net_usd is not None:
            max_exposure_usd = min(max_exposure_usd, remaining_net_usd)
        if remaining_strategy_usd is not None:
            max_exposure_usd = min(max_exposure_usd, remaining_strategy_usd)
        if max_notional_total is not None:
            max_exposure_usd = min(max_exposure_usd, max_notional_total)
        if max_notional_symbol is not None:
            max_exposure_usd = min(max_exposure_usd, max_notional_symbol)
        max_units = max_exposure_usd / price if price > 0 else 0.0
        requested_units = signal.get("size")
        if requested_units is None:
            size_units = min(risk_units, max_units)
        else:
            size_units = min(float(requested_units), risk_units, max_units)
        if leverage_cap_units is not None:
            size_units = min(size_units, leverage_cap_units)
        size_usd = size_units * price
        if effective_config.max_position_size_usd is not None:
            size_usd = min(size_usd, effective_config.max_position_size_usd)
            size_units = size_usd / price if price > 0 else size_units
        if size_units <= 0:
            await self._emit_guardrail(symbol, "exposure_limit", None)
            await self._snapshot_rejection(
                decision,
                signal,
                exposure,
                real_account_equity,
                deployable_capital,
                total_exposure_pct,
                strategy_id,
                effective_config,
                reason="exposure_limit",
            )
            await self._publish_risk_decision(
                symbol,
                {
                    "symbol": symbol,
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "exposure_limit",
                    "signal": signal,
                },
            )
            return
        if size_usd < effective_config.min_position_size_usd:
            await self._emit_guardrail(symbol, "min_position_size", {"size_usd": size_usd})
            await self._publish_risk_decision(
                decision.get("symbol"),
                {
                    "symbol": decision.get("symbol"),
                    "timestamp": decision.get("timestamp"),
                    "status": "rejected",
                    "rejection_reason": "min_position_size",
                    "signal": signal,
                },
            )
            return
        limits_payload = {
            "max_positions": effective_config.max_positions,
            "max_positions_per_symbol": effective_config.max_positions_per_symbol,
            "max_positions_per_strategy": effective_config.max_positions_per_strategy,
            "max_total_exposure_pct": effective_config.max_total_exposure_pct,
            "max_exposure_per_symbol_pct": effective_config.max_exposure_per_symbol_pct,
            "max_exposure_per_strategy_pct": effective_config.max_exposure_per_strategy_pct,
            "max_long_exposure_pct": effective_config.max_long_exposure_pct,
            "max_short_exposure_pct": effective_config.max_short_exposure_pct,
            "max_net_exposure_pct": effective_config.max_net_exposure_pct,
            "max_daily_loss_pct": effective_config.max_daily_loss_pct,
            "max_drawdown_pct": effective_config.max_drawdown_pct,
            "max_consecutive_losses": effective_config.max_consecutive_losses,
            "max_position_size_usd": effective_config.max_position_size_usd,
            "max_notional_total": effective_config.max_notional_total,
            "max_notional_per_symbol": effective_config.max_notional_per_symbol,
            "max_leverage": effective_config.max_leverage,
            "risk_per_trade_pct": effective_config.risk_per_trade_pct,
            "min_position_size_usd": effective_config.min_position_size_usd,
        }
        remaining_payload = {
            "total_usd": remaining_total_usd,
            "symbol_usd": remaining_symbol_usd,
            "side_usd": remaining_side_usd,
            "net_usd": remaining_net_usd,
            "strategy_usd": remaining_strategy_usd,
            "notional_total_usd": max_notional_total,
            "notional_symbol_usd": max_notional_symbol,
        }
        exposure_payload = {
            "total_usd": exposure["total_usd"],
            "total_pct": total_exposure_pct,
            "long_usd": exposure["long_usd"],
            "short_usd": exposure["short_usd"],
            "net_usd": exposure["net_usd"],
            "net_pct": net_exposure_pct,
            "symbol_usd": exposure["per_symbol"].get(symbol, 0.0) if symbol else None,
            "strategy_usd": exposure["per_strategy"].get(strategy_id, 0.0) if strategy_id else None,
        }
        signal = dict(signal)
        signal["size"] = size_units
        signal["sizing_context"] = {
            "risk_budget_usd": risk_budget_usd,
            "max_exposure_usd": max_exposure_usd,
            "max_notional_total": max_notional_total,
            "max_notional_symbol": max_notional_symbol,
            "leverage_cap_units": leverage_cap_units,
            "remaining_total_usd": remaining_total_usd,
            "remaining_symbol_usd": remaining_symbol_usd,
            "remaining_side_usd": remaining_side_usd,
            "remaining_net_usd": remaining_net_usd,
            "remaining_strategy_usd": remaining_strategy_usd,
        }
        if hasattr(self.validator, "_validator"):
            validator = getattr(self.validator, "_validator")
            validator.max_positions = effective_config.max_positions
            validator.max_positions_per_symbol = effective_config.max_positions_per_symbol
            validator.max_total_exposure_pct = effective_config.max_total_exposure_pct
            validator.max_exposure_per_symbol_pct = effective_config.max_exposure_per_symbol_pct
            validator.max_daily_loss_pct = effective_config.max_daily_loss_pct
            validator.max_consecutive_losses = effective_config.max_consecutive_losses
            validator.max_drawdown_pct = effective_config.max_drawdown_pct
        allowed = self.validator.allow(
            signal,
            context={
                "positions": all_positions,
                "account": {
                    "equity": sizing_equity,
                    "daily_pnl": account_state.daily_pnl,
                },
                "price": signal.get("entry_price"),
                "peak_balance": account_state.peak_balance,
                "consecutive_losses": account_state.consecutive_losses,
                "min_position_size_usd": effective_config.min_position_size_usd,
                "position_size_usd": size_usd,
            },
        )
        status = "accepted" if allowed else "rejected"
        reason = self.validator.last_rejection_reason
        risk_payload = {
            "symbol": decision.get("symbol"),
            "timestamp": decision.get("timestamp"),
            "status": status,
            "rejection_reason": reason,
            "signal": signal,
            "overrides": overrides or None,
            "limits": limits_payload,
            "remaining": remaining_payload,
            "exposure": exposure_payload,
            "account_equity": real_account_equity,
            "deployable_capital": deployable_capital,
            "total_exposure_usd": exposure["total_usd"],
            "total_exposure_pct": total_exposure_pct,
            "long_exposure_usd": exposure["long_usd"],
            "short_exposure_usd": exposure["short_usd"],
            "net_exposure_usd": exposure["net_usd"],
            "net_exposure_pct": net_exposure_pct,
            "symbol_exposure_usd": exposure["per_symbol"].get(symbol, 0.0) if symbol else None,
            "strategy_exposure_usd": exposure["per_strategy"].get(strategy_id, 0.0) if strategy_id else None,
            "risk_budget_usd": risk_budget_usd,
            "risk_multiplier": risk_multiplier,
            "size_usd": size_usd,
        }
        await self._publish_risk_decision(decision.get("symbol"), risk_payload)
        if self.telemetry and self.telemetry_context:
            await self.telemetry.publish_risk(
                ctx=self.telemetry_context,
                payload={
                    "status": status,
                    "rejection_reason": reason,
                    "symbol": decision.get("symbol"),
                    "overrides": overrides or None,
                    "account_equity": real_account_equity,
                    "deployable_capital": deployable_capital,
                    "total_exposure_usd": exposure["total_usd"],
                    "total_exposure_pct": total_exposure_pct,
                    "long_exposure_usd": exposure["long_usd"],
                    "short_exposure_usd": exposure["short_usd"],
                    "net_exposure_usd": exposure["net_usd"],
                    "net_exposure_pct": net_exposure_pct,
                    "symbol_exposure_usd": exposure["per_symbol"].get(symbol, 0.0) if symbol else None,
                    "strategy_exposure_usd": exposure["per_strategy"].get(strategy_id, 0.0) if strategy_id else None,
                    "risk_budget_usd": risk_budget_usd,
                    "risk_multiplier": risk_multiplier,
                    "size_usd": size_usd,
                    "limits": limits_payload,
                    "remaining": remaining_payload,
                },
            )
        if self.snapshot_writer and self.snapshot_key:
            snapshot_payload = dict(risk_payload)
            snapshot_payload["equity"] = real_account_equity
            snapshot_payload["account_balance"] = real_account_equity
            snapshot_payload["account_equity"] = real_account_equity
            snapshot_payload["deployable_capital"] = deployable_capital
            snapshot_payload["peak_balance"] = account_state.peak_balance
            snapshot_payload["daily_pnl"] = account_state.daily_pnl
            snapshot_payload["consecutive_losses"] = account_state.consecutive_losses
            snapshot_payload["config"] = {
                "max_positions": effective_config.max_positions,
                "max_positions_per_symbol": effective_config.max_positions_per_symbol,
                "max_total_exposure_pct": effective_config.max_total_exposure_pct,
                "max_exposure_per_symbol_pct": effective_config.max_exposure_per_symbol_pct,
                "max_notional_total": effective_config.max_notional_total,
                "max_notional_per_symbol": effective_config.max_notional_per_symbol,
                "max_leverage": effective_config.max_leverage,
            }
            await self.snapshot_writer.write(self.snapshot_key, snapshot_payload)

    def _get_overrides(self, symbol: Optional[str]) -> dict:
        if not self.override_store:
            return {}
        return self.override_store.get_overrides(
            bot_id=self.bot_id,
            symbol=symbol,
            exchange=self.exchange,
        )

    async def _load_pending_positions(self, config: RiskWorkerConfig) -> list[PositionSnapshot]:
        if not config.include_pending_intents or not self.order_store:
            return []
        try:
            pending = await self.order_store.load_pending_intents()
        except Exception as exc:
            log_warning("risk_worker_pending_intents_failed", error=str(exc))
            return []
        snapshots: list[PositionSnapshot] = []
        for intent in pending:
            symbol = intent.get("symbol")
            side = _normalize_signal_side(intent.get("side"))
            size = intent.get("size")
            if not symbol or not side or size is None:
                continue
            entry_price = intent.get("entry_price")
            reference_price = None
            if entry_price is None and symbol:
                price, _ = _resolve_price_with_reason(
                    None, symbol, self.price_provider, config.max_reference_price_age_sec
                )
                reference_price = price
            snapshots.append(
                PositionSnapshot(
                    symbol=symbol,
                    side=side,
                    size=float(size),
                    entry_price=float(entry_price) if entry_price is not None else None,
                    reference_price=reference_price,
                    stop_loss=intent.get("stop_loss"),
                    take_profit=intent.get("take_profit"),
                    strategy_id=intent.get("strategy_id"),
                    profile_id=intent.get("profile_id"),
                )
            )
        return snapshots

    async def _load_positions_for_risk(self):
        """Load positions for risk/exposure accounting.

        Include positions marked closing until finalize_close completes, so
        exposure caps cannot be bypassed while close orders are in-flight.
        """
        list_positions = getattr(self.state_manager, "list_positions", None)
        if callable(list_positions):
            try:
                return await list_positions(include_closing=True)
            except TypeError:
                return await list_positions()
        return await self.state_manager.list_open_positions()

    async def _emit_guardrail(self, symbol: Optional[str], reason: str, extra: Optional[dict]) -> None:
        if not (self.telemetry and self.telemetry_context):
            return
        payload = {"type": "risk_guardrail", "symbol": symbol, "reason": reason}
        if extra:
            payload.update(extra)
        await self.telemetry.publish_guardrail(self.telemetry_context, payload)
        # Also emit to incidents/log streams for dashboard
        await self.telemetry.publish_risk_incident(self.telemetry_context, payload)
        await self.telemetry.publish_log(
            self.telemetry_context,
            {
                "level": "WARNING",
                "msg": f"Guardrail triggered: {reason}",
                "symbol": symbol,
                "reason": reason,
            },
        )

    async def _publish_risk_decision(self, symbol: str, payload: dict) -> None:
        ts_us = sec_to_us(float(payload.get("timestamp"))) if payload.get("timestamp") is not None else None
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type="risk_decision",
            schema_version="v1",
            timestamp=str(payload.get("timestamp")),
            ts_recv_us=ts_us,
            ts_canon_us=ts_us,
            ts_exchange_s=None,
            bot_id=self.bot_id,
            symbol=symbol,
            exchange=self.exchange,
            payload=payload,
        )
        await self.redis.publish_event(self.config.output_stream, event)

    async def _maybe_trigger_kill_switch_and_flatten(self, guardrail_reason: str, symbol: Optional[str] = None) -> None:
        """Hard-stop behavior on catastrophic guardrails: latch kill switch and flatten."""
        if guardrail_reason not in {
            "max_daily_loss_exceeded",
            "max_drawdown_exceeded",
            "max_consecutive_losses_exceeded",
        }:
            return
        if not (self.config.trigger_kill_switch_on_guardrail or self.config.flatten_on_guardrail):
            return

        message = f"guardrail:{guardrail_reason}"
        trigger_map = {
            "max_drawdown_exceeded": KillSwitchTrigger.EQUITY_DRAWDOWN,
            "max_daily_loss_exceeded": KillSwitchTrigger.EQUITY_DRAWDOWN,
            "max_consecutive_losses_exceeded": KillSwitchTrigger.REPEATED_REJECTS,
        }
        trigger_reason = trigger_map.get(guardrail_reason, KillSwitchTrigger.EQUITY_DRAWDOWN)
        kill_active = False
        if self._kill_switch and self.config.trigger_kill_switch_on_guardrail:
            try:
                # Avoid spamming flatten if the kill switch is already latched.
                kill_active = bool(getattr(self._kill_switch, "is_active", lambda: False)())
            except Exception:
                kill_active = False
            try:
                if not kill_active:
                    await self._kill_switch.trigger(trigger_reason, message=message)
                    log_warning("risk_worker_kill_switch_triggered", reason=guardrail_reason, trigger=trigger_reason.value)
            except Exception as exc:
                log_warning("risk_worker_kill_switch_trigger_failed", reason=guardrail_reason, error=str(exc))

        if not self.config.flatten_on_guardrail:
            return
        # Flatten once per process lifetime (kill switch should latch and prevent further triggers).
        if self._flatten_sent or kill_active:
            return
        await self._publish_flatten_command(symbol=None, reason=message)
        self._flatten_sent = True

    async def _publish_flatten_command(self, symbol: Optional[str], reason: str) -> None:
        if not self.tenant_id:
            # Without tenant scope, we don't know which runtime command stream to target.
            log_warning("risk_worker_flatten_missing_tenant_id", reason=reason)
            return
        stream = command_stream_name(self.tenant_id, self.bot_id)
        cmd = Command(
            command_id=str(uuid.uuid4()),
            type="FLATTEN",
            scope={"tenant_id": self.tenant_id, "bot_id": self.bot_id, "symbol": symbol} if symbol else {"tenant_id": self.tenant_id, "bot_id": self.bot_id},
            requested_by="risk_worker",
            requested_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            reason=reason,
            confirm_required=False,
            payload=None,
        )
        try:
            await self.redis.publish_command(stream, cmd)
            log_warning("risk_worker_flatten_published", stream=stream, reason=reason)
        except Exception as exc:
            log_warning("risk_worker_flatten_publish_failed", stream=stream, error=str(exc))
        log_info(
            "risk_decision_emitted",
            symbol=symbol,
            bot_id=self.bot_id,
            status=payload.get("status"),
            rejection_reason=payload.get("rejection_reason"),
        )

    def _debug_state(self, account_equity: float, positions: list[PositionSnapshot], exposure: dict) -> None:
        if os.getenv("RISK_DEBUG_STATE", "").lower() not in {"1", "true", "yes"}:
            return
        summarized = []
        for pos in positions:
            summarized.append(
                {
                    "symbol": pos.symbol,
                    "side": getattr(pos, "side", None),
                    "size": getattr(pos, "size", None),
                    "entry_price": getattr(pos, "entry_price", None),
                }
            )
        log_info(
            "risk_state_debug",
            bot_id=self.bot_id,
            account_equity=account_equity,
            positions=summarized,
            exposure={
                "total_usd": exposure.get("total_usd"),
                "long_usd": exposure.get("long_usd"),
                "short_usd": exposure.get("short_usd"),
                "net_usd": exposure.get("net_usd"),
                "per_symbol": exposure.get("per_symbol"),
            },
        )

    async def _maybe_publish_positions_snapshot(self, positions: list[PositionSnapshot]) -> None:
        if not (self._persist_positions and self.telemetry and self.telemetry_context):
            return
        now = time.time()
        if now - self._last_positions_snapshot < self._positions_snapshot_interval:
            return
        self._last_positions_snapshot = now
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
                    "age_sec": (now - _normalize_timestamp_seconds(pos.opened_at))
                    if _normalize_timestamp_seconds(pos.opened_at)
                    else None,
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

    async def _snapshot_rejection(
        self,
        decision: dict,
        signal: dict,
        exposure: dict,
        real_account_equity: float,
        deployable_capital: float,
        total_exposure_pct: float,
        strategy_id: Optional[str],
        effective_config: RiskWorkerConfig,
        reason: str,
    ) -> None:
        if not (self.snapshot_writer and self.snapshot_key):
            return
        symbol = decision.get("symbol")
        snapshot_payload = {
            "symbol": symbol,
            "timestamp": decision.get("timestamp"),
            "status": "rejected",
            "rejection_reason": reason,
            "signal": signal,
            "equity": real_account_equity,
            "account_balance": real_account_equity,
            "account_equity": real_account_equity,
            "deployable_capital": deployable_capital,
            "peak_balance": self.state_manager.get_account_state().peak_balance,
            "daily_pnl": self.state_manager.get_account_state().daily_pnl,
            "consecutive_losses": self.state_manager.get_account_state().consecutive_losses,
            "total_exposure_usd": exposure.get("total_usd"),
            "total_exposure_pct": total_exposure_pct,
            "symbol_exposure_usd": exposure.get("per_symbol", {}).get(symbol, 0.0) if symbol else None,
            "strategy_exposure_usd": exposure.get("per_strategy", {}).get(strategy_id, 0.0) if strategy_id else None,
            "config": {
                "max_positions": effective_config.max_positions,
                "max_positions_per_symbol": effective_config.max_positions_per_symbol,
                "max_total_exposure_pct": effective_config.max_total_exposure_pct,
                "max_exposure_per_symbol_pct": effective_config.max_exposure_per_symbol_pct,
                "max_notional_total": effective_config.max_notional_total,
                "max_notional_per_symbol": effective_config.max_notional_per_symbol,
                "max_leverage": effective_config.max_leverage,
            },
        }
        await self.snapshot_writer.write(self.snapshot_key, snapshot_payload)


def _calculate_size_units_from_budget(
    risk_budget_usd: float,
    entry_price: Optional[float],
    stop_loss: Optional[float],
) -> float:
    if entry_price and stop_loss:
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit > 0:
            return risk_budget_usd / risk_per_unit
    if entry_price:
        return risk_budget_usd / entry_price
    return risk_budget_usd


def _portfolio_heat_scale(total_exposure_pct: float, max_total_exposure_pct: float) -> float:
    if max_total_exposure_pct <= 0:
        return 0.0
    heat_ratio = total_exposure_pct / max_total_exposure_pct
    return max(0.0, 1.0 - heat_ratio)


def _risk_context_multiplier(risk_context: dict) -> float:
    if not risk_context:
        return 1.0
    multiplier = 1.0
    risk_scale = risk_context.get("risk_scale")
    if risk_scale is not None:
        try:
            risk_scale_val = float(risk_scale)
        except (TypeError, ValueError):
            risk_scale_val = 1.0
        if risk_scale_val > 0:
            multiplier *= risk_scale_val
    volatility_regime = risk_context.get("volatility_regime")
    if volatility_regime:
        try:
            from quantgambit.deeptrader_core.layer1_predictions.volatility_classifier import (
                get_volatility_multiplier,
            )

            multiplier *= get_volatility_multiplier(str(volatility_regime))
        except Exception:
            pass
    liquidity_regime = risk_context.get("liquidity_regime")
    if liquidity_regime:
        try:
            from quantgambit.deeptrader_core.layer1_predictions.liquidity_classifier import (
                get_liquidity_multiplier,
            )

            multiplier *= get_liquidity_multiplier(str(liquidity_regime))
        except Exception:
            pass
    market_regime = risk_context.get("market_regime")
    if market_regime:
        confidence = risk_context.get("regime_confidence", 0.0)
        try:
            confidence_val = float(confidence)
        except (TypeError, ValueError):
            confidence_val = 0.0
        try:
            from quantgambit.deeptrader_core.layer1_predictions.regime_classifier import (
                get_regime_position_multiplier,
            )

            multiplier *= get_regime_position_multiplier(str(market_regime), confidence_val)
        except Exception:
            pass
    return max(0.0, multiplier)


def _resolve_price_with_reason(
    entry_price: Optional[float],
    symbol: Optional[str],
    price_provider,
    max_age_sec: float,
) -> tuple[Optional[float], Optional[str]]:
    if entry_price:
        return float(entry_price), None
    if not symbol or price_provider is None:
        return None, "missing_price"
    if hasattr(price_provider, "get_reference_price_with_ts"):
        result = price_provider.get_reference_price_with_ts(symbol)
        if not result:
            return None, "missing_price"
        price, ts = result
        if max_age_sec > 0 and time.time() - float(ts) > max_age_sec:
            return None, "stale_reference_price"
        return float(price), None
    price = price_provider.get_reference_price(symbol)
    if price:
        return float(price), None
    return None, "missing_price"


def _portfolio_exposure(positions, price_provider, max_age_sec: float = 0.0) -> dict:
    total = 0.0
    long_usd = 0.0
    short_usd = 0.0
    per_symbol: dict[str, float] = {}
    per_strategy: dict[str, float] = {}
    now = time.time()
    for pos in positions:
        price = _resolve_position_price(pos, price_provider, max_age_sec, now)
        if price is None:
            continue
        value = abs(pos.size * price)
        total += value
        side = _normalize_position_side(getattr(pos, "side", None))
        if side == "long":
            long_usd += value
        elif side == "short":
            short_usd += value
        per_symbol[pos.symbol] = per_symbol.get(pos.symbol, 0.0) + value
        strategy_id = getattr(pos, "strategy_id", None)
        if strategy_id:
            per_strategy[strategy_id] = per_strategy.get(strategy_id, 0.0) + value
    net_usd = long_usd - short_usd
    return {
        "total_usd": total,
        "long_usd": long_usd,
        "short_usd": short_usd,
        "net_usd": net_usd,
        "per_symbol": per_symbol,
        "per_strategy": per_strategy,
    }


def _resolve_position_price(pos, price_provider, max_age_sec: float, now: float) -> Optional[float]:
    price = getattr(pos, "entry_price", None) or getattr(pos, "reference_price", None)
    if price is not None:
        return float(price)
    if not price_provider:
        return None
    if hasattr(price_provider, "get_reference_price_with_ts"):
        result = price_provider.get_reference_price_with_ts(pos.symbol)
        if not result:
            return None
        ref_price, ts = result
        if max_age_sec > 0 and now - float(ts) > max_age_sec:
            return None
        return float(ref_price)
    price = price_provider.get_reference_price(pos.symbol)
    return float(price) if price is not None else None


def _count_positions(positions, symbol: Optional[str]) -> int:
    if not symbol:
        return 0
    return sum(1 for pos in positions if pos.symbol == symbol)


def _count_positions_for_strategy(positions, strategy_id: Optional[str]) -> int:
    if not strategy_id:
        return 0
    return sum(1 for pos in positions if getattr(pos, "strategy_id", None) == strategy_id)


def _normalize_signal_side(side: Optional[str]) -> Optional[str]:
    if not side:
        return None
    normalized = str(side).lower()
    if normalized in {"buy", "long"}:
        return "long"
    if normalized in {"sell", "short"}:
        return "short"
    return normalized


def _normalize_position_side(side: Optional[str]) -> Optional[str]:
    return _normalize_signal_side(side)


def _is_opposite_side(new_side: Optional[str], existing_side: Optional[str]) -> bool:
    if not new_side or not existing_side:
        return False
    return _normalize_signal_side(new_side) != _normalize_position_side(existing_side)


def _extract_signal_confidence(decision: dict, signal: dict) -> Optional[float]:
    value = signal.get("prediction_confidence")
    if value is None:
        value = signal.get("confidence")
    if value is None:
        value = decision.get("prediction_confidence")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _extract_expected_edge_bps(decision: dict, signal: dict) -> Optional[float]:
    for key in ("expected_edge_bps", "edge_bps"):
        value = signal.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    candidate = decision.get("candidate") or {}
    value = candidate.get("expected_edge_bps")
    if value is None:
        metrics = decision.get("metrics") or {}
        value = metrics.get("expected_edge_bps")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_timestamp_seconds(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    # Normalize ms -> seconds if needed
    return ts / 1000.0 if ts > 1e12 else ts


def _evaluate_replacement(
    decision: dict,
    signal: dict,
    positions: list[PositionSnapshot],
    config: RiskWorkerConfig,
) -> Optional[dict]:
    if not config.allow_position_replacement:
        return None
    if not positions:
        return None
    new_side = _normalize_signal_side(signal.get("side"))
    existing = positions[0]
    existing_side = _normalize_position_side(existing.side)
    if config.replace_opposite_only and not _is_opposite_side(new_side, existing_side):
        return None
    if config.replace_min_hold_sec > 0 and existing.opened_at:
        opened_at = _normalize_timestamp_seconds(existing.opened_at)
        if opened_at is not None and time.time() - opened_at < config.replace_min_hold_sec:
            return None
    expected_edge_bps = _extract_expected_edge_bps(decision, signal)
    if expected_edge_bps is not None and expected_edge_bps < config.replace_min_edge_bps:
        return None
    signal_confidence = _extract_signal_confidence(decision, signal)
    if signal_confidence is not None and signal_confidence < config.replace_min_confidence:
        return None
    return {
        "reason": "replace_opposite_side" if _is_opposite_side(new_side, existing_side) else "replace_allowed",
        "existing_side": existing_side,
        "existing_size": existing.size,
        "expected_edge_bps": expected_edge_bps,
        "signal_confidence": signal_confidence,
    }


def _apply_overrides(config: RiskWorkerConfig, overrides: dict) -> RiskWorkerConfig:
    if not overrides:
        return config
    updates = {}
    for key, value in overrides.items():
        if not hasattr(config, key):
            log_warning("risk_override_unknown_key", key=key)
            continue
        updates[key] = value
    if not updates:
        return config
    return replace(config, **updates)


def _check_account_guardrails(
    account_state,
    account_equity: float,
    config: RiskWorkerConfig,
) -> Optional[str]:
    if account_equity <= 0:
        return "account_equity_unavailable"
    daily_loss_limit = config.max_daily_loss_pct * account_equity if config.max_daily_loss_pct > 0 else None
    if daily_loss_limit is not None and account_state.daily_pnl <= -daily_loss_limit:
        return "max_daily_loss_exceeded"
    if config.max_consecutive_losses > 0 and account_state.consecutive_losses >= config.max_consecutive_losses:
        return "max_consecutive_losses_exceeded"
    if account_state.peak_balance > 0 and config.max_drawdown_pct > 0:
        # max_drawdown_pct is stored as a decimal (e.g., 0.10 = 10%)
        drawdown_ratio = (account_state.peak_balance - account_equity) / account_state.peak_balance
        if drawdown_ratio >= config.max_drawdown_pct:
            return "max_drawdown_exceeded"
    return None
