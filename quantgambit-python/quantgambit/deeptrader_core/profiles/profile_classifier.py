"""Profile Classifier - Classify market regimes from features

Uses simple, fast logic to classify current market state:
- Trend: EMAs comparison
- Volatility: ATR ratio to baseline
- Session: UTC hour
- Risk mode: Daily PnL thresholds + Session-based adjustments

Session-Aware Risk (Requirements 5.1, 5.2, 5.3):
- Overnight session: risk_mode = "off"
- US dead hours (0-6 UTC): position_size_multiplier = 0.5
- Asia low volatility: prefer trend following
"""

from datetime import datetime, timezone
from typing import Optional
from quantgambit.deeptrader_core.types import Features, AccountState, Profile


def classify_trend(price: float, ema_fast: float, ema_slow: float) -> str:
    """
    Classify trend from EMA relationship
    
    Returns: "up", "down", or "flat"
    """
    if ema_fast > ema_slow * 1.001:
        return "up"
    elif ema_fast < ema_slow * 0.999:
        return "down"
    return "flat"


def classify_volatility(atr: float, atr_baseline: float) -> str:
    """
    Classify volatility from ATR ratio
    
    Returns: "low", "normal", or "high"
    """
    if atr_baseline <= 0:
        return "normal"
    
    ratio = atr / atr_baseline
    if ratio < 0.7:
        return "low"
    if ratio > 1.3:
        return "high"
    return "normal"


def classify_session(timestamp: float) -> str:
    """
    Classify trading session from UTC time
    
    Session definitions (optimized for crypto trading with US market correlation):
    - Asia: 0-7 UTC (Tokyo/HK hours, 7am-2pm Thailand)
    - Europe: 7-12 UTC (London hours, 2pm-7pm Thailand)
    - US: 12-22 UTC (8pm-5am Thailand)
        * Captures pre-market: 8-9:30 AM ET
        * Full regular hours: 9:30 AM - 4 PM ET
        * After-hours: 4-8 PM ET
        * Works for both EST (UTC-5) and EDT (UTC-4)
    - Overnight: 22-24 UTC (5am-7am Thailand)
    
    US Market in UTC:
    - EST (Nov-Mar): Market 9:30 AM-4 PM EST = 14:30-21:00 UTC
    - EDT (Mar-Nov): Market 9:30 AM-4 PM EDT = 13:30-20:00 UTC
    
    Returns: "asia", "europe", "us", or "overnight"
    """
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    h = dt.hour
    
    if 0 <= h < 7:
        return "asia"
    if 7 <= h < 12:
        return "europe"
    if 12 <= h < 22:
        return "us"
    return "overnight"


def classify_profile(
    features: Features,
    account: AccountState,
    apply_session_risk: bool = True,
) -> Profile:
    """
    Classify complete market profile from features and account state.
    
    Args:
        features: Market features including price, EMAs, ATR, etc.
        account: Account state with daily PnL and risk limits
        apply_session_risk: If True, apply session-based risk adjustments
                           (Requirements 5.1, 5.2, 5.3)
    
    Returns:
        Profile with all dimensions classified, including session risk adjustments
    """
    # Classify each dimension
    trend = classify_trend(features.price, features.ema_fast_15m, features.ema_slow_15m)
    vol = classify_volatility(features.atr_5m, features.atr_5m_baseline)
    session = classify_session(features.timestamp)
    value_loc = features.position_in_value or "inside"  # Default to "inside" if None/empty
    
    # Validate value_loc
    if value_loc not in ["above", "inside", "below"]:
        value_loc = "inside"  # Safe default
    
    # Risk mode based on daily PnL
    # max_daily_loss is negative (e.g., -500), so we use abs() for comparison
    risk_mode = "normal"
    position_size_multiplier = 1.0
    preferred_strategies = None
    session_risk_reason = None
    
    # Hard stop: if losses exceed 70% of max daily loss, turn off trading
    if account.daily_pnl < 0.7 * account.max_daily_loss:
        risk_mode = "off"
    # Recovery mode: if losses are between 30-70% of max daily loss, reduce risk
    elif account.daily_pnl < 0.3 * account.max_daily_loss:
        risk_mode = "recovery"
    # Protection mode: if profits exceed 50% of abs(max daily loss), protect gains
    elif account.daily_pnl > abs(account.max_daily_loss) * 0.5:
        risk_mode = "protection"
    
    # Kill switch: flat + inside + low vol = off
    if trend == "flat" and vol == "low" and value_loc == "inside":
        risk_mode = "off"
    
    # Apply session-based risk adjustments (Requirements 5.1, 5.2, 5.3)
    if apply_session_risk and risk_mode != "off":
        from quantgambit.signals.stages.session_risk import classify_session_risk, get_utc_hour_from_timestamp
        
        utc_hour = get_utc_hour_from_timestamp(features.timestamp)
        session_risk = classify_session_risk(session, vol, utc_hour)
        
        # Requirement 5.1: Overnight session sets risk_mode to "off"
        if session_risk.risk_mode == "off":
            risk_mode = "off"
            session_risk_reason = session_risk.reason
        # Requirement 5.3: Apply position size multiplier for reduced risk
        elif session_risk.risk_mode == "reduced":
            position_size_multiplier = session_risk.position_size_multiplier
            session_risk_reason = session_risk.reason
        
        # Requirement 5.2: Store preferred strategies for session
        preferred_strategies = session_risk.preferred_strategies
    
    # Generate profile ID
    profile_id = f"{trend}_{value_loc}_{vol}_{session}_{risk_mode}"
    
    return Profile(
        id=profile_id,
        trend=trend,
        volatility=vol,
        value_location=value_loc,
        session=session,
        risk_mode=risk_mode,
        position_size_multiplier=position_size_multiplier,
        preferred_strategies=preferred_strategies,
        session_risk_reason=session_risk_reason,
    )

