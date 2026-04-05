"""
Loss Prevention Configuration Loader

Loads configuration for loss prevention stages from environment variables
and config files. Supports runtime configuration updates.

Requirements: 1.3 - Load thresholds from config file or environment
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any

from quantgambit.signals.stages.confidence_gate import ConfidenceGateConfig
from quantgambit.signals.stages.strategy_trend_alignment import StrategyTrendAlignmentConfig
from quantgambit.signals.stages.fee_aware_entry import FeeAwareEntryConfig
from quantgambit.signals.stages.session_filter import SessionFilterConfig
from quantgambit.signals.stages.confidence_position_sizer import ConfidencePositionSizerConfig
from quantgambit.signals.stages.ev_gate import EVGateConfig
from quantgambit.signals.stages.ev_position_sizer import EVPositionSizerConfig
from quantgambit.signals.stages.cost_data_quality import CostDataQualityConfig
from quantgambit.signals.stages.global_gate import GlobalGateConfig
from quantgambit.signals.stages.cooldown import CooldownConfig
from quantgambit.observability.logger import log_info, log_warning


def _parse_symbol_float_overrides(raw: str) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for part in (raw or "").split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        symbol, value = token.split(":", 1)
        key = symbol.strip().upper()
        if not key:
            continue
        try:
            parsed = float(value.strip())
        except (TypeError, ValueError):
            continue
        if parsed < 0:
            continue
        mapping[key] = parsed
    return mapping


def _parse_side_float_overrides(raw: str) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for part in (raw or "").split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        side, value = token.split(":", 1)
        key = side.strip().lower()
        if key not in {"long", "short"}:
            continue
        try:
            parsed = float(value.strip())
        except (TypeError, ValueError):
            continue
        if parsed < 0:
            continue
        mapping[key] = parsed
    return mapping


def _parse_symbol_side_float_overrides(raw: str) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for part in (raw or "").split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        symbol_side_raw, value = token.rsplit(":", 1)
        key = symbol_side_raw.strip().upper()
        if ":" not in key:
            continue
        symbol, side = key.split(":", 1)
        side_l = side.strip().lower()
        if not symbol.strip() or side_l not in {"long", "short"}:
            continue
        normalized_key = f"{symbol.strip().upper()}:{side_l}"
        try:
            parsed = float(value.strip())
        except (TypeError, ValueError):
            continue
        if parsed < 0:
            continue
        mapping[normalized_key] = parsed
    return mapping


@dataclass
class LossPreventionConfig:
    """Aggregated configuration for all loss prevention stages.
    
    Attributes:
        strategy_trend_alignment: Configuration for StrategyTrendAlignmentStage
        fee_aware_entry: Configuration for FeeAwareEntryStage
        session_filter: Configuration for SessionFilterStage
        ev_gate: Configuration for EVGateStage
        ev_position_sizer: Configuration for EVPositionSizerStage
        cost_data_quality: Configuration for CostDataQualityStage (runs before EVGate)
        global_gate: Configuration for GlobalGateStage
        cooldown: Configuration for CooldownStage
        enabled: Master switch to enable/disable all loss prevention stages
    """
    strategy_trend_alignment: StrategyTrendAlignmentConfig
    fee_aware_entry: FeeAwareEntryConfig
    session_filter: SessionFilterConfig
    ev_gate: Optional[EVGateConfig] = None
    ev_position_sizer: Optional[EVPositionSizerConfig] = None
    cost_data_quality: Optional[CostDataQualityConfig] = None
    global_gate: Optional[GlobalGateConfig] = None
    cooldown: Optional[CooldownConfig] = None
    enabled: bool = True


def load_confidence_gate_config() -> ConfidenceGateConfig:
    """Load ConfidenceGateConfig from environment variables.
    
    Environment Variables:
        CONFIDENCE_GATE_MIN_CONFIDENCE: Minimum confidence threshold (0.0-1.0)
                                       Default: 0.50 (50%)
    
    Returns:
        ConfidenceGateConfig with values from environment or defaults.
    """
    min_confidence = float(os.getenv("CONFIDENCE_GATE_MIN_CONFIDENCE", "0.50"))
    
    # Validate and clamp to valid range
    min_confidence = max(0.0, min(1.0, min_confidence))
    
    config = ConfidenceGateConfig(min_confidence=min_confidence)
    
    log_info(
        "loss_prevention_config_loaded",
        stage="confidence_gate",
        min_confidence=min_confidence,
    )
    
    return config


def load_strategy_trend_alignment_config() -> StrategyTrendAlignmentConfig:
    """Load StrategyTrendAlignmentConfig from environment variables.
    
    Environment Variables:
        STRATEGY_TREND_EMA_THRESHOLD: EMA difference threshold for trend classification
                                     Default: 0.001 (0.1%)
    
    Returns:
        StrategyTrendAlignmentConfig with values from environment or defaults.
    """
    ema_threshold = float(os.getenv("STRATEGY_TREND_EMA_THRESHOLD", "0.001"))
    
    config = StrategyTrendAlignmentConfig(ema_trend_threshold=ema_threshold)
    
    log_info(
        "loss_prevention_config_loaded",
        stage="strategy_trend_alignment",
        ema_trend_threshold=ema_threshold,
    )
    
    return config


def load_fee_aware_entry_config() -> FeeAwareEntryConfig:
    """Load FeeAwareEntryConfig from environment variables.
    
    Environment Variables:
        FEE_AWARE_ENTRY_FEE_RATE_BPS: Taker fee rate in basis points
                                     Default: 5.5 (0.055% Bybit)
        FEE_AWARE_ENTRY_MIN_EDGE_MULTIPLIER: Edge must be this multiple of fees
                                            Default: 2.0
        FEE_AWARE_ENTRY_SLIPPAGE_BPS: Expected slippage in basis points
                                     Default: 2.0
    
    Returns:
        FeeAwareEntryConfig with values from environment or defaults.
    """
    fee_rate_bps = float(os.getenv("FEE_AWARE_ENTRY_FEE_RATE_BPS", "5.5"))
    min_edge_multiplier = float(os.getenv("FEE_AWARE_ENTRY_MIN_EDGE_MULTIPLIER", "2.0"))
    slippage_bps = float(os.getenv("FEE_AWARE_ENTRY_SLIPPAGE_BPS", "2.0"))
    
    config = FeeAwareEntryConfig(
        fee_rate_bps=fee_rate_bps,
        min_edge_multiplier=min_edge_multiplier,
        slippage_bps=slippage_bps,
    )
    
    log_info(
        "loss_prevention_config_loaded",
        stage="fee_aware_entry",
        fee_rate_bps=fee_rate_bps,
        min_edge_multiplier=min_edge_multiplier,
        slippage_bps=slippage_bps,
    )
    
    return config


def load_session_filter_config() -> SessionFilterConfig:
    """Load SessionFilterConfig from environment variables.
    
    Environment Variables:
        SESSION_FILTER_ENFORCE_PREFERENCES: Enforce session preferences (true/false)
                                           Default: true
        SESSION_FILTER_ENFORCE_STRATEGY_SESSIONS: Enforce strategy sessions (true/false)
                                                 Default: true
        SESSION_FILTER_APPLY_SIZE_MULTIPLIER: Apply position size multiplier (true/false)
                                             Default: true
    
    Returns:
        SessionFilterConfig with values from environment or defaults.
    """
    enforce_preferences = os.getenv(
        "SESSION_FILTER_ENFORCE_PREFERENCES", "true"
    ).lower() in {"1", "true", "yes"}
    
    enforce_strategy_sessions = os.getenv(
        "SESSION_FILTER_ENFORCE_STRATEGY_SESSIONS", "true"
    ).lower() in {"1", "true", "yes"}
    
    apply_size_multiplier = os.getenv(
        "SESSION_FILTER_APPLY_SIZE_MULTIPLIER", "true"
    ).lower() in {"1", "true", "yes"}

    enabled = os.getenv(
        "SESSION_FILTER_ENABLED", "true"
    ).lower() in {"1", "true", "yes"}
    
    config = SessionFilterConfig(
        enforce_session_preferences=enforce_preferences,
        enforce_strategy_sessions=enforce_strategy_sessions,
        apply_position_size_multiplier=apply_size_multiplier,
        enabled=enabled,
    )
    
    log_info(
        "loss_prevention_config_loaded",
        stage="session_filter",
        enabled=enabled,
        enforce_session_preferences=enforce_preferences,
        enforce_strategy_sessions=enforce_strategy_sessions,
        apply_position_size_multiplier=apply_size_multiplier,
    )
    
    return config


def load_confidence_position_sizer_config() -> ConfidencePositionSizerConfig:
    """Load ConfidencePositionSizerConfig from environment variables.
    
    Environment Variables:
        CONFIDENCE_SIZER_DEFAULT_MULTIPLIER: Default multiplier when no band matches
                                            Default: 1.0
        CONFIDENCE_SIZER_MIN_CONFIDENCE: Minimum confidence for sizing
                                        Default: 0.50
    
    Note: The confidence bands are not configurable via environment variables
    as they are part of the core trading strategy. To customize bands,
    pass a custom config to the DecisionEngine.
    
    Returns:
        ConfidencePositionSizerConfig with values from environment or defaults.
    """
    default_multiplier = float(os.getenv("CONFIDENCE_SIZER_DEFAULT_MULTIPLIER", "1.0"))
    min_confidence = float(os.getenv("CONFIDENCE_SIZER_MIN_CONFIDENCE", "0.50"))
    
    config = ConfidencePositionSizerConfig(
        default_multiplier=default_multiplier,
        min_confidence_for_sizing=min_confidence,
    )
    
    log_info(
        "loss_prevention_config_loaded",
        stage="confidence_position_sizer",
        default_multiplier=default_multiplier,
        min_confidence_for_sizing=min_confidence,
    )
    
    return config


def load_ev_gate_config() -> EVGateConfig:
    """Load EVGateConfig from environment variables.
    
    Environment Variables:
        EV_GATE_EV_MIN: Minimum EV threshold (default 0.02)
        EV_GATE_EV_MIN_FLOOR: Absolute minimum after relaxation (default 0.01)
        EV_GATE_ADVERSE_SELECTION_BPS: Adverse selection buffer in bps (default 1.5)
        EV_GATE_MIN_SLIPPAGE_BPS: Minimum slippage floor in bps (default 0.5)
        EV_GATE_MAX_BOOK_AGE_MS: Maximum orderbook staleness in ms (default 250)
        EV_GATE_MAX_SPREAD_AGE_MS: Maximum spread staleness in ms (default 250)
        EV_GATE_MIN_STOP_DISTANCE_BPS: Minimum stop loss distance in bps (default 5.0)
        EV_GATE_P_MARGIN_UNCALIBRATED: EV_Min increase when uncalibrated (default 0.02)
        EV_GATE_MIN_RELIABILITY_SCORE: Minimum calibration reliability (default 0.6)
        EV_GATE_MIN_EXPECTED_EDGE_BPS: Minimum expected net edge in bps after costs (default 0.0)
        EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SYMBOL: Optional per-symbol override map (e.g. ETHUSDT:1.2,BTCUSDT:0.8)
        EV_GATE_MAX_EXCHANGE_LATENCY_MS: Maximum exchange latency in ms (default 500)
        EV_GATE_MODE: "shadow" or "enforce" (default "shadow" for safe rollout)
    
    Returns:
        EVGateConfig with values from environment or defaults.
    """
    ev_min = float(os.getenv("EV_GATE_EV_MIN", "0.02"))
    ev_min_floor = float(os.getenv("EV_GATE_EV_MIN_FLOOR", "0.01"))
    adverse_selection_bps = float(os.getenv("EV_GATE_ADVERSE_SELECTION_BPS", "1.5"))
    min_slippage_bps = float(os.getenv("EV_GATE_MIN_SLIPPAGE_BPS", "0.5"))
    max_book_age_ms = int(os.getenv("EV_GATE_MAX_BOOK_AGE_MS", "250"))
    max_spread_age_ms = int(os.getenv("EV_GATE_MAX_SPREAD_AGE_MS", "250"))
    min_stop_distance_bps = float(os.getenv("EV_GATE_MIN_STOP_DISTANCE_BPS", "5.0"))
    p_margin_uncalibrated = float(os.getenv("EV_GATE_P_MARGIN_UNCALIBRATED", "0.02"))
    min_reliability_score = float(os.getenv("EV_GATE_MIN_RELIABILITY_SCORE", "0.6"))
    min_expected_edge_bps = float(os.getenv("EV_GATE_MIN_EXPECTED_EDGE_BPS", "0.0"))
    min_expected_edge_bps_by_symbol = _parse_symbol_float_overrides(
        os.getenv("EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SYMBOL", "")
    )
    min_expected_edge_bps_by_side = _parse_side_float_overrides(
        os.getenv("EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SIDE", "")
    )
    min_expected_edge_bps_by_symbol_side = _parse_symbol_side_float_overrides(
        os.getenv("EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SYMBOL_SIDE", "")
    )
    max_exchange_latency_ms = int(os.getenv("EV_GATE_MAX_EXCHANGE_LATENCY_MS", "500"))
    mode = os.getenv("EV_GATE_MODE", "shadow")  # Default to shadow for safe rollout
    
    # Validate mode
    if mode not in ("shadow", "enforce"):
        log_warning(
            "ev_gate_invalid_mode",
            mode=mode,
            fallback="shadow",
        )
        mode = "shadow"
    
    config = EVGateConfig(
        ev_min=ev_min,
        ev_min_floor=ev_min_floor,
        adverse_selection_bps=adverse_selection_bps,
        min_slippage_bps=min_slippage_bps,
        max_book_age_ms=max_book_age_ms,
        max_spread_age_ms=max_spread_age_ms,
        min_stop_distance_bps=min_stop_distance_bps,
        p_margin_uncalibrated=p_margin_uncalibrated,
        min_reliability_score=min_reliability_score,
        min_expected_edge_bps=min_expected_edge_bps,
        min_expected_edge_bps_by_symbol=min_expected_edge_bps_by_symbol,
        min_expected_edge_bps_by_side=min_expected_edge_bps_by_side,
        min_expected_edge_bps_by_symbol_side=min_expected_edge_bps_by_symbol_side,
        max_exchange_latency_ms=max_exchange_latency_ms,
        mode=mode,
    )
    
    log_info(
        "loss_prevention_config_loaded",
        stage="ev_gate",
        ev_min=ev_min,
        ev_min_floor=ev_min_floor,
        adverse_selection_bps=adverse_selection_bps,
        min_slippage_bps=min_slippage_bps,
        max_book_age_ms=max_book_age_ms,
        max_spread_age_ms=max_spread_age_ms,
        min_stop_distance_bps=min_stop_distance_bps,
        min_expected_edge_bps=min_expected_edge_bps,
        min_expected_edge_bps_by_symbol=min_expected_edge_bps_by_symbol,
        min_expected_edge_bps_by_side=min_expected_edge_bps_by_side,
        min_expected_edge_bps_by_symbol_side=min_expected_edge_bps_by_symbol_side,
        max_exchange_latency_ms=max_exchange_latency_ms,
        mode=mode,
    )
    
    return config


def load_ev_position_sizer_config() -> EVPositionSizerConfig:
    """Load EVPositionSizerConfig from environment variables.
    
    Environment Variables:
        EV_SIZER_K: Edge-to-multiplier scaling factor (default 2.0)
        EV_SIZER_MIN_MULT: Minimum size multiplier (default 0.5)
        EV_SIZER_MAX_MULT: Maximum size multiplier (default 1.25)
        EV_SIZER_COST_ALPHA: Cost environment scaling factor (default 0.5)
        EV_SIZER_MIN_RELIABILITY_MULT: Minimum reliability multiplier (default 0.8)
        EV_SIZER_ENABLED: Whether EV sizing is enabled (default true)
    
    Returns:
        EVPositionSizerConfig with values from environment or defaults.
    """
    k = float(os.getenv("EV_SIZER_K", "2.0"))
    min_mult = float(os.getenv("EV_SIZER_MIN_MULT", "0.5"))
    max_mult = float(os.getenv("EV_SIZER_MAX_MULT", "1.25"))
    cost_alpha = float(os.getenv("EV_SIZER_COST_ALPHA", "0.5"))
    min_reliability_mult = float(os.getenv("EV_SIZER_MIN_RELIABILITY_MULT", "0.8"))
    enabled = os.getenv("EV_SIZER_ENABLED", "true").lower() in {"1", "true", "yes"}
    
    config = EVPositionSizerConfig(
        k=k,
        min_mult=min_mult,
        max_mult=max_mult,
        cost_alpha=cost_alpha,
        min_reliability_mult=min_reliability_mult,
        enabled=enabled,
    )
    
    log_info(
        "loss_prevention_config_loaded",
        stage="ev_position_sizer",
        k=k,
        min_mult=min_mult,
        max_mult=max_mult,
        cost_alpha=cost_alpha,
        min_reliability_mult=min_reliability_mult,
        enabled=enabled,
    )
    
    return config


def load_cost_data_quality_config() -> CostDataQualityConfig:
    """Load CostDataQualityConfig from environment variables.
    
    Environment Variables:
        COST_DATA_QUALITY_ENABLED: Whether the stage is enabled (default false - disabled until timestamps are verified)
        COST_DATA_QUALITY_MAX_SPREAD_AGE_MS: Maximum spread staleness in ms (default 500)
        COST_DATA_QUALITY_MAX_BOOK_AGE_MS: Maximum book staleness in ms (default 500)
        COST_DATA_QUALITY_REQUIRE_SLIPPAGE_MODEL: Whether slippage model is required (default false)
    
    Returns:
        CostDataQualityConfig with values from environment or defaults.
    """
    # IMPORTANT: Disabled by default until market data timestamps are verified to be set correctly
    # This prevents the stage from blocking ALL signals due to missing timestamps
    enabled = os.getenv("COST_DATA_QUALITY_ENABLED", "false").lower() in {"1", "true", "yes"}
    max_spread_age_ms = int(
        os.getenv(
            "COST_DATA_QUALITY_MAX_SPREAD_AGE_MS",
            os.getenv("EV_GATE_MAX_SPREAD_AGE_MS", "250"),
        )
    )
    max_book_age_ms = int(
        os.getenv(
            "COST_DATA_QUALITY_MAX_BOOK_AGE_MS",
            os.getenv("EV_GATE_MAX_BOOK_AGE_MS", "250"),
        )
    )
    require_slippage_model = os.getenv("COST_DATA_QUALITY_REQUIRE_SLIPPAGE_MODEL", "false").lower() in {"1", "true", "yes"}
    
    config = CostDataQualityConfig(
        enabled=enabled,
        max_spread_age_ms=max_spread_age_ms,
        max_book_age_ms=max_book_age_ms,
        require_slippage_model=require_slippage_model,
    )
    
    log_info(
        "loss_prevention_config_loaded",
        stage="cost_data_quality",
        enabled=enabled,
        max_spread_age_ms=max_spread_age_ms,
        max_book_age_ms=max_book_age_ms,
        require_slippage_model=require_slippage_model,
    )
    
    return config


def load_global_gate_config() -> GlobalGateConfig:
    """Load GlobalGateConfig from environment variables.
    
    Environment Variables:
        GLOBAL_GATE_MIN_DEPTH_USD: Minimum depth per side in USD (default 2000)
        GLOBAL_GATE_MAX_SPREAD_BPS: Maximum spread in basis points (default 30)
        GLOBAL_GATE_SNAPSHOT_AGE_OK_MS: Snapshot age for full trading (default 2000)
        GLOBAL_GATE_SNAPSHOT_AGE_REDUCE_MS: Snapshot age for reduced size (default 5000)
        GLOBAL_GATE_SNAPSHOT_AGE_BLOCK_MS: Snapshot age to block entries (default 10000)
        GLOBAL_GATE_MAX_SPREAD_VS_TYPICAL: Max spread vs typical ratio (default 3.0)
        GLOBAL_GATE_DEPTH_TYPICAL_MULT: Depth multiplier vs typical (default 0.5)
        GLOBAL_GATE_BLOCK_VOL_SHOCK: Block on volatility shock (default true)
    
    Returns:
        GlobalGateConfig with values from environment or defaults.
    """
    min_depth_usd = float(os.getenv("GLOBAL_GATE_MIN_DEPTH_USD", "2000"))
    max_spread_bps = float(os.getenv("GLOBAL_GATE_MAX_SPREAD_BPS", "30"))
    snapshot_age_ok_ms = float(os.getenv("GLOBAL_GATE_SNAPSHOT_AGE_OK_MS", "2000"))
    snapshot_age_reduce_ms = float(os.getenv("GLOBAL_GATE_SNAPSHOT_AGE_REDUCE_MS", "5000"))
    snapshot_age_block_ms = float(os.getenv("GLOBAL_GATE_SNAPSHOT_AGE_BLOCK_MS", "10000"))
    max_spread_vs_typical = float(os.getenv("GLOBAL_GATE_MAX_SPREAD_VS_TYPICAL", "3.0"))
    depth_typical_mult = float(os.getenv("GLOBAL_GATE_DEPTH_TYPICAL_MULT", "0.5"))
    block_vol_shock = os.getenv("GLOBAL_GATE_BLOCK_VOL_SHOCK", "true").lower() in {"1", "true", "yes"}
    
    config = GlobalGateConfig(
        min_depth_per_side_usd=min_depth_usd,
        max_spread_bps=max_spread_bps,
        snapshot_age_ok_ms=snapshot_age_ok_ms,
        snapshot_age_reduce_ms=snapshot_age_reduce_ms,
        snapshot_age_block_ms=snapshot_age_block_ms,
        max_spread_vs_typical_ratio=max_spread_vs_typical,
        depth_typical_multiplier=depth_typical_mult,
        block_on_vol_shock=block_vol_shock,
    )
    
    log_info(
        "loss_prevention_config_loaded",
        stage="global_gate",
        min_depth_usd=min_depth_usd,
        max_spread_bps=max_spread_bps,
        snapshot_age_ok_ms=snapshot_age_ok_ms,
        snapshot_age_reduce_ms=snapshot_age_reduce_ms,
        snapshot_age_block_ms=snapshot_age_block_ms,
        depth_typical_mult=depth_typical_mult,
        block_vol_shock=block_vol_shock,
    )
    
    return config


def load_cooldown_config() -> CooldownConfig:
    """Load CooldownConfig from environment variables.
    
    Environment Variables:
        COOLDOWN_ENTRY_SEC: Default entry cooldown in seconds (default 15)
        COOLDOWN_EXIT_SEC: Exit cooldown in seconds (default 30)
        COOLDOWN_STOP_OUT_SEC: Stop-out cooldown in seconds (default 60)
        COOLDOWN_SAME_DIRECTION_SEC: Same direction hysteresis in seconds (default 30)
        COOLDOWN_MAX_ENTRIES_PER_HOUR: Maximum entries per symbol per hour (default 50)
    
    Returns:
        CooldownConfig with values from environment or defaults.
    """
    entry_cooldown = float(os.getenv("COOLDOWN_ENTRY_SEC", "15"))
    exit_cooldown = float(os.getenv("COOLDOWN_EXIT_SEC", "30"))
    stop_out_cooldown = float(os.getenv("COOLDOWN_STOP_OUT_SEC", "60"))
    same_direction = float(os.getenv("COOLDOWN_SAME_DIRECTION_SEC", "30"))
    max_entries = int(os.getenv("COOLDOWN_MAX_ENTRIES_PER_HOUR", "50"))
    
    config = CooldownConfig(
        default_entry_cooldown_sec=entry_cooldown,
        exit_cooldown_sec=exit_cooldown,
        stop_out_cooldown_sec=stop_out_cooldown,
        same_direction_hysteresis_sec=same_direction,
        max_entries_per_hour=max_entries,
    )
    
    log_info(
        "loss_prevention_config_loaded",
        stage="cooldown",
        entry_cooldown_sec=entry_cooldown,
        exit_cooldown_sec=exit_cooldown,
        stop_out_cooldown_sec=stop_out_cooldown,
        same_direction_sec=same_direction,
        max_entries_per_hour=max_entries,
    )
    
    return config


def load_loss_prevention_config() -> LossPreventionConfig:
    """Load all loss prevention configurations from environment variables.
    
    Environment Variables:
        LOSS_PREVENTION_ENABLED: Master switch to enable/disable all stages
                                Default: true
    
    Returns:
        LossPreventionConfig with all stage configurations.
    """
    enabled = os.getenv("LOSS_PREVENTION_ENABLED", "true").lower() in {"1", "true", "yes"}
    
    config = LossPreventionConfig(
        strategy_trend_alignment=load_strategy_trend_alignment_config(),
        fee_aware_entry=load_fee_aware_entry_config(),
        session_filter=load_session_filter_config(),
        ev_gate=load_ev_gate_config(),
        ev_position_sizer=load_ev_position_sizer_config(),
        cost_data_quality=load_cost_data_quality_config(),
        global_gate=load_global_gate_config(),
        cooldown=load_cooldown_config(),
        enabled=enabled,
    )
    
    log_info(
        "loss_prevention_config_loaded",
        stage="all",
        enabled=enabled,
        ev_gate_mode=config.ev_gate.mode if config.ev_gate else None,
        ev_sizer_enabled=config.ev_position_sizer.enabled if config.ev_position_sizer else None,
        cost_data_quality_enabled=config.cost_data_quality.enabled if config.cost_data_quality else None,
        global_gate_min_depth=config.global_gate.min_depth_per_side_usd if config.global_gate else None,
        cooldown_entry_sec=config.cooldown.default_entry_cooldown_sec if config.cooldown else None,
    )
    
    return config


class LossPreventionConfigManager:
    """Manager for loss prevention configuration with runtime update support.
    
    This class provides a centralized way to manage loss prevention configuration
    and supports runtime updates without restarting the application.
    """
    
    def __init__(self):
        """Initialize the config manager with default configuration."""
        self._config: Optional[LossPreventionConfig] = None
        self._callbacks: list = []
    
    @property
    def config(self) -> LossPreventionConfig:
        """Get the current configuration, loading from environment if not set."""
        if self._config is None:
            self._config = load_loss_prevention_config()
        return self._config
    
    def reload(self) -> LossPreventionConfig:
        """Reload configuration from environment variables.
        
        This method can be called to pick up configuration changes
        without restarting the application.
        
        Returns:
            The newly loaded configuration.
        """
        self._config = load_loss_prevention_config()
        
        # Notify callbacks of configuration change
        for callback in self._callbacks:
            try:
                callback(self._config)
            except Exception:
                pass  # Don't let callback errors break the reload
        
        return self._config
    
    def register_callback(self, callback) -> None:
        """Register a callback to be notified when configuration changes.
        
        Args:
            callback: Function that takes LossPreventionConfig as argument.
        """
        self._callbacks.append(callback)
    
    def update_from_dict(self, updates: Dict[str, Any]) -> LossPreventionConfig:
        """Update configuration from a dictionary.
        
        This method allows runtime configuration updates from API calls
        or configuration files.
        
        Args:
            updates: Dictionary with configuration updates.
                    Keys can be:
                    - "confidence_gate.min_confidence"
                    - "fee_aware_entry.fee_rate_bps"
                    - etc.
        
        Returns:
            The updated configuration.
        """
        # Ensure we have a base config
        config = self.config
        
        # Apply updates
        for key, value in updates.items():
            parts = key.split(".")
            if len(parts) == 2:
                stage_name, param_name = parts
                stage_config = getattr(config, stage_name, None)
                if stage_config and hasattr(stage_config, param_name):
                    setattr(stage_config, param_name, value)
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(config)
            except Exception:
                pass
        
        log_info(
            "loss_prevention_config_updated",
            updates=updates,
        )
        
        return config


# Global config manager instance
_config_manager: Optional[LossPreventionConfigManager] = None


def get_config_manager() -> LossPreventionConfigManager:
    """Get the global loss prevention config manager.
    
    Returns:
        The global LossPreventionConfigManager instance.
    """
    global _config_manager
    if _config_manager is None:
        _config_manager = LossPreventionConfigManager()
    return _config_manager
