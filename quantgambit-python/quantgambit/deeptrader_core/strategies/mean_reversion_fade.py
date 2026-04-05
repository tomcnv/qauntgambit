"""
Mean Reversion Fade Strategy

Fades overextensions in ranging markets by trading back towards the Point of Control.

Entry Conditions:
- Flat market (trend: flat)
- Price >30 bps from POC (overextended) - using canonical formula with mid_price denominator
- Rotation factor turning (crossing 0 threshold)
- Low ATR (calm, range-bound market)
- Sufficient edge after fees (expected profit > min_edge_bps)

Risk Profile:
- Tight stops (0.3% - 0.5%)
- Medium position size (0.5% - 0.8% risk)
- Target: Return to POC

Exit Logic:
- Take profit at POC
- Exit if doesn't reverse within 2 minutes (time-based exit)
- Stop loss at recent high/low

Best Market Conditions:
- Trend: flat
- Volatility: low to normal
- Value Location: above or below (extended from POC)
- Distance from POC: >30 bps

BPS Standardization (Strategy Signal Architecture Fixes Requirement 1.4):
- min_distance_from_poc_bps: Distance threshold in basis points (default 30 bps)
- Uses canonical formula: (price - poc) / mid_price * 10000
- All threshold logging includes "bps" suffix for clarity

Symbol-Adaptive Parameters (Requirement 4.5):
- min_distance_from_poc_bps: Read from resolved_params if available
- stop_loss_pct: Read from resolved_params if available
- take_profit_pct: Read from resolved_params if available

Fee-Aware Entry Filtering (US-4):
- min_edge_bps: Minimum edge after fees/slippage (default 3 bps, configurable via STRATEGY_MIN_EDGE_BPS)
- fee_bps: Estimated round-trip fees in basis points (default 6 bps, configurable via STRATEGY_FEE_BPS)
- slippage_bps: Estimated slippage in basis points (default 2 bps, configurable via STRATEGY_SLIPPAGE_BPS)
"""

from typing import Optional, Dict, Any, Union
import logging
import os
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal, CandidateSignal
from quantgambit.risk.fee_model import FeeModel, FeeConfig
from quantgambit.execution.execution_policy import ExecutionPolicy, calculate_expected_fees_bps
from quantgambit.risk.slippage_model import SlippageModel, calculate_adverse_selection_bps
from quantgambit.core.unit_converter import pct_to_bps, bps_to_pct
from quantgambit.signals.services.threshold_calculator import (
    ThresholdCalculator,
    ThresholdConfig,
    DualThreshold,
    get_threshold_calculator,
)
from .base import Strategy

logger = logging.getLogger(__name__)


def _parse_symbol_float_map(raw: str) -> Dict[str, float]:
    parsed: Dict[str, float] = {}
    if not raw:
        return parsed
    for token in raw.split(","):
        token = token.strip()
        if not token or ":" not in token:
            continue
        sym_raw, val_raw = token.split(":", 1)
        sym = sym_raw.strip().upper()
        try:
            val = float(val_raw.strip())
        except ValueError:
            continue
        if sym:
            parsed[sym] = val
    return parsed


def _symbol_override(symbol: str, env_key: str) -> Optional[float]:
    sym = (symbol or "").upper()
    if not sym:
        return None
    return _parse_symbol_float_map(os.getenv(env_key, "")).get(sym)

# Default values used when resolved_params unavailable
# BPS Standardization: Use bps as primary unit (Requirement 1.4.1)
DEFAULT_MIN_DISTANCE_FROM_POC_BPS = 30.0  # 30 bps = 0.3%
DEFAULT_MIN_DISTANCE_FROM_POC_PCT = 0.003  # Legacy: 0.3% - kept for backward compatibility
# Stop sizing should be scalp-sized by default; the resolver will provide symbol-adaptive values
# when available, but we keep a tighter fallback here to avoid swing-like behavior.
DEFAULT_STOP_LOSS_PCT = 0.008  # 0.8%
DEFAULT_TAKE_PROFIT_TARGET_PCT = 0.0  # 0 = target POC exactly

# Dual Threshold Configuration (Requirement 2.6, 2.7)
# Default expected cost when not available from context
DEFAULT_EXPECTED_COST_BPS = 13.0  # 7 bps fees + 3 bps spread + 3 bps slippage
# Default VA width when not available from AMT levels
DEFAULT_VA_WIDTH_BPS = 100.0  # Conservative default for BTC-like markets

# Fee model configuration
# Default to OKX regular fees, can be overridden via params
DEFAULT_FEE_CONFIG = FeeConfig.bybit_regular()


class MeanReversionFade(Strategy):
    """
    Mean reversion strategy for ranging markets.
    
    Fades price overextensions by trading back towards POC when rotation
    factor signals a reversal in low volatility conditions.
    
    Symbol-Adaptive Parameters (Requirement 4.5):
    This strategy reads min_distance_from_poc_pct, stop_loss_pct, and
    take_profit_pct from resolved_params when available, falling back
    to hardcoded defaults if unavailable.
    
    Architecture (V2 Proposal):
    - Strategy validates GEOMETRY only (is this a valid pattern?)
    - EVGate validates ECONOMICS (is this profitable after costs?)
    - ExecutionPolicy provides execution assumptions (maker/taker mix)
    - SlippageModel provides market-state-adaptive slippage (Phase 2)
    """
    
    strategy_id = "mean_reversion_fade"
    
    def __init__(self):
        """Initialize strategy with ExecutionPolicy, SlippageModel, and ThresholdCalculator."""
        super().__init__()
        self.execution_policy = ExecutionPolicy()
        self.slippage_model = SlippageModel()
        self.threshold_calculator = get_threshold_calculator()
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """
        Generate mean reversion signal when price overextended from POC.
        
        Args:
            features: Market features including price, AMT metrics, indicators
            account: Account state for position sizing
            profile: Current market profile
            params: Strategy parameters from profile config. May contain:
                - resolved_params: ResolvedParameters with symbol-adaptive values
                - symbol_characteristics: SymbolCharacteristics for transparency
            
        Returns:
            StrategySignal if conditions met, None otherwise
        """
        # Extract resolved parameters if available (Requirement 4.5)
        resolved_params = params.get("resolved_params")
        
        # Extract parameters with symbol-adaptive fallback
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)
        
        # min_distance_from_poc_bps: Use resolved_params if available (Requirement 1.4.1, 4.5)
        # BPS Standardization: Primary unit is now bps
        if resolved_params is not None and hasattr(resolved_params, "min_distance_from_poc_bps"):
            min_distance_from_poc_bps = resolved_params.min_distance_from_poc_bps
        elif "min_distance_from_poc_bps" in params:
            min_distance_from_poc_bps = params["min_distance_from_poc_bps"]
        elif resolved_params is not None and hasattr(resolved_params, "min_distance_from_poc_pct"):
            # Legacy: Convert pct to bps
            min_distance_from_poc_bps = pct_to_bps(resolved_params.min_distance_from_poc_pct)
        elif "min_distance_from_poc_pct" in params:
            # Legacy: Convert pct to bps
            min_distance_from_poc_bps = pct_to_bps(params["min_distance_from_poc_pct"])
        else:
            min_distance_from_poc_bps = DEFAULT_MIN_DISTANCE_FROM_POC_BPS
        
        # Make rotation check permissive when enabled via env; default stays as configured
        rotation_reversal_threshold = params.get("rotation_reversal_threshold", 0.0)  # Tolerance around zero
        max_atr_ratio = params.get("max_atr_ratio", 1.0)  # ATR must be calm (not expanding)
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.006)
        
        # stop_loss_pct: Use resolved_params if available (Requirement 4.5)
        if resolved_params is not None and hasattr(resolved_params, "stop_loss_pct"):
            stop_loss_pct = resolved_params.stop_loss_pct
        else:
            stop_loss_pct = params.get("stop_loss_pct", DEFAULT_STOP_LOSS_PCT)
        
        # take_profit_pct: Use resolved_params if available (Requirement 4.5)
        if resolved_params is not None and hasattr(resolved_params, "take_profit_pct"):
            take_profit_target_pct = resolved_params.take_profit_pct
        else:
            take_profit_target_pct = params.get("take_profit_target_pct", DEFAULT_TAKE_PROFIT_TARGET_PCT)
        
        max_spread = params.get("max_spread", 0.002)
        # CRITICAL: Max orderflow imbalance against our trade direction
        # Exit logic triggers at 0.6, so don't enter if imbalance would immediately trigger exit
        max_adverse_orderflow = params.get("max_adverse_orderflow", 0.5)
        override_adverse_orderflow = _symbol_override(
            features.symbol, "MEAN_REVERSION_MAX_ADVERSE_ORDERFLOW_BY_SYMBOL"
        )
        if override_adverse_orderflow is not None:
            max_adverse_orderflow = max(0.0, min(1.0, float(override_adverse_orderflow)))
        
        # Initialize fee model with exchange-specific config
        fee_config = params.get("fee_config", DEFAULT_FEE_CONFIG)
        if isinstance(fee_config, dict):
            fee_config = FeeConfig.from_dict(fee_config)
        fee_model = FeeModel(fee_config)
        
        # Get execution plan from ExecutionPolicy
        execution_plan = self.execution_policy.plan_execution(
            strategy_id=self.strategy_id,
            setup_type="mean_reversion",
            market_state=None,  # Phase 2: pass market state for adaptive planning
        )
        
        # Extract profile_id for logging attribution (Requirement 7.2, 7.3, 7.4)
        profile_id = profile.id if profile else "unknown"
        
        # Sanity checks - need POC data
        if features.point_of_control is None:
            logger.info(
                f"[{features.symbol}] mean_reversion_fade: Rejecting - missing POC data. "
                f"profile_id={profile_id}"
            )
            return None
        if features.distance_to_poc is None or features.price is None:
            logger.info(
                f"[{features.symbol}] mean_reversion_fade: Rejecting - missing distance_to_poc or price. "
                f"distance_to_poc={features.distance_to_poc}, price={features.price}, "
                f"profile_id={profile_id}"
            )
            return None
        
        # Calculate ATR ratio early for logging
        atr_ratio = None
        if features.atr_5m and features.atr_5m_baseline:
            atr_ratio = features.atr_5m / features.atr_5m_baseline
        
        # BPS Standardization: Calculate distance from POC in bps (Requirement 1.4.2)
        # Use distance_to_poc_bps if available from AMTLevels, otherwise calculate
        if hasattr(features, 'distance_to_poc_bps') and features.distance_to_poc_bps is not None:
            distance_from_poc_bps = abs(features.distance_to_poc_bps)
        else:
            # Fallback: Calculate using canonical formula with price as mid_price
            distance_from_poc_bps = abs(features.distance_to_poc) / features.price * 10000
        
        # Legacy: Calculate distance as percentage for backward compatibility
        distance_from_poc_pct = abs(features.distance_to_poc) / features.price
        
        # Optional override to allow ultra-tight entries for diagnostics/validation
        allow_near_poc = os.getenv("ALLOW_NEAR_POC_ENTRIES", "false").lower() in {"1", "true", "yes"}
        
        # Fast filter: spread check
        if features.spread > max_spread:
            atr_ratio_str = f"{atr_ratio:.3f}" if atr_ratio else "N/A"
            logger.info(
                f"[{features.symbol}] mean_reversion_fade: Rejecting - spread too wide. "
                f"spread={features.spread:.6f}, max_spread={max_spread:.6f}, "
                f"atr_ratio={atr_ratio_str}, "
                f"poc_distance_bps={distance_from_poc_bps:.2f}bps, "
                f"profile_id={profile_id}"
            )
            return None
        
        # Check ATR - must be calm market (not expanding volatility)
        if atr_ratio is not None and atr_ratio > max_atr_ratio:
            rotation_str = f"{features.rotation_factor:.3f}" if features.rotation_factor else "N/A"
            logger.info(
                f"[{features.symbol}] mean_reversion_fade: Rejecting - ATR ratio too high. "
                f"atr_ratio={atr_ratio:.3f}, max_atr_ratio={max_atr_ratio:.3f}, "
                f"poc_distance_bps={distance_from_poc_bps:.2f}bps, "
                f"rotation={rotation_str}, "
                f"profile_id={profile_id}"
            )
            return None  # Too much volatility for mean reversion
        
        # GEOMETRY VALIDATION: Must be far enough from POC to justify mean reversion trade
        # This is a setup hygiene check, NOT an economics check
        # Economics (profitability after costs) is handled by EVGate
        # BPS Standardization: Compare in bps (Requirement 1.4.2)
        if distance_from_poc_bps < min_distance_from_poc_bps:
            atr_ratio_str = f"{atr_ratio:.3f}" if atr_ratio else "N/A"
            rotation_str = f"{features.rotation_factor:.3f}" if features.rotation_factor else "N/A"
            if not allow_near_poc:
                logger.info(
                    f"[{features.symbol}] mean_reversion_fade: Rejecting - POC distance too small (geometry). "
                    f"poc_distance_bps={distance_from_poc_bps:.2f}bps, min_distance_bps={min_distance_from_poc_bps:.2f}bps, "
                    f"atr_ratio={atr_ratio_str}, "
                    f"rotation={rotation_str}, "
                    f"profile_id={profile_id}"
                )
                return None
            else:
                # Allow ultra-tight entries; use observed distance as effective min for downstream telemetry
                min_distance_from_poc_bps = distance_from_poc_bps

        # Optional: disable rotation requirement for validation runs
        rotation = features.rotation_factor
        ignore_rotation = os.getenv("ALLOW_NEAR_POC_ENTRIES", "false").lower() in {"1", "true", "yes"}
        rotation_check_enabled = not ignore_rotation
        if rotation is None and ignore_rotation:
            rotation = 0.0
        
        # Determine which side of POC we're on
        price_above_poc = features.distance_to_poc > 0
        
        poc_price = features.point_of_control
        current_price = features.price
        
        if price_above_poc:
            # Price ABOVE POC (overextended high) → Consider SHORT (fade down to POC)
            if not allow_shorts:
                logger.debug(
                    f"[{features.symbol}] mean_reversion_fade: Rejecting - shorts not allowed. "
                    f"profile_id={profile_id}"
                )
                return None
            
            # CRITICAL: Check orderflow imbalance - don't short into strong buy pressure
            # This prevents immediate exit triggers from the position evaluation stage
            orderflow = features.orderflow_imbalance
            if orderflow is not None and orderflow > max_adverse_orderflow:
                atr_ratio_str = f"{atr_ratio:.3f}" if atr_ratio else "N/A"
                logger.info(
                    f"[{features.symbol}] mean_reversion_fade: Rejecting short - adverse orderflow. "
                    f"orderflow={orderflow:.3f}, max_adverse={max_adverse_orderflow:.3f}, "
                    f"atr_ratio={atr_ratio_str}, "
                    f"poc_distance_bps={distance_from_poc_bps:.2f}bps, "
                    f"profile_id={profile_id}"
                )
                return None  # Too much buy pressure to short
            
            # Need rotation turning negative (reversal signal)
            # In this case, rotation should be crossing below threshold (turning down)
            # Allow small positive rotation within tolerance (avoid missing mild reversals)
            if rotation_check_enabled and rotation > rotation_reversal_threshold:
                atr_ratio_str = f"{atr_ratio:.3f}" if atr_ratio else "N/A"
                logger.info(
                    f"[{features.symbol}] mean_reversion_fade: Rejecting short - rotation not reversing. "
                    f"rotation={rotation:.3f}, threshold={rotation_reversal_threshold:.3f}, "
                    f"atr_ratio={atr_ratio_str}, "
                    f"poc_distance_bps={distance_from_poc_bps:.2f}bps, "
                    f"profile_id={profile_id}"
                )
                return None  # Not reversing yet
            
            # Calculate trade parameters
            entry = current_price
            
            # Take profit at POC (or slightly below for safety)
            if take_profit_target_pct > 0:
                tp = poc_price * (1.0 - take_profit_target_pct)
            else:
                tp = poc_price
            
            # Stop loss above entry (if price continues up instead of reversing)
            sl = entry * (1.0 + stop_loss_pct)
            
            # Position sizing based on stop distance
            stop_distance = sl - entry
            size = (account.equity * risk_per_trade_pct) / stop_distance
            
            # Calculate and log costs for transparency (V2 Proposal Section 9)
            self._log_signal_costs(
                symbol=features.symbol,
                side="short",
                entry_price=entry,
                exit_price=tp,
                stop_loss=sl,
                size=size,
                fee_model=fee_model,
                execution_plan=execution_plan,
                features=features,
                profile_id=profile_id,
            )
            
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=features.symbol,
                side="short",
                size=size,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                meta_reason=f"mean_rev_short_poc_dist_{distance_from_poc_bps:.1f}bps",
                profile_id=profile.id,
            )
        
        else:
            # Price BELOW POC (overextended low) → Consider LONG (fade up to POC)
            if not allow_longs:
                logger.debug(
                    f"[{features.symbol}] mean_reversion_fade: Rejecting - longs not allowed. "
                    f"profile_id={profile_id}"
                )
                return None
            
            # CRITICAL: Check orderflow imbalance - don't long into strong sell pressure
            # This prevents immediate exit triggers from the position evaluation stage
            orderflow = features.orderflow_imbalance
            if orderflow is not None and orderflow < -max_adverse_orderflow:
                atr_ratio_str = f"{atr_ratio:.3f}" if atr_ratio else "N/A"
                logger.info(
                    f"[{features.symbol}] mean_reversion_fade: Rejecting long - adverse orderflow. "
                    f"orderflow={orderflow:.3f}, max_adverse={-max_adverse_orderflow:.3f}, "
                    f"atr_ratio={atr_ratio_str}, "
                    f"poc_distance_bps={distance_from_poc_bps:.2f}bps, "
                    f"profile_id={profile_id}"
                )
                return None  # Too much sell pressure to long
            
            # Need rotation turning positive (reversal signal)
            # In this case, rotation should be crossing above threshold (turning up)
            # Allow small negative rotation within tolerance (avoid missing mild reversals)
            if rotation_check_enabled and rotation < -rotation_reversal_threshold:
                atr_ratio_str = f"{atr_ratio:.3f}" if atr_ratio else "N/A"
                logger.info(
                    f"[{features.symbol}] mean_reversion_fade: Rejecting long - rotation not reversing. "
                    f"rotation={rotation:.3f}, threshold={-rotation_reversal_threshold:.3f}, "
                    f"atr_ratio={atr_ratio_str}, "
                    f"poc_distance_bps={distance_from_poc_bps:.2f}bps, "
                    f"profile_id={profile_id}"
                )
                return None  # Not reversing yet
            
            # Calculate trade parameters
            entry = current_price
            
            # Take profit at POC (or slightly above for safety)
            if take_profit_target_pct > 0:
                tp = poc_price * (1.0 + take_profit_target_pct)
            else:
                tp = poc_price
            
            # Stop loss below entry (if price continues down instead of reversing)
            sl = entry * (1.0 - stop_loss_pct)
            
            # Position sizing based on stop distance
            stop_distance = entry - sl
            size = (account.equity * risk_per_trade_pct) / stop_distance
            
            # Calculate and log costs for transparency (V2 Proposal Section 9)
            self._log_signal_costs(
                symbol=features.symbol,
                side="long",
                entry_price=entry,
                exit_price=tp,
                stop_loss=sl,
                size=size,
                fee_model=fee_model,
                execution_plan=execution_plan,
                features=features,
                profile_id=profile_id,
            )
            
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=features.symbol,
                side="long",
                size=size,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                meta_reason=f"mean_rev_long_poc_dist_{distance_from_poc_bps:.1f}bps",
                profile_id=profile.id,
            )
        
        return None
    
    def generate_candidate(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[CandidateSignal]:
        """
        Generate CandidateSignal for mean reversion setup.
        
        This method implements the Candidate Generation Architecture (Requirement 4.4).
        Instead of returning a final StrategySignal, it returns a CandidateSignal
        that will be validated by the ConfirmationStage using flow_rotation and
        trend_bias.
        
        The CandidateSignal includes confirmation_requirements that specify what
        conditions must be met for the candidate to be confirmed.
        
        Args:
            features: Market features including price, AMT metrics, indicators
            account: Account state for position sizing
            profile: Current market profile
            params: Strategy parameters from profile config
            
        Returns:
            CandidateSignal if geometric setup detected, None otherwise
        """
        # Extract resolved parameters if available
        resolved_params = params.get("resolved_params")
        
        # Extract parameters with symbol-adaptive fallback
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)
        
        # min_distance_from_poc_bps: Use resolved_params if available
        if resolved_params is not None and hasattr(resolved_params, "min_distance_from_poc_bps"):
            min_distance_from_poc_bps = resolved_params.min_distance_from_poc_bps
        elif "min_distance_from_poc_bps" in params:
            min_distance_from_poc_bps = params["min_distance_from_poc_bps"]
        elif resolved_params is not None and hasattr(resolved_params, "min_distance_from_poc_pct"):
            min_distance_from_poc_bps = pct_to_bps(resolved_params.min_distance_from_poc_pct)
        elif "min_distance_from_poc_pct" in params:
            min_distance_from_poc_bps = pct_to_bps(params["min_distance_from_poc_pct"])
        else:
            min_distance_from_poc_bps = DEFAULT_MIN_DISTANCE_FROM_POC_BPS
        
        max_atr_ratio = params.get("max_atr_ratio", 1.0)
        
        # stop_loss_pct: Use resolved_params if available
        if resolved_params is not None and hasattr(resolved_params, "stop_loss_pct"):
            stop_loss_pct = resolved_params.stop_loss_pct
        else:
            stop_loss_pct = params.get("stop_loss_pct", DEFAULT_STOP_LOSS_PCT)
        
        # take_profit_pct: Use resolved_params if available
        if resolved_params is not None and hasattr(resolved_params, "take_profit_pct"):
            take_profit_target_pct = resolved_params.take_profit_pct
        else:
            take_profit_target_pct = params.get("take_profit_target_pct", DEFAULT_TAKE_PROFIT_TARGET_PCT)
        
        max_spread = params.get("max_spread", 0.002)
        max_adverse_orderflow = params.get("max_adverse_orderflow", 0.5)
        override_adverse_orderflow = _symbol_override(
            features.symbol, "MEAN_REVERSION_MAX_ADVERSE_ORDERFLOW_BY_SYMBOL"
        )
        if override_adverse_orderflow is not None:
            max_adverse_orderflow = max(0.0, min(1.0, float(override_adverse_orderflow)))
        max_adverse_trend_bias = params.get("max_adverse_trend_bias", 0.5)
        
        # Extract profile_id for logging
        profile_id = profile.id if profile else "unknown"
        
        # Sanity checks - need POC data
        if features.point_of_control is None:
            logger.debug(
                f"[{features.symbol}] mean_reversion_fade: Candidate rejected - missing POC data. "
                f"profile_id={profile_id}"
            )
            return None
        if features.distance_to_poc is None or features.price is None:
            logger.debug(
                f"[{features.symbol}] mean_reversion_fade: Candidate rejected - missing distance_to_poc or price. "
                f"profile_id={profile_id}"
            )
            return None
        
        # Calculate ATR ratio for logging
        atr_ratio = None
        if features.atr_5m and features.atr_5m_baseline:
            atr_ratio = features.atr_5m / features.atr_5m_baseline
        
        # Calculate distance from POC in bps
        if hasattr(features, 'distance_to_poc_bps') and features.distance_to_poc_bps is not None:
            distance_from_poc_bps = abs(features.distance_to_poc_bps)
        else:
            distance_from_poc_bps = abs(features.distance_to_poc) / features.price * 10000
        
        # =================================================================
        # DUAL THRESHOLD CALCULATION (Requirement 2.1-2.12)
        # =================================================================
        # Get VA width from params or calculate from features
        va_width_bps = params.get("va_width_bps")
        if va_width_bps is None and features.value_area_high and features.value_area_low:
            va_width_bps = self.threshold_calculator.calculate_va_width_bps(
                vah=features.value_area_high,
                val=features.value_area_low,
                mid_price=features.price,
            )
        if va_width_bps is None:
            va_width_bps = DEFAULT_VA_WIDTH_BPS
        
        # Get expected cost from params or use default
        expected_cost_bps = params.get("expected_cost_bps", DEFAULT_EXPECTED_COST_BPS)
        
        # Get threshold config from params or use default
        threshold_config = params.get("threshold_config")
        if threshold_config is None:
            # Check for individual threshold params
            k = params.get("threshold_k", 3.0)
            b = params.get("threshold_b", 0.25)
            floor_bps = params.get("threshold_floor_bps", 12.0)
            threshold_config = ThresholdConfig(k=k, b=b, floor_bps=floor_bps)
        
        # Calculate dual thresholds
        dual_threshold = self.threshold_calculator.calculate_dual_threshold(
            expected_cost_bps=expected_cost_bps,
            va_width_bps=va_width_bps,
            config=threshold_config,
        )
        
        # Use setup_threshold_bps for geometric condition evaluation (Requirement 2.10)
        setup_threshold_bps = dual_threshold.setup_threshold_bps
        profitability_threshold_bps = dual_threshold.profitability_threshold_bps
        
        # Log both thresholds alongside actual distance (Requirement 2.12)
        self.threshold_calculator.log_thresholds(
            symbol=features.symbol,
            dual_threshold=dual_threshold,
            actual_distance_bps=distance_from_poc_bps,
            strategy_id=self.strategy_id,
            profile_id=profile_id,
        )
        
        # Fast filter: spread check
        if features.spread > max_spread:
            logger.info(
                f"[{features.symbol}] mean_reversion_fade: Candidate rejected - spread too wide. "
                f"spread={features.spread:.6f}, max_spread={max_spread:.6f}, "
                f"poc_distance_bps={distance_from_poc_bps:.2f}bps, "
                f"setup_threshold_bps={setup_threshold_bps:.2f}bps, "
                f"profile_id={profile_id}"
            )
            return None
        
        # Check ATR - must be calm market
        if atr_ratio is not None and atr_ratio > max_atr_ratio:
            logger.info(
                f"[{features.symbol}] mean_reversion_fade: Candidate rejected - ATR ratio too high. "
                f"atr_ratio={atr_ratio:.3f}, max_atr_ratio={max_atr_ratio:.3f}, "
                f"poc_distance_bps={distance_from_poc_bps:.2f}bps, "
                f"setup_threshold_bps={setup_threshold_bps:.2f}bps, "
                f"profile_id={profile_id}"
            )
            return None
        
        # GEOMETRY VALIDATION: Must be far enough from POC using setup_threshold_bps (Requirement 2.10)
        # This uses the regime-relative setup threshold instead of static min_distance_from_poc_bps
        if distance_from_poc_bps < setup_threshold_bps:
            logger.info(
                f"[{features.symbol}] mean_reversion_fade: Candidate rejected - POC distance too small. "
                f"poc_distance_bps={distance_from_poc_bps:.2f}bps, "
                f"setup_threshold_bps={setup_threshold_bps:.2f}bps, "
                f"binding_constraint={dual_threshold.setup_binding_constraint}, "
                f"va_component_bps={dual_threshold.va_component_bps:.2f}bps, "
                f"floor_component_bps={dual_threshold.floor_component_bps:.2f}bps, "
                f"profile_id={profile_id}"
            )
            return None
        
        # Determine side based on position relative to POC
        price_above_poc = features.distance_to_poc > 0
        poc_price = features.point_of_control
        current_price = features.price
        
        if price_above_poc:
            # Price ABOVE POC → SHORT candidate
            if not allow_shorts:
                return None
            
            # Check orderflow - don't short into strong buy pressure
            orderflow = features.orderflow_imbalance
            if orderflow is not None and orderflow > max_adverse_orderflow:
                logger.info(
                    f"[{features.symbol}] mean_reversion_fade: Candidate rejected - adverse orderflow for short. "
                    f"orderflow={orderflow:.3f}, max_adverse={max_adverse_orderflow:.3f}, "
                    f"profile_id={profile_id}"
                )
                return None
            
            side = "short"
            entry = current_price
            
            # Calculate SL/TP distances in bps
            sl_distance_bps = stop_loss_pct * 10000  # Convert pct to bps
            
            # TP at POC
            if take_profit_target_pct > 0:
                tp_price = poc_price * (1.0 - take_profit_target_pct)
            else:
                tp_price = poc_price
            tp_distance_bps = abs(entry - tp_price) / entry * 10000
            
            # Flow direction required: negative for short
            flow_direction_required = "negative"
            
        else:
            # Price BELOW POC → LONG candidate
            if not allow_longs:
                return None
            
            # Check orderflow - don't long into strong sell pressure
            orderflow = features.orderflow_imbalance
            if orderflow is not None and orderflow < -max_adverse_orderflow:
                logger.info(
                    f"[{features.symbol}] mean_reversion_fade: Candidate rejected - adverse orderflow for long. "
                    f"orderflow={orderflow:.3f}, max_adverse={-max_adverse_orderflow:.3f}, "
                    f"profile_id={profile_id}"
                )
                return None
            
            side = "long"
            entry = current_price
            
            # Calculate SL/TP distances in bps
            sl_distance_bps = stop_loss_pct * 10000  # Convert pct to bps
            
            # TP at POC
            if take_profit_target_pct > 0:
                tp_price = poc_price * (1.0 + take_profit_target_pct)
            else:
                tp_price = poc_price
            tp_distance_bps = abs(tp_price - entry) / entry * 10000
            
            # Flow direction required: positive for long
            flow_direction_required = "positive"
        
        # Calculate setup score based on distance from POC relative to setup threshold
        # Higher distance = higher score (more overextended = better setup)
        # Normalize to 0-1 range using setup_threshold_bps as baseline
        setup_score = min(1.0, 0.5 + (distance_from_poc_bps - setup_threshold_bps) / 100)
        
        # Create CandidateSignal with profitability_threshold_bps for EVGate (Requirement 2.11)
        candidate = CandidateSignal(
            symbol=features.symbol,
            side=side,
            strategy_id=self.strategy_id,
            profile_id=profile_id,
            entry_price=entry,
            sl_distance_bps=sl_distance_bps,
            tp_distance_bps=tp_distance_bps,
            setup_reason=f"mean_rev_{side}_poc_dist_{distance_from_poc_bps:.1f}bps",
            setup_score=setup_score,
            requires_flow_reversal=True,
            flow_direction_required=flow_direction_required,
            max_adverse_trend_bias=max_adverse_trend_bias,
            profitability_threshold_bps=profitability_threshold_bps,
        )
        
        logger.info(
            f"[{features.symbol}] mean_reversion_fade: CandidateSignal generated. "
            f"side={side}, "
            f"entry={entry:.2f}, "
            f"sl_distance_bps={sl_distance_bps:.1f}bps, "
            f"tp_distance_bps={tp_distance_bps:.1f}bps, "
            f"setup_score={setup_score:.3f}, "
            f"poc_distance_bps={distance_from_poc_bps:.2f}bps, "
            f"setup_threshold_bps={setup_threshold_bps:.2f}bps, "
            f"profitability_threshold_bps={profitability_threshold_bps:.2f}bps, "
            f"flow_direction_required={flow_direction_required}, "
            f"profile_id={profile_id}"
        )
        
        return candidate
    
    def _log_signal_costs(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        stop_loss: float,
        size: float,
        fee_model: FeeModel,
        execution_plan,
        features: Features,
        profile_id: str,
    ) -> None:
        """Log comprehensive cost breakdown for signal.
        
        Phase 2: Uses SlippageModel for market-state-adaptive slippage
        and includes adverse selection costs.
        
        Requirements: V2 Proposal Section 9 - Cost Logging
        """
        # Calculate expected fees using ExecutionPolicy
        expected_fee_bps = calculate_expected_fees_bps(
            fee_model=fee_model,
            execution_plan=execution_plan,
            entry_price=entry_price,
            exit_price=exit_price,
            size=size,
        )
        
        # Calculate spread cost (half-spread on entry, half on exit)
        spread_bps = features.spread * 10000  # Convert to bps
        
        # Phase 2: Calculate market-state-adaptive slippage
        order_size_usd = size * entry_price
        book_depth_usd = None
        if features.bid_depth_usd is not None and features.ask_depth_usd is not None:
            book_depth_usd = min(features.bid_depth_usd, features.ask_depth_usd)
        
        # Get volatility regime from features if available
        volatility_regime = getattr(features, "volatility_regime", None)
        spread_percentile = getattr(features, "spread_percentile", None)
        
        slippage_bps = self.slippage_model.calculate_slippage_bps(
            symbol=symbol,
            spread_bps=spread_bps,
            spread_percentile=spread_percentile,
            book_depth_usd=book_depth_usd,
            order_size_usd=order_size_usd,
            volatility_regime=volatility_regime,
            urgency=execution_plan.entry_urgency,
        )
        
        # Phase 2: Calculate adverse selection
        # Estimate hold time based on distance to POC
        # Mean reversion typically holds 2-5 minutes
        estimated_hold_time_sec = 180.0  # 3 minutes default
        
        adverse_selection_bps = calculate_adverse_selection_bps(
            symbol=symbol,
            volatility_regime=volatility_regime,
            hold_time_expected_sec=estimated_hold_time_sec,
        )
        
        # Calculate stop loss distance
        sl_distance_bps = abs(entry_price - stop_loss) / entry_price * 10000
        
        # Calculate take profit distance
        tp_distance_bps = abs(exit_price - entry_price) / entry_price * 10000
        
        # Calculate R (reward-to-risk ratio)
        R = tp_distance_bps / sl_distance_bps if sl_distance_bps > 0 else 0.0
        
        # Total cost (Phase 2: includes adverse selection)
        total_cost_bps = expected_fee_bps + spread_bps + slippage_bps + adverse_selection_bps
        
        # Calculate C (cost ratio)
        C = total_cost_bps / sl_distance_bps if sl_distance_bps > 0 else 0.0
        
        logger.info(
            f"[{symbol}] mean_reversion_fade: Signal cost breakdown (Phase 2). "
            f"side={side}, "
            f"expected_fee={expected_fee_bps:.1f}bps "
            f"(p_entry_maker={execution_plan.p_entry_maker:.1%}, "
            f"p_exit_maker={execution_plan.p_exit_maker:.1%}), "
            f"spread={spread_bps:.1f}bps, "
            f"slippage={slippage_bps:.1f}bps (adaptive), "
            f"adverse_sel={adverse_selection_bps:.1f}bps, "
            f"total_cost={total_cost_bps:.1f}bps, "
            f"SL_distance={sl_distance_bps:.1f}bps, "
            f"TP_distance={tp_distance_bps:.1f}bps, "
            f"R={R:.2f}, "
            f"C={C:.3f}, "
            f"execution_plan={execution_plan.entry_urgency}/{execution_plan.exit_urgency}, "
            f"vol_regime={volatility_regime or 'unknown'}, "
            f"profile_id={profile_id}"
        )