"""
Graceful degradation manager for trading mode transitions.

Trading modes (in order of degradation):
    NORMAL       -> Full trading, normal position sizes
    REDUCE_SIZE  -> Trade but with reduced position sizes (50%)
    NO_ENTRIES   -> No new positions, only manage existing (exits allowed)
    FLATTEN      -> Actively close all positions

Triggers for degradation:
    - Data staleness (per-feed)
    - Data quality score
    - Connectivity issues
    - Market conditions (extreme volatility, thin liquidity)
    - Manual override

The system should NEVER jump directly from NORMAL to FLATTEN without
going through intermediate steps (unless in emergency).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from enum import IntEnum
from typing import Dict, List, Optional, Tuple
import time

from quantgambit.observability.logger import log_info, log_warning


class TradingMode(IntEnum):
    """
    Trading modes in order of degradation severity.
    
    Higher values = more restrictive.
    Using IntEnum for easy comparison: mode >= TradingMode.NO_ENTRIES
    """
    NORMAL = 0           # Full trading
    REDUCE_SIZE = 1      # Reduced position sizes
    NO_ENTRIES = 2       # No new entries, exits OK
    FLATTEN = 3          # Close all positions
    
    def allows_entries(self) -> bool:
        """Check if this mode allows new entries."""
        return self < TradingMode.NO_ENTRIES
    
    def allows_exits(self) -> bool:
        """Check if this mode allows exits (always True)."""
        return True  # Exits always allowed for risk management
    
    def size_multiplier(self) -> float:
        """Get position size multiplier for this mode."""
        if self == TradingMode.NORMAL:
            return 1.0
        elif self == TradingMode.REDUCE_SIZE:
            return 0.5
        else:
            return 0.0  # No new entries


@dataclass
class DegradationConfig:
    """Configuration for degradation thresholds.
    
    Philosophy:
    - FLATTEN is extremely aggressive and should only happen on catastrophic failures
    - For normal staleness/quality issues, use NO_ENTRIES (blocks new trades, allows exits)
    - REDUCE_SIZE is for minor degradation where we can still trade cautiously
    """
    
    # Data staleness thresholds (seconds)
    # Trade feed
    trade_stale_reduce_sec: float = 15.0    # Reduce size after 15s
    trade_stale_no_entry_sec: float = 30.0  # No entries after 30s
    trade_stale_flatten_sec: float = 600.0  # Flatten only after 10 min (catastrophic)
    
    # Orderbook feed
    orderbook_stale_reduce_sec: float = 10.0
    orderbook_stale_no_entry_sec: float = 30.0
    orderbook_stale_flatten_sec: float = 600.0  # Flatten only after 10 min (catastrophic)
    
    # Data quality thresholds
    quality_reduce_threshold: float = 0.5   # Reduce below 50% quality
    quality_no_entry_threshold: float = 0.3 # No entries below 30%
    quality_flatten_threshold: float = 0.05 # Flatten only below 5% (catastrophic)
    
    # Spread thresholds (bps)
    spread_reduce_bps: float = 20.0         # Reduce size if spread > 20 bps
    spread_no_entry_bps: float = 50.0       # No entries if spread > 50 bps
    
    # Depth thresholds (USD)
    depth_reduce_usd: float = 5000.0        # Reduce if depth < $5k per side
    depth_no_entry_usd: float = 1000.0      # No entries if depth < $1k
    
    # Cooldown between mode changes (seconds)
    upgrade_cooldown_sec: float = 60.0      # Wait 60s before upgrading mode
    downgrade_cooldown_sec: float = 0.0     # Immediate downgrades for safety
    
    # Flatten trigger
    # NOTE: False by default - flatten is very aggressive; temporary staleness shouldn't trigger it
    # Use NO_ENTRIES mode instead (via stale thresholds) for data quality issues
    # Only enable this for extreme scenarios (e.g., operator emergency)
    flatten_on_ws_disconnect: bool = False


@dataclass
class DegradationState:
    """Per-symbol degradation state."""
    current_mode: TradingMode = TradingMode.NORMAL
    mode_since: float = field(default_factory=time.time)
    last_evaluation: float = field(default_factory=time.time)
    reasons: List[str] = field(default_factory=list)
    
    # Tracking for hysteresis
    consecutive_healthy_checks: int = 0
    consecutive_unhealthy_checks: int = 0


@dataclass
class DegradationDecision:
    """Result of degradation evaluation."""
    mode: TradingMode
    reasons: List[str]
    size_multiplier: float
    allows_entries: bool
    allows_exits: bool
    should_flatten: bool
    metrics: Dict[str, float]


class DegradationManager:
    """
    Manages trading mode degradation based on data quality and market conditions.
    
    Usage:
        manager = DegradationManager(config)
        
        # Evaluate degradation for a symbol
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 5.0, "orderbook": 2.0},
            data_quality=0.8,
            spread_bps=5.0,
            bid_depth_usd=50000,
            ask_depth_usd=45000,
        )
        
        if not decision.allows_entries:
            # Block new entries
            ...
        
        if decision.should_flatten:
            # Trigger flatten operation
            ...
    """
    
    def __init__(self, config: Optional[DegradationConfig] = None):
        self.config = config or DegradationConfig()
        self._states: Dict[str, DegradationState] = {}
    
    def evaluate(
        self,
        symbol: str,
        feed_staleness: Optional[Dict[str, float]] = None,
        data_quality: Optional[float] = None,
        spread_bps: Optional[float] = None,
        bid_depth_usd: Optional[float] = None,
        ask_depth_usd: Optional[float] = None,
        ws_connected: bool = True,
        manual_override: Optional[TradingMode] = None,
    ) -> DegradationDecision:
        """
        Evaluate degradation state and return recommended trading mode.
        
        Args:
            symbol: Trading symbol
            feed_staleness: Dict of feed_type -> seconds since last update
            data_quality: Overall data quality score (0-1)
            spread_bps: Current spread in basis points
            bid_depth_usd: Bid side depth in USD
            ask_depth_usd: Ask side depth in USD
            ws_connected: Whether WebSocket is connected
            manual_override: Optional manual mode override
        
        Returns:
            DegradationDecision with recommended mode and reasons
        """
        state = self._get_or_create_state(symbol)
        now = time.time()
        
        # Collect degradation reasons
        reasons: List[str] = []
        recommended_modes: List[TradingMode] = []
        metrics: Dict[str, float] = {}
        
        # Manual override takes precedence
        if manual_override is not None:
            reasons.append(f"manual_override:{manual_override.name}")
            recommended_modes.append(manual_override)
        
        # Check WebSocket connectivity
        if not ws_connected and self.config.flatten_on_ws_disconnect:
            reasons.append("ws_disconnected")
            recommended_modes.append(TradingMode.FLATTEN)
        
        # Check feed staleness
        if feed_staleness:
            trade_stale = feed_staleness.get("trade")
            orderbook_stale = feed_staleness.get("orderbook")
            
            if trade_stale is not None:
                metrics["trade_stale_sec"] = trade_stale
                if trade_stale >= self.config.trade_stale_flatten_sec:
                    reasons.append(f"trade_stale_flatten:{trade_stale:.1f}s")
                    recommended_modes.append(TradingMode.FLATTEN)
                elif trade_stale >= self.config.trade_stale_no_entry_sec:
                    reasons.append(f"trade_stale_no_entry:{trade_stale:.1f}s")
                    recommended_modes.append(TradingMode.NO_ENTRIES)
                elif trade_stale >= self.config.trade_stale_reduce_sec:
                    reasons.append(f"trade_stale_reduce:{trade_stale:.1f}s")
                    recommended_modes.append(TradingMode.REDUCE_SIZE)
            
            if orderbook_stale is not None:
                metrics["orderbook_stale_sec"] = orderbook_stale
                if orderbook_stale >= self.config.orderbook_stale_flatten_sec:
                    reasons.append(f"orderbook_stale_flatten:{orderbook_stale:.1f}s")
                    recommended_modes.append(TradingMode.FLATTEN)
                elif orderbook_stale >= self.config.orderbook_stale_no_entry_sec:
                    reasons.append(f"orderbook_stale_no_entry:{orderbook_stale:.1f}s")
                    recommended_modes.append(TradingMode.NO_ENTRIES)
                elif orderbook_stale >= self.config.orderbook_stale_reduce_sec:
                    reasons.append(f"orderbook_stale_reduce:{orderbook_stale:.1f}s")
                    recommended_modes.append(TradingMode.REDUCE_SIZE)
        
        # Check data quality
        if data_quality is not None:
            metrics["data_quality"] = data_quality
            if data_quality < self.config.quality_flatten_threshold:
                reasons.append(f"quality_flatten:{data_quality:.2f}")
                recommended_modes.append(TradingMode.FLATTEN)
            elif data_quality < self.config.quality_no_entry_threshold:
                reasons.append(f"quality_no_entry:{data_quality:.2f}")
                recommended_modes.append(TradingMode.NO_ENTRIES)
            elif data_quality < self.config.quality_reduce_threshold:
                reasons.append(f"quality_reduce:{data_quality:.2f}")
                recommended_modes.append(TradingMode.REDUCE_SIZE)
        
        # Check spread
        if spread_bps is not None:
            metrics["spread_bps"] = spread_bps
            if spread_bps >= self.config.spread_no_entry_bps:
                reasons.append(f"spread_no_entry:{spread_bps:.1f}bps")
                recommended_modes.append(TradingMode.NO_ENTRIES)
            elif spread_bps >= self.config.spread_reduce_bps:
                reasons.append(f"spread_reduce:{spread_bps:.1f}bps")
                recommended_modes.append(TradingMode.REDUCE_SIZE)
        
        # Check depth
        min_depth = None
        if bid_depth_usd is not None and ask_depth_usd is not None:
            min_depth = min(bid_depth_usd, ask_depth_usd)
            metrics["min_depth_usd"] = min_depth
            if min_depth < self.config.depth_no_entry_usd:
                reasons.append(f"depth_no_entry:{min_depth:.0f}")
                recommended_modes.append(TradingMode.NO_ENTRIES)
            elif min_depth < self.config.depth_reduce_usd:
                reasons.append(f"depth_reduce:{min_depth:.0f}")
                recommended_modes.append(TradingMode.REDUCE_SIZE)
        
        # Determine final mode (most restrictive wins)
        if recommended_modes:
            new_mode = max(recommended_modes)  # Higher = more restrictive
        else:
            new_mode = TradingMode.NORMAL
            reasons.append("healthy")
        
        # Apply mode transition logic
        final_mode = self._apply_transition_rules(state, new_mode, now)
        
        # Update state
        if final_mode != state.current_mode:
            old_mode = state.current_mode
            state.current_mode = final_mode
            state.mode_since = now
            log_info(
                "degradation_mode_change",
                symbol=symbol,
                old_mode=old_mode.name,
                new_mode=final_mode.name,
                reasons=reasons,
            )
        
        state.reasons = reasons
        state.last_evaluation = now
        
        return DegradationDecision(
            mode=final_mode,
            reasons=reasons,
            size_multiplier=final_mode.size_multiplier(),
            allows_entries=final_mode.allows_entries(),
            allows_exits=final_mode.allows_exits(),
            should_flatten=(final_mode == TradingMode.FLATTEN),
            metrics=metrics,
        )
    
    def _get_or_create_state(self, symbol: str) -> DegradationState:
        """Get or create state for a symbol."""
        if symbol not in self._states:
            self._states[symbol] = DegradationState()
        return self._states[symbol]
    
    def _apply_transition_rules(
        self,
        state: DegradationState,
        new_mode: TradingMode,
        now: float,
    ) -> TradingMode:
        """
        Apply transition rules for mode changes.
        
        Rules:
        - Downgrades (worse mode) are immediate
        - Upgrades (better mode) require cooldown period
        - Never skip more than one level on upgrade
        """
        current = state.current_mode
        
        if new_mode > current:
            # Downgrade - immediate for safety
            return new_mode
        
        if new_mode < current:
            # Upgrade - apply cooldown
            time_in_current = now - state.mode_since
            if time_in_current < self.config.upgrade_cooldown_sec:
                return current  # Not enough time, stay in current mode
            
            # Only upgrade one level at a time
            if current - new_mode > 1:
                return TradingMode(current - 1)
            
            return new_mode
        
        return current  # No change
    
    def get_mode(self, symbol: str) -> TradingMode:
        """Get current mode for a symbol."""
        if symbol in self._states:
            return self._states[symbol].current_mode
        return TradingMode.NORMAL
    
    def force_mode(self, symbol: str, mode: TradingMode, reason: str = "manual") -> None:
        """Force a specific mode for a symbol."""
        state = self._get_or_create_state(symbol)
        old_mode = state.current_mode
        state.current_mode = mode
        state.mode_since = time.time()
        state.reasons = [f"forced:{reason}"]
        
        if old_mode != mode:
            log_warning(
                "degradation_mode_forced",
                symbol=symbol,
                old_mode=old_mode.name,
                new_mode=mode.name,
                reason=reason,
            )
    
    def reset(self, symbol: Optional[str] = None) -> None:
        """Reset degradation state for a symbol or all symbols."""
        if symbol:
            if symbol in self._states:
                del self._states[symbol]
        else:
            self._states.clear()
    
    def get_status(self) -> Dict[str, Dict]:
        """Get status for all tracked symbols."""
        return {
            symbol: {
                "mode": state.current_mode.name,
                "mode_since": state.mode_since,
                "reasons": state.reasons,
                "allows_entries": state.current_mode.allows_entries(),
                "size_multiplier": state.current_mode.size_multiplier(),
            }
            for symbol, state in self._states.items()
        }


# Singleton instance for global access
_default_manager: Optional[DegradationManager] = None


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).lower() in {"1", "true", "yes"}


def _load_degradation_config_from_env() -> DegradationConfig:
    base = DegradationConfig()
    return DegradationConfig(
        trade_stale_reduce_sec=_env_float("DEGRADATION_TRADE_STALE_REDUCE_SEC", base.trade_stale_reduce_sec),
        trade_stale_no_entry_sec=_env_float("DEGRADATION_TRADE_STALE_NO_ENTRY_SEC", base.trade_stale_no_entry_sec),
        trade_stale_flatten_sec=_env_float("DEGRADATION_TRADE_STALE_FLATTEN_SEC", base.trade_stale_flatten_sec),
        orderbook_stale_reduce_sec=_env_float("DEGRADATION_ORDERBOOK_STALE_REDUCE_SEC", base.orderbook_stale_reduce_sec),
        orderbook_stale_no_entry_sec=_env_float("DEGRADATION_ORDERBOOK_STALE_NO_ENTRY_SEC", base.orderbook_stale_no_entry_sec),
        orderbook_stale_flatten_sec=_env_float("DEGRADATION_ORDERBOOK_STALE_FLATTEN_SEC", base.orderbook_stale_flatten_sec),
        quality_reduce_threshold=_env_float("DEGRADATION_QUALITY_REDUCE_THRESHOLD", base.quality_reduce_threshold),
        quality_no_entry_threshold=_env_float("DEGRADATION_QUALITY_NO_ENTRY_THRESHOLD", base.quality_no_entry_threshold),
        quality_flatten_threshold=_env_float("DEGRADATION_QUALITY_FLATTEN_THRESHOLD", base.quality_flatten_threshold),
        spread_reduce_bps=_env_float("DEGRADATION_SPREAD_REDUCE_BPS", base.spread_reduce_bps),
        spread_no_entry_bps=_env_float("DEGRADATION_SPREAD_NO_ENTRY_BPS", base.spread_no_entry_bps),
        depth_reduce_usd=_env_float("DEGRADATION_DEPTH_REDUCE_USD", base.depth_reduce_usd),
        depth_no_entry_usd=_env_float("DEGRADATION_DEPTH_NO_ENTRY_USD", base.depth_no_entry_usd),
        upgrade_cooldown_sec=_env_float("DEGRADATION_UPGRADE_COOLDOWN_SEC", base.upgrade_cooldown_sec),
        downgrade_cooldown_sec=_env_float("DEGRADATION_DOWNGRADE_COOLDOWN_SEC", base.downgrade_cooldown_sec),
        flatten_on_ws_disconnect=_env_bool("DEGRADATION_FLATTEN_ON_WS_DISCONNECT", base.flatten_on_ws_disconnect),
    )


def get_degradation_manager() -> DegradationManager:
    """Get the default degradation manager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = DegradationManager(_load_degradation_config_from_env())
    return _default_manager


def set_degradation_manager(manager: DegradationManager) -> None:
    """Set the default degradation manager instance."""
    global _default_manager
    _default_manager = manager
