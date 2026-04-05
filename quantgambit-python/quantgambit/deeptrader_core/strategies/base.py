"""Base Strategy - Abstract interface for trading strategies

All strategies implement this interface to:
- Generate signals from features
- Receive profile-specific parameters
- Return standardized StrategySignal objects
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal


class Strategy(ABC):
    """Abstract base class for trading strategies"""
    
    strategy_id: str
    
    @abstractmethod
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """
        Generate trading signal based on features and profile
        
        Args:
            features: Current market features
            account: Current account/risk state
            profile: Classified market profile
            params: Strategy-specific parameters from profile config
            
        Returns:
            StrategySignal if signal found, None otherwise
        """
        pass

