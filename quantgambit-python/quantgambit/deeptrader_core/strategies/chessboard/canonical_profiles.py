"""
Canonical Profile Definitions — Orthogonal Redesign

Design principles:
1. Each strategy maps to EXACTLY ONE profile (1:1).
2. Condition spaces are non-overlapping via hard constraints.
3. Profiles partition the market along 3 axes:
   - Volatility regime: low / normal / high
   - Trend: flat / trending
   - Session: asia / europe / us / overnight / any
4. Every implemented strategy has a home; no dead profiles.

Axis partitioning (ATR ratio with hysteresis):
  low:    < 0.65 entry, < 0.75 exit
  normal: 0.65–1.35
  high:   > 1.35 entry, > 1.25 exit

Trend (EMA spread):
  flat:   |ema_spread| < 0.001
  up/down: |ema_spread| >= 0.001

Sessions (UTC):
  asia:      0–7
  europe:    7–12
  us:       12–22
  overnight: 22–24
"""

from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
    ProfileSpec, ProfileConditions, ProfileRiskParameters, ProfileLifecycle,
    StrategyFamily, TIME_BUDGET_DEFAULTS,
)

_MR = TIME_BUDGET_DEFAULTS[StrategyFamily.MEAN_REVERSION]
_MS = TIME_BUDGET_DEFAULTS[StrategyFamily.MICROSTRUCTURE]
_MOM = TIME_BUDGET_DEFAULTS[StrategyFamily.MOMENTUM]
_POC = TIME_BUDGET_DEFAULTS[StrategyFamily.POC_ROTATION]
_TREND = TIME_BUDGET_DEFAULTS[StrategyFamily.TREND]


# ═══════════════════════════════════════════════════════════════
# QUADRANT 1: LOW VOL + FLAT  (range-bound, quiet markets)
# ═══════════════════════════════════════════════════════════════

POC_MAGNET_SCALP = ProfileSpec(
    id="poc_magnet_profile",
    name="POC Magnet Scalp",
    description="Trade toward POC in quiet, flat markets. Best edge from backtest.",
    conditions=ProfileConditions(
        required_volatility="low",
        required_trend="flat",
        required_value_location="inside",
        max_spread=0.0004,  # 4 bps
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.03,  # 3% = $2,400 on $80K
        max_leverage=2.0,
        stop_loss_pct=0.008,  # Wider SL: 0.8%
        take_profit_pct=0.010,  # Wider TP: 1.0%
        max_hold_time_seconds=180,  # 3 minutes (was 60s)
        min_hold_time_seconds=5,
        time_to_work_sec=60.0,  # 1 minute to show progress
        mfe_min_bps=3.0,
        expected_horizon_sec=120.0,
        poc_distance_atr_multiplier=0.3,
        spread_typical_multiplier=1.5,
        depth_typical_multiplier=0.5,
        stop_loss_atr_multiplier=0.5,
        take_profit_atr_multiplier=0.75,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=5,
    ),
    strategy_ids=["poc_magnet_scalp"],
    strategy_params={
        "poc_magnet_scalp": {
            "min_distance_from_poc_bps": 8.0,
            "max_distance_from_poc_bps": 100.0,
            "rotation_threshold": 0.4,
            "max_adverse_orderflow": 0.6,
            "min_edge_bps": 10.0,
            "fee_bps": 6.0,
            "slippage_bps": 2.0,
        },
    },
    tags=["poc", "mean_reversion", "scalp", "low_vol"],
)

SPREAD_COMPRESSION = ProfileSpec(
    id="spread_compression_profile",
    name="Spread Compression Scalp",
    description="Scalp ultra-tight spreads in compressed, quiet ranges.",
    conditions=ProfileConditions(
        required_volatility="low",
        required_trend="flat",
        max_spread=0.0002,  # 2 bps — ultra tight
        min_trades_per_second=2.0,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.005,
        stop_loss_pct=0.005,
        take_profit_pct=0.005,
        max_hold_time_seconds=_MS.max_hold_sec,
        min_hold_time_seconds=_MS.min_hold_sec,
        time_to_work_sec=_MS.time_to_work_sec,
        mfe_min_bps=_MS.mfe_min_bps,
        expected_horizon_sec=5.0,
        poc_distance_atr_multiplier=0.2,
        spread_typical_multiplier=1.0,
        depth_typical_multiplier=0.7,
        stop_loss_atr_multiplier=0.4,
        take_profit_atr_multiplier=0.65,
    ),
    strategy_ids=["spread_compression"],
    tags=["scalp", "microstructure", "low_vol"],
)

LOW_VOL_GRIND = ProfileSpec(
    id="low_vol_grind_profile",
    name="Low-Vol Grind",
    description="Patient grinding in low-vol flat markets when spreads aren't ultra-tight.",
    conditions=ProfileConditions(
        required_volatility="low",
        required_trend="flat",
        required_value_location="inside",
        # Differentiated from spread_compression by NOT requiring ultra-tight spread
        min_trades_per_second=0.5,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.005,
        max_leverage=1.5,
        stop_loss_pct=0.005,
        take_profit_pct=0.006,
        max_hold_time_seconds=180.0,
        min_hold_time_seconds=5.0,
        time_to_work_sec=20.0,
        mfe_min_bps=3.0,
        expected_horizon_sec=60.0,
        poc_distance_atr_multiplier=0.3,
        spread_typical_multiplier=2.0,
        depth_typical_multiplier=0.5,
        stop_loss_atr_multiplier=0.5,
        take_profit_atr_multiplier=0.75,
    ),
    strategy_ids=["low_vol_grind"],
    tags=["scalp", "low_vol", "conservative"],
)


# ═══════════════════════════════════════════════════════════════
# QUADRANT 2: NORMAL VOL + FLAT  (ranging, moderate activity)
# ═══════════════════════════════════════════════════════════════

VWAP_REVERSION = ProfileSpec(
    id="vwap_reversion_profile",
    name="VWAP Reversion",
    description="Mean reversion to VWAP in normal-vol ranging markets.",
    conditions=ProfileConditions(
        required_volatility="normal",
        required_trend="flat",
        required_value_location="inside",
        min_distance_from_poc=0.0010,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.008,
        stop_loss_pct=0.006,
        take_profit_pct=0.010,
        max_hold_time_seconds=300,
        min_hold_time_seconds=5.0,
        time_to_work_sec=40.0,
        mfe_min_bps=3.0,
        expected_horizon_sec=90.0,
        poc_distance_atr_multiplier=0.4,
        spread_typical_multiplier=2.0,
        depth_typical_multiplier=0.5,
        stop_loss_atr_multiplier=0.6,
        take_profit_atr_multiplier=1.0,
    ),
    strategy_ids=["vwap_reversion"],
    tags=["mean_reversion", "vwap", "normal_vol"],
)

VALUE_AREA_REJECTION = ProfileSpec(
    id="value_area_rejection",
    name="Value Area Rejection",
    description="Fade price rejections at VAH/VAL in normal-vol ranging markets.",
    conditions=ProfileConditions(
        required_volatility="normal",
        required_trend="flat",
        required_value_location="inside",
        min_rotation_factor=3.0,
        min_distance_from_vah=0.0015,
        min_distance_from_val=0.0015,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.04,  # 4% = $3,200 on $80K
        max_leverage=2.5,
        stop_loss_pct=0.005,
        take_profit_pct=0.008,
        max_hold_time_seconds=_POC.max_hold_sec,
        min_hold_time_seconds=_POC.min_hold_sec,
        time_to_work_sec=_POC.time_to_work_sec,
        mfe_min_bps=_POC.mfe_min_bps,
        expected_horizon_sec=120.0,
        poc_distance_atr_multiplier=0.4,
        spread_typical_multiplier=2.5,
        depth_typical_multiplier=0.5,
        stop_loss_atr_multiplier=0.65,
        take_profit_atr_multiplier=1.0,
    ),
    strategy_ids=["amt_value_area_rejection_scalp"],
    strategy_params={
        "amt_value_area_rejection_scalp": {
            "rotation_threshold": 3.0,
            "value_margin": 0.0020,
            "min_edge_bps": 8.0,
            "max_adverse_orderflow": 0.5,
            "fee_bps": 6.0,
            "slippage_bps": 2.0,
            "max_spread": 0.0015,
        },
    },
    tags=["value_area", "rejection", "mean_reversion", "normal_vol"],
)

VALUE_AREA_BREAKOUT_FADE = ProfileSpec(
    id="value_area_breakout_fade_profile",
    name="Value Area Breakout Fade",
    description="Fade breakouts above/below value area - expect rejection back to POC.",
    conditions=ProfileConditions(
        required_volatility="low",  # Changed from normal - match current market
        required_trend="flat",
        required_value_location="outside",  # Above VAH or below VAL
        max_spread=0.0015,  # Raised from 6bps to 15bps for SOL
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.004,  # Smaller size for counter-trend
        max_leverage=1.5,
        stop_loss_pct=0.008,  # 80 bps - wider stop for breakout fades
        take_profit_pct=0.012,  # 120 bps - target back to value area
        max_hold_time_seconds=300.0,  # 5min max
        min_hold_time_seconds=5.0,
        time_to_work_sec=30.0,
        mfe_min_bps=5.0,
        expected_horizon_sec=120.0,
        poc_distance_atr_multiplier=0.5,
        spread_typical_multiplier=2.0,
        depth_typical_multiplier=0.6,
        stop_loss_atr_multiplier=0.8,
        take_profit_atr_multiplier=1.2,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=4,
    ),
    strategy_ids=["amt_value_area_rejection_scalp"],
    strategy_params={
        "amt_value_area_rejection_scalp": {
            "min_distance_from_boundary_bps": 20.0,
            "max_distance_from_boundary_bps": 200.0,
            "rotation_threshold": -0.5,  # Negative = moving away from boundary (breakout)
            "max_favorable_orderflow": 0.7,  # Don't fade strong momentum
            "min_edge_bps": 12.0,
            "fee_bps": 6.0,
            "slippage_bps": 3.0,
        },
    },
    tags=["breakout_fade", "mean_reversion", "scalp", "counter_trend"],
)


# ═══════════════════════════════════════════════════════════════
# QUADRANT 3: NORMAL VOL + TRENDING
# ═══════════════════════════════════════════════════════════════

TREND_PULLBACK = ProfileSpec(
    id="trend_pullback_profile",
    name="Trend Pullback",
    description="Buy dips in uptrend / sell rallies in downtrend. Normal vol.",
    conditions=ProfileConditions(
        required_volatility="normal",
        min_trend_strength=0.0008,
        required_value_location="inside",
        min_rotation_factor=1.5,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.007,
        max_leverage=2.5,
        stop_loss_pct=0.006,
        take_profit_pct=0.010,
        max_hold_time_seconds=_TREND.max_hold_sec,
        min_hold_time_seconds=_TREND.min_hold_sec,
        time_to_work_sec=_TREND.time_to_work_sec,
        mfe_min_bps=_TREND.mfe_min_bps,
        expected_horizon_sec=120.0,
        poc_distance_atr_multiplier=0.5,
        spread_typical_multiplier=2.5,
        depth_typical_multiplier=0.4,
        stop_loss_atr_multiplier=0.75,
        take_profit_atr_multiplier=1.25,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=4,
    ),
    strategy_ids=["trend_pullback"],
    tags=["trend", "pullback", "continuation", "normal_vol"],
)

BREAKOUT_SCALP = ProfileSpec(
    id="breakout_scalp_profile",
    name="Breakout Scalp",
    description="Scalp confirmed breakouts in normal vol with strong rotation.",
    conditions=ProfileConditions(
        required_volatility="normal",
        min_trend_strength=0.0008,
        min_rotation_factor=5.0,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.008,
        max_leverage=3.0,
        stop_loss_pct=0.006,
        take_profit_pct=0.012,
        max_hold_time_seconds=_MOM.max_hold_sec,
        min_hold_time_seconds=_MOM.min_hold_sec,
        time_to_work_sec=_MOM.time_to_work_sec,
        mfe_min_bps=_MOM.mfe_min_bps,
        expected_horizon_sec=20.0,
        poc_distance_atr_multiplier=0.5,
        spread_typical_multiplier=2.5,
        depth_typical_multiplier=0.4,
        stop_loss_atr_multiplier=0.8,
        take_profit_atr_multiplier=1.6,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=3,
    ),
    strategy_ids=["breakout_scalp"],
    tags=["breakout", "momentum", "normal_vol"],
)


# ═══════════════════════════════════════════════════════════════
# QUADRANT 4: HIGH VOL + FLAT  (volatile range, choppy)
# ═══════════════════════════════════════════════════════════════

LIQUIDITY_HUNT = ProfileSpec(
    id="liquidity_hunt_profile",
    name="Stop-Run / Liquidity Hunt",
    description="Fade liquidity hunts and stop runs in high-vol ranging markets.",
    conditions=ProfileConditions(
        required_volatility="high",
        required_trend="flat",
        min_rotation_factor=4.0,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.01,
        stop_loss_pct=0.006,
        take_profit_pct=0.012,
        max_hold_time_seconds=300,
        poc_distance_atr_multiplier=0.7,
        spread_typical_multiplier=3.0,
        depth_typical_multiplier=0.3,
        stop_loss_atr_multiplier=0.8,
        take_profit_atr_multiplier=1.6,
    ),
    strategy_ids=["liquidity_hunt"],
    strategy_params={
        "liquidity_hunt": {
            "min_rotation_factor": 4.0,
            "min_wick_size_pct": 0.0035,
            "max_spread": 0.0025,
        },
    },
    tags=["reversal", "microstructure", "high_vol"],
)

VOL_EXPANSION = ProfileSpec(
    id="vol_expansion_profile",
    name="Volatility Expansion",
    description="Trade vol expansion breakouts in high-vol ranging conditions.",
    conditions=ProfileConditions(
        required_volatility="high",
        required_trend="flat",
        min_rotation_factor=4.0,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.015,
        max_leverage=2.0,
        stop_loss_pct=0.01,
        take_profit_pct=0.02,
        max_hold_time_seconds=600,
        time_to_work_sec=20.0,
        mfe_min_bps=5.0,
        expected_horizon_sec=120.0,
        poc_distance_atr_multiplier=0.7,
        spread_typical_multiplier=3.5,
        depth_typical_multiplier=0.3,
        stop_loss_atr_multiplier=1.2,
        take_profit_atr_multiplier=2.4,
    ),
    strategy_ids=["vol_expansion"],
    tags=["volatility", "breakout", "high_vol"],
)


# ═══════════════════════════════════════════════════════════════
# QUADRANT 5: HIGH VOL + TRENDING  (strong moves)
# ═══════════════════════════════════════════════════════════════

HIGH_VOL_BREAKOUT = ProfileSpec(
    id="high_vol_breakout_profile",
    name="High-Vol Breakout",
    description="Ride strong momentum in high-vol trending markets.",
    conditions=ProfileConditions(
        required_volatility="high",
        min_trend_strength=0.0008,
        min_rotation_factor=3.0,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.02,
        max_leverage=3.0,
        stop_loss_pct=0.008,
        take_profit_pct=0.015,
        max_hold_time_seconds=_MOM.max_hold_sec,
        min_hold_time_seconds=_MOM.min_hold_sec,
        time_to_work_sec=_MOM.time_to_work_sec,
        mfe_min_bps=_MOM.mfe_min_bps,
        expected_horizon_sec=20.0,
        poc_distance_atr_multiplier=0.8,
        spread_typical_multiplier=3.0,
        depth_typical_multiplier=0.4,
        stop_loss_atr_multiplier=1.0,
        take_profit_atr_multiplier=1.9,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=3,
    ),
    strategy_ids=["high_vol_breakout"],
    tags=["momentum", "breakout", "high_vol"],
)

MEAN_REVERSION_FADE = ProfileSpec(
    id="mean_reversion_fade_profile",
    name="Late Trend Exhaustion Fade",
    description="Fade overextended trends in high vol. Counter-trend.",
    conditions=ProfileConditions(
        required_volatility="high",
        min_trend_strength=0.005,
        max_rotation_factor=1.0,  # Weakening momentum
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.01,
        max_leverage=2.0,
        stop_loss_pct=0.008,
        take_profit_pct=0.01,
        max_hold_time_seconds=600,
        min_hold_time_seconds=5.0,
        time_to_work_sec=30.0,
        mfe_min_bps=5.0,
        expected_horizon_sec=180.0,
        poc_distance_atr_multiplier=0.6,
        spread_typical_multiplier=3.0,
        depth_typical_multiplier=0.3,
        stop_loss_atr_multiplier=1.0,
        take_profit_atr_multiplier=1.25,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=4,
    ),
    strategy_ids=["mean_reversion_fade"],
    tags=["reversal", "fade", "contrarian", "high_vol"],
)


# ═══════════════════════════════════════════════════════════════
# SESSION-SPECIFIC PROFILES  (hard session constraint = orthogonal)
# ═══════════════════════════════════════════════════════════════

ASIA_RANGE = ProfileSpec(
    id="asia_range_profile",
    name="Asia Range Scalp",
    description="Range-bound scalping during quiet Asia session.",
    conditions=ProfileConditions(
        required_session="asia",
        required_volatility="low",
        required_value_location="inside",
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.008,
        stop_loss_pct=0.005,
        take_profit_pct=0.008,
        max_hold_time_seconds=300,
        poc_distance_atr_multiplier=0.4,
        spread_typical_multiplier=2.0,
        depth_typical_multiplier=0.5,
        stop_loss_atr_multiplier=0.6,
        take_profit_atr_multiplier=1.0,
    ),
    strategy_ids=["asia_range_scalp"],
    tags=["session", "range", "asia"],
)

EUROPE_OPEN = ProfileSpec(
    id="europe_open_profile",
    name="Europe Open Volatility",
    description="Trade Europe session volatility and opening range breakouts.",
    conditions=ProfileConditions(
        required_session="europe",
        required_volatility="normal",
        min_rotation_factor=2.5,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.015,
        stop_loss_pct=0.008,
        take_profit_pct=0.015,
        max_hold_time_seconds=1800,
        poc_distance_atr_multiplier=0.6,
        spread_typical_multiplier=3.0,
        depth_typical_multiplier=0.4,
        stop_loss_atr_multiplier=1.0,
        take_profit_atr_multiplier=1.9,
    ),
    strategy_ids=["europe_open_vol"],
    tags=["session", "volatility", "europe"],
)

US_OPEN = ProfileSpec(
    id="us_open_profile",
    name="US Open Momentum",
    description="Trade US market open momentum and opening range breakouts.",
    conditions=ProfileConditions(
        required_session="us",
        min_rotation_factor=7.0,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.02,
        max_leverage=3.0,
        stop_loss_pct=0.01,
        take_profit_pct=0.02,
        max_hold_time_seconds=1800,
        poc_distance_atr_multiplier=0.7,
        spread_typical_multiplier=3.0,
        depth_typical_multiplier=0.4,
        stop_loss_atr_multiplier=1.2,
        take_profit_atr_multiplier=2.4,
    ),
    strategy_ids=["us_open_momentum"],
    tags=["session", "momentum", "us"],
)

OVERNIGHT_THIN = ProfileSpec(
    id="overnight_thin_profile",
    name="Overnight Thin Liquidity",
    description="Conservative trading during thin overnight hours.",
    conditions=ProfileConditions(
        required_session="overnight",
        max_spread=0.001,
        min_rotation_factor=8.0,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.005,
        max_leverage=1.5,
        stop_loss_pct=0.005,
        take_profit_pct=0.006,
        max_hold_time_seconds=180.0,
        min_hold_time_seconds=5.0,
        time_to_work_sec=20.0,
        mfe_min_bps=5.0,
        expected_horizon_sec=90.0,
        poc_distance_atr_multiplier=0.3,
        spread_typical_multiplier=1.5,
        depth_typical_multiplier=0.6,
        stop_loss_atr_multiplier=0.5,
        take_profit_atr_multiplier=0.75,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=5,
    ),
    strategy_ids=["overnight_thin"],
    strategy_params={
        "overnight_thin": {
            "min_edge_bps": 12.0,
            "fee_bps": 6.0,
            "slippage_bps": 4.0,
        },
    },
    tags=["session", "conservative", "overnight"],
)

OPENING_RANGE_BREAKOUT = ProfileSpec(
    id="opening_range_breakout_profile",
    name="Opening Range Breakout",
    description="Trade breakouts of first 30min range at session opens.",
    conditions=ProfileConditions(
        # No required_session — works at any session open (router boost for US/EU)
        min_rotation_factor=7.0,
        min_trend_strength=0.001,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.007,
        max_leverage=2.5,
        stop_loss_pct=0.006,
        take_profit_pct=0.012,
        max_hold_time_seconds=1800,
        poc_distance_atr_multiplier=0.5,
        spread_typical_multiplier=2.5,
        depth_typical_multiplier=0.5,
        stop_loss_atr_multiplier=0.75,
        take_profit_atr_multiplier=1.5,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=3,
    ),
    strategy_ids=["opening_range_breakout"],
    tags=["orb", "session_open", "breakout"],
)


# ═══════════════════════════════════════════════════════════════
# COMPATIBILITY PROFILES (legacy IDs retained for router/tests)
# ═══════════════════════════════════════════════════════════════

MIDVOL_MEAN_REVERSION = ProfileSpec(
    id="midvol_mean_reversion",
    name="Mid-Volatility Mean Reversion",
    description="Mean reversion in normal volatility (ATR 1.0-1.6). Legacy compatibility profile for dead-zone coverage.",
    conditions=ProfileConditions(
        min_volatility=1.0,
        max_volatility=1.6,
        required_trend="flat",
        required_value_location="inside",
        max_spread=0.003,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.008,
        max_leverage=2.0,
        stop_loss_pct=0.006,
        take_profit_pct=0.010,
        max_hold_time_seconds=300,
        min_hold_time_seconds=5.0,
        time_to_work_sec=40.0,
        mfe_min_bps=3.0,
        expected_horizon_sec=90.0,
        poc_distance_atr_multiplier=0.6,
        spread_typical_multiplier=2.0,
        depth_typical_multiplier=0.5,
        stop_loss_atr_multiplier=0.7,
        take_profit_atr_multiplier=1.2,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=4,
    ),
    strategy_ids=["mean_reversion_fade"],
    strategy_params={
        "mean_reversion_fade": {
            "max_atr_ratio": 1.4,
            "min_distance_from_poc_pct": 0.003,
            "min_edge_bps": 8.0,
            "max_adverse_orderflow": 0.5,
            "fee_bps": 6.0,
            "slippage_bps": 2.0,
            "max_spread": 0.0020,
            "rotation_reversal_threshold": 0.8,
        },
    },
    tags=["mean_reversion", "mid_vol", "legacy_compat"],
)

MIDVOL_EXPANSION = ProfileSpec(
    id="midvol_expansion",
    name="Mid-Volatility Expansion",
    description="Trade volatility expansion in the 1.4-2.0 ATR zone. Legacy compatibility profile.",
    conditions=ProfileConditions(
        min_volatility=1.4,
        max_volatility=2.0,
        min_rotation_factor=5.0,
        max_spread=0.004,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.01,
        max_leverage=2.5,
        stop_loss_pct=0.008,
        take_profit_pct=0.015,
        max_hold_time_seconds=600,
        min_hold_time_seconds=5.0,
        time_to_work_sec=20.0,
        mfe_min_bps=5.0,
        expected_horizon_sec=120.0,
        poc_distance_atr_multiplier=0.5,
        spread_typical_multiplier=2.5,
        depth_typical_multiplier=0.4,
        stop_loss_atr_multiplier=0.9,
        take_profit_atr_multiplier=1.7,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=3,
    ),
    strategy_ids=["vol_expansion", "breakout_scalp"],
    strategy_params={
        "vol_expansion": {
            "expansion_threshold": 1.4,
            "max_atr_ratio": 2.0,
            "rotation_threshold": 3.0,
            "min_edge_bps": 8.0,
            "fee_bps": 6.0,
            "slippage_bps": 3.0,
        },
        "breakout_scalp": {
            "rotation_threshold": 6.0,
            "min_edge_bps": 8.0,
            "fee_bps": 6.0,
            "slippage_bps": 3.0,
        },
    },
    tags=["vol_expansion", "mid_vol", "legacy_compat"],
)

RANGE_MARKET_SCALP = ProfileSpec(
    id="range_market_scalp",
    name="Range Market Scalp",
    description="Conservative scalping in ranging/quiet markets. Legacy compatibility profile.",
    conditions=ProfileConditions(
        max_spread=0.005,
        required_volatility="normal",
        required_trend="flat",
        required_value_location="inside",
        required_session="us",
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.01,
        max_leverage=2.0,
        stop_loss_pct=0.005,
        take_profit_pct=0.008,
        max_hold_time_seconds=600,
        poc_distance_atr_multiplier=0.5,
        spread_typical_multiplier=2.0,
        depth_typical_multiplier=0.5,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=5,
    ),
    strategy_ids=["mean_reversion_fade", "low_vol_grind"],
    strategy_params={
        "mean_reversion_fade": {
            "max_atr_ratio": 1.5,
            "min_distance_from_poc_pct": 0.0015,
            "rotation_reversal_threshold": 0.05,
            "min_edge_bps": 4.0,
            "max_adverse_orderflow": 0.55,
            "fee_bps": 6.0,
            "slippage_bps": 2.0,
        },
        "low_vol_grind": {
            "max_atr_ratio": 0.8,
            "min_edge_bps": 4.0,
            "fee_bps": 6.0,
            "slippage_bps": 2.0,
        },
    },
    tags=["range", "mean_reversion", "legacy_compat"],
)


# ═══════════════════════════════════════════════════════════════
# TEST PROFILES (only with ENABLE_TEST_PROFILES=true)
# ═══════════════════════════════════════════════════════════════

TEST_SIGNAL_CATCH_ALL = ProfileSpec(
    id="test_signal_catch_all",
    name="Test Signal Catch-All",
    description="TEST MODE: Always generates signals. USE ON TESTNET ONLY.",
    conditions=ProfileConditions(
        max_spread=1.0,
        min_trades_per_second=0.0,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.0005,
        max_leverage=1.0,
        stop_loss_pct=0.02,
        take_profit_pct=0.03,
        max_hold_time_seconds=300,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=0,
        disable_after_consecutive_losses=999,
    ),
    strategy_ids=["test_signal_generator"],
    strategy_params={
        "test_signal_generator": {
            "test_mode_enabled": True,
            "risk_per_trade_pct": 0.05,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.03,
            "allow_longs": True,
            "allow_shorts": True,
        }
    },
    tags=["test"],
)


# ═══════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════

SPREAD_CAPTURE = ProfileSpec(
    id="spread_capture_profile",
    name="Spread Capture Scalp",
    description="Fade orderflow imbalance with maker orders. No directional prediction.",
    conditions=ProfileConditions(
        required_volatility=None,  # works in any volatility
        required_trend=None,  # works in any trend
        required_value_location=None,  # works anywhere
        max_spread=0.0005,  # 5 bps — loosened for more trades
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.025,  # 2.5% = $2,000 on $80K
        max_leverage=2.0,
        stop_loss_pct=0.005,  # Wider SL: 0.5%
        take_profit_pct=0.004,  # Wider TP: 0.4% (was 0.2%)
        max_hold_time_seconds=90,  # 1.5 minutes (was 30s)
        min_hold_time_seconds=5,
        time_to_work_sec=30.0,  # 30 sec to show progress
        mfe_min_bps=2.0,
        expected_horizon_sec=60.0,
        poc_distance_atr_multiplier=0.0,
        spread_typical_multiplier=1.0,
        depth_typical_multiplier=1.0,
        stop_loss_atr_multiplier=0.2,
        take_profit_atr_multiplier=0.15,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=5,
        disable_after_consecutive_losses=10,  # more tolerant
    ),
    strategy_ids=["spread_capture_scalp"],
    strategy_params={
        "spread_capture_scalp": {
            "min_imbalance": 0.35,  # allow moderate but real imbalance spikes
            "max_spread_bps": 5.0,  # loosened from 3.0
            "min_depth_usd": 3000.0,  # lowered from 5000
            "tp_spread_fraction": 4.0,  # current live 0.1 bps books need larger capture target
            "sl_spread_multiple": 3.0,  # 3x spread SL
            "max_hold_sec": 90.0,
            "min_edge_bps": 0.2,  # still positive edge, but not impossible on very tight books
            "fee_bps": 0.0,
            "risk_per_trade_pct": 0.025,
        },
    },
    tags=["microstructure", "mean_reversion", "scalp", "maker"],
)

LIQUIDITY_FADE = ProfileSpec(
    id="liquidity_fade_profile",
    name="Liquidity Fade Scalp",
    description="Fade liquidation cascades after exhaustion. High edge, low frequency.",
    conditions=ProfileConditions(
        required_volatility="high",
        required_trend=None,  # works in any trend during cascades
        max_spread=0.0010,  # 10 bps — cascades widen spreads
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.05,  # 5% = $4,000 on $80K (highest edge)
        max_leverage=2.0,
        stop_loss_pct=0.008,
        take_profit_pct=0.010,
        max_hold_time_seconds=120,
        min_hold_time_seconds=5,
        time_to_work_sec=30.0,
        mfe_min_bps=5.0,
        expected_horizon_sec=60.0,
        poc_distance_atr_multiplier=0.0,
        spread_typical_multiplier=2.0,
        depth_typical_multiplier=0.5,
        stop_loss_atr_multiplier=0.5,
        take_profit_atr_multiplier=0.75,
    ),
    lifecycle=ProfileLifecycle(
        warmup_duration_seconds=10,
        disable_after_consecutive_losses=4,
    ),
    strategy_ids=["liquidity_fade_scalp"],
    strategy_params={
        "liquidity_fade_scalp": {
            "min_move_bps": 12.0,
            "min_trades_per_sec": 3.0,
            "reversal_threshold": 0.2,
            "tp_retrace_fraction": 0.5,
            "sl_buffer_bps": 5.0,
            "max_hold_sec": 120.0,
            "min_edge_bps": 10.0,
            "fee_bps": 0.0,
            "risk_per_trade_pct": 0.05,
        },
    },
    tags=["microstructure", "mean_reversion", "scalp", "high_vol", "maker"],
)

PRODUCTION_PROFILES = [
    # Low vol + flat (range-bound)
    POC_MAGNET_SCALP,
    SPREAD_COMPRESSION,
    LOW_VOL_GRIND,
    # Normal vol + flat (ranging)
    VWAP_REVERSION,
    VALUE_AREA_REJECTION,
    VALUE_AREA_BREAKOUT_FADE,  # NEW: Fade breakouts outside value area
    # Normal vol + trending
    TREND_PULLBACK,
    BREAKOUT_SCALP,
    # High vol + flat (choppy)
    LIQUIDITY_HUNT,
    VOL_EXPANSION,
    # High vol + trending (strong moves)
    HIGH_VOL_BREAKOUT,
    MEAN_REVERSION_FADE,
    # Session-specific
    ASIA_RANGE,
    EUROPE_OPEN,
    US_OPEN,
    OVERNIGHT_THIN,
    OPENING_RANGE_BREAKOUT,
    # Legacy compatibility profiles retained because router/tests still depend on them
    MIDVOL_MEAN_REVERSION,
    MIDVOL_EXPANSION,
    RANGE_MARKET_SCALP,
    # Microstructure / non-directional
    SPREAD_CAPTURE,
    LIQUIDITY_FADE,
]

TEST_PROFILES = [
    TEST_SIGNAL_CATCH_ALL,
]

# ═══════════════════════════════════════════════════════════════
# SPOT PROFILES
# ═══════════════════════════════════════════════════════════════

SPOT_ACCUMULATION = ProfileSpec(
    id="spot_accumulation",
    name="Spot Dip Accumulation",
    description="Default spot profile for normal conditions inside value area. Moderate conviction.",
    conditions=ProfileConditions(
        max_trend_strength=0.45,
        required_value_location="inside",
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.05,  # 5% = $500 per trade
        max_leverage=1.0,
        stop_loss_pct=0.01,
        take_profit_pct=0.012,
        max_hold_time_seconds=14400,
        min_hold_time_seconds=120,
        expected_horizon_sec=3600.0,
    ),
    strategy_ids=["spot_dip_accumulator", "spot_mean_reversion", "spot_momentum_breakout"],
    strategy_params={
        "spot_dip_accumulator": {
            "stop_loss_pct": 0.007,
            "take_profit_pct": 0.006,
            "min_poc_distance_bps": 5.0,
            "max_adverse_orderflow": 0.7,
            "max_spread": 0.006,
        },
        "spot_mean_reversion": {
            "stop_loss_pct": 0.007,
            "take_profit_pct": 0.006,
            "min_poc_distance_bps": 1.0,
            "max_poc_distance_bps": 80.0,
            "max_trend_strength": 0.4,
            "max_spread": 0.006,
        },
        "spot_momentum_breakout": {
            "stop_loss_pct": 0.025,
            "take_profit_pct": 0.03,
            "min_trend_strength": 0.15,
            "min_orderflow": 0.05,
            "min_vah_distance_bps": 1.5,
            "max_spread": 0.006,
        },
    },
    tags=["spot", "accumulation", "dip_buy"],
)

# ── Spot Trend Following ──────────────────────────────────────
# Buys confirmed uptrends. Rides momentum with trailing stop.
# Orthogonal to accumulation: only fires in trending markets.
SPOT_TREND_FOLLOW = ProfileSpec(
    id="spot_trend_follow",
    name="Spot Trend Following",
    description="Buy confirmed uptrends above POC with strong momentum.",
    conditions=ProfileConditions(
        min_trend_strength=0.2,
        required_trend="up",
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.05,  # 5% = $500 per trade
        max_leverage=1.0,
        stop_loss_pct=0.012,
        take_profit_pct=0.02,
        max_hold_time_seconds=28800,
        min_hold_time_seconds=120,
        expected_horizon_sec=3600.0,
    ),
    strategy_ids=["spot_momentum_breakout", "spot_dip_accumulator"],
    strategy_params={
        "spot_momentum_breakout": {
            "stop_loss_pct": 0.012,
            "take_profit_pct": 0.02,
            "min_trend_strength": 0.2,
            "min_orderflow": 0.05,
            "min_vah_distance_bps": 2.0,
            "max_spread": 0.006,
        },
        "spot_dip_accumulator": {
            "stop_loss_pct": 0.012,
            "take_profit_pct": 0.02,
            "max_adverse_orderflow": 0.7,
            "max_spread": 0.006,
        },
    },
    tags=["spot", "trend", "momentum"],
)

# ── Spot Mean Reversion ───────────────────────────────────────
# Range-bound markets only. Buys below POC, sells at POC.
# Orthogonal to trend: only fires when trend is flat/weak.
SPOT_MEAN_REVERT = ProfileSpec(
    id="spot_mean_revert",
    name="Spot Mean Reversion",
    description="Buy below POC in range-bound low-vol markets, target POC reversion.",
    conditions=ProfileConditions(
        max_trend_strength=0.4,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.05,  # 5% = $500 per trade
        max_leverage=1.0,
        stop_loss_pct=0.008,
        take_profit_pct=0.008,
        max_hold_time_seconds=7200,
        min_hold_time_seconds=60,
        expected_horizon_sec=1800.0,
    ),
    strategy_ids=["spot_mean_reversion"],
    strategy_params={
        "spot_mean_reversion": {
            "stop_loss_pct": 0.005,
            "take_profit_pct": 0.004,
            "min_poc_distance_bps": 0.5,
            "max_poc_distance_bps": 150.0,
            "max_trend_strength": 0.45,
            "max_spread": 0.004,
        },
    },
    tags=["spot", "mean_reversion", "range"],
)

# ── Spot Volatility Breakout ──────────────────────────────────
# High vol expansion after squeeze. Catches big moves.
# Orthogonal: only fires in high volatility.
SPOT_VOL_BREAKOUT = ProfileSpec(
    id="spot_vol_breakout",
    name="Spot Volatility Breakout",
    description="Buy breakouts during volatility expansion with strong orderflow.",
    conditions=ProfileConditions(
        required_volatility="high",
        required_value_location="above",
        min_rotation_factor=1.0,
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.04,  # 4% = $400 per trade
        max_leverage=1.0,
        stop_loss_pct=0.01,
        take_profit_pct=0.015,
        max_hold_time_seconds=7200,
        min_hold_time_seconds=120,
        expected_horizon_sec=1800.0,
    ),
    strategy_ids=["spot_momentum_breakout"],
    strategy_params={
        "spot_momentum_breakout": {
            "stop_loss_pct": 0.01,
            "take_profit_pct": 0.015,
            "min_trend_strength": 0.2,
            "min_orderflow": 0.08,
            "min_vah_distance_bps": 2.0,
            "max_spread": 0.01,
        },
    },
    tags=["spot", "volatility", "breakout"],
)

# ── Spot Value Area Dip ───────────────────────────────────────
# The original accumulator but ONLY when price is below value area.
# Most selective — waits for real dips. Best risk/reward.
SPOT_VALUE_DIP = ProfileSpec(
    id="spot_value_dip",
    name="Spot Value Area Dip",
    description="Buy only when price drops below value area low. High conviction dip buy.",
    conditions=ProfileConditions(
        required_value_location="below",
    ),
    risk=ProfileRiskParameters(
        risk_per_trade_pct=0.06,  # 6% = $600 per trade
        max_leverage=1.0,
        stop_loss_pct=0.012,
        take_profit_pct=0.02,
        max_hold_time_seconds=28800,
        min_hold_time_seconds=120,
        expected_horizon_sec=3600.0,
    ),
    strategy_ids=["spot_dip_accumulator"],
    strategy_params={
        "spot_dip_accumulator": {
            "stop_loss_pct": 0.012,
            "take_profit_pct": 0.02,
            "min_poc_distance_bps": 3.0,
            "max_adverse_orderflow": 0.8,
            "max_spread": 0.008,
        },
    },
    tags=["spot", "dip", "value_area", "high_conviction"],
)

SPOT_PROFILES = [SPOT_ACCUMULATION, SPOT_TREND_FOLLOW, SPOT_MEAN_REVERT, SPOT_VOL_BREAKOUT, SPOT_VALUE_DIP]

ALL_CANONICAL_PROFILES = PRODUCTION_PROFILES + TEST_PROFILES


def register_canonical_profiles(include_test_profiles: bool = False) -> None:
    """Register canonical profiles with the global registry."""
    import os
    from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry

    env_include_test = os.getenv("ENABLE_TEST_PROFILES", "false").lower() in ("true", "1", "yes")
    include_test = include_test_profiles or env_include_test
    include_spot = os.getenv("ENABLE_SPOT_PROFILES", "false").lower() in ("true", "1", "yes")
    spot_only = os.getenv("MARKET_TYPE", "").lower() == "spot"

    registry = get_profile_registry()

    if spot_only:
        for profile in SPOT_PROFILES:
            registry.register(profile)
        print(f"✅ Registered {len(SPOT_PROFILES)} Spot profiles (spot-only mode)")
    else:
        for profile in PRODUCTION_PROFILES:
            registry.register(profile)
        if include_spot:
            for profile in SPOT_PROFILES:
                registry.register(profile)
        print(f"✅ Registered {len(PRODUCTION_PROFILES)} Chessboard profiles")

    if include_test:
        for profile in TEST_PROFILES:
            registry.register(profile)
        print("⚠️  TEST PROFILES ENABLED - Not for production use!")
