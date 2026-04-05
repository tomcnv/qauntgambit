"""
CooldownStage - Manages entry cooldowns and hysteresis.

Prevents flip-flop churn by enforcing:
1. Cooldown after entry (per symbol/strategy)
2. Cooldown after exit (per symbol)
3. Hysteresis to prevent immediate re-entry after position close
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, TYPE_CHECKING

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.deeptrader_core.types import GateDecision
from quantgambit.observability.logger import log_info, log_warning

if TYPE_CHECKING:
    from quantgambit.config.trading_mode import TradingModeManager
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


@dataclass
class CooldownConfig:
    """Configuration for CooldownStage."""
    # Default cooldown after entry (per symbol/strategy pair)
    default_entry_cooldown_sec: float = 60.0
    
    # Cooldown after exit (per symbol)
    exit_cooldown_sec: float = 30.0
    # Optional longer cooldown after stop-outs
    stop_out_cooldown_sec: float = 60.0
    
    # Per-strategy cooldown overrides
    strategy_cooldowns: Dict[str, float] = field(default_factory=dict)
    
    # Hysteresis: minimum time before re-entering same direction
    same_direction_hysteresis_sec: float = 120.0
    
    # Maximum entries per symbol per hour (0 = unlimited)
    max_entries_per_hour: int = 10


class CooldownManager:
    """
    Tracks cooldowns and entry history.
    
    Thread-safe via simple dict operations (no external locking needed
    for single-threaded async code).
    """
    
    def __init__(self):
        # Last entry time per (symbol, strategy) pair
        self._last_entry: Dict[tuple, float] = {}
        # Last exit time per symbol
        self._last_exit: Dict[str, float] = {}
        # Last entry direction per symbol
        self._last_direction: Dict[str, str] = {}
        # Entry count per symbol per hour
        self._hourly_entries: Dict[str, list] = {}
        # Track P&L of last trade for hysteresis reduction (Requirement 2.3)
        self._last_trade_pnl: Dict[str, float] = {}
        # Track last exit reason for stop-out specific cooldown.
        self._last_exit_reason: Dict[str, str] = {}
    
    def record_entry(self, symbol: str, strategy_id: str, side: str) -> None:
        """Record an entry for cooldown tracking."""
        now = time.time()
        key = (symbol, strategy_id)
        self._last_entry[key] = now
        self._last_direction[symbol] = side
        
        # Track hourly entries
        if symbol not in self._hourly_entries:
            self._hourly_entries[symbol] = []
        self._hourly_entries[symbol].append(now)
        
        # Clean up old entries (older than 1 hour)
        cutoff = now - 3600
        self._hourly_entries[symbol] = [
            t for t in self._hourly_entries[symbol] if t > cutoff
        ]
    
    def record_exit(self, symbol: str, pnl_pct: Optional[float] = None, exit_reason: Optional[str] = None) -> None:
        """Record an exit for cooldown tracking.
        
        Args:
            symbol: The symbol being exited
            pnl_pct: Optional P&L percentage for hysteresis reduction
        """
        self._last_exit[symbol] = time.time()
        if pnl_pct is not None:
            self._last_trade_pnl[symbol] = pnl_pct
        if exit_reason:
            self._last_exit_reason[symbol] = str(exit_reason).lower()
    
    def was_last_trade_profitable(self, symbol: str) -> bool:
        """Check if last trade was profitable (for hysteresis reduction)."""
        return self._last_trade_pnl.get(symbol, 0.0) > 0.0
    
    def get_last_trade_pnl(self, symbol: str) -> Optional[float]:
        """Get P&L of last trade for symbol."""
        return self._last_trade_pnl.get(symbol)
    
    def get_time_since_entry(self, symbol: str, strategy_id: str) -> Optional[float]:
        """Get time since last entry for symbol/strategy pair."""
        key = (symbol, strategy_id)
        if key not in self._last_entry:
            return None
        return time.time() - self._last_entry[key]
    
    def get_time_since_exit(self, symbol: str) -> Optional[float]:
        """Get time since last exit for symbol."""
        if symbol not in self._last_exit:
            return None
        return time.time() - self._last_exit[symbol]

    def was_last_exit_stop_out(self, symbol: str) -> bool:
        reason = self._last_exit_reason.get(symbol, "")
        return any(token in reason for token in ("stop", "invalidation", "safety"))
    
    def get_last_direction(self, symbol: str) -> Optional[str]:
        """Get direction of last entry for symbol."""
        return self._last_direction.get(symbol)
    
    def get_hourly_entry_count(self, symbol: str) -> int:
        """Get number of entries in the last hour for symbol."""
        if symbol not in self._hourly_entries:
            return 0
        
        # Clean up old entries first
        now = time.time()
        cutoff = now - 3600
        self._hourly_entries[symbol] = [
            t for t in self._hourly_entries[symbol] if t > cutoff
        ]
        
        return len(self._hourly_entries[symbol])


class CooldownStage(Stage):
    """
    Manage entry cooldowns to prevent flip-flop churn.
    
    Checks:
    1. Time since last entry (per symbol/strategy)
    2. Time since last exit (per symbol)
    3. Hysteresis for same-direction re-entry
    4. Hourly entry rate limit
    """
    name = "cooldown"
    
    def __init__(
        self,
        config: Optional[CooldownConfig] = None,
        manager: Optional[CooldownManager] = None,
        trading_mode_manager: Optional["TradingModeManager"] = None,
        blocked_signal_telemetry: Optional["BlockedSignalTelemetry"] = None,
    ):
        self.config = config or CooldownConfig()
        self.manager = manager or CooldownManager()
        self._trading_mode_manager = trading_mode_manager
        self._blocked_signal_telemetry = blocked_signal_telemetry
        self._trace_enabled = os.getenv("COOLDOWN_TRACE", "").lower() in {"1", "true"}
    
    def _get_mode_config(self, symbol: str):
        """Get mode-specific config for symbol."""
        if self._trading_mode_manager:
            return self._trading_mode_manager.get_config(symbol)
        return None
    
    async def run(self, ctx: StageContext) -> StageResult:
        reasons = []
        metrics = {}
        
        # Exit signals bypass cooldown (Requirement 8.2, 8.3)
        signal = ctx.signal
        if signal:
            if isinstance(signal, dict):
                is_exit = signal.get("is_exit_signal", False) or signal.get("reduce_only", False)
                pnl_pct = signal.get("pnl_pct")  # Get P&L if available
                exit_reason = signal.get("meta_reason") or signal.get("exit_reason") or signal.get("exit_type")
            else:
                is_exit = getattr(signal, "is_exit_signal", False) or getattr(signal, "reduce_only", False)
                pnl_pct = getattr(signal, "pnl_pct", None)
                exit_reason = getattr(signal, "meta_reason", None) or getattr(signal, "exit_reason", None) or getattr(signal, "exit_type", None)
            
            if is_exit:
                # Record exit for hysteresis with P&L for reduction
                self.manager.record_exit(ctx.symbol, pnl_pct=pnl_pct, exit_reason=exit_reason)
                if self._trace_enabled:
                    log_info(
                        "cooldown_exit_recorded",
                        symbol=ctx.symbol,
                        pnl_pct=pnl_pct,
                        bypassed_cooldown=True,
                    )
                return StageResult.CONTINUE
        
        # Get candidate for strategy/side info
        candidate = ctx.data.get("candidate")
        if not candidate:
            # No candidate, nothing to check cooldown for
            return StageResult.CONTINUE
        
        symbol = ctx.symbol
        strategy_id = candidate.strategy_id
        side = candidate.side
        
        # Get mode-specific config (Requirement 2.1, 4.1)
        mode_config = self._get_mode_config(symbol)
        
        # Get cooldown parameters - use mode config if available, else fall back to static config
        if mode_config:
            entry_cooldown_sec = mode_config.entry_cooldown_sec
            exit_cooldown_sec = mode_config.exit_cooldown_sec
            same_direction_hysteresis_sec = mode_config.same_direction_hysteresis_sec
            max_entries_per_hour = mode_config.max_entries_per_hour
            metrics["trading_mode"] = mode_config.mode.value
        else:
            # Fall back to strategy-specific or default cooldown
            entry_cooldown_sec = self.config.strategy_cooldowns.get(
                strategy_id,
                self.config.default_entry_cooldown_sec
            )
            exit_cooldown_sec = self.config.exit_cooldown_sec
            same_direction_hysteresis_sec = self.config.same_direction_hysteresis_sec
            max_entries_per_hour = self.config.max_entries_per_hour
        
        # =================================================================
        # Check 1: Time since last entry (per symbol/strategy)
        # =================================================================
        time_since_entry = self.manager.get_time_since_entry(symbol, strategy_id)
        if time_since_entry is not None:
            metrics["time_since_entry_sec"] = time_since_entry
            if time_since_entry < entry_cooldown_sec:
                remaining = entry_cooldown_sec - time_since_entry
                reasons.append(f"entry_cooldown:{remaining:.0f}s_remaining")
        
        # =================================================================
        # Check 2: Time since last exit (per symbol)
        # =================================================================
        time_since_exit = self.manager.get_time_since_exit(symbol)
        if time_since_exit is not None:
            metrics["time_since_exit_sec"] = time_since_exit
            effective_exit_cooldown = exit_cooldown_sec
            if self.manager.was_last_exit_stop_out(symbol):
                effective_exit_cooldown = max(exit_cooldown_sec, self.config.stop_out_cooldown_sec)
                metrics["stop_out_cooldown_sec"] = effective_exit_cooldown
            if time_since_exit < effective_exit_cooldown:
                remaining = effective_exit_cooldown - time_since_exit
                reasons.append(f"exit_cooldown:{remaining:.0f}s_remaining")
        
        # =================================================================
        # Check 3: Hysteresis for same-direction re-entry (Requirement 2.3)
        # Reduce hysteresis by 50% if last trade was profitable
        # =================================================================
        last_direction = self.manager.get_last_direction(symbol)
        if last_direction == side and time_since_entry is not None:
            # Apply 50% reduction if last trade was profitable (Requirement 2.3)
            effective_hysteresis = same_direction_hysteresis_sec
            last_trade_profitable = self.manager.was_last_trade_profitable(symbol)
            if last_trade_profitable:
                effective_hysteresis *= 0.5
                metrics["hysteresis_reduced"] = True
                metrics["last_trade_pnl"] = self.manager.get_last_trade_pnl(symbol)
            
            if time_since_entry < effective_hysteresis:
                remaining = effective_hysteresis - time_since_entry
                reasons.append(f"same_direction_hysteresis:{remaining:.0f}s_remaining")
                metrics["effective_hysteresis_sec"] = effective_hysteresis
        
        # =================================================================
        # Check 4: Hourly entry rate limit (Requirement 4.1, 4.2, 4.3)
        # =================================================================
        if max_entries_per_hour > 0:
            hourly_count = self.manager.get_hourly_entry_count(symbol)
            metrics["hourly_entry_count"] = hourly_count
            metrics["max_entries_per_hour"] = max_entries_per_hour
            if hourly_count >= max_entries_per_hour:
                reasons.append(f"hourly_limit_reached:{hourly_count}>={max_entries_per_hour}")
        
        if reasons:
            return self._reject(ctx, reasons, metrics)
        
        # Record this entry attempt (will be confirmed by execution stage)
        # Note: We record here optimistically. If the trade is rejected later,
        # we still count it for rate limiting (conservative approach)
        self.manager.record_entry(symbol, strategy_id, side)
        
        # Store gate decision for telemetry
        ctx.data["gate_decisions"] = ctx.data.get("gate_decisions") or []
        ctx.data["gate_decisions"].append(GateDecision(
            allowed=True,
            gate_name=self.name,
            reasons=[],
            metrics=metrics,
        ))
        
        if self._trace_enabled:
            log_info(
                "cooldown_pass",
                symbol=symbol,
                strategy_id=strategy_id,
                side=side,
                metrics=metrics,
            )
        
        return StageResult.CONTINUE
    
    def _reject(self, ctx: StageContext, reasons: list, metrics: dict) -> StageResult:
        """Record rejection and return REJECT result."""
        ctx.rejection_reason = reasons[0] if reasons else "cooldown_active"
        ctx.rejection_stage = self.name
        ctx.rejection_detail = {
            "reasons": reasons,
            "metrics": metrics,
        }
        
        # Store gate decision for telemetry
        ctx.data["gate_decisions"] = ctx.data.get("gate_decisions") or []
        ctx.data["gate_decisions"].append(GateDecision(
            allowed=False,
            gate_name=self.name,
            reasons=reasons,
            metrics=metrics,
        ))
        
        if self._trace_enabled:
            log_warning(
                "cooldown_reject",
                symbol=ctx.symbol,
                reasons=reasons,
                metrics=metrics,
            )
        
        # Emit blocked signal telemetry (Requirement 9.2)
        if self._blocked_signal_telemetry:
            # Determine the specific gate type based on reasons
            gate_name = "cooldown"  # Default
            for reason in reasons:
                if "hysteresis" in reason:
                    gate_name = "hysteresis"
                    break
                elif "hourly_limit" in reason:
                    gate_name = "hourly_limit"
                    break
            
            # Use asyncio to run the async method (we're in a sync context)
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Schedule the coroutine to run
                    asyncio.create_task(
                        self._blocked_signal_telemetry.record_blocked(
                            symbol=ctx.symbol,
                            gate_name=gate_name,
                            reason=reasons[0] if reasons else "cooldown_active",
                            metrics=metrics,
                        )
                    )
            except RuntimeError:
                pass  # No event loop, skip telemetry
        
        return StageResult.REJECT
