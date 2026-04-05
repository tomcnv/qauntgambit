"""
AMT (Auction Market Theory) Scalping Strategy with Multi-Factor Scoring

This strategy implements rule-based scalping using Auction Market Theory principles
enhanced with multi-factor signal scoring:
- Trades value area rejections and breakouts (AMT primary)
- Uses technical indicators for confirmation
- Incorporates sentiment analysis (news + social)
- Considers on-chain whale activity
- Implements strict risk management
- Focuses on short-term scalps with tight stops
"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from .base_strategy import BaseStrategy, TradingSignal
from .multi_factor_scorer import multi_factor_scorer, SignalDirection
from config.strategies import StrategyConfig, TradingMode, strategy_manager
from quantgambit.deeptrader_core.features import feature_engineer
from quantgambit.deeptrader_core.observability.logger import get_logger

logger = get_logger("amt_scalping")


class AMTScalpingStrategy(BaseStrategy):
    """AMT-based scalping strategy"""

    def __init__(self):
        config = strategy_manager.get_strategy("amt_scalping")
        super().__init__(config)

        # AMT-specific parameters
        self.min_volume_profile_completeness = 0.7
        self.min_rotation_threshold = 3.0
        self.max_holding_minutes = 15
        self.min_time_between_trades = 5  # minutes

    async def analyze_market(self, features: Dict[str, Any], user_settings: Dict[str, Any]) -> Optional[TradingSignal]:
        """
        Analyze market using AMT principles enhanced with multi-factor scoring
        
        AI FILTER INTEGRATION:
        - AI determines IF scalping should run (via strategy_worker check)
        - AI provides position size and stop loss multipliers
        - Rules still determine WHEN to enter/exit (AMT + multi-factor)

        Multi-factor analysis combines:
        1. AMT (40%): Value Area, POC, Rotation factor, Order book imbalance
        2. Technical (25%): RSI, MACD, Bollinger Bands, EMAs
        3. Sentiment (20%): News + Social sentiment
        4. On-chain (15%): Whale activity and flows
        """
        if not self.should_generate_signal(features, user_settings):
            return None

        symbol = features["symbol"]
        exchange = features["exchange"]
        current_price = features.get("last_price", 0)
        user_id = user_settings.get("user_id", "default")
        
        # Extract AI adjustments if present
        ai_adjustments = features.get('ai_adjustments', {})
        position_size_mult = ai_adjustments.get('position_size_multiplier', 1.0)
        stop_loss_mult = ai_adjustments.get('stop_loss_multiplier', 1.0)
        regime_type = ai_adjustments.get('regime_type', 'neutral_ranging')
        risk_level = ai_adjustments.get('risk_level', 'medium')
        ai_reasoning = ai_adjustments.get('reasoning', 'No AI assessment')
        
        if ai_adjustments:
            logger.info(
                f"🤖 AI adjustments for {symbol}: "
                f"regime={regime_type}, risk={risk_level}, "
                f"size={position_size_mult:.2f}x, stop={stop_loss_mult:.2f}x"
            )

        # Use multi-factor scorer to analyze all data sources
        multi_signal = multi_factor_scorer.score_signal(features)
        
        # Log detailed scoring breakdown
        logger.info(
            f"📊 Multi-factor analysis for {symbol}: "
            f"direction={multi_signal.direction.value}, "
            f"score={multi_signal.total_score:.3f}, "
            f"confidence={multi_signal.confidence:.3f}, "
            f"factors={multi_signal.factors_used}/4"
        )
        logger.debug(f"Factor breakdown: {multi_signal.reasons}")
        
        # Check if we should trade based on multi-factor analysis
        if not multi_signal.should_trade:
            logger.debug(f"Multi-factor analysis rejected trade for {symbol}")
            return None
        
        # Create signal based on direction
        # Pass AI adjustments to signal creation
        if multi_signal.direction == SignalDirection.LONG:
            signal = self._create_multi_factor_long_signal(
                symbol, exchange, current_price, multi_signal, features, user_id, user_settings
            )
        elif multi_signal.direction == SignalDirection.SHORT:
            signal = self._create_multi_factor_short_signal(
                symbol, exchange, current_price, multi_signal, features, user_id, user_settings
            )
        else:
            return None
        
        # Apply AI adjustments to signal if present
        if signal and ai_adjustments:
            signal = self._apply_ai_adjustments(signal, ai_adjustments)
        
        return signal

    def _extract_amt_features(self, features: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract AMT-specific features from the feature set"""
        amt_features = {}

        # Value area features
        amt_features["value_area_low"] = features.get("value_area_low")
        amt_features["value_area_high"] = features.get("value_area_high")
        amt_features["point_of_control"] = features.get("point_of_control")
        amt_features["position_in_value"] = features.get("position_in_value")

        # Auction analysis
        amt_features["rotation_factor"] = features.get("rotation_factor", 0)
        amt_features["auction_type"] = features.get("auction_type")

        # Order book features
        amt_features["bid_ask_imbalance"] = features.get("bid_ask_imbalance", 0)
        amt_features["order_book_depth_5"] = features.get("order_book_depth_5", {})

        # Microstructure
        amt_features["trade_flow_imbalance"] = features.get("trade_flow_imbalance", 0)
        amt_features["vwap_deviation"] = features.get("vwap_deviation")

        # Market regime
        amt_features["market_regime"] = features.get("market_regime")
        amt_features["trend_strength"] = features.get("trend_strength", 0)

        # Validate feature completeness
        required_features = ["value_area_low", "value_area_high", "rotation_factor"]
        if not all(amt_features.get(feat) is not None for feat in required_features):
            return None

        return amt_features

    def _check_long_scalp_conditions(self, amt_features: Dict[str, Any],
                                   features: Dict[str, Any], user_settings: Dict[str, Any]) -> bool:
        """
        Check conditions for a long scalping opportunity

        AMT Long Scalp Criteria:
        1. Price testing/rejecting value area low
        2. Strong bid imbalance in order book
        3. Positive rotation factor (buying pressure)
        4. Not in messy market regime
        5. Volume confirmation
        """
        # Price position check
        position = amt_features["position_in_value"]
        if position not in ["below_value", "at_value"]:
            return False

        # Value area rejection check
        current_price = features.get("current_price", 0)
        value_low = amt_features["value_area_low"]

        # Price should be close to value area low (within 0.1%)
        if abs(current_price - value_low) / value_low > 0.001:
            return False

        # Order book confirmation
        bid_imbalance = amt_features["bid_ask_imbalance"]
        if bid_imbalance < 0.3:  # Need strong bid pressure
            return False

        # Rotation factor (buying pressure)
        rotation = amt_features["rotation_factor"]
        if rotation < self.min_rotation_threshold:
            return False

        # Market regime filter
        regime = amt_features.get("market_regime", "")
        if "ranging" in regime and amt_features.get("trend_strength", 0) < 0.3:
            return False  # Too choppy

        # Volume confirmation
        volume_ratio = features.get("volume_ratio", 1.0)
        min_volume = user_settings.get("scalping_min_volume_multiplier", 2.0)
        if volume_ratio < min_volume:
            return False

        # Technical confirmation (RSI not overbought)
        rsi = features.get("rsi")
        if rsi and rsi > 75:
            return False

        # Auction type should be balanced or imbalanced_up
        auction_type = amt_features.get("auction_type")
        if auction_type not in ["balanced", "imbalanced_up", None]:
            return False

        return True

    def _check_short_scalp_conditions(self, amt_features: Dict[str, Any],
                                    features: Dict[str, Any], user_settings: Dict[str, Any]) -> bool:
        """
        Check conditions for a short scalping opportunity

        AMT Short Scalp Criteria:
        1. Price testing/rejecting value area high
        2. Strong ask imbalance in order book
        3. Negative rotation factor (selling pressure)
        4. Not in messy market regime
        5. Volume confirmation
        """
        # Price position check
        position = amt_features["position_in_value"]
        if position not in ["above_value", "at_value"]:
            return False

        # Value area rejection check
        current_price = features.get("current_price", 0)
        value_high = amt_features["value_area_high"]

        # Price should be close to value area high (within 0.1%)
        if abs(current_price - value_high) / value_high > 0.001:
            return False

        # Order book confirmation
        bid_imbalance = amt_features["bid_ask_imbalance"]
        if bid_imbalance > -0.3:  # Need strong ask pressure (negative imbalance)
            return False

        # Rotation factor (selling pressure)
        rotation = amt_features["rotation_factor"]
        if rotation > -self.min_rotation_threshold:
            return False

        # Market regime filter
        regime = amt_features.get("market_regime", "")
        if "ranging" in regime and amt_features.get("trend_strength", 0) < 0.3:
            return False  # Too choppy

        # Volume confirmation
        volume_ratio = features.get("volume_ratio", 1.0)
        min_volume = user_settings.get("scalping_min_volume_multiplier", 2.0)
        if volume_ratio < min_volume:
            return False

        # Technical confirmation (RSI not oversold)
        rsi = features.get("rsi")
        if rsi and rsi < 25:
            return False

        # Auction type should be balanced or imbalanced_down
        auction_type = amt_features.get("auction_type")
        if auction_type not in ["balanced", "imbalanced_down", None]:
            return False

        return True

    def _check_exit_conditions(self, amt_features: Dict[str, Any],
                             features: Dict[str, Any], user_settings: Dict[str, Any]) -> Optional[str]:
        """
        Check for position exit conditions

        Exit signals based on:
        1. Time-based exits (max holding time)
        2. Profit target reached
        3. Stop loss hit
        4. AMT reversal signals
        """
        # This would be implemented with position tracking
        # For now, return None (no exit signals)
        return None

    def _create_multi_factor_long_signal(self, symbol: str, exchange: str, current_price: float,
                                        multi_signal, features: Dict[str, Any],
                                        user_id: str, user_settings: Dict[str, Any]) -> TradingSignal:
        """Create a long signal based on multi-factor analysis"""
        # Calculate position size based on confidence
        available_capital = 10000  # Would come from user portfolio
        risk_per_trade = user_settings.get("risk_per_trade_percent", 0.01)
        
        # Adjust risk based on signal confidence
        adjusted_risk = risk_per_trade * multi_signal.confidence
        
        # Calculate stop loss (tighter for scalping)
        stop_distance_percent = 0.005  # 0.5% for scalping
        stop_loss = current_price * (1 - stop_distance_percent)
        
        # Calculate take profit (2:1 reward/risk)
        take_profit = current_price * (1 + stop_distance_percent * 2)
        
        # Position size
        risk_amount = available_capital * adjusted_risk
        position_size = risk_amount / (current_price * stop_distance_percent)
        
        # Create comprehensive reason string
        reason = f"Multi-factor LONG signal (score={multi_signal.total_score:.3f}, conf={multi_signal.confidence:.3f}): " + \
                 "; ".join(multi_signal.reasons)
        
        return TradingSignal(
            strategy_id=self.config.strategy_id,
            strategy_version="2.0.0",  # Multi-factor version
            symbol=symbol,
            exchange=exchange,
            direction="long",
            signal_type="entry",
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            confidence=multi_signal.confidence,
            reason=reason,
            metadata={
                "multi_factor_score": multi_signal.total_score,
                "amt_score": multi_signal.amt_score.score,
                "technical_score": multi_signal.technical_score.score,
                "sentiment_score": multi_signal.sentiment_score.score,
                "onchain_score": multi_signal.onchain_score.score,
                "factors_used": multi_signal.factors_used,
                "signal_breakdown": multi_signal.reasons
            },
            user_id=user_id,
            timestamp=datetime.utcnow()
        )
    
    def _create_multi_factor_short_signal(self, symbol: str, exchange: str, current_price: float,
                                         multi_signal, features: Dict[str, Any],
                                         user_id: str, user_settings: Dict[str, Any]) -> TradingSignal:
        """Create a short signal based on multi-factor analysis"""
        # Calculate position size based on confidence
        available_capital = 10000  # Would come from user portfolio
        risk_per_trade = user_settings.get("risk_per_trade_percent", 0.01)
        
        # Adjust risk based on signal confidence
        adjusted_risk = risk_per_trade * multi_signal.confidence
        
        # Calculate stop loss (tighter for scalping)
        stop_distance_percent = 0.005  # 0.5% for scalping
        stop_loss = current_price * (1 + stop_distance_percent)
        
        # Calculate take profit (2:1 reward/risk)
        take_profit = current_price * (1 - stop_distance_percent * 2)
        
        # Position size
        risk_amount = available_capital * adjusted_risk
        position_size = risk_amount / (current_price * stop_distance_percent)
        
        # Create comprehensive reason string
        reason = f"Multi-factor SHORT signal (score={multi_signal.total_score:.3f}, conf={multi_signal.confidence:.3f}): " + \
                 "; ".join(multi_signal.reasons)
        
        return TradingSignal(
            strategy_id=self.config.strategy_id,
            strategy_version="2.0.0",  # Multi-factor version
            symbol=symbol,
            exchange=exchange,
            direction="short",
            signal_type="entry",
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            confidence=multi_signal.confidence,
            reason=reason,
            metadata={
                "multi_factor_score": multi_signal.total_score,
                "amt_score": multi_signal.amt_score.score,
                "technical_score": multi_signal.technical_score.score,
                "sentiment_score": multi_signal.sentiment_score.score,
                "onchain_score": multi_signal.onchain_score.score,
                "factors_used": multi_signal.factors_used,
                "signal_breakdown": multi_signal.reasons
            },
            user_id=user_id,
            timestamp=datetime.utcnow()
        )

    def _create_long_signal(self, symbol: str, exchange: str, current_price: float,
                          amt_features: Dict[str, Any], features: Dict[str, Any],
                          user_id: str, user_settings: Dict[str, Any]) -> TradingSignal:
        """Create a long scalping signal"""
        # Calculate position size
        available_capital = 10000  # This would come from user portfolio data
        position_size_usd = self.calculate_position_size(features, user_settings, current_price, available_capital)

        # Calculate stop loss and take profit
        stop_loss = self.calculate_stop_loss(current_price, features, user_settings, is_long=True)
        take_profit = self.calculate_take_profit(current_price, stop_loss, features, user_settings, is_long=True)

        # Build reasoning
        reasoning = self._build_long_reasoning(amt_features, features)

        # Calculate confidence based on signal strength
        confidence = self._calculate_signal_confidence(amt_features, features, "long")

        return TradingSignal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            exchange=exchange,
            action="buy",
            confidence=confidence,
            reasoning=reasoning,
            features_snapshot=features,
            user_id=user_id,
            position_size_usd=position_size_usd,
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
            entry_price=current_price,
            risk_reward_ratio=(take_profit - current_price) / (current_price - stop_loss),
            holding_period_minutes=self.max_holding_minutes
        )

    def _create_short_signal(self, symbol: str, exchange: str, current_price: float,
                           amt_features: Dict[str, Any], features: Dict[str, Any],
                           user_id: str, user_settings: Dict[str, Any]) -> TradingSignal:
        """Create a short scalping signal"""
        # Calculate position size
        available_capital = 10000  # This would come from user portfolio data
        position_size_usd = self.calculate_position_size(features, user_settings, current_price, available_capital)

        # Calculate stop loss and take profit
        stop_loss = self.calculate_stop_loss(current_price, features, user_settings, is_long=False)
        take_profit = self.calculate_take_profit(current_price, stop_loss, features, user_settings, is_long=False)

        # Build reasoning
        reasoning = self._build_short_reasoning(amt_features, features)

        # Calculate confidence based on signal strength
        confidence = self._calculate_signal_confidence(amt_features, features, "short")

        return TradingSignal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            exchange=exchange,
            action="sell",
            confidence=confidence,
            reasoning=reasoning,
            features_snapshot=features,
            user_id=user_id,
            position_size_usd=position_size_usd,
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
            entry_price=current_price,
            risk_reward_ratio=(current_price - take_profit) / (stop_loss - current_price),
            holding_period_minutes=self.max_holding_minutes
        )

    def _create_exit_signal(self, symbol: str, exchange: str, amt_features: Dict[str, Any],
                          features: Dict[str, Any], user_id: str) -> TradingSignal:
        """Create an exit signal"""
        reasoning = "AMT-based exit signal: market conditions changed"

        return TradingSignal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            exchange=exchange,
            action="hold",  # Would be "close" in full implementation
            confidence=7.0,
            reasoning=reasoning,
            features_snapshot=features,
            user_id=user_id
        )

    def _build_long_reasoning(self, amt_features: Dict[str, Any], features: Dict[str, Any]) -> str:
        """Build detailed reasoning for long signal"""
        reasons = []

        # Value area analysis
        position = amt_features["position_in_value"]
        if position in ["below_value", "at_value"]:
            reasons.append(f"Price at value area low (${amt_features['value_area_low']:.2f})")

        # Order book
        imbalance = amt_features["bid_ask_imbalance"]
        if imbalance > 0.3:
            reasons.append(f"Strong bid imbalance ({imbalance:.2f})")

        # Rotation factor
        rotation = amt_features["rotation_factor"]
        if rotation > self.min_rotation_threshold:
            reasons.append(f"Positive rotation factor ({rotation:.1f})")

        # Market regime
        regime = amt_features.get("market_regime", "")
        if regime:
            reasons.append(f"Market regime: {regime}")

        return "Long scalp signal: " + "; ".join(reasons)

    def _build_short_reasoning(self, amt_features: Dict[str, Any], features: Dict[str, Any]) -> str:
        """Build detailed reasoning for short signal"""
        reasons = []

        # Value area analysis
        position = amt_features["position_in_value"]
        if position in ["above_value", "at_value"]:
            reasons.append(f"Price at value area high (${amt_features['value_area_high']:.2f})")

        # Order book
        imbalance = amt_features["bid_ask_imbalance"]
        if imbalance < -0.3:
            reasons.append(f"Strong ask imbalance ({imbalance:.2f})")

        # Rotation factor
        rotation = amt_features["rotation_factor"]
        if rotation < -self.min_rotation_threshold:
            reasons.append(f"Negative rotation factor ({rotation:.1f})")

        # Market regime
        regime = amt_features.get("market_regime", "")
        if regime:
            reasons.append(f"Market regime: {regime}")

        return "Short scalp signal: " + "; ".join(reasons)

    def _calculate_signal_confidence(self, amt_features: Dict[str, Any],
                                   features: Dict[str, Any], direction: str) -> float:
        """Calculate confidence score for the signal (0-10 scale)"""
        confidence = 5.0  # Base confidence

        # AMT alignment (40% weight)
        amt_score = 0
        if amt_features["position_in_value"] in ["at_value"]:
            amt_score += 2  # Exact value area test
        elif amt_features["position_in_value"] in ["below_value", "above_value"]:
            amt_score += 1  # Near value area

        if abs(amt_features["rotation_factor"]) > self.min_rotation_threshold:
            amt_score += 2  # Strong rotation

        if abs(amt_features["bid_ask_imbalance"]) > 0.3:
            amt_score += 1  # Good order book confirmation

        confidence += (amt_score / 5) * 4  # Scale to 0-4 points

        # Technical confirmation (30% weight)
        tech_score = 0
        rsi = features.get("rsi")
        if rsi:
            if direction == "long" and rsi < 70:
                tech_score += 1
            elif direction == "short" and rsi > 30:
                tech_score += 1

        macd_hist = features.get("macd_histogram")
        if macd_hist:
            if (direction == "long" and macd_hist > 0) or (direction == "short" and macd_hist < 0):
                tech_score += 1

        confidence += (tech_score / 2) * 3  # Scale to 0-3 points

        # Market regime (20% weight)
        regime_score = 0
        regime = amt_features.get("market_regime", "")
        trend_strength = amt_features.get("trend_strength", 0)

        if "trend" in regime and trend_strength > 0.5:
            regime_score = 2  # Good trending market
        elif "ranging" in regime and trend_strength < 0.3:
            regime_score = 0  # Too choppy
        else:
            regime_score = 1  # Neutral

        confidence += (regime_score / 2) * 2  # Scale to 0-2 points

        # Volume confirmation (10% weight)
        volume_ratio = features.get("volume_ratio", 1.0)
        if volume_ratio > 2.0:
            confidence += 1

        return min(confidence, 10.0)  # Cap at 10
    
    def _apply_ai_adjustments(self, signal: TradingSignal, ai_adjustments: Dict[str, Any]) -> TradingSignal:
        """
        Apply AI-driven adjustments to the trading signal
        
        AI acts as a filter/supervisor:
        - Adjusts position size based on market regime
        - Widens stops during high volatility
        - Logs AI influence for analysis
        """
        position_size_mult = ai_adjustments.get('position_size_multiplier', 1.0)
        stop_loss_mult = ai_adjustments.get('stop_loss_multiplier', 1.0)
        regime_type = ai_adjustments.get('regime_type', 'neutral_ranging')
        risk_level = ai_adjustments.get('risk_level', 'medium')
        reasoning = ai_adjustments.get('reasoning', 'No AI reasoning provided')
        
        # Store original values for logging
        original_size = signal.position_size
        original_stop = signal.stop_loss
        
        # Apply position size multiplier
        signal.position_size = signal.position_size * position_size_mult
        
        # Apply stop loss multiplier (widen stop distance)
        if signal.side == "long":
            stop_distance = signal.entry_price - signal.stop_loss
            signal.stop_loss = signal.entry_price - (stop_distance * stop_loss_mult)
        else:  # short
            stop_distance = signal.stop_loss - signal.entry_price
            signal.stop_loss = signal.entry_price + (stop_distance * stop_loss_mult)
        
        # Add AI metadata to signal
        if not hasattr(signal, 'metadata'):
            signal.metadata = {}
        
        signal.metadata['ai_adjusted'] = True
        signal.metadata['ai_regime'] = regime_type
        signal.metadata['ai_risk_level'] = risk_level
        signal.metadata['ai_reasoning'] = reasoning
        signal.metadata['position_size_multiplier'] = position_size_mult
        signal.metadata['stop_loss_multiplier'] = stop_loss_mult
        signal.metadata['original_position_size'] = original_size
        signal.metadata['original_stop_loss'] = original_stop
        
        logger.info(
            f"🤖 AI adjustments applied to {signal.symbol} {signal.side} signal: "
            f"size {original_size:.4f} → {signal.position_size:.4f} ({position_size_mult:.2f}x), "
            f"stop ${original_stop:.2f} → ${signal.stop_loss:.2f} ({stop_loss_mult:.2f}x), "
            f"regime={regime_type}, risk={risk_level}"
        )
        logger.debug(f"AI reasoning: {reasoning}")
        
        return signal
