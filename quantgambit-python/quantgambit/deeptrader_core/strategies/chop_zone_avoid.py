"""
Chop Zone Avoid Strategy

Defensive strategy that steps aside in unfavorable conditions.

Entry Conditions:
- NONE - This strategy NEVER generates signals
- It exists to explicitly handle "chop zone" market conditions
- Acts as a "wait" strategy

Market Conditions:
- Trend: flat
- Volatility: low
- Value Location: inside
- Rotation: Oscillating (<3)
- Low volume

Purpose:
- Prevent overtrading in choppy, range-bound markets
- Keep system in "observe mode"
- Record metrics for learning
- Better to wait than force trades in poor conditions

Risk Profile:
- Risk per trade: 0% (no trades)
- This profile routes to NO strategy execution

Best Market Conditions to AVOID:
- Flat trend with low volatility
- Price oscillating inside value area
- Weak rotation (no directional bias)
- Low trading volume
"""

import logging
from typing import Optional, Dict, Any
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy

logger = logging.getLogger(__name__)


class ChopZoneAvoid(Strategy):
    """
    Defensive strategy that never trades.
    
    Explicitly handles choppy, low-conviction market conditions by
    stepping aside and waiting for better opportunities.
    """
    
    strategy_id = "chop_zone_avoid"
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """
        Generate signal - ALWAYS returns None (defensive strategy).
        
        Args:
            features: Market features (observed but not acted upon)
            account: Account state (observed but not acted upon)
            profile: Current market profile
            params: Strategy parameters (not used)
            
        Returns:
            None - this strategy never generates signals
        """
        if features.rotation_factor is None:
            return None
        # Log activation for observability and learning
        logger.info(
            f"🛑 Chop Zone Avoid activated | "
            f"profile={profile.id} | "
            f"rotation={features.rotation_factor:.2f} | "
            f"volatility={profile.volatility} | "
            f"Sitting out this market condition"
        )
        
        # ALWAYS return None - this is a "wait" strategy
        return None
