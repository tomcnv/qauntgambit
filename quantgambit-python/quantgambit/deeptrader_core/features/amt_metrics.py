"""
AMT (Auction Market Theory) metrics calculator
Implements value areas, point of control, rotation factors, and auction analysis
"""
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

from config.config import config
from quantgambit.deeptrader_core.storage.timescale_writer import TimescaleWriter


class AMTMetricsCalculator:
    """Calculates Auction Market Theory metrics from market data"""

    def __init__(self):
        self.timescale_writer = TimescaleWriter()
        self.cache = {}  # Cache for computed metrics

    async def calculate_intraday_volume_profile(
        self,
        symbol: str,
        exchange: str,
        timeframe: str = "5m",
        lookback_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Calculate intraday volume profile for AMT analysis

        The volume profile shows where trading activity is concentrated,
        helping identify value areas and points of control.
        """
        try:
            # Get recent candles
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=lookback_hours)

            # Query candles from TimescaleDB
            candles = await self.timescale_writer.get_recent_candles(
                symbol, exchange, timeframe, limit=lookback_hours * 12  # Assume 5m candles = 12 per hour
            )

            if len(candles) < 10:
                return {"error": "Insufficient data for volume profile"}

            # Extract price and volume data
            prices = []
            volumes = []

            for candle in candles:
                # Use OHLC average as representative price
                price = (candle["open"] + candle["high"] + candle["low"] + candle["close"]) / 4
                prices.append(price)
                volumes.append(candle["volume"])

            # Calculate volume profile
            volume_profile = self._calculate_volume_profile(prices, volumes)

            # Determine position relative to value area
            current_price = prices[-1] if prices else None
            position_in_value = self._determine_position_in_value(
                current_price, volume_profile
            )

            result = {
                "symbol": symbol,
                "exchange": exchange,
                "timeframe": timeframe,
                "timestamp": datetime.utcnow(),
                "value_area_low": volume_profile["value_area_low"],
                "value_area_high": volume_profile["value_area_high"],
                "point_of_control": volume_profile["point_of_control"],
                "total_volume": volume_profile["total_volume"],
                "position_in_value": position_in_value,
                "value_area_percentage": volume_profile.get("value_area_percentage", 68.0),
                "profile_bins": volume_profile["bins"],
                "profile_range": {
                    "min_price": volume_profile["min_price"],
                    "max_price": volume_profile["max_price"]
                }
            }

            return result

        except Exception as e:
            return {"error": f"Failed to calculate volume profile: {e}"}

    async def calculate_rotation_factor(
        self,
        symbol: str,
        exchange: str,
        timeframe: str = "1m",
        lookback_minutes: int = 60
    ) -> float:
        """
        Calculate rotation factor - measures directional auction attempts

        Rotation factor indicates how aggressively price is being pushed
        in one direction vs the other, helping identify imbalance.
        """
        try:
            # Get recent trades
            trades = await self.timescale_writer.get_recent_trades(
                symbol, exchange, limit=lookback_minutes * 10  # Estimate trades per minute
            )

            if len(trades) < 20:
                return 0.0

            # Calculate buying vs selling pressure
            buy_volume = sum(trade["volume"] for trade in trades if trade["side"] == "buy")
            sell_volume = sum(trade["volume"] for trade in trades if trade["side"] == "sell")
            total_volume = buy_volume + sell_volume

            if total_volume == 0:
                return 0.0

            # Rotation factor: positive = buying pressure, negative = selling pressure
            rotation_factor = (buy_volume - sell_volume) / total_volume

            # Scale to -10 to +10 range for better interpretation
            rotation_factor *= 10

            return float(rotation_factor)

        except Exception as e:
            print(f"❌ Error calculating rotation factor: {e}")
            return 0.0

    async def detect_auction_type(
        self,
        symbol: str,
        exchange: str,
        current_price: float,
        volume_profile: Dict[str, Any]
    ) -> str:
        """
        Detect current auction type based on price position and volume profile

        Returns:
        - 'balanced': Price in value area, normal activity
        - 'imbalanced_up': Price above value area, potential uptrend
        - 'imbalanced_down': Price below value area, potential downtrend
        """
        try:
            position = self._determine_position_in_value(current_price, volume_profile)

            if position == "inside_value":
                return "balanced"
            elif position == "above_value":
                return "imbalanced_up"
            elif position == "below_value":
                return "imbalanced_down"
            else:
                return "unknown"

        except Exception as e:
            return "unknown"

    async def calculate_session_open_analysis(
        self,
        symbol: str,
        exchange: str,
        session_start_hour: int = 9,
        session_start_minute: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze how the session opened relative to previous value areas

        This helps determine if the market is opening with continuation
        or reversal characteristics.
        """
        try:
            # Get previous day's volume profile
            prev_profile = await self.calculate_intraday_volume_profile(
                symbol, exchange, lookback_hours=24
            )

            if "error" in prev_profile:
                return {"error": "Could not get previous volume profile"}

            # Get session open price (simplified - would need proper session detection)
            # For now, return placeholder analysis
            return {
                "symbol": symbol,
                "exchange": exchange,
                "session_open_type": "gap_up_outside_prior_value",  # Placeholder
                "previous_value_area": {
                    "low": prev_profile["value_area_low"],
                    "high": prev_profile["value_area_high"]
                },
                "analysis": "Session opened above previous value area, suggesting bullish momentum"
            }

        except Exception as e:
            return {"error": f"Failed to analyze session open: {e}"}

    async def calculate_market_regime(
        self,
        symbol: str,
        exchange: str,
        lookback_periods: int = 20
    ) -> Dict[str, Any]:
        """
        Determine current market regime (trending vs ranging)

        Uses volatility and trend strength to classify market conditions.
        """
        try:
            # Get recent candles for analysis
            candles = await self.timescale_writer.get_recent_candles(
                symbol, exchange, "5m", limit=lookback_periods
            )

            if len(candles) < 10:
                return {"regime": "unknown", "confidence": 0.0}

            # Calculate returns
            prices = [candle["close"] for candle in candles]
            returns = np.diff(np.log(prices))

            # Calculate volatility (standard deviation of returns)
            volatility = np.std(returns) * np.sqrt(252)  # Annualized

            # Calculate trend strength (ADX-like measure)
            highs = np.array([candle["high"] for candle in candles])
            lows = np.array([candle["low"] for candle in candles])

            # Simplified trend strength calculation
            price_range = highs[-1] - lows[-1]
            total_range = np.max(highs) - np.min(lows)
            trend_strength = price_range / total_range if total_range > 0 else 0

            # Classify regime
            if volatility > 0.05 and trend_strength > 0.7:
                regime = "strong_trend"
                confidence = 0.8
            elif volatility > 0.03 and trend_strength > 0.5:
                regime = "moderate_trend"
                confidence = 0.6
            elif volatility < 0.02:
                regime = "ranging_low_vol"
                confidence = 0.7
            else:
                regime = "ranging_normal"
                confidence = 0.5

            return {
                "regime": regime,
                "confidence": confidence,
                "volatility": float(volatility),
                "trend_strength": float(trend_strength),
                "analysis": f"Market showing {regime.replace('_', ' ')} characteristics"
            }

        except Exception as e:
            return {"regime": "unknown", "confidence": 0.0, "error": str(e)}

    async def get_comprehensive_amt_features(
        self,
        symbol: str,
        exchange: str,
        current_price: float
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive AMT features for strategy decisions

        Returns all relevant AMT metrics in one call for efficiency.
        """
        try:
            # Calculate volume profile
            volume_profile = await self.calculate_intraday_volume_profile(symbol, exchange)

            # Calculate rotation factor
            rotation_factor = await self.calculate_rotation_factor(symbol, exchange)

            # Detect auction type
            auction_type = await self.detect_auction_type(symbol, exchange, current_price, volume_profile)

            # Get market regime
            market_regime = await self.calculate_market_regime(symbol, exchange)

            # Combine all features
            features = {
                "symbol": symbol,
                "exchange": exchange,
                "timestamp": datetime.utcnow(),

                # Volume profile features
                "value_area_low": volume_profile.get("value_area_low"),
                "value_area_high": volume_profile.get("value_area_high"),
                "point_of_control": volume_profile.get("point_of_control"),
                "position_in_value": volume_profile.get("position_in_value"),
                "total_volume_profile": volume_profile.get("total_volume"),

                # Auction analysis
                "rotation_factor": rotation_factor,
                "auction_type": auction_type,

                # Market regime
                "market_regime": market_regime.get("regime"),
                "regime_confidence": market_regime.get("confidence"),
                "volatility": market_regime.get("volatility"),
                "trend_strength": market_regime.get("trend_strength"),

                # Derived features for strategy
                "is_in_value_area": volume_profile.get("position_in_value") == "inside_value",
                "is_above_value": volume_profile.get("position_in_value") == "above_value",
                "is_below_value": volume_profile.get("position_in_value") == "below_value",
                "is_strong_buy_rotation": rotation_factor > 3.0,
                "is_strong_sell_rotation": rotation_factor < -3.0,
                "is_trending_market": market_regime.get("regime", "").endswith("_trend"),

                # Confidence scores
                "feature_completeness": self._calculate_feature_completeness(volume_profile, rotation_factor, market_regime)
            }

            # Cache the results
            cache_key = f"{symbol}_{exchange}_{datetime.utcnow().date()}"
            self.cache[cache_key] = features

            return features

        except Exception as e:
            return {"error": f"Failed to calculate AMT features: {e}"}

    def _calculate_volume_profile(self, prices: List[float], volumes: List[float], bins: int = 20) -> Dict[str, Any]:
        """Calculate volume profile from price and volume data"""
        if not prices or not volumes or len(prices) != len(volumes):
            return {}

        # Get price range
        min_price = min(prices)
        max_price = max(prices)

        if min_price == max_price:
            # All prices are the same
            return {
                "point_of_control": min_price,
                "value_area_low": min_price,
                "value_area_high": min_price,
                "total_volume": sum(volumes),
                "bins": [sum(volumes)],
                "bin_size": 0,
                "min_price": min_price,
                "max_price": max_price
            }

        # Create price bins
        bin_size = (max_price - min_price) / bins
        volume_bins = [0.0] * bins

        # Distribute volume across bins
        for price, volume in zip(prices, volumes):
            if min_price <= price <= max_price:
                bin_index = min(int((price - min_price) / bin_size), bins - 1)
                volume_bins[bin_index] += volume

        # Find Point of Control (POC) - highest volume bin
        max_volume = max(volume_bins)
        poc_bin = volume_bins.index(max_volume)
        point_of_control = min_price + (poc_bin * bin_size) + (bin_size / 2)

        # Calculate Value Area (68% of volume around POC)
        total_volume = sum(volume_bins)
        value_area_volume = total_volume * (config.trading.value_area_percent / 100)

        # Find value area bounds by expanding from POC
        accumulated_volume = volume_bins[poc_bin]
        value_area_start = poc_bin
        value_area_end = poc_bin

        while accumulated_volume < value_area_volume:
            expanded = False

            # Try to expand left
            if value_area_start > 0:
                value_area_start -= 1
                accumulated_volume += volume_bins[value_area_start]
                expanded = True

            # Try to expand right
            if accumulated_volume < value_area_volume and value_area_end < bins - 1:
                value_area_end += 1
                accumulated_volume += volume_bins[value_area_end]
                expanded = True

            # Break if we can't expand further
            if not expanded:
                break

        value_area_low = min_price + (value_area_start * bin_size)
        value_area_high = min_price + ((value_area_end + 1) * bin_size)

        return {
            "point_of_control": point_of_control,
            "value_area_low": value_area_low,
            "value_area_high": value_area_high,
            "total_volume": total_volume,
            "bins": volume_bins,
            "bin_size": bin_size,
            "min_price": min_price,
            "max_price": max_price,
            "value_area_percentage": config.trading.value_area_percent
        }

    def _determine_position_in_value(self, current_price: float, volume_profile: Dict[str, Any]) -> str:
        """Determine if price is inside, above, or below value area"""
        if not current_price or "value_area_low" not in volume_profile:
            return "unknown"

        value_low = volume_profile["value_area_low"]
        value_high = volume_profile["value_area_high"]

        if value_low <= current_price <= value_high:
            return "inside_value"
        elif current_price > value_high:
            return "above_value"
        elif current_price < value_low:
            return "below_value"
        else:
            return "unknown"

    def _calculate_feature_completeness(self, volume_profile: Dict, rotation_factor: float, market_regime: Dict) -> float:
        """Calculate how complete our feature set is"""
        completeness = 0.0
        total_checks = 3

        # Check volume profile completeness
        if volume_profile and "value_area_low" in volume_profile:
            completeness += 1.0

        # Check rotation factor validity
        if rotation_factor != 0.0:
            completeness += 1.0

        # Check market regime completeness
        if market_regime and market_regime.get("regime") != "unknown":
            completeness += 1.0

        return completeness / total_checks


# Global AMT calculator instance
amt_calculator = AMTMetricsCalculator()
