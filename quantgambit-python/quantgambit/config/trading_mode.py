"""
Throttle Mode Configuration.

Defines throttle modes (SCALPING, SPOT, SWING, CONSERVATIVE) with preset parameters
for throttling, cooldowns, and exit behavior. Addresses the compounding
conservative safeguards that block ~80% of valid signals.

Note: This is separate from TRADING_MODE (live/paper) - this controls
the aggressiveness of throttling and gating parameters.

Environment variable: THROTTLE_MODE (default: market-aware; spot defaults to scalping, otherwise swing)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Optional, TYPE_CHECKING

from quantgambit.observability.logger import log_info, log_warning

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from quantgambit.observability.telemetry import TelemetryPipeline, TelemetryContext


class TradingMode(str, Enum):
    """Trading mode presets for different trading styles."""
    SCALPING = "scalping"       # MFT: 12-60 second holds, high frequency
    SPOT = "spot"               # Spot swing/accumulation with active entry cadence
    SWING = "swing"             # Medium: 5-30 minute holds
    CONSERVATIVE = "conservative"  # Low frequency, strict controls


@dataclass
class TradingModeConfig:
    """Configuration parameters for each trading mode.
    
    These parameters control throttling, cooldowns, and exit behavior
    across ExecutionWorker, CooldownStage, and PositionEvaluationStage.
    """
    mode: TradingMode
    
    # Execution throttle (ExecutionWorker)
    min_order_interval_sec: float
    
    # Cooldown parameters (CooldownStage)
    entry_cooldown_sec: float
    exit_cooldown_sec: float
    same_direction_hysteresis_sec: float
    max_entries_per_hour: int
    
    # Exit parameters (PositionEvaluationStage)
    min_hold_time_sec: float
    min_confirmations_for_exit: int
    
    # Fee-aware exit parameters
    min_profit_buffer_bps: float
    fee_check_grace_period_sec: float
    
    # Urgency bypass thresholds
    urgency_bypass_threshold: float  # Bypass fee check if urgency >= this
    confirmation_bypass_count: int   # Bypass fee check if confirmations >= this
    deterioration_force_exit_count: int  # Force exit after N deteriorating ticks
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        result["mode"] = self.mode.value
        return result
    
    @classmethod
    def from_dict(cls, data: Dict) -> "TradingModeConfig":
        """Create from dictionary."""
        data = data.copy()
        data["mode"] = TradingMode(data["mode"])
        return cls(**data)


# Preset configurations for each trading mode
TRADING_MODE_PRESETS: Dict[TradingMode, TradingModeConfig] = {
    TradingMode.SCALPING: TradingModeConfig(
        mode=TradingMode.SCALPING,
        # Execution: 15s between orders (was 60s)
        min_order_interval_sec=15.0,
        # Cooldowns: Aggressive for high-frequency
        entry_cooldown_sec=15.0,
        exit_cooldown_sec=10.0,
        same_direction_hysteresis_sec=30.0,  # Was 120s
        max_entries_per_hour=50,  # Was 10
        # Exits: Quick exits allowed
        min_hold_time_sec=10.0,  # Was 30s
        min_confirmations_for_exit=1,  # Was 2
        # Fee-aware: Relaxed for scalping
        min_profit_buffer_bps=3.0,  # Was 5.0
        fee_check_grace_period_sec=15.0,
        # Urgency bypass: Standard thresholds
        urgency_bypass_threshold=0.8,
        confirmation_bypass_count=3,
        deterioration_force_exit_count=3,
    ),
    TradingMode.SPOT: TradingModeConfig(
        mode=TradingMode.SPOT,
        # Execution: same active cadence as scalping so spot entries are not
        # starved by an arbitrary swing throttle.
        min_order_interval_sec=15.0,
        # Cooldowns: more patient than scalp, still far more active than swing.
        entry_cooldown_sec=45.0,
        exit_cooldown_sec=10.0,
        same_direction_hysteresis_sec=90.0,
        max_entries_per_hour=24,
        # Exits: allow spot exits quickly, but not with scalp churn.
        min_hold_time_sec=60.0,
        min_confirmations_for_exit=1,
        # Fee-aware: slightly more conservative than scalp, below swing.
        min_profit_buffer_bps=4.0,
        fee_check_grace_period_sec=20.0,
        urgency_bypass_threshold=0.8,
        confirmation_bypass_count=3,
        deterioration_force_exit_count=4,
    ),
    TradingMode.SWING: TradingModeConfig(
        mode=TradingMode.SWING,
        # Execution: 60s between orders (current default)
        min_order_interval_sec=60.0,
        # Cooldowns: Moderate
        entry_cooldown_sec=60.0,
        exit_cooldown_sec=30.0,
        same_direction_hysteresis_sec=120.0,
        max_entries_per_hour=10,
        # Exits: Standard hold times
        min_hold_time_sec=30.0,
        min_confirmations_for_exit=2,
        # Fee-aware: Standard buffer
        min_profit_buffer_bps=5.0,
        fee_check_grace_period_sec=30.0,
        # Urgency bypass: Standard thresholds
        urgency_bypass_threshold=0.8,
        confirmation_bypass_count=3,
        deterioration_force_exit_count=5,
    ),
    TradingMode.CONSERVATIVE: TradingModeConfig(
        mode=TradingMode.CONSERVATIVE,
        # Execution: 120s between orders
        min_order_interval_sec=120.0,
        # Cooldowns: Strict
        entry_cooldown_sec=120.0,
        exit_cooldown_sec=60.0,
        same_direction_hysteresis_sec=300.0,
        max_entries_per_hour=6,
        # Exits: Longer hold times
        min_hold_time_sec=60.0,
        min_confirmations_for_exit=2,
        # Fee-aware: Higher buffer
        min_profit_buffer_bps=10.0,
        fee_check_grace_period_sec=60.0,
        # Urgency bypass: Higher thresholds
        urgency_bypass_threshold=0.9,
        confirmation_bypass_count=4,
        deterioration_force_exit_count=7,
    ),
}


def get_preset(mode: TradingMode) -> TradingModeConfig:
    """Get the preset configuration for a trading mode."""
    return TRADING_MODE_PRESETS[mode]


def validate_config(config: TradingModeConfig) -> bool:
    """Validate that a config has valid parameter ranges."""
    if config.min_order_interval_sec <= 0:
        return False
    if config.max_entries_per_hour <= 0:
        return False
    if not (0 < config.urgency_bypass_threshold <= 1.0):
        return False
    if config.deterioration_force_exit_count < 1:
        return False
    if config.min_hold_time_sec < 0:
        return False
    if config.min_confirmations_for_exit < 1:
        return False
    return True



class TradingModeManager:
    """
    Manages trading mode configuration across components.
    
    Provides:
    - Global default mode
    - Per-symbol mode overrides
    - Redis persistence
    - Telemetry on mode changes
    """
    
    def __init__(
        self,
        redis_client: Optional["Redis"] = None,
        bot_id: str = "default",
        default_mode: TradingMode = TradingMode.SWING,
        telemetry: Optional["TelemetryPipeline"] = None,
        telemetry_context: Optional["TelemetryContext"] = None,
    ):
        self._redis = redis_client
        self._bot_id = bot_id
        self._default_mode = default_mode
        self._symbol_overrides: Dict[str, TradingMode] = {}
        self._config_cache: Dict[TradingMode, TradingModeConfig] = {
            mode: config for mode, config in TRADING_MODE_PRESETS.items()
        }
        self._telemetry = telemetry
        self._telemetry_context = telemetry_context
        self._loaded = False
    
    @property
    def default_mode(self) -> TradingMode:
        """Get the current default trading mode."""
        return self._default_mode
    
    @property
    def symbol_overrides(self) -> Dict[str, TradingMode]:
        """Get all symbol-specific mode overrides."""
        return self._symbol_overrides.copy()
    
    def get_mode(self, symbol: Optional[str] = None) -> TradingMode:
        """Get the trading mode for a symbol (or global default)."""
        if symbol and symbol in self._symbol_overrides:
            return self._symbol_overrides[symbol]
        return self._default_mode
    
    def get_config(self, symbol: Optional[str] = None) -> TradingModeConfig:
        """Get trading mode config, with optional symbol override."""
        mode = self.get_mode(symbol)
        return self._config_cache[mode]
    
    async def set_mode(
        self,
        mode: TradingMode,
        symbol: Optional[str] = None,
        persist: bool = True,
    ) -> None:
        """
        Set trading mode globally or per-symbol.
        
        Args:
            mode: The trading mode to set
            symbol: If provided, set mode for this symbol only
            persist: If True, persist to Redis
        """
        old_mode = self.get_mode(symbol)
        
        if symbol:
            self._symbol_overrides[symbol] = mode
            log_info(
                "trading_mode_symbol_override",
                bot_id=self._bot_id,
                symbol=symbol,
                old_mode=old_mode.value,
                new_mode=mode.value,
            )
        else:
            self._default_mode = mode
            log_info(
                "trading_mode_default_changed",
                bot_id=self._bot_id,
                old_mode=old_mode.value,
                new_mode=mode.value,
            )
        
        if persist:
            await self._persist()
        
        await self._emit_mode_change(mode, symbol, old_mode)
    
    async def clear_symbol_override(self, symbol: str, persist: bool = True) -> None:
        """Remove a symbol-specific mode override."""
        if symbol in self._symbol_overrides:
            old_mode = self._symbol_overrides.pop(symbol)
            log_info(
                "trading_mode_override_cleared",
                bot_id=self._bot_id,
                symbol=symbol,
                old_mode=old_mode.value,
                new_mode=self._default_mode.value,
            )
            if persist:
                await self._persist()
    
    async def load(self) -> None:
        """Load persisted mode configuration from Redis."""
        if not self._redis:
            self._loaded = True
            return
        
        try:
            key = self._redis_key()
            data = await self._redis.get(key)
            if data:
                config = json.loads(data)
                self._default_mode = TradingMode(config.get("default_mode", "swing"))
                self._symbol_overrides = {
                    symbol: TradingMode(mode)
                    for symbol, mode in config.get("symbol_overrides", {}).items()
                }
                log_info(
                    "trading_mode_loaded",
                    bot_id=self._bot_id,
                    default_mode=self._default_mode.value,
                    override_count=len(self._symbol_overrides),
                )
            self._loaded = True
        except Exception as e:
            log_warning(
                "trading_mode_load_failed",
                bot_id=self._bot_id,
                error=str(e),
            )
            self._loaded = True
    
    async def _persist(self) -> None:
        """Persist mode configuration to Redis."""
        if not self._redis:
            return
        
        try:
            key = self._redis_key()
            data = {
                "default_mode": self._default_mode.value,
                "symbol_overrides": {
                    symbol: mode.value
                    for symbol, mode in self._symbol_overrides.items()
                },
                "updated_at": time.time(),
            }
            await self._redis.set(key, json.dumps(data))
        except Exception as e:
            log_warning(
                "trading_mode_persist_failed",
                bot_id=self._bot_id,
                error=str(e),
            )
    
    def _redis_key(self) -> str:
        """Get the Redis key for storing mode configuration."""
        return f"quantgambit:{self._bot_id}:config:trading_mode"
    
    async def _emit_mode_change(
        self,
        new_mode: TradingMode,
        symbol: Optional[str],
        old_mode: TradingMode,
    ) -> None:
        """Emit telemetry when mode changes."""
        if not self._telemetry or not self._telemetry_context:
            return
        
        try:
            await self._telemetry.publish_event(
                ctx=self._telemetry_context,
                event_type="trading_mode_changed",
                payload={
                    "bot_id": self._bot_id,
                    "symbol": symbol,
                    "old_mode": old_mode.value,
                    "new_mode": new_mode.value,
                    "timestamp": time.time(),
                },
            )
        except Exception as e:
            log_warning(
                "trading_mode_telemetry_failed",
                bot_id=self._bot_id,
                error=str(e),
            )



def create_trading_mode_manager_from_env(
    redis_client: Optional["Redis"] = None,
    bot_id: Optional[str] = None,
    telemetry: Optional["TelemetryPipeline"] = None,
    telemetry_context: Optional["TelemetryContext"] = None,
) -> TradingModeManager:
    """
    Create a TradingModeManager from environment variables.
    
    Environment variables:
    - THROTTLE_MODE: Default throttle mode (scalping, spot, swing, conservative)
    - MARKET_TYPE: Used only when THROTTLE_MODE is unset; spot defaults to scalping
    - BOT_ID: Bot identifier for Redis key scoping
    
    Note: THROTTLE_MODE is separate from TRADING_MODE (live/paper).
    THROTTLE_MODE controls the aggressiveness of throttling parameters.
    """
    import os
    
    market_type = os.getenv("MARKET_TYPE", "").strip().lower()
    default_throttle_mode = "spot" if market_type == "spot" else "swing"

    # Get throttle mode from env (default is market-aware; spot should not inherit swing cadence)
    throttle_mode_str = os.getenv("THROTTLE_MODE", default_throttle_mode).lower()
    try:
        default_mode = TradingMode(throttle_mode_str)
    except ValueError:
        log_warning(
            "invalid_throttle_mode",
            throttle_mode=throttle_mode_str,
            using_default=default_throttle_mode,
        )
        default_mode = TradingMode(default_throttle_mode)
    
    # Get bot_id from env if not provided
    if bot_id is None:
        bot_id = os.getenv("BOT_ID", "default")
    
    log_info(
        "trading_mode_manager_created",
        bot_id=bot_id,
        default_mode=default_mode.value,
    )
    
    return TradingModeManager(
        redis_client=redis_client,
        bot_id=bot_id,
        default_mode=default_mode,
        telemetry=telemetry,
        telemetry_context=telemetry_context,
    )
