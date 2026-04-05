"""
Feature engineering module for DeepTrader
Combines all feature calculators into a unified interface
"""
from typing import Dict, List, Any, Optional
from datetime import datetime

from .amt_metrics import amt_calculator
from .order_book_features import order_book_calculator
from .technical_indicators import technical_calculator
from .microstructure import microstructure_calculator


class FeatureEngineer:
    """Unified feature engineering interface"""

    def __init__(self):
        self.amt_calculator = amt_calculator
        self.order_book_calculator = order_book_calculator
        self.technical_calculator = technical_calculator
        self.microstructure_calculator = microstructure_calculator

    async def calculate_all_features(
        self,
        symbol: str,
        exchange: str,
        market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive feature set for strategy decisions

        Args:
            symbol: Trading symbol
            exchange: Exchange name
            market_data: Dictionary containing:
                - candles: List of OHLCV candles
                - orderbook: Current order book
                - recent_trades: Recent trades
                - current_price: Current price

        Returns:
            Comprehensive feature dictionary
        """
        try:
            current_price = market_data.get("current_price", 0)
            candles = market_data.get("candles", [])
            orderbook = market_data.get("orderbook", {})
            recent_trades = market_data.get("recent_trades", [])

            # Calculate features in parallel where possible
            features = {
                "symbol": symbol,
                "exchange": exchange,
                "timestamp": datetime.utcnow(),
                "current_price": current_price,
                "data_quality": self._assess_data_quality(market_data)
            }

            # AMT features (asynchronous)
            amt_features = await self.amt_calculator.get_comprehensive_amt_features(
                symbol, exchange, current_price
            )
            features.update(amt_features)

            # Technical indicators (synchronous)
            if candles:
                tech_features = self.technical_calculator.calculate_all_indicators(candles)
                features.update(tech_features)

            # Order book features (synchronous)
            if orderbook:
                ob_features = self.order_book_calculator.calculate_microstructure_features(
                    orderbook, recent_trades
                )
                features.update(ob_features)

            # Microstructure features (synchronous)
            if orderbook and recent_trades:
                micro_features = self.microstructure_calculator.calculate_comprehensive_microstructure(
                    symbol, exchange, orderbook, recent_trades
                )
                features.update(micro_features)

            # Calculate overall feature confidence
            features["feature_confidence"] = self._calculate_feature_confidence(features)

            # Add metadata
            features["feature_calculation_time"] = datetime.utcnow()
            features["feature_version"] = "1.0.0"

            return features

        except Exception as e:
            return {
                "error": f"Feature calculation failed: {e}",
                "symbol": symbol,
                "exchange": exchange,
                "timestamp": datetime.utcnow()
            }

    def _assess_data_quality(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Assess the quality of input market data"""
        quality = {
            "candles_available": len(market_data.get("candles", [])) > 0,
            "orderbook_available": bool(market_data.get("orderbook")),
            "trades_available": len(market_data.get("recent_trades", [])) > 0,
            "current_price_available": market_data.get("current_price", 0) > 0,
            "overall_quality": "poor"
        }

        # Calculate overall quality score
        quality_components = [
            quality["candles_available"],
            quality["orderbook_available"],
            quality["trades_available"],
            quality["current_price_available"]
        ]

        quality_score = sum(quality_components) / len(quality_components)

        if quality_score >= 0.75:
            quality["overall_quality"] = "excellent"
        elif quality_score >= 0.5:
            quality["overall_quality"] = "good"
        elif quality_score >= 0.25:
            quality["overall_quality"] = "fair"
        else:
            quality["overall_quality"] = "poor"

        return quality

    def _calculate_feature_confidence(self, features: Dict[str, Any]) -> float:
        """Calculate overall confidence in the feature set"""
        confidence_components = []

        # AMT confidence
        if "feature_completeness" in features:
            confidence_components.append(features["feature_completeness"])

        # Technical indicators confidence
        if "indicator_completeness" in features:
            confidence_components.append(features["indicator_completeness"])

        # Data quality confidence
        data_quality = features.get("data_quality", {})
        if data_quality.get("overall_quality") == "excellent":
            confidence_components.append(1.0)
        elif data_quality.get("overall_quality") == "good":
            confidence_components.append(0.8)
        elif data_quality.get("overall_quality") == "fair":
            confidence_components.append(0.6)
        else:
            confidence_components.append(0.3)

        # Microstructure confidence
        if "microstructure_health_score" in features:
            confidence_components.append(features["microstructure_health_score"])

        return sum(confidence_components) / len(confidence_components) if confidence_components else 0.0

    async def calculate_realtime_features(
        self,
        symbol: str,
        exchange: str,
        current_price: float,
        orderbook: Dict[str, Any],
        recent_trades: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculate real-time features for high-frequency decisions

        This is a lighter version optimized for speed in live trading.
        """
        try:
            features = {
                "symbol": symbol,
                "exchange": exchange,
                "timestamp": datetime.utcnow(),
                "current_price": current_price,
                "feature_type": "realtime"
            }

            # Fast AMT features
            amt_features = await self.amt_calculator.calculate_intraday_volume_profile(
                symbol, exchange, lookback_hours=4  # Shorter lookback for speed
            )
            features.update(amt_features)

            # Fast order book features
            if orderbook:
                ob_features = self.order_book_calculator.calculate_microstructure_features(
                    orderbook, recent_trades[-20:]  # Last 20 trades only
                )
                features.update(ob_features)

            # Fast microstructure
            if orderbook and recent_trades:
                micro_features = self.microstructure_calculator.calculate_comprehensive_microstructure(
                    symbol, exchange, orderbook, recent_trades[-50:], lookback_seconds=30  # 30 seconds
                )
                features.update(micro_features)

            features["feature_confidence"] = self._calculate_feature_confidence(features)

            return features

        except Exception as e:
            return {
                "error": f"Realtime feature calculation failed: {e}",
                "symbol": symbol,
                "exchange": exchange,
                "timestamp": datetime.utcnow()
            }

    def get_feature_importance(self) -> Dict[str, float]:
        """Get relative importance weights for different feature categories"""
        return {
            "amt_features": 0.35,  # Auction Market Theory (most important for scalping)
            "technical_indicators": 0.25,
            "orderbook_features": 0.20,
            "microstructure_features": 0.15,
            "data_quality": 0.05
        }

    def validate_features(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Validate feature completeness and reasonableness"""
        validation = {
            "is_valid": True,
            "missing_features": [],
            "invalid_values": [],
            "warnings": []
        }

        # Check for required features
        required_features = [
            "current_price", "value_area_low", "value_area_high",
            "rsi", "ema_9", "bid_ask_imbalance"
        ]

        for feature in required_features:
            if feature not in features or features[feature] is None:
                validation["missing_features"].append(feature)
                validation["is_valid"] = False

        # Check for reasonable value ranges
        if features.get("current_price", 0) <= 0:
            validation["invalid_values"].append("current_price")
            validation["is_valid"] = False

        if features.get("rsi", 50) < 0 or features.get("rsi", 50) > 100:
            validation["warnings"].append("rsi_out_of_range")

        # Check feature confidence
        if features.get("feature_confidence", 0) < 0.3:
            validation["warnings"].append("low_feature_confidence")

        return validation


# Global feature engineer instance
feature_engineer = FeatureEngineer()
