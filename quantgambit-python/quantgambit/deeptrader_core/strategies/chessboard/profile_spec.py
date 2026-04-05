"""
Chessboard Profile Specifications

Formal typed specifications for the 20 canonical market structure patterns.
Each profile defines setup conditions, entry/exit logic, risk parameters, and lifecycle state.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from datetime import datetime
from pathlib import Path
import json


# ═══════════════════════════════════════════════════════════════
# TIME BUDGET CONFIGURATION (MFT Scalping)
# ═══════════════════════════════════════════════════════════════

class StrategyFamily(Enum):
    """Strategy family for time budget defaults."""
    MICROSTRUCTURE = "microstructure"  # L1/L2 imbalance, queue games
    MOMENTUM = "momentum"  # Short momentum / breakout scalps
    MEAN_REVERSION = "mean_reversion"  # Fade back to micro-POC
    POC_ROTATION = "poc_rotation"  # Rotation to POC / value magnet
    TREND = "trend"  # Trend following


@dataclass(frozen=True)
class TimeBudgetDefaults:
    """Default time budgets per strategy family.
    
    Based on battle-tested MFT scalping rules:
    - Microstructure: 0.3s-5s holds, single-digit seconds
    - Momentum: 2s-20s holds
    - Mean reversion: 5s-60s holds
    - POC rotation: 15s-180s holds
    """
    min_hold_sec: float
    time_to_work_sec: float  # T_work: time to first progress
    max_hold_sec: float
    mfe_min_bps: float  # Minimum favorable excursion expected quickly


# Default time budgets per strategy family
TIME_BUDGET_DEFAULTS: Dict[StrategyFamily, TimeBudgetDefaults] = {
    StrategyFamily.MICROSTRUCTURE: TimeBudgetDefaults(
        min_hold_sec=0.3,
        time_to_work_sec=2.0,
        max_hold_sec=12.0,
        mfe_min_bps=2.0,  # +2 bps net progress
    ),
    StrategyFamily.MOMENTUM: TimeBudgetDefaults(
        min_hold_sec=1.0,
        time_to_work_sec=6.0,
        max_hold_sec=45.0,
        mfe_min_bps=3.0,
    ),
    StrategyFamily.MEAN_REVERSION: TimeBudgetDefaults(
        min_hold_sec=3.0,
        time_to_work_sec=20.0,
        max_hold_sec=120.0,
        mfe_min_bps=3.0,
    ),
    StrategyFamily.POC_ROTATION: TimeBudgetDefaults(
        min_hold_sec=5.0,
        time_to_work_sec=30.0,
        max_hold_sec=180.0,
        mfe_min_bps=5.0,
    ),
    StrategyFamily.TREND: TimeBudgetDefaults(
        min_hold_sec=5.0,
        time_to_work_sec=30.0,
        max_hold_sec=300.0,  # 5 minutes for trend following
        mfe_min_bps=5.0,
    ),
}


def get_time_budget_for_strategy(strategy_id: str) -> TimeBudgetDefaults:
    """Get time budget defaults based on strategy ID.
    
    Maps strategy IDs to their family for time budget defaults.
    """
    # Strategy ID to family mapping
    strategy_family_map = {
        # Microstructure
        "spread_compression": StrategyFamily.MICROSTRUCTURE,
        "spread_compression_scalp": StrategyFamily.MICROSTRUCTURE,
        "low_vol_grind": StrategyFamily.MICROSTRUCTURE,
        # Momentum
        "breakout_scalp": StrategyFamily.MOMENTUM,
        "vol_expansion": StrategyFamily.MOMENTUM,
        "high_vol_breakout": StrategyFamily.MOMENTUM,
        "us_open_momentum": StrategyFamily.MOMENTUM,
        "momentum_ignition": StrategyFamily.MOMENTUM,
        # Mean reversion
        "mean_reversion_fade": StrategyFamily.MEAN_REVERSION,
        "vwap_reversion": StrategyFamily.MEAN_REVERSION,
        # POC rotation
        "poc_magnet_scalp": StrategyFamily.POC_ROTATION,
        "amt_value_area_rejection_scalp": StrategyFamily.POC_ROTATION,
        # Trend
        "trend_pullback": StrategyFamily.TREND,
    }
    
    family = strategy_family_map.get(strategy_id, StrategyFamily.MEAN_REVERSION)
    return TIME_BUDGET_DEFAULTS[family]


# ═══════════════════════════════════════════════════════════════
# LIFECYCLE STATES
# ═══════════════════════════════════════════════════════════════

class ProfileLifecycleState(Enum):
    """Lifecycle states for a profile"""
    WARMING = "warming"  # Collecting data, not yet active
    ACTIVE = "active"  # Fully operational, can generate signals
    COOLING = "cooling"  # Winding down, no new positions
    DISABLED = "disabled"  # Turned off, no activity
    ERROR = "error"  # Error state, needs intervention


# ═══════════════════════════════════════════════════════════════
# PROFILE SPECIFICATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class ProfileConditions:
    """Setup conditions that must be met for profile activation"""
    # Trend conditions
    min_trend_strength: Optional[float] = None  # EMA spread threshold
    max_trend_strength: Optional[float] = None
    required_trend: Optional[str] = None  # 'up', 'down', 'flat'
    
    # Volatility conditions
    min_volatility: Optional[float] = None  # ATR ratio threshold
    max_volatility: Optional[float] = None
    required_volatility: Optional[str] = None  # 'low', 'normal', 'high'
    
    # Value area conditions
    required_value_location: Optional[str] = None  # 'above', 'below', 'inside'
    min_distance_from_vah: Optional[float] = None  # Basis points
    min_distance_from_val: Optional[float] = None
    min_distance_from_poc: Optional[float] = None
    
    # Session conditions
    required_session: Optional[str] = None  # 'asia', 'europe', 'us', 'overnight'
    allowed_sessions: Optional[List[str]] = None
    
    # Risk mode conditions
    required_risk_mode: Optional[str] = None  # 'normal', 'protection', 'recovery', 'off'

    # Regime conditions
    allowed_regimes: Optional[List[str]] = None  # 'trend', 'mean_revert', 'avoid' or 'range', 'breakout', 'squeeze', 'chop'
    
    # Microstructure conditions
    min_spread: Optional[float] = None  # Basis points
    max_spread: Optional[float] = None
    min_trades_per_second: Optional[float] = None
    min_orderbook_depth: Optional[float] = None  # USD
    
    # Rotation conditions
    min_rotation_factor: Optional[float] = None
    max_rotation_factor: Optional[float] = None
    
    # === Symbol-Adaptive Multiplier Fields ===
    # These take precedence over absolute fields when set (Requirement 3.8)
    # See: .kiro/specs/symbol-adaptive-parameters/requirements.md
    
    # Spread threshold as multiplier of typical spread
    # Requirement 3.8: Multiplier-based condition fields for profile matching
    max_spread_typical_multiplier: Optional[float] = None
    
    # Distance from POC as multiplier of daily range (ATR-based)
    # Requirement 3.8: Multiplier-based condition fields for profile matching
    min_distance_from_poc_atr_multiplier: Optional[float] = None


@dataclass
class ProfileRiskParameters:
    """Risk parameters for a profile"""
    # Position sizing
    risk_per_trade_pct: float = 0.01  # Decimal % of account per trade
    max_leverage: float = 1.0
    
    # Position limits
    max_positions_per_symbol: int = 1
    max_total_positions: int = 4
    
    # Stop loss / take profit (Phase 3: Adaptive Adjustments)
    stop_loss_pct: float = 0.01  # 1% default
    take_profit_pct: Optional[float] = None  # None = use strategy logic
    sl_tp_policy: str = "static"  # "static", "trailing", "adaptive"
    trailing_stop_trigger_pct: Optional[float] = None  # % profit before trailing starts
    trailing_stop_distance_pct: Optional[float] = None  # Distance to trail behind price
    adaptive_sl_use_atr: bool = False  # Use ATR for dynamic SL placement
    adaptive_sl_atr_multiplier: float = 2.0  # ATR multiplier for SL distance
    adaptive_tp_use_value_area: bool = False  # Use VAH/VAL for TP targets
    
    # Time limits (legacy - use time_budget for MFT scalping)
    max_hold_time_seconds: Optional[float] = None
    min_hold_time_seconds: Optional[float] = None
    
    # Time budget for MFT scalping (see docs/MEDIUM_FREQUENCY_EXCELLENCE_PLAN.md)
    # T_work: Time to first progress - if no MFE_min by T_work, scratch/de-risk
    time_to_work_sec: Optional[float] = None
    # MFE_min: Minimum favorable excursion expected quickly (in bps, net of spread)
    mfe_min_bps: Optional[float] = None
    # Expected horizon: How long the signal is expected to be valid
    expected_horizon_sec: Optional[float] = None
    # Regime multipliers for time budgets
    time_budget_shock_multiplier: float = 0.5  # Shrink holds in chaos
    time_budget_trend_multiplier: float = 1.2  # Extend slightly in clean trends (trend strats only)
    
    # Risk budget
    daily_risk_budget_usd: Optional[float] = None  # Max loss per day for this profile
    max_drawdown_pct: Optional[float] = None  # Max drawdown before disable
    
    # === Symbol-Adaptive Multiplier Fields ===
    # These take precedence over absolute fields when set (Requirement 3.7)
    # See: .kiro/specs/symbol-adaptive-parameters/requirements.md
    
    # Distance thresholds (multiplied by typical_daily_range_pct)
    # Requirement 3.2: POC distance threshold as multiplier of daily range
    poc_distance_atr_multiplier: Optional[float] = None
    # Requirement 3.5: Stop loss as multiplier of daily range
    stop_loss_atr_multiplier: Optional[float] = None
    # Requirement 3.6: Take profit as multiplier of daily range
    take_profit_atr_multiplier: Optional[float] = None
    
    # Spread thresholds (multiplied by typical_spread_bps)
    # Requirement 3.3: Spread threshold as multiplier of typical spread
    spread_typical_multiplier: Optional[float] = None
    
    # Depth thresholds (multiplied by typical_depth_usd)
    # Requirement 3.4: Depth threshold as multiplier of typical depth
    depth_typical_multiplier: Optional[float] = None


@dataclass
class ProfileLifecycle:
    """Lifecycle management for a profile"""
    # Warm-up phase
    warmup_duration_seconds: float = 300.0  # 5 minutes default
    warmup_data_points_required: int = 100  # Min data points before activation
    
    # Cool-down phase
    cooldown_duration_seconds: float = 60.0  # 1 minute default
    cooldown_close_positions: bool = True  # Close positions during cooldown
    
    # Auto-disable conditions
    disable_after_consecutive_losses: Optional[int] = None
    disable_after_drawdown_pct: Optional[float] = None
    disable_after_error_count: Optional[int] = 3
    
    # Re-enable conditions
    reenable_after_seconds: Optional[float] = 3600.0  # 1 hour default
    reenable_requires_manual: bool = False


@dataclass
class ProfileSpec:
    """Complete specification for a chessboard profile"""
    # Identity
    id: str
    name: str
    description: str
    version: str = "1.0.0"
    
    # Conditions
    conditions: ProfileConditions = field(default_factory=ProfileConditions)
    
    # Risk parameters
    risk: ProfileRiskParameters = field(default_factory=ProfileRiskParameters)
    
    # Lifecycle
    lifecycle: ProfileLifecycle = field(default_factory=ProfileLifecycle)
    
    # Strategy mapping
    strategy_ids: List[str] = field(default_factory=list)  # Strategies to use
    strategy_params: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # Per-strategy params
    
    # Performance tracking
    min_win_rate: float = 0.45  # Disable if win rate drops below this
    min_profit_factor: float = 1.0  # Disable if profit factor drops below this
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    author: str = "system"
    tags: List[str] = field(default_factory=list)
    
    def apply_overrides(self, overrides: Dict[str, Any]) -> "ProfileSpec":
        """Apply parameter overrides from backtest config.
        
        Returns a new ProfileSpec with overridden risk parameters.
        Only risk parameters can be overridden (not conditions or lifecycle).
        """
        import os
        from copy import deepcopy
        
        # Check for env var overrides first (set by backtest executor)
        env_overrides = {}
        for key in dir(self.risk):
            if key.startswith('_'):
                continue
            env_key = f"PROFILE_OVERRIDE_{key.upper()}"
            if env_key in os.environ:
                try:
                    value = os.environ[env_key]
                    # Try to parse as float, then int, then bool, then string
                    if '.' in value:
                        env_overrides[key] = float(value)
                    elif value.lower() in ('true', 'false'):
                        env_overrides[key] = value.lower() == 'true'
                    else:
                        try:
                            env_overrides[key] = int(value)
                        except ValueError:
                            env_overrides[key] = value
                except (ValueError, AttributeError):
                    pass
        
        # Merge explicit overrides with env overrides (explicit takes precedence)
        all_overrides = {**env_overrides, **overrides}
        
        if not all_overrides:
            return self
        
        # Create a copy with overridden risk parameters
        new_spec = deepcopy(self)
        for key, value in all_overrides.items():
            if hasattr(new_spec.risk, key):
                setattr(new_spec.risk, key, value)
        
        return new_spec


# ═══════════════════════════════════════════════════════════════
# PROFILE INSTANCE (RUNTIME STATE)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ProfileInstance:
    """Runtime instance of a profile for a specific symbol"""
    spec: ProfileSpec
    symbol: str
    
    # State
    state: ProfileLifecycleState = ProfileLifecycleState.WARMING
    state_entered_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Warm-up tracking
    warmup_data_points: int = 0
    warmup_started_at: Optional[datetime] = None
    
    # Performance tracking
    trades_count: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    consecutive_losses: int = 0
    max_drawdown: float = 0.0
    
    # Error tracking
    error_count: int = 0
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    
    # Positions
    open_positions: List[str] = field(default_factory=list)  # Position IDs
    
    def can_trade(self) -> bool:
        """
        Check if profile can currently trade
        
        NOTE: Lifecycle state is NOT used to block trading anymore.
        Data readiness is validated by DataReadinessStage before profile routing.
        This method is kept for backward compatibility but always returns True
        unless profile is DISABLED or ERROR (for auto-disable/error handling).
        """
        return self.state not in [ProfileLifecycleState.DISABLED, ProfileLifecycleState.ERROR]
    
    def can_generate_signals(self) -> bool:
        """
        Check if profile can generate new trading signals
        
        NOTE: Lifecycle state is NOT used to block signal generation anymore.
        Data readiness is validated by DataReadinessStage before profile routing.
        This method is kept for backward compatibility but always returns True
        unless profile is DISABLED or ERROR (for auto-disable/error handling).
        """
        return self.state not in [ProfileLifecycleState.DISABLED, ProfileLifecycleState.ERROR]
    
    def can_close_positions(self) -> bool:
        """Check if profile can close existing positions"""
        # Can close in ACTIVE or COOLING states
        return self.state in [ProfileLifecycleState.ACTIVE, ProfileLifecycleState.COOLING]
    
    def can_open_position(self) -> bool:
        """Check if profile can open new position"""
        if not self.can_trade():
            return False
        
        # Check position limits
        if len(self.open_positions) >= self.spec.risk.max_positions_per_symbol:
            return False
        
        return True
    
    def update_lifecycle(self, current_time: float) -> None:
        """
        Update lifecycle state based on time and conditions
        
        Args:
            current_time: Current timestamp (seconds since epoch)
        """
        # Convert datetime to timestamp for comparison
        state_entered_timestamp = self.state_entered_at.timestamp()
        time_in_state = current_time - state_entered_timestamp
        
        # Handle WARMING → ACTIVE transition
        if self.state == ProfileLifecycleState.WARMING:
            if self.warmup_started_at:
                warmup_elapsed = current_time - self.warmup_started_at.timestamp()
                if warmup_elapsed >= self.spec.lifecycle.warmup_duration_seconds:
                    self.transition_to(ProfileLifecycleState.ACTIVE, "Warmup complete")
        
        # Handle COOLING → DISABLED transition
        elif self.state == ProfileLifecycleState.COOLING:
            if len(self.open_positions) == 0:
                self.transition_to(ProfileLifecycleState.DISABLED, "All positions closed")
            elif self.spec.lifecycle.cooldown_duration_seconds:
                if time_in_state >= self.spec.lifecycle.cooldown_duration_seconds:
                    # Force disable even if positions remain (emergency)
                    self.transition_to(ProfileLifecycleState.DISABLED, "Cooldown timeout - force disabled")
    
    def record_trade(self, pnl: float) -> None:
        """Record trade result"""
        self.trades_count += 1
        self.total_pnl += pnl
        self.updated_at = datetime.utcnow()
        
        if pnl > 0:
            self.wins += 1
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.consecutive_losses += 1
        
        # Update max drawdown
        if pnl < 0:
            self.max_drawdown = min(self.max_drawdown, pnl)
        
        # Check auto-disable conditions
        self._check_auto_disable()
    
    def record_trade_outcome(self, is_win: bool, pnl: float) -> None:
        """
        Record trade outcome and update metrics
        
        Args:
            is_win: Whether the trade was profitable
            pnl: Profit/loss amount
        """
        self.record_trade(pnl)
    
    def record_error(self, error: str) -> None:
        """Record error"""
        self.error_count += 1
        self.last_error = error
        self.last_error_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        
        # Check auto-disable
        if (self.spec.lifecycle.disable_after_error_count and 
            self.error_count >= self.spec.lifecycle.disable_after_error_count):
            self.transition_to(
                ProfileLifecycleState.DISABLED,
                f"Error count exceeded: {self.error_count}"
            )
    
    def transition_to(self, new_state: ProfileLifecycleState, reason: str = "") -> None:
        """
        Transition to new lifecycle state
        
        Args:
            new_state: Target lifecycle state
            reason: Reason for transition (for audit trail)
        """
        old_state = self.state
        self.state = new_state
        self.state_entered_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        
        reason_str = f" - {reason}" if reason else ""
        print(f"🔄 Profile {self.spec.id} ({self.symbol}): {old_state.value} → {new_state.value}{reason_str}")
        
        # Handle state-specific logic
        if new_state == ProfileLifecycleState.COOLING:
            if self.spec.lifecycle.cooldown_close_positions:
                # Signal to close all positions
                pass  # Handled by caller
        
        elif new_state == ProfileLifecycleState.DISABLED:
            # Clear any remaining position references (should be empty)
            if len(self.open_positions) > 0:
                print(f"⚠️  Profile {self.spec.id} disabled with {len(self.open_positions)} open positions")
    
    def check_auto_disable(self) -> bool:
        """
        Check if auto-disable conditions are met
        
        Returns:
            True if profile was auto-disabled, False otherwise
        """
        return self._check_auto_disable()
    
    def _check_auto_disable(self) -> bool:
        """
        Internal method to check and apply auto-disable conditions
        
        Returns:
            True if profile was disabled, False otherwise
        """
        # Only check if profile is ACTIVE
        if self.state != ProfileLifecycleState.ACTIVE:
            return False
        
        # Consecutive losses
        if (self.spec.lifecycle.disable_after_consecutive_losses and
            self.consecutive_losses >= self.spec.lifecycle.disable_after_consecutive_losses):
            self.transition_to(
                ProfileLifecycleState.DISABLED,
                f"Consecutive losses: {self.consecutive_losses}"
            )
            return True
        
        # Drawdown
        if (self.spec.lifecycle.disable_after_drawdown_pct and
            self.max_drawdown < -self.spec.lifecycle.disable_after_drawdown_pct * 100):
            self.transition_to(
                ProfileLifecycleState.DISABLED,
                f"Max drawdown exceeded: {self.max_drawdown:.2f}"
            )
            return True
        
        # Win rate (need minimum sample size)
        if self.trades_count >= 20:
            win_rate = self.get_win_rate()
            if win_rate < self.spec.min_win_rate:
                self.transition_to(
                    ProfileLifecycleState.DISABLED,
                    f"Low win rate: {win_rate:.1%} < {self.spec.min_win_rate:.1%}"
                )
                return True
        
        # Profit factor (need minimum sample size)
        if self.trades_count >= 20:
            profit_factor = self.get_profit_factor()
            if profit_factor < self.spec.min_profit_factor:
                self.transition_to(
                    ProfileLifecycleState.DISABLED,
                    f"Low profit factor: {profit_factor:.2f} < {self.spec.min_profit_factor:.2f}"
                )
                return True
        
        return False
    
    def get_win_rate(self) -> float:
        """Calculate current win rate"""
        if self.trades_count == 0:
            return 0.0
        return self.wins / self.trades_count
    
    def get_profit_factor(self) -> float:
        """Calculate current profit factor"""
        if self.trades_count == 0:
            return 0.0
        
        # Simplified - in reality would track individual trade PnLs
        if self.total_pnl > 0:
            return float('inf')  # All wins
        elif self.total_pnl < 0:
            return 0.0  # All losses
        return 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize instance to dictionary for persistence
        
        Returns:
            Dictionary representation of instance state
        """
        return {
            'profile_id': self.spec.id,
            'symbol': self.symbol,
            'state': self.state.value,
            'state_entered_at': self.state_entered_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'warmup_data_points': self.warmup_data_points,
            'warmup_started_at': self.warmup_started_at.isoformat() if self.warmup_started_at else None,
            'trades_count': self.trades_count,
            'wins': self.wins,
            'losses': self.losses,
            'total_pnl': self.total_pnl,
            'consecutive_losses': self.consecutive_losses,
            'max_drawdown': self.max_drawdown,
            'error_count': self.error_count,
            'last_error': self.last_error,
            'last_error_at': self.last_error_at.isoformat() if self.last_error_at else None,
            'open_positions': self.open_positions,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], spec: ProfileSpec) -> 'ProfileInstance':
        """
        Deserialize instance from dictionary
        
        Args:
            data: Dictionary representation
            spec: Profile specification
            
        Returns:
            ProfileInstance
        """
        instance = cls(spec=spec, symbol=data['symbol'])
        
        # Restore state
        instance.state = ProfileLifecycleState(data['state'])
        instance.state_entered_at = datetime.fromisoformat(data['state_entered_at'])
        instance.updated_at = datetime.fromisoformat(data['updated_at'])
        
        # Restore warm-up tracking
        instance.warmup_data_points = data.get('warmup_data_points', 0)
        if data.get('warmup_started_at'):
            instance.warmup_started_at = datetime.fromisoformat(data['warmup_started_at'])
        
        # Restore performance metrics
        instance.trades_count = data.get('trades_count', 0)
        instance.wins = data.get('wins', 0)
        instance.losses = data.get('losses', 0)
        instance.total_pnl = data.get('total_pnl', 0.0)
        instance.consecutive_losses = data.get('consecutive_losses', 0)
        instance.max_drawdown = data.get('max_drawdown', 0.0)
        
        # Restore error tracking
        instance.error_count = data.get('error_count', 0)
        instance.last_error = data.get('last_error')
        if data.get('last_error_at'):
            instance.last_error_at = datetime.fromisoformat(data['last_error_at'])
        
        # Restore positions
        instance.open_positions = data.get('open_positions', [])
        
        return instance


# ═══════════════════════════════════════════════════════════════
# PROFILE REGISTRY
# ═══════════════════════════════════════════════════════════════

class ProfileRegistry:
    """
    Central registry of profile specifications
    
    Usage:
        registry = ProfileRegistry()
        registry.register(profile_spec)
        spec = registry.get("micro_range_mean_reversion")
    """
    
    def __init__(self):
        self._specs: Dict[str, ProfileSpec] = {}
        self._instances: Dict[tuple, ProfileInstance] = {}  # (profile_id, symbol) -> instance
    
    def register(self, spec: ProfileSpec) -> None:
        """Register a profile specification"""
        self._specs[spec.id] = spec
        print(f"✅ Registered profile: {spec.id} - {spec.name}")
    
    def get_spec(self, profile_id: str) -> Optional[ProfileSpec]:
        """Get profile specification by ID"""
        return self._specs.get(profile_id)
    
    def get_instance(self, profile_id: str, symbol: str) -> Optional[ProfileInstance]:
        """Get profile instance for symbol"""
        return self._instances.get((profile_id, symbol))
    
    def create_instance(self, profile_id: str, symbol: str) -> ProfileInstance:
        """Create new profile instance for symbol"""
        spec = self.get_spec(profile_id)
        if not spec:
            raise ValueError(f"Profile spec not found: {profile_id}")
        
        instance = ProfileInstance(spec=spec, symbol=symbol)
        self._instances[(profile_id, symbol)] = instance
        
        # If warmup duration is 0, immediately activate (for testing)
        if spec.lifecycle.warmup_duration_seconds == 0:
            instance.transition_to(ProfileLifecycleState.ACTIVE, "Immediate activation (warmup=0)")
        else:
            # Start warm-up phase (proper lifecycle)
            instance.warmup_started_at = datetime.utcnow()
            instance.transition_to(ProfileLifecycleState.WARMING, "Starting warmup phase")
        
        return instance
    
    def get_or_create_instance(self, profile_id: str, symbol: str) -> ProfileInstance:
        """Get existing instance or create new one"""
        instance = self.get_instance(profile_id, symbol)
        if instance is None:
            instance = self.create_instance(profile_id, symbol)
        return instance
    
    def list_specs(self) -> List[ProfileSpec]:
        """List all registered profile specs"""
        return list(self._specs.values())
    
    def list_instances(self, symbol: Optional[str] = None) -> List[ProfileInstance]:
        """List all profile instances, optionally filtered by symbol"""
        instances = list(self._instances.values())
        if symbol:
            instances = [i for i in instances if i.symbol == symbol]
        return instances
    
    def get_active_instances(self, symbol: Optional[str] = None) -> List[ProfileInstance]:
        """Get all ACTIVE profile instances"""
        instances = self.list_instances(symbol)
        return [i for i in instances if i.state == ProfileLifecycleState.ACTIVE]
    
    def update_all_lifecycles(self, symbol: str, current_time: float) -> None:
        """Update lifecycle states for all instances of a symbol"""
        instances = self.list_instances(symbol)
        for instance in instances:
            instance.update_lifecycle(current_time)
    
    def save_state(self, symbol: str, data_dir: str = "data/profiles") -> None:
        """
        Save profile states for a symbol to disk
        
        Args:
            symbol: Symbol to save states for
            data_dir: Directory to save state files
        """
        # Create directory if it doesn't exist
        path = Path(data_dir)
        path.mkdir(parents=True, exist_ok=True)
        
        # Get all instances for symbol
        instances = self.list_instances(symbol)
        
        # Serialize to dict
        state_data = {}
        for instance in instances:
            state_data[instance.spec.id] = instance.to_dict()
        
        # Write to file (atomic write with backup)
        file_path = path / f"{symbol.replace('/', '-')}.json"
        temp_path = path / f"{symbol.replace('/', '-')}.json.tmp"
        backup_path = path / f"{symbol.replace('/', '-')}.json.bak"
        
        try:
            # Write to temp file
            with open(temp_path, 'w') as f:
                json.dump(state_data, f, indent=2)
            
            # Backup existing file if it exists
            if file_path.exists():
                if backup_path.exists():
                    backup_path.unlink()
                file_path.rename(backup_path)
            
            # Move temp to final location
            temp_path.rename(file_path)
            
        except Exception as e:
            print(f"❌ Error saving profile state for {symbol}: {e}")
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()
    
    def load_state(self, symbol: str, data_dir: str = "data/profiles") -> None:
        """
        Load profile states for a symbol from disk
        
        Args:
            symbol: Symbol to load states for
            data_dir: Directory containing state files
        """
        file_path = Path(data_dir) / f"{symbol.replace('/', '-')}.json"
        
        if not file_path.exists():
            return  # No saved state
        
        try:
            with open(file_path, 'r') as f:
                state_data = json.load(f)
            
            # Restore instances
            for profile_id, instance_data in state_data.items():
                spec = self.get_spec(profile_id)
                if not spec:
                    print(f"⚠️  Profile spec not found for {profile_id}, skipping")
                    continue
                
                # Create instance from saved data
                instance = ProfileInstance.from_dict(instance_data, spec)
                self._instances[(profile_id, symbol)] = instance
                
                print(f"✅ Restored profile {profile_id} for {symbol} (state: {instance.state.value})")
        
        except Exception as e:
            print(f"❌ Error loading profile state for {symbol}: {e}")
    
    def save_all_states(self, data_dir: str = "data/profiles") -> None:
        """Save states for all symbols"""
        symbols = set(instance.symbol for instance in self._instances.values())
        for symbol in symbols:
            self.save_state(symbol, data_dir)
    
    def load_all_states(self, data_dir: str = "data/profiles") -> None:
        """Load states for all available symbols"""
        path = Path(data_dir)
        if not path.exists():
            return
        
        for file_path in path.glob("*.json"):
            if file_path.suffix == '.json' and not file_path.stem.endswith('.bak'):
                symbol = file_path.stem.replace('-', '/')
                self.load_state(symbol, data_dir)


# Global registry instance
_profile_registry: Optional[ProfileRegistry] = None


def get_profile_registry() -> ProfileRegistry:
    """Get or create global profile registry"""
    global _profile_registry
    if _profile_registry is None:
        _profile_registry = ProfileRegistry()
    return _profile_registry
