"""
Risk profiles as product feature.

Risk profiles are parameter sets for the RiskMapper. They control:
- Deadband threshold (tau): How strong signal must be to trade
- Maximum position weight (w_max): Position size limit
- Target volatility: Volatility scaling factor
- Churn guard: Minimum position change to trade

Same RiskMapper, different parameters = different trading behavior.

Profiles:
- Conservative: Trade less, smaller positions, strong churn guard
- Balanced: Moderate parameters
- Aggressive: Trade more, larger positions, relaxed churn guard
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any

from quantgambit.core.config.bundle import ConfigObject, create_config_object


@dataclass(frozen=True)
class RiskProfile:
    """
    Risk profile parameters.
    
    These parameters control the RiskMapper behavior.
    
    Attributes:
        name: Profile name
        tau: Deadband threshold (signal must exceed this to trade)
        k: Edge curve steepness (tanh scaling)
        w_max: Maximum position weight (fraction of equity)
        target_vol: Target annualized volatility
        min_delta_w: Minimum position change (churn guard)
        max_leverage: Maximum allowed leverage
        stop_loss_pct: Default stop loss percentage
        take_profit_pct: Default take profit percentage
    """
    
    name: str
    tau: float  # Deadband threshold
    k: float  # Edge curve steepness
    w_max: float  # Max position weight
    target_vol: float  # Target volatility
    min_delta_w: float  # Churn guard threshold
    max_leverage: float  # Max leverage
    stop_loss_pct: float  # Default SL %
    take_profit_pct: float  # Default TP %
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "tau": self.tau,
            "k": self.k,
            "w_max": self.w_max,
            "target_vol": self.target_vol,
            "min_delta_w": self.min_delta_w,
            "max_leverage": self.max_leverage,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskProfile":
        """Deserialize from dictionary."""
        return cls(
            name=data["name"],
            tau=data["tau"],
            k=data["k"],
            w_max=data["w_max"],
            target_vol=data["target_vol"],
            min_delta_w=data["min_delta_w"],
            max_leverage=data["max_leverage"],
            stop_loss_pct=data["stop_loss_pct"],
            take_profit_pct=data["take_profit_pct"],
        )
    
    def to_config_object(self, revision: str = "1.0.0") -> ConfigObject:
        """Convert to versioned ConfigObject."""
        return create_config_object(
            name=f"risk_profile_{self.name}",
            revision=revision,
            content=self.to_dict(),
            created_by="system",
        )
    
    def with_overrides(self, **kwargs) -> "RiskProfile":
        """Create a copy with overridden parameters."""
        data = self.to_dict()
        data.update(kwargs)
        return RiskProfile.from_dict(data)


# =============================================================================
# Standard Risk Profiles
# =============================================================================

CONSERVATIVE_PROFILE = RiskProfile(
    name="conservative",
    tau=0.20,  # Higher deadband - trade less
    k=2.0,  # Gentler curve
    w_max=0.25,  # Max 25% of equity per position
    target_vol=0.15,  # Lower target vol
    min_delta_w=0.10,  # Strong churn guard (10% change minimum)
    max_leverage=2.0,  # Low leverage
    stop_loss_pct=0.015,  # 1.5% tighter stops
    take_profit_pct=0.02,  # 2.0% smaller targets
)

BALANCED_PROFILE = RiskProfile(
    name="balanced",
    tau=0.15,  # Medium deadband
    k=2.5,  # Medium curve
    w_max=0.50,  # Max 50% of equity per position
    target_vol=0.25,  # Medium target vol
    min_delta_w=0.05,  # Moderate churn guard (5% change minimum)
    max_leverage=5.0,  # Medium leverage
    stop_loss_pct=0.02,  # 2.0% medium stops
    take_profit_pct=0.03,  # 3.0% medium targets
)

AGGRESSIVE_PROFILE = RiskProfile(
    name="aggressive",
    tau=0.12,  # Lower deadband - trade more
    k=3.0,  # Steeper curve
    w_max=0.75,  # Max 75% of equity per position
    target_vol=0.40,  # Higher target vol
    min_delta_w=0.03,  # Relaxed churn guard (3% change minimum)
    max_leverage=10.0,  # Higher leverage
    stop_loss_pct=0.03,  # 3.0% wider stops
    take_profit_pct=0.05,  # 5.0% larger targets
)

# Scalping-specific profile (for quant-grade scalping)
SCALPER_PROFILE = RiskProfile(
    name="scalper",
    tau=0.08,  # Very low deadband - trade frequently
    k=3.5,  # Steep curve for decisive signals
    w_max=0.30,  # Moderate position size
    target_vol=0.50,  # High target vol for quick moves
    min_delta_w=0.02,  # Very relaxed churn guard
    max_leverage=10.0,  # High leverage for small moves
    stop_loss_pct=0.005,  # 0.5% very tight stops
    take_profit_pct=0.008,  # 0.8% small targets
)

# Profile registry
PROFILES: Dict[str, RiskProfile] = {
    "conservative": CONSERVATIVE_PROFILE,
    "balanced": BALANCED_PROFILE,
    "aggressive": AGGRESSIVE_PROFILE,
    "scalper": SCALPER_PROFILE,
}


def get_profile_by_name(name: str) -> Optional[RiskProfile]:
    """
    Get a risk profile by name.
    
    Args:
        name: Profile name (case-insensitive)
        
    Returns:
        RiskProfile or None if not found
    """
    return PROFILES.get(name.lower())


def list_profiles() -> list[str]:
    """Get list of available profile names."""
    return list(PROFILES.keys())


def create_custom_profile(
    name: str,
    base: str = "balanced",
    **overrides,
) -> RiskProfile:
    """
    Create a custom profile based on an existing one.
    
    Args:
        name: Name for the new profile
        base: Base profile name
        **overrides: Parameters to override
        
    Returns:
        New RiskProfile
        
    Raises:
        ValueError: If base profile not found
    """
    base_profile = get_profile_by_name(base)
    if base_profile is None:
        raise ValueError(f"Unknown base profile: {base}")
    
    return base_profile.with_overrides(name=name, **overrides)
