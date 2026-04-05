"""
Session-Aware Risk Mode Stage

Adjusts risk parameters based on trading session and market conditions.

Session Risk Rules:
- Overnight session (22-24 UTC): risk_mode = "off", no trading
- US session dead hours (0-6 UTC): position_size_multiplier = 0.5
- Asia low volatility: prefer trend following over mean reversion

Requirements:
- 5.1: Overnight session sets risk_mode to "off"
- 5.2: Asia low volatility prefers trend following
- 5.3: US session 0-6 UTC reduces position sizes by 50%
- 5.4: Strategies can define preferred_sessions
- 5.5: Check session match before signal generation
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone


@dataclass
class SessionRiskResult:
    """Result of session risk classification.
    
    Attributes:
        risk_mode: "off", "reduced", or "normal"
        position_size_multiplier: 0.0 to 1.25 (0 = no trading)
        preferred_strategies: List of strategy IDs preferred for this session,
                             or None if all strategies allowed
        session: The classified session name
        reason: Human-readable reason for the classification
    """
    risk_mode: str
    position_size_multiplier: float
    preferred_strategies: Optional[List[str]]
    session: str
    reason: str


def classify_session_risk(
    session: str,
    volatility: str,
    utc_hour: int,
) -> SessionRiskResult:
    """
    Determine session-based risk adjustments.
    
    This function classifies the current trading session and returns
    appropriate risk adjustments based on session, volatility, and time.
    
    Args:
        session: Trading session ("asia", "europe", "us", "overnight")
        volatility: Volatility regime ("low", "normal", "high")
        utc_hour: Current UTC hour (0-23)
    
    Returns:
        SessionRiskResult with risk_mode, position_size_multiplier,
        preferred_strategies, session, and reason.
    
    Session Risk Rules (Requirements 5.1, 5.2, 5.3):
    - Overnight (22-24 UTC): risk_mode = "off", no trading
    - Low liquidity hours (0-6 UTC): 50% position size (US market closed)
    - Asia low volatility: prefer trend following
    """
    # Validate inputs
    session = session.lower() if session else "unknown"
    volatility = volatility.lower() if volatility else "normal"
    utc_hour = max(0, min(23, utc_hour))
    
    # Overnight: no scalping — moves are too small to cover fees
    if session == "overnight":
        return SessionRiskResult(
            risk_mode="off",
            position_size_multiplier=0.0,
            preferred_strategies=None,
            session=session,
            reason="overnight_session_no_scalping",
        )
    
    # Requirement 5.3: Low liquidity hours (0-6 UTC = US market closed)
    # Asia dead zone — avg move only 2.2 bps, not enough for scalping
    if 0 <= utc_hour < 6:
        return SessionRiskResult(
            risk_mode="off",
            position_size_multiplier=0.0,
            preferred_strategies=None,
            session=session,
            reason="low_liquidity_hours_no_scalping",
        )
    
    # Early Asia (6-8 UTC): reduced size, trend only
    if 6 <= utc_hour < 8:
        return SessionRiskResult(
            risk_mode="reduced",
            position_size_multiplier=0.5,
            preferred_strategies=["trend_following", "trend_pullback", "overnight_thin"],
            session=session,
            reason="early_asia_reduced_size",
        )
    
    # Requirement 5.2: Asia low volatility = prefer trend following
    # Mean reversion is risky in low vol Asia sessions
    if session == "asia" and volatility == "low":
        return SessionRiskResult(
            risk_mode="normal",
            position_size_multiplier=1.0,
            preferred_strategies=["trend_following", "trend_pullback", "asia_range_scalp", "spot_dip_accumulator", "spot_mean_reversion", "spot_momentum_breakout"],
            session=session,
            reason="asia_low_vol_prefer_trend",
        )
    
    # Default: normal trading
    return SessionRiskResult(
        risk_mode="normal",
        position_size_multiplier=1.0,
        preferred_strategies=None,  # All strategies allowed
        session=session,
        reason="normal_session",
    )


def get_utc_hour_from_timestamp(timestamp: float) -> int:
    """Extract UTC hour from Unix timestamp."""
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return dt.hour


# Strategy session preferences (Requirement 5.4, 5.5)
# Maps strategy_id to list of preferred sessions
# If a strategy is not in this dict, it's allowed in all sessions
STRATEGY_SESSION_PREFERENCES: Dict[str, List[str]] = {
    # Session-specific strategies
    "asia_range_scalp": ["asia"],
    "europe_open_vol": ["europe"],
    "us_open_momentum": ["us"],
    "overnight_thin": ["overnight"],  # Only strategy allowed overnight
    "opening_range_breakout": ["us", "europe"],  # Market open strategies
    
    # Mean reversion strategies - NOW ENABLED FOR ASIA
    "mean_reversion_fade": ["asia", "europe", "us"],
    "poc_magnet_scalp": ["asia", "europe", "us"],
    "vwap_reversion": ["asia", "europe", "us"],
    "amt_value_area_rejection_scalp": ["asia", "europe", "us"],
    "spread_compression": ["asia", "europe", "us"],
    "low_vol_grind": ["asia", "europe", "us"],
    "breakout_scalp": ["asia", "europe", "us"],
    "order_flow_imbalance": ["asia", "europe", "us"],
    "amt_scalping": ["asia", "europe", "us"],
    "spread_capture_scalp": ["asia", "europe", "us"],
    "liquidity_fade_scalp": ["asia", "europe", "us"],
    
    # Trend strategies - work in most sessions
    "trend_following": ["asia", "europe", "us"],
    "trend_pullback": ["asia", "europe", "us"],
    "high_vol_breakout": ["europe", "us"],  # Need volatility
    
    # All-session strategies (not listed = allowed everywhere)
    # "breakout_scalp", "vol_expansion", etc.
}


def is_strategy_allowed_in_session(
    strategy_id: str,
    session: str,
) -> bool:
    """
    Check if a strategy is allowed in the current session.
    
    Args:
        strategy_id: The strategy identifier
        session: Current trading session
    
    Returns:
        True if strategy is allowed, False otherwise
    
    Requirements 5.4, 5.5: Strategies can define preferred_sessions
    and the system checks session match before signal generation.
    """
    # If strategy not in preferences, it's allowed in all sessions
    if strategy_id not in STRATEGY_SESSION_PREFERENCES:
        return True
    
    allowed_sessions = STRATEGY_SESSION_PREFERENCES[strategy_id]
    return session.lower() in allowed_sessions


def is_strategy_preferred_for_session_risk(
    strategy_id: str,
    session_risk: SessionRiskResult,
) -> bool:
    """
    Check if a strategy is preferred given the session risk result.
    
    Args:
        strategy_id: The strategy identifier
        session_risk: Result from classify_session_risk()
    
    Returns:
        True if strategy is preferred (or all allowed), False otherwise
    """
    # If no preferred strategies, all are allowed
    if session_risk.preferred_strategies is None:
        return True
    
    # If empty list, no strategies allowed (e.g., overnight)
    if len(session_risk.preferred_strategies) == 0:
        return False
    
    return strategy_id in session_risk.preferred_strategies
