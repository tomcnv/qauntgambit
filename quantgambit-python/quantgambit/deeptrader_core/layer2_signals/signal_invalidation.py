"""
Signal Invalidation - Detects when signals become invalid

Monitors active signals and detects invalidation conditions:
- Price moved against us significantly
- Market regime changed
- Trend reversed
- Volatility spiked
- Liquidity dried up
- Time-based invalidation (signal too old)

Returns invalidation status and reason.
"""

import time
from typing import Optional, Tuple
from quantgambit.deeptrader_core.layer1_predictions import MarketContext
from .trading_signal import TradingSignal, SignalType


class SignalInvalidation:
    """Detects signal invalidation conditions"""
    
    def __init__(
        self,
        max_adverse_move_bps: float = 20.0,  # 20 bps adverse move = invalidation
        max_signal_age_sec: float = 60.0,    # 60 seconds = signal too old
        volatility_spike_threshold: float = 0.9,  # 90th percentile = spike
    ):
        self.max_adverse_move_bps = max_adverse_move_bps
        self.max_signal_age_sec = max_signal_age_sec
        self.volatility_spike_threshold = volatility_spike_threshold
        
        # Stats
        self.total_invalidations = 0
        self.invalidation_reasons = {}
    
    def check_long_invalidation(
        self,
        signal: TradingSignal,
        context: MarketContext
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a LONG signal is invalidated
        
        Args:
            signal: TradingSignal to check
            context: Current MarketContext
            
        Returns:
            Tuple of (is_invalidated, reason)
        """
        current_price = context.price
        entry_price = signal.entry_price
        
        # 1. Price moved against us significantly
        adverse_move_bps = (entry_price - current_price) / entry_price * 10000
        if adverse_move_bps > self.max_adverse_move_bps:
            return True, f"adverse_move_{adverse_move_bps:.1f}bps"
        
        # 2. Trend reversed
        if context.trend_bias == "short" and context.trend_confidence > 0.7:
            return True, f"trend_reversal_short (conf={context.trend_confidence:.2f})"
        
        # 3. Market regime changed to chop
        if context.market_regime == "chop" and context.regime_confidence > 0.6:
            return True, f"regime_chop (conf={context.regime_confidence:.2f})"
        
        # 4. Volatility spiked
        if context.volatility_percentile > self.volatility_spike_threshold:
            return True, f"volatility_spike (pct={context.volatility_percentile:.2f})"
        
        # 5. Liquidity dried up
        if context.liquidity_regime == "thin":
            return True, "liquidity_thin"
        
        # 6. Orderflow reversed strongly
        if context.orderflow_imbalance < -0.5:
            return True, f"orderflow_reversal (imb={context.orderflow_imbalance:+.2f})"
        
        # 7. Signal too old
        signal_age = time.time() - signal.timestamp
        if signal_age > self.max_signal_age_sec:
            return True, f"signal_too_old ({signal_age:.1f}s)"
        
        return False, None
    
    def check_short_invalidation(
        self,
        signal: TradingSignal,
        context: MarketContext
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a SHORT signal is invalidated
        
        Args:
            signal: TradingSignal to check
            context: Current MarketContext
            
        Returns:
            Tuple of (is_invalidated, reason)
        """
        current_price = context.price
        entry_price = signal.entry_price
        
        # 1. Price moved against us significantly
        adverse_move_bps = (current_price - entry_price) / entry_price * 10000
        if adverse_move_bps > self.max_adverse_move_bps:
            return True, f"adverse_move_{adverse_move_bps:.1f}bps"
        
        # 2. Trend reversed
        if context.trend_bias == "long" and context.trend_confidence > 0.7:
            return True, f"trend_reversal_long (conf={context.trend_confidence:.2f})"
        
        # 3. Market regime changed to chop
        if context.market_regime == "chop" and context.regime_confidence > 0.6:
            return True, f"regime_chop (conf={context.regime_confidence:.2f})"
        
        # 4. Volatility spiked
        if context.volatility_percentile > self.volatility_spike_threshold:
            return True, f"volatility_spike (pct={context.volatility_percentile:.2f})"
        
        # 5. Liquidity dried up
        if context.liquidity_regime == "thin":
            return True, "liquidity_thin"
        
        # 6. Orderflow reversed strongly
        if context.orderflow_imbalance > 0.5:
            return True, f"orderflow_reversal (imb={context.orderflow_imbalance:+.2f})"
        
        # 7. Signal too old
        signal_age = time.time() - signal.timestamp
        if signal_age > self.max_signal_age_sec:
            return True, f"signal_too_old ({signal_age:.1f}s)"
        
        return False, None
    
    def check_invalidation(
        self,
        signal: TradingSignal,
        context: MarketContext
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a signal is invalidated
        
        Args:
            signal: TradingSignal to check
            context: Current MarketContext
            
        Returns:
            Tuple of (is_invalidated, reason)
        """
        if signal.signal_type == SignalType.LONG:
            is_invalidated, reason = self.check_long_invalidation(signal, context)
        elif signal.signal_type == SignalType.SHORT:
            is_invalidated, reason = self.check_short_invalidation(signal, context)
        else:
            # Close signals don't get invalidated
            return False, None
        
        if is_invalidated:
            self.total_invalidations += 1
            if reason:
                self.invalidation_reasons[reason] = self.invalidation_reasons.get(reason, 0) + 1
        
        return is_invalidated, reason
    
    def get_stats(self) -> dict:
        """Get invalidation statistics"""
        return {
            'total_invalidations': self.total_invalidations,
            'invalidation_reasons': dict(self.invalidation_reasons),
        }


def check_invalidation(
    signal: TradingSignal,
    context: MarketContext
) -> Tuple[bool, Optional[str]]:
    """
    Check if a signal is invalidated
    
    Args:
        signal: TradingSignal to check
        context: Current MarketContext
        
    Returns:
        Tuple of (is_invalidated, reason)
    """
    invalidator = SignalInvalidation()
    return invalidator.check_invalidation(signal, context)























