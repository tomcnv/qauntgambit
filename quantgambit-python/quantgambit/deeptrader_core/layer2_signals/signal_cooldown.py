"""
Signal Cooldown - Prevents over-trading

Tracks cooldowns per symbol to prevent:
- Rapid-fire signals
- Whipsaw trades
- Over-trading in choppy markets

Cooldown types:
- Standard cooldown: After any signal (default: 5 seconds)
- Loss cooldown: After a losing trade (default: 30 seconds)
- Chop cooldown: In choppy markets (default: 60 seconds)
"""

import time
from typing import Dict, Optional
from collections import defaultdict


class SignalCooldown:
    """Manages signal cooldowns per symbol"""
    
    def __init__(
        self,
        standard_cooldown_sec: float = 5.0,
        loss_cooldown_sec: float = 30.0,
        chop_cooldown_sec: float = 60.0
    ):
        self.standard_cooldown_sec = standard_cooldown_sec
        self.loss_cooldown_sec = loss_cooldown_sec
        self.chop_cooldown_sec = chop_cooldown_sec
        
        # Cooldown tracking per symbol
        self.cooldowns: Dict[str, float] = {}  # symbol -> cooldown_until timestamp
        self.cooldown_reasons: Dict[str, str] = {}  # symbol -> reason
        
        # Stats
        self.total_cooldowns = 0
        self.cooldown_types = defaultdict(int)
    
    def set_cooldown(
        self,
        symbol: str,
        cooldown_type: str = "standard",
        custom_duration_sec: Optional[float] = None
    ):
        """
        Set a cooldown for a symbol
        
        Args:
            symbol: Trading symbol
            cooldown_type: Type of cooldown ('standard', 'loss', 'chop')
            custom_duration_sec: Custom cooldown duration (overrides type)
        """
        # Determine cooldown duration
        if custom_duration_sec is not None:
            duration_sec = custom_duration_sec
        elif cooldown_type == "loss":
            duration_sec = self.loss_cooldown_sec
        elif cooldown_type == "chop":
            duration_sec = self.chop_cooldown_sec
        else:
            duration_sec = self.standard_cooldown_sec
        
        # Set cooldown
        cooldown_until = time.time() + duration_sec
        self.cooldowns[symbol] = cooldown_until
        self.cooldown_reasons[symbol] = cooldown_type
        
        # Update stats
        self.total_cooldowns += 1
        self.cooldown_types[cooldown_type] += 1
    
    def is_on_cooldown(self, symbol: str) -> bool:
        """
        Check if a symbol is on cooldown
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if on cooldown, False otherwise
        """
        if symbol not in self.cooldowns:
            return False
        
        cooldown_until = self.cooldowns[symbol]
        now = time.time()
        
        if now < cooldown_until:
            return True
        else:
            # Cooldown expired, remove it
            del self.cooldowns[symbol]
            if symbol in self.cooldown_reasons:
                del self.cooldown_reasons[symbol]
            return False
    
    def get_cooldown_remaining(self, symbol: str) -> float:
        """
        Get remaining cooldown time in seconds
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Remaining cooldown time in seconds (0 if not on cooldown)
        """
        if not self.is_on_cooldown(symbol):
            return 0.0
        
        cooldown_until = self.cooldowns[symbol]
        now = time.time()
        return max(0.0, cooldown_until - now)
    
    def get_cooldown_reason(self, symbol: str) -> Optional[str]:
        """
        Get the reason for the cooldown
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Cooldown reason or None if not on cooldown
        """
        if not self.is_on_cooldown(symbol):
            return None
        
        return self.cooldown_reasons.get(symbol)
    
    def clear_cooldown(self, symbol: str):
        """
        Clear cooldown for a symbol
        
        Args:
            symbol: Trading symbol
        """
        if symbol in self.cooldowns:
            del self.cooldowns[symbol]
        if symbol in self.cooldown_reasons:
            del self.cooldown_reasons[symbol]
    
    def clear_all_cooldowns(self):
        """Clear all cooldowns"""
        self.cooldowns.clear()
        self.cooldown_reasons.clear()
    
    def get_stats(self) -> Dict:
        """Get cooldown statistics"""
        active_cooldowns = sum(1 for symbol in list(self.cooldowns.keys()) if self.is_on_cooldown(symbol))
        
        return {
            'total_cooldowns': self.total_cooldowns,
            'active_cooldowns': active_cooldowns,
            'cooldown_types': dict(self.cooldown_types),
            'symbols_on_cooldown': list(self.cooldowns.keys()),
        }
    
    def __str__(self) -> str:
        """Human-readable string representation"""
        active = sum(1 for symbol in list(self.cooldowns.keys()) if self.is_on_cooldown(symbol))
        return f"SignalCooldown(active={active}, total={self.total_cooldowns})"























