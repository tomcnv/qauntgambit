"""
TradingSignal - Unified signal dataclass

This is Layer 2's output: a trading signal with all context needed
for Layer 3 (Risk/Execution) to make a decision.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import time


class SignalType(Enum):
    """Type of trading signal"""
    LONG = "long"
    SHORT = "short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"


class SignalStrength(Enum):
    """Strength of trading signal"""
    WEAK = "weak"          # 1-2 confirmations
    MODERATE = "moderate"  # 3-4 confirmations
    STRONG = "strong"      # 5+ confirmations


@dataclass
class TradingSignal:
    """
    Complete trading signal for a symbol at a point in time
    
    This is the unified output of Layer 2 (Signals) and serves as
    the input to Layer 3 (Risk/Execution).
    
    Contains:
    - Signal type (long/short/close)
    - Signal strength (weak/moderate/strong)
    - Entry/exit prices
    - Stop loss and take profit levels
    - Confirmations (what factors support this signal)
    - Invalidations (what would invalidate this signal)
    - Cooldown info (when can we trade again)
    """
    # Identity
    symbol: str
    timestamp: float
    signal_id: str  # Unique ID for tracking
    
    # Signal Type & Strength
    signal_type: SignalType
    signal_strength: SignalStrength
    confidence: float = 0.0  # 0.0-1.0 overall confidence
    
    # Pricing
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    current_price: float = 0.0
    
    # Risk/Reward
    risk_bps: float = 0.0  # Risk in basis points
    reward_bps: float = 0.0  # Reward in basis points
    risk_reward_ratio: float = 0.0  # Reward / Risk
    
    # Confirmations (what supports this signal)
    confirmations: List[str] = field(default_factory=list)
    confirmation_count: int = 0
    
    # Invalidations (what would invalidate this signal)
    invalidation_triggers: List[str] = field(default_factory=list)
    is_invalidated: bool = False
    invalidation_reason: Optional[str] = None
    
    # Cooldown
    cooldown_until: float = 0.0  # Timestamp when cooldown expires
    is_on_cooldown: bool = False
    
    # Context (from Layer 1)
    trend_bias: str = "neutral"
    volatility_regime: str = "normal"
    liquidity_regime: str = "normal"
    market_regime: str = "range"
    
    # Metadata
    profile_id: Optional[str] = None  # Which profile generated this signal
    strategy_id: Optional[str] = None  # Which strategy generated this signal
    notes: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/storage"""
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            'signal_id': self.signal_id,
            'signal_type': self.signal_type.value,
            'signal_strength': self.signal_strength.value,
            'confidence': self.confidence,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'current_price': self.current_price,
            'risk_bps': self.risk_bps,
            'reward_bps': self.reward_bps,
            'risk_reward_ratio': self.risk_reward_ratio,
            'confirmations': self.confirmations,
            'confirmation_count': self.confirmation_count,
            'invalidation_triggers': self.invalidation_triggers,
            'is_invalidated': self.is_invalidated,
            'invalidation_reason': self.invalidation_reason,
            'cooldown_until': self.cooldown_until,
            'is_on_cooldown': self.is_on_cooldown,
            'trend_bias': self.trend_bias,
            'volatility_regime': self.volatility_regime,
            'liquidity_regime': self.liquidity_regime,
            'market_regime': self.market_regime,
            'profile_id': self.profile_id,
            'strategy_id': self.strategy_id,
            'notes': self.notes,
        }
    
    def is_valid(self) -> bool:
        """Check if signal is valid and ready for execution"""
        return (
            not self.is_invalidated
            and not self.is_on_cooldown
            and self.confidence > 0.0
            and self.confirmation_count >= 1
            and self.entry_price > 0
            and self.stop_loss > 0
            and self.take_profit > 0
            and self.risk_reward_ratio >= 1.0  # Minimum 1:1 R/R
        )
    
    def get_direction(self) -> str:
        """Get signal direction as string"""
        if self.signal_type == SignalType.LONG:
            return "long"
        elif self.signal_type == SignalType.SHORT:
            return "short"
        else:
            return "close"
    
    def get_side(self) -> str:
        """Get order side (buy/sell)"""
        if self.signal_type == SignalType.LONG:
            return "buy"
        elif self.signal_type == SignalType.SHORT:
            return "sell"
        elif self.signal_type == SignalType.CLOSE_LONG:
            return "sell"
        elif self.signal_type == SignalType.CLOSE_SHORT:
            return "buy"
        else:
            return "unknown"
    
    def __str__(self) -> str:
        """Human-readable string representation"""
        return (
            f"TradingSignal({self.symbol} {self.signal_type.value.upper()} "
            f"{self.signal_strength.value} conf={self.confidence:.2f} "
            f"entry=${self.entry_price:.2f} sl=${self.stop_loss:.2f} "
            f"tp=${self.take_profit:.2f} rr={self.risk_reward_ratio:.1f}:1 "
            f"confirmations={self.confirmation_count})"
        )


def create_signal_id(symbol: str, signal_type: SignalType, timestamp: float) -> str:
    """
    Create a unique signal ID
    
    Args:
        symbol: Trading symbol
        signal_type: Signal type
        timestamp: Signal timestamp
        
    Returns:
        Unique signal ID
    """
    return f"{symbol}_{signal_type.value}_{int(timestamp * 1000)}"























