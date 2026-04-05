"""
Signal Engine - Main signal generation engine

Generates trading signals from MarketContext with:
- Entry/exit signal generation
- Multi-factor confirmation
- Stop loss and take profit calculation
- Signal strength scoring
- Cooldown management
- Invalidation detection

This is the main entry point for Layer 2 (Signals).
"""

import time
from typing import List, Optional
from quantgambit.deeptrader_core.layer1_predictions import MarketContext
from .trading_signal import TradingSignal, SignalType, SignalStrength, create_signal_id
from .signal_confirmation import SignalConfirmation
from .signal_cooldown import SignalCooldown
from .signal_invalidation import SignalInvalidation


class SignalEngine:
    """Main signal generation engine"""
    
    def __init__(
        self,
        min_confirmations: int = 2,  # Minimum confirmations for a signal
        min_risk_reward: float = 1.5,  # Minimum risk/reward ratio
        standard_cooldown_sec: float = 5.0,
        loss_cooldown_sec: float = 30.0,
        chop_cooldown_sec: float = 60.0,
    ):
        self.min_confirmations = min_confirmations
        self.min_risk_reward = min_risk_reward
        
        # Components
        self.confirmer = SignalConfirmation()
        self.cooldown = SignalCooldown(
            standard_cooldown_sec=standard_cooldown_sec,
            loss_cooldown_sec=loss_cooldown_sec,
            chop_cooldown_sec=chop_cooldown_sec
        )
        self.invalidator = SignalInvalidation()
        
        # Stats
        self.signals_generated = 0
        self.signals_confirmed = 0
        self.signals_rejected = 0
        self.rejection_reasons = {}
        self.last_rejection_reason: Optional[str] = None
    
    def generate_entry_signal(
        self,
        context: MarketContext,
        profile_id: Optional[str] = None,
        strategy_id: Optional[str] = None
    ) -> Optional[TradingSignal]:
        """
        Generate an entry signal (LONG or SHORT)
        
        Args:
            context: MarketContext from Layer 1
            profile_id: Profile ID (optional)
            strategy_id: Strategy ID (optional)
            
        Returns:
            TradingSignal or None if no signal
        """
        symbol = context.symbol
        
        # Check cooldown
        if self.cooldown.is_on_cooldown(symbol):
            self._reject_signal("on_cooldown")
            return None
        
        # Determine signal type based on trend and regime
        signal_type = self._determine_signal_type(context, profile_id=profile_id)
        if signal_type is None:
            self._reject_signal("no_clear_direction")
            return None
        
        # Get confirmations
        confirmations, confirmation_count = self.confirmer.confirm_long_signal(context) if signal_type == SignalType.LONG else self.confirmer.confirm_short_signal(context)
        
        # Check minimum confirmations
        if confirmation_count < self.min_confirmations:
            self._reject_signal(f"insufficient_confirmations ({confirmation_count}/{self.min_confirmations})")
            return None
        
        # Calculate entry, stop loss, and take profit
        entry_price = context.price
        stop_loss, take_profit = self._calculate_levels(context, signal_type)
        
        # Calculate risk/reward
        if signal_type == SignalType.LONG:
            risk_bps = (entry_price - stop_loss) / entry_price * 10000
            reward_bps = (take_profit - entry_price) / entry_price * 10000
        else:  # SHORT
            risk_bps = (stop_loss - entry_price) / entry_price * 10000
            reward_bps = (entry_price - take_profit) / entry_price * 10000
        
        risk_reward_ratio = reward_bps / risk_bps if risk_bps > 0 else 0.0
        
        # Check minimum risk/reward
        if risk_reward_ratio < self.min_risk_reward:
            self._reject_signal(f"insufficient_risk_reward ({risk_reward_ratio:.2f}/{self.min_risk_reward})")
            return None
        
        # Determine signal strength
        signal_strength = self._calculate_signal_strength(confirmation_count, context)
        
        # Calculate confidence
        confidence = self._calculate_confidence(context, confirmation_count)
        
        # Create signal
        signal = TradingSignal(
            symbol=symbol,
            timestamp=time.time(),
            signal_id=create_signal_id(symbol, signal_type, time.time()),
            signal_type=signal_type,
            signal_strength=signal_strength,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_price=entry_price,
            risk_bps=risk_bps,
            reward_bps=reward_bps,
            risk_reward_ratio=risk_reward_ratio,
            confirmations=confirmations,
            confirmation_count=confirmation_count,
            trend_bias=context.trend_bias,
            volatility_regime=context.volatility_regime,
            liquidity_regime=context.liquidity_regime,
            market_regime=context.market_regime,
            profile_id=profile_id,
            strategy_id=strategy_id,
        )
        self.last_rejection_reason = None
        
        # Update stats
        self.signals_generated += 1
        self.signals_confirmed += 1
        
        return signal
    
    def generate_exit_signal(
        self,
        context: MarketContext,
        position_side: str,
        entry_price: float,
        profile_id: Optional[str] = None,
        strategy_id: Optional[str] = None
    ) -> Optional[TradingSignal]:
        """
        Generate an exit signal (CLOSE_LONG or CLOSE_SHORT)
        
        Args:
            context: MarketContext from Layer 1
            position_side: Current position side ('long' or 'short')
            entry_price: Entry price of the position
            profile_id: Profile ID (optional)
            strategy_id: Strategy ID (optional)
            
        Returns:
            TradingSignal or None if no signal
        """
        symbol = context.symbol
        
        # Determine signal type
        if position_side == "long":
            signal_type = SignalType.CLOSE_LONG
        elif position_side == "short":
            signal_type = SignalType.CLOSE_SHORT
        else:
            return None
        
        # Get confirmations
        confirmations, confirmation_count = self.confirmer.confirm_close_signal(
            context, position_side, entry_price
        )
        
        # Check minimum confirmations (lower threshold for exits)
        if confirmation_count < 1:
            return None
        
        # Calculate current P&L
        current_price = context.price
        if position_side == "long":
            pnl_bps = (current_price - entry_price) / entry_price * 10000
        else:
            pnl_bps = (entry_price - current_price) / entry_price * 10000
        
        # Determine signal strength
        signal_strength = self._calculate_signal_strength(confirmation_count, context)
        
        # Calculate confidence
        confidence = self._calculate_confidence(context, confirmation_count)
        
        # Create signal
        signal = TradingSignal(
            symbol=symbol,
            timestamp=time.time(),
            signal_id=create_signal_id(symbol, signal_type, time.time()),
            signal_type=signal_type,
            signal_strength=signal_strength,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=0.0,  # Not applicable for close signals
            take_profit=0.0,  # Not applicable for close signals
            current_price=current_price,
            risk_bps=0.0,
            reward_bps=pnl_bps,
            risk_reward_ratio=0.0,
            confirmations=confirmations,
            confirmation_count=confirmation_count,
            trend_bias=context.trend_bias,
            volatility_regime=context.volatility_regime,
            liquidity_regime=context.liquidity_regime,
            market_regime=context.market_regime,
            profile_id=profile_id,
            strategy_id=strategy_id,
        )
        
        # Update stats
        self.signals_generated += 1
        self.signals_confirmed += 1
        
        return signal
    
    def _determine_signal_type(self, context: MarketContext, profile_id: Optional[str] = None) -> Optional[SignalType]:
        """
        Determine signal type from context
        
        For neutral_market_scalp profile (testing), use more lenient thresholds
        """
        # For neutral profile (testing), use more lenient thresholds
        is_neutral_profile = profile_id == "neutral_market_scalp"
        trend_threshold = 0.3 if is_neutral_profile else 0.5  # Lower threshold for neutral
        orderflow_threshold = 0.2 if is_neutral_profile else 0.3  # Lower threshold for neutral
        orderflow_confidence_threshold = 0.3 if is_neutral_profile else 0.5  # Lower threshold for neutral
        
        # Primary: Use trend bias
        if context.trend_bias == "long" and context.trend_confidence > trend_threshold:
            return SignalType.LONG
        elif context.trend_bias == "short" and context.trend_confidence > trend_threshold:
            return SignalType.SHORT
        
        # Secondary: Use orderflow if trend is neutral
        if context.trend_bias == "neutral":
            if context.orderflow_imbalance > orderflow_threshold and context.orderflow_confidence > orderflow_confidence_threshold:
                return SignalType.LONG
            elif context.orderflow_imbalance < -orderflow_threshold and context.orderflow_confidence > orderflow_confidence_threshold:
                return SignalType.SHORT
        
        # For neutral profile, if still no clear direction, allow a default signal for testing
        if is_neutral_profile and context.trend_bias == "neutral":
            # Default to LONG if orderflow is slightly positive, otherwise SHORT
            if context.orderflow_imbalance >= 0:
                return SignalType.LONG
            else:
                return SignalType.SHORT
        
        return None
    
    def _calculate_levels(
        self,
        context: MarketContext,
        signal_type: SignalType
    ) -> tuple:
        """Calculate stop loss and take profit levels"""
        entry_price = context.price
        atr = context.atr_5m
        
        # Use ATR for stop loss and take profit
        # Stop loss: 1.5 * ATR
        # Take profit: 3.0 * ATR (2:1 R/R)
        
        if signal_type == SignalType.LONG:
            stop_loss = entry_price - (1.5 * atr)
            take_profit = entry_price + (3.0 * atr)
        else:  # SHORT
            stop_loss = entry_price + (1.5 * atr)
            take_profit = entry_price - (3.0 * atr)
        
        return stop_loss, take_profit
    
    def _calculate_signal_strength(
        self,
        confirmation_count: int,
        context: MarketContext
    ) -> SignalStrength:
        """Calculate signal strength from confirmations"""
        if confirmation_count >= 5:
            return SignalStrength.STRONG
        elif confirmation_count >= 3:
            return SignalStrength.MODERATE
        else:
            return SignalStrength.WEAK
    
    def _calculate_confidence(
        self,
        context: MarketContext,
        confirmation_count: int
    ) -> float:
        """Calculate overall signal confidence"""
        # Weighted average of:
        # - Confirmation count (40%)
        # - Trend confidence (30%)
        # - Regime confidence (20%)
        # - Orderflow confidence (10%)
        
        conf_score = min(1.0, confirmation_count / 7.0)  # Max 7 confirmations
        trend_score = context.trend_confidence
        regime_score = context.regime_confidence
        orderflow_score = context.orderflow_confidence
        
        confidence = (
            0.4 * conf_score +
            0.3 * trend_score +
            0.2 * regime_score +
            0.1 * orderflow_score
        )
        
        return min(1.0, max(0.0, confidence))
    
    def _reject_signal(self, reason: str):
        """Record signal rejection"""
        self.signals_rejected += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1
        self.last_rejection_reason = reason
    
    def get_stats(self) -> dict:
        """Get signal engine statistics"""
        return {
            'signals_generated': self.signals_generated,
            'signals_confirmed': self.signals_confirmed,
            'signals_rejected': self.signals_rejected,
            'rejection_reasons': dict(self.rejection_reasons),
            'cooldown_stats': self.cooldown.get_stats(),
            'invalidation_stats': self.invalidator.get_stats(),
        }


def generate_signals(
    context: MarketContext,
    position_side: Optional[str] = None,
    entry_price: Optional[float] = None,
    profile_id: Optional[str] = None,
    strategy_id: Optional[str] = None
) -> List[TradingSignal]:
    """
    Generate trading signals from MarketContext
    
    Args:
        context: MarketContext from Layer 1
        position_side: Current position side (if any)
        entry_price: Entry price (if position exists)
        profile_id: Profile ID (optional)
        strategy_id: Strategy ID (optional)
        
    Returns:
        List of TradingSignals (may be empty)
    """
    engine = SignalEngine()
    signals = []
    
    # Generate exit signal if position exists
    if position_side and entry_price:
        exit_signal = engine.generate_exit_signal(
            context, position_side, entry_price, profile_id, strategy_id
        )
        if exit_signal:
            signals.append(exit_signal)
    
    # Generate entry signal if no position
    if not position_side:
        entry_signal = engine.generate_entry_signal(
            context, profile_id, strategy_id
        )
        if entry_signal:
            signals.append(entry_signal)
    
    return signals























