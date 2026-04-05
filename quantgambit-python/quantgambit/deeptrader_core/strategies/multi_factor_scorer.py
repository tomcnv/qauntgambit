"""
Multi-Factor Signal Scoring System

Combines multiple data sources to generate high-confidence trading signals:
- AMT (Auction Market Theory) signals - Primary factor
- Technical indicators - Confirmation factor
- Sentiment analysis - Market psychology factor
- On-chain data - Institutional/whale activity factor

Each factor is scored independently and then weighted to produce a final signal score.
"""
from typing import Dict, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

from quantgambit.deeptrader_core.observability.logger import get_logger

logger = get_logger("multi_factor_scorer")


class SignalDirection(Enum):
    """Signal direction"""
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


@dataclass
class FactorScore:
    """Individual factor score"""
    score: float  # -1.0 to 1.0
    confidence: float  # 0.0 to 1.0
    reason: str


@dataclass
class MultiFactorSignal:
    """Multi-factor trading signal"""
    direction: SignalDirection
    total_score: float  # -1.0 to 1.0
    confidence: float  # 0.0 to 1.0
    amt_score: FactorScore
    technical_score: FactorScore
    sentiment_score: FactorScore
    onchain_score: FactorScore
    factors_used: int
    should_trade: bool
    reasons: list


class MultiFactorScorer:
    """
    Multi-factor scoring system for trading signals
    
    Scoring weights (configurable):
    - AMT: 40% (primary - market microstructure)
    - Technical: 25% (confirmation - traditional indicators)
    - Sentiment: 20% (psychology - news + social)
    - On-chain: 15% (institutional - whale activity)
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize multi-factor scorer with optional config"""
        config = config or {}
        
        # Factor weights (must sum to 1.0)
        self.weights = {
            "amt": config.get("amt_weight", 0.40),
            "technical": config.get("technical_weight", 0.25),
            "sentiment": config.get("sentiment_weight", 0.20),
            "onchain": config.get("onchain_weight", 0.15)
        }
        
        # Minimum thresholds
        self.min_signal_score = config.get("min_signal_score", 0.60)  # 60% confidence
        self.min_factors_required = config.get("min_factors_required", 3)  # At least 3 factors
        self.min_amt_score = config.get("min_amt_score", 0.50)  # AMT must be positive
        
        # Sentiment thresholds
        self.strong_sentiment_threshold = 0.5
        self.weak_sentiment_threshold = 0.2
        
        logger.info(f"📊 Multi-factor scorer initialized with weights: {self.weights}")
    
    def score_signal(self, features: Dict[str, Any]) -> MultiFactorSignal:
        """
        Score a potential trading signal using all available factors
        
        Args:
            features: Enriched market features from feature_worker
            
        Returns:
            MultiFactorSignal with scores and trading decision
        """
        # Score each factor independently
        amt_score = self._score_amt_factor(features)
        technical_score = self._score_technical_factor(features)
        sentiment_score = self._score_sentiment_factor(features)
        onchain_score = self._score_onchain_factor(features)
        
        # Count available factors
        factors_used = sum([
            amt_score.confidence > 0,
            technical_score.confidence > 0,
            sentiment_score.confidence > 0,
            onchain_score.confidence > 0
        ])
        
        # Calculate weighted total score
        total_score = (
            amt_score.score * self.weights["amt"] * amt_score.confidence +
            technical_score.score * self.weights["technical"] * technical_score.confidence +
            sentiment_score.score * self.weights["sentiment"] * sentiment_score.confidence +
            onchain_score.score * self.weights["onchain"] * onchain_score.confidence
        )
        
        # Calculate overall confidence (weighted average of factor confidences)
        total_confidence = (
            amt_score.confidence * self.weights["amt"] +
            technical_score.confidence * self.weights["technical"] +
            sentiment_score.confidence * self.weights["sentiment"] +
            onchain_score.confidence * self.weights["onchain"]
        )
        
        # Determine direction
        if total_score > 0.1:
            direction = SignalDirection.LONG
        elif total_score < -0.1:
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.NEUTRAL
        
        # Collect reasons
        reasons = []
        if amt_score.confidence > 0:
            reasons.append(f"AMT: {amt_score.reason}")
        if technical_score.confidence > 0:
            reasons.append(f"Technical: {technical_score.reason}")
        if sentiment_score.confidence > 0:
            reasons.append(f"Sentiment: {sentiment_score.reason}")
        if onchain_score.confidence > 0:
            reasons.append(f"On-chain: {onchain_score.reason}")
        
        # Decide if we should trade
        should_trade = self._should_execute_trade(
            total_score, total_confidence, factors_used, amt_score
        )
        
        signal = MultiFactorSignal(
            direction=direction,
            total_score=total_score,
            confidence=total_confidence,
            amt_score=amt_score,
            technical_score=technical_score,
            sentiment_score=sentiment_score,
            onchain_score=onchain_score,
            factors_used=factors_used,
            should_trade=should_trade,
            reasons=reasons
        )
        
        # Log signal
        logger.info(
            f"📊 Multi-factor signal: {direction.value} | "
            f"score={total_score:.3f} | confidence={total_confidence:.3f} | "
            f"factors={factors_used}/4 | trade={should_trade}"
        )
        
        # Metrics
        
        return signal
    
    def _score_amt_factor(self, features: Dict[str, Any]) -> FactorScore:
        """
        Score AMT (Auction Market Theory) factor
        
        Looks at:
        - Value area position
        - POC (Point of Control) proximity
        - Rotation factor
        - Auction type
        - Order book imbalance
        """
        score = 0.0
        confidence = 0.0
        reason = "No AMT data"
        
        # Check if AMT features are available
        poc = features.get("poc_price")
        value_high = features.get("value_area_high")
        value_low = features.get("value_area_low")
        rotation = features.get("rotation_factor")
        auction_type = features.get("auction_type")
        bid_ask_imbalance = features.get("bid_ask_imbalance", 0.0)
        
        if poc is None or value_high is None or value_low is None:
            return FactorScore(score=0.0, confidence=0.0, reason="AMT data unavailable")
        
        current_price = features.get("last_price", 0)
        if current_price == 0:
            return FactorScore(score=0.0, confidence=0.0, reason="No price data")
        
        # Calculate value area position (-1 = below, 0 = inside, 1 = above)
        if current_price < value_low:
            value_position = -1
            position_str = "below value area"
        elif current_price > value_high:
            value_position = 1
            position_str = "above value area"
        else:
            value_position = 0
            position_str = "inside value area"
        
        # Score based on value area rejection/breakout
        if value_position == -1 and bid_ask_imbalance > 0.3:
            # Below value with strong bids = potential long
            score = 0.7
            confidence = 0.9
            reason = f"Value area rejection (long) - {position_str}, bid imbalance={bid_ask_imbalance:.2f}"
        elif value_position == 1 and bid_ask_imbalance < -0.3:
            # Above value with strong asks = potential short
            score = -0.7
            confidence = 0.9
            reason = f"Value area rejection (short) - {position_str}, ask imbalance={-bid_ask_imbalance:.2f}"
        elif value_position == 0:
            # Inside value area - use rotation factor
            if rotation and rotation > 3.0:
                score = 0.5
                confidence = 0.7
                reason = f"Strong rotation up (rotation={rotation:.1f})"
            elif rotation and rotation < -3.0:
                score = -0.5
                confidence = 0.7
                reason = f"Strong rotation down (rotation={rotation:.1f})"
            else:
                score = 0.0
                confidence = 0.3
                reason = f"Neutral - {position_str}"
        
        # Boost score if auction type confirms
        if auction_type == "trending_up" and score > 0:
            score = min(1.0, score * 1.2)
            reason += " + trending auction"
        elif auction_type == "trending_down" and score < 0:
            score = max(-1.0, score * 1.2)
            reason += " + trending auction"
        
        return FactorScore(score=score, confidence=confidence, reason=reason)
    
    def _score_technical_factor(self, features: Dict[str, Any]) -> FactorScore:
        """
        Score technical indicators factor
        
        Looks at:
        - RSI (overbought/oversold)
        - MACD (momentum)
        - Bollinger Bands (volatility)
        - EMAs (trend)
        """
        score = 0.0
        confidence = 0.0
        signals = []
        
        # RSI scoring
        rsi = features.get("rsi")
        if rsi is not None:
            if rsi < 30:
                score += 0.4
                signals.append("RSI oversold")
                confidence += 0.3
            elif rsi > 70:
                score -= 0.4
                signals.append("RSI overbought")
                confidence += 0.3
            elif 40 < rsi < 60:
                signals.append("RSI neutral")
                confidence += 0.1
        
        # MACD scoring
        macd_line = features.get("macd_line")
        macd_signal = features.get("macd_signal")
        macd_hist = features.get("macd_histogram")
        
        if macd_line is not None and macd_signal is not None:
            if macd_line > macd_signal and macd_hist and macd_hist > 0:
                score += 0.3
                signals.append("MACD bullish")
                confidence += 0.25
            elif macd_line < macd_signal and macd_hist and macd_hist < 0:
                score -= 0.3
                signals.append("MACD bearish")
                confidence += 0.25
        
        # Bollinger Bands scoring
        price = features.get("last_price", 0)
        bb_upper = features.get("bollinger_upper")
        bb_lower = features.get("bollinger_lower")
        bb_middle = features.get("bollinger_middle")
        
        if price > 0 and bb_upper and bb_lower and bb_middle:
            if price < bb_lower:
                score += 0.3
                signals.append("Price below BB lower")
                confidence += 0.25
            elif price > bb_upper:
                score -= 0.3
                signals.append("Price above BB upper")
                confidence += 0.25
        
        # EMA trend scoring
        ema_9 = features.get("ema_9")
        ema_21 = features.get("ema_21")
        
        if ema_9 and ema_21:
            if ema_9 > ema_21:
                score += 0.2
                signals.append("EMA bullish")
                confidence += 0.2
            elif ema_9 < ema_21:
                score -= 0.2
                signals.append("EMA bearish")
                confidence += 0.2
        
        # Normalize score to -1 to 1
        score = max(-1.0, min(1.0, score))
        
        # Normalize confidence to 0 to 1
        confidence = min(1.0, confidence)
        
        reason = ", ".join(signals) if signals else "No technical data"
        
        return FactorScore(score=score, confidence=confidence, reason=reason)
    
    def _score_sentiment_factor(self, features: Dict[str, Any]) -> FactorScore:
        """
        Score sentiment factor (news + social)
        
        Combines:
        - News sentiment
        - Social sentiment
        - Mention volume
        """
        news_sentiment = features.get("news_sentiment", 0.0)
        social_sentiment = features.get("social_sentiment", 0.0)
        news_articles = features.get("news_article_count", 0)
        social_mentions = features.get("social_mention_count", 0)
        
        # Weight news more heavily if there are many articles
        news_weight = 0.6 if news_articles > 5 else 0.5
        social_weight = 1.0 - news_weight
        
        # Combined sentiment score
        combined_sentiment = (
            news_sentiment * news_weight +
            social_sentiment * social_weight
        )
        
        # Confidence based on data availability
        confidence = 0.0
        if news_articles > 0:
            confidence += 0.5
        if social_mentions > 10:
            confidence += 0.5
        
        # Interpret sentiment
        if abs(combined_sentiment) > self.strong_sentiment_threshold:
            strength = "strong"
        elif abs(combined_sentiment) > self.weak_sentiment_threshold:
            strength = "moderate"
        else:
            strength = "weak"
        
        direction = "bullish" if combined_sentiment > 0 else "bearish" if combined_sentiment < 0 else "neutral"
        
        reason = (
            f"{strength} {direction} sentiment "
            f"(news={news_sentiment:.2f} [{news_articles}], "
            f"social={social_sentiment:.2f} [{social_mentions}])"
        )
        
        return FactorScore(
            score=combined_sentiment,
            confidence=confidence,
            reason=reason
        )
    
    def _score_onchain_factor(self, features: Dict[str, Any]) -> FactorScore:
        """
        Score on-chain factor (whale activity)
        
        Looks at:
        - On-chain sentiment
        - Whale activity count
        - Exchange flows
        """
        onchain_sentiment = features.get("onchain_sentiment", 0.0)
        whale_count = features.get("whale_activity_count", 0)
        
        # Confidence based on whale activity
        if whale_count > 5:
            confidence = 0.9
        elif whale_count > 2:
            confidence = 0.6
        elif whale_count > 0:
            confidence = 0.3
        else:
            confidence = 0.1
        
        # Interpret on-chain sentiment
        if abs(onchain_sentiment) > 0.5:
            strength = "strong"
        elif abs(onchain_sentiment) > 0.2:
            strength = "moderate"
        else:
            strength = "weak"
        
        direction = "bullish" if onchain_sentiment > 0 else "bearish" if onchain_sentiment < 0 else "neutral"
        
        reason = f"{strength} {direction} on-chain activity (whales={whale_count}, sentiment={onchain_sentiment:.2f})"
        
        return FactorScore(
            score=onchain_sentiment,
            confidence=confidence,
            reason=reason
        )
    
    def _should_execute_trade(
        self,
        total_score: float,
        confidence: float,
        factors_used: int,
        amt_score: FactorScore
    ) -> bool:
        """
        Determine if we should execute a trade based on multi-factor analysis
        
        Requirements:
        1. Total score above minimum threshold
        2. Confidence above minimum threshold
        3. Minimum number of factors available
        4. AMT score must be positive (primary factor)
        """
        # Check minimum score
        if abs(total_score) < self.min_signal_score:
            logger.debug(f"Signal score too low: {abs(total_score):.3f} < {self.min_signal_score}")
            return False
        
        # Check minimum confidence
        if confidence < self.min_signal_score:
            logger.debug(f"Confidence too low: {confidence:.3f} < {self.min_signal_score}")
            return False
        
        # Check minimum factors
        if factors_used < self.min_factors_required:
            logger.debug(f"Not enough factors: {factors_used} < {self.min_factors_required}")
            return False
        
        # AMT must agree with signal direction (primary factor)
        if abs(amt_score.score) < self.min_amt_score:
            logger.debug(f"AMT score too weak: {abs(amt_score.score):.3f} < {self.min_amt_score}")
            return False
        
        # AMT direction must match total signal direction
        if (total_score > 0 and amt_score.score < 0) or (total_score < 0 and amt_score.score > 0):
            logger.debug("AMT direction conflicts with total signal")
            return False
        
        logger.info(f"✅ Trade approved: score={total_score:.3f}, confidence={confidence:.3f}, factors={factors_used}")
        return True


# Global scorer instance
multi_factor_scorer = MultiFactorScorer()

