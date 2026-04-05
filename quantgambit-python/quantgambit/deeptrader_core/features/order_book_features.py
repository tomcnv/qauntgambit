"""
Order book microstructure features calculator
Analyzes bid-ask spread, depth, imbalance, and liquidity metrics
"""
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from collections import deque

from config.config import config


class OrderBookFeaturesCalculator:
    """Calculates microstructure features from order book data"""

    def __init__(self, max_history: int = 100):
        self.price_history = deque(maxlen=max_history)
        self.spread_history = deque(maxlen=max_history)
        self.imbalance_history = deque(maxlen=max_history)

    def calculate_microstructure_features(
        self,
        orderbook: Dict[str, Any],
        recent_trades: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive order book microstructure features

        Args:
            orderbook: Normalized order book data
            recent_trades: Recent trades for additional context

        Returns:
            Dictionary of microstructure features
        """
        try:
            bids = np.array(orderbook["bids"])
            asks = np.array(orderbook["asks"])

            if len(bids) == 0 or len(asks) == 0:
                return {"error": "Insufficient order book data"}

            # Basic spread metrics
            best_bid = bids[0, 0] if len(bids) > 0 else None
            best_ask = asks[0, 0] if len(asks) > 0 else None

            if best_bid is None or best_ask is None:
                return {"error": "Invalid bid/ask prices"}

            spread = best_ask - best_bid
            spread_bps = (spread / best_bid) * 10000  # Basis points
            mid_price = (best_bid + best_ask) / 2

            # Order book depth analysis
            depth_5 = self._calculate_depth(bids, asks, levels=5)
            depth_10 = self._calculate_depth(bids, asks, levels=10)
            depth_20 = self._calculate_depth(bids, asks, levels=20)

            # Bid-ask imbalance
            bid_volume_5 = sum(bids[:5, 1]) if len(bids) >= 5 else sum(bids[:, 1])
            ask_volume_5 = sum(asks[:5, 1]) if len(asks) >= 5 else sum(asks[:, 1])

            total_volume_5 = bid_volume_5 + ask_volume_5
            imbalance = (bid_volume_5 - ask_volume_5) / total_volume_5 if total_volume_5 > 0 else 0

            # Slope analysis (price elasticity)
            bid_slope = self._calculate_slope(bids[:10, 0]) if len(bids) >= 10 else 0
            ask_slope = self._calculate_slope(asks[:10, 0]) if len(asks) >= 10 else 0

            # Concentration analysis
            bid_concentration = self._calculate_concentration(bids[:10, 1]) if len(bids) >= 10 else 0
            ask_concentration = self._calculate_concentration(asks[:10, 1]) if len(asks) >= 10 else 0

            # Market impact estimation
            market_impact_1000 = self._estimate_market_impact(bids, asks, 1000)
            market_impact_10000 = self._estimate_market_impact(bids, asks, 10000)

            # Trade flow analysis (if trades provided)
            trade_flow_features = {}
            if recent_trades:
                trade_flow_features = self._analyze_trade_flow(recent_trades, mid_price)

            # Update historical data
            self.price_history.append(mid_price)
            self.spread_history.append(spread)
            self.imbalance_history.append(imbalance)

            # Calculate momentum indicators
            spread_momentum = self._calculate_momentum(self.spread_history)
            imbalance_momentum = self._calculate_momentum(self.imbalance_history)
            price_momentum = self._calculate_momentum(self.price_history)

            # Liquidity classification
            liquidity_score = self._calculate_liquidity_score(
                spread_bps, depth_10, imbalance, len(bids), len(asks)
            )

            features = {
                "symbol": orderbook["symbol"],
                "exchange": orderbook["exchange"],
                "timestamp": orderbook["timestamp"],

                # Basic spread metrics
                "spread": spread,
                "spread_bps": spread_bps,
                "mid_price": mid_price,

                # Depth metrics
                "depth_5": depth_5,
                "depth_10": depth_10,
                "depth_20": depth_20,

                # Imbalance metrics
                "bid_ask_imbalance": imbalance,
                "bid_volume_5": bid_volume_5,
                "ask_volume_5": ask_volume_5,

                # Slope and elasticity
                "bid_slope": bid_slope,
                "ask_slope": ask_slope,

                # Concentration
                "bid_concentration": bid_concentration,
                "ask_concentration": ask_concentration,

                # Market impact
                "market_impact_1000": market_impact_1000,
                "market_impact_10000": market_impact_10000,

                # Momentum indicators
                "spread_momentum": spread_momentum,
                "imbalance_momentum": imbalance_momentum,
                "price_momentum": price_momentum,

                # Liquidity assessment
                "liquidity_score": liquidity_score,
                "liquidity_classification": self._classify_liquidity(liquidity_score),

                # Trade flow features
                **trade_flow_features,

                # Derived signals
                "strong_bid_imbalance": imbalance > 0.6,
                "strong_ask_imbalance": imbalance < -0.6,
                "tight_spread": spread_bps < 5,  # Less than 5 bps
                "high_liquidity": liquidity_score > 0.7,

                # Data quality
                "bid_levels": len(bids),
                "ask_levels": len(asks),
                "data_completeness": min(len(bids), len(asks)) / 20  # 20 levels ideal
            }

            return features

        except Exception as e:
            return {"error": f"Failed to calculate microstructure features: {e}"}

    def _calculate_depth(self, bids: np.ndarray, asks: np.ndarray, levels: int) -> Dict[str, float]:
        """Calculate order book depth metrics"""
        try:
            bid_depth = sum(bids[:levels, 1]) if len(bids) >= levels else sum(bids[:, 1])
            ask_depth = sum(asks[:levels, 1]) if len(asks) >= levels else sum(asks[:, 1])

            return {
                "bid_depth": bid_depth,
                "ask_depth": ask_depth,
                "total_depth": bid_depth + ask_depth,
                "depth_imbalance": (bid_depth - ask_depth) / (bid_depth + ask_depth) if (bid_depth + ask_depth) > 0 else 0
            }
        except:
            return {"bid_depth": 0, "ask_depth": 0, "total_depth": 0, "depth_imbalance": 0}

    def _calculate_slope(self, prices: np.ndarray) -> float:
        """Calculate slope of price levels (price elasticity)"""
        if len(prices) < 2:
            return 0

        try:
            # Simple linear regression slope
            x = np.arange(len(prices))
            slope, _ = np.polyfit(x, prices, 1)
            return float(slope)
        except:
            return 0

    def _calculate_concentration(self, volumes: np.ndarray) -> float:
        """Calculate volume concentration (Herfindahl-Hirschman Index)"""
        if len(volumes) == 0:
            return 0

        try:
            total_volume = np.sum(volumes)
            if total_volume == 0:
                return 0

            # Normalize volumes to proportions
            proportions = volumes / total_volume

            # Calculate HHI
            hhi = np.sum(proportions ** 2)

            # Normalize to 0-1 scale (0 = perfectly distributed, 1 = single level has all volume)
            return float(hhi)
        except:
            return 0

    def _estimate_market_impact(self, bids: np.ndarray, asks: np.ndarray, trade_size: float) -> float:
        """Estimate price impact of a market order"""
        try:
            # Simulate walking the book
            remaining_size = trade_size
            total_cost = 0
            weighted_price = 0

            # Buy order simulation (walk asks)
            for price, volume in asks:
                if remaining_size <= 0:
                    break

                fill_size = min(remaining_size, volume)
                total_cost += fill_size * price
                remaining_size -= fill_size

            if total_cost > 0 and trade_size > remaining_size:
                avg_fill_price = total_cost / (trade_size - remaining_size)
                impact = (avg_fill_price - bids[0, 0]) / bids[0, 0] if len(bids) > 0 else 0
                return float(impact)
            else:
                return 0
        except:
            return 0

    def _analyze_trade_flow(self, trades: List[Dict[str, Any]], mid_price: float) -> Dict[str, Any]:
        """Analyze recent trade flow for microstructure insights"""
        if not trades:
            return {}

        try:
            # Classify trades as aggressive buys/sells
            aggressive_buys = []
            aggressive_sells = []

            for trade in trades[-50:]:  # Last 50 trades
                if trade["side"] == "buy":
                    aggressive_buys.append(trade)
                elif trade["side"] == "sell":
                    aggressive_sells.append(trade)

            # Calculate trade flow imbalance
            buy_volume = sum(t["volume"] for t in aggressive_buys)
            sell_volume = sum(t["volume"] for t in aggressive_sells)
            total_volume = buy_volume + sell_volume

            flow_imbalance = (buy_volume - sell_volume) / total_volume if total_volume > 0 else 0

            # Detect large trades (whale activity)
            avg_volume = total_volume / len(trades) if trades else 0
            large_trades = [t for t in trades if t["volume"] > avg_volume * 3]

            return {
                "trade_flow_imbalance": flow_imbalance,
                "aggressive_buy_volume": buy_volume,
                "aggressive_sell_volume": sell_volume,
                "large_trade_count": len(large_trades),
                "large_trade_ratio": len(large_trades) / len(trades) if trades else 0
            }
        except:
            return {}

    def _calculate_momentum(self, data: deque) -> float:
        """Calculate momentum from recent data"""
        if len(data) < 5:
            return 0

        try:
            # Simple momentum as recent change rate
            recent = list(data)[-5:]
            if len(recent) < 2:
                return 0

            # Linear trend
            x = np.arange(len(recent))
            slope, _ = np.polyfit(x, recent, 1)

            # Normalize by recent average
            avg_value = np.mean(recent)
            return float(slope / avg_value) if avg_value != 0 else 0
        except:
            return 0

    def _calculate_liquidity_score(self, spread_bps: float, depth: Dict, imbalance: float,
                                 bid_levels: int, ask_levels: int) -> float:
        """Calculate overall liquidity score (0-1)"""
        try:
            # Spread component (lower spread = higher score)
            spread_score = max(0, 1 - (spread_bps / 50))  # 50 bps = very wide

            # Depth component
            total_depth = depth.get("total_depth", 0)
            depth_score = min(1, total_depth / 10000)  # 10k units = good depth

            # Imbalance component (balanced = higher score)
            imbalance_score = 1 - abs(imbalance)

            # Level count component
            level_score = min(1, (bid_levels + ask_levels) / 40)  # 20 levels each ideal

            # Weighted average
            weights = [0.4, 0.3, 0.2, 0.1]  # Spread most important
            scores = [spread_score, depth_score, imbalance_score, level_score]

            return float(np.average(scores, weights=weights))
        except:
            return 0

    def _classify_liquidity(self, score: float) -> str:
        """Classify liquidity based on score"""
        if score >= 0.8:
            return "excellent"
        elif score >= 0.6:
            return "good"
        elif score >= 0.4:
            return "moderate"
        elif score >= 0.2:
            return "poor"
        else:
            return "very_poor"

    def get_feature_history(self) -> Dict[str, List]:
        """Get historical feature data for analysis"""
        return {
            "price_history": list(self.price_history),
            "spread_history": list(self.spread_history),
            "imbalance_history": list(self.imbalance_history)
        }

    def reset_history(self):
        """Reset historical data"""
        self.price_history.clear()
        self.spread_history.clear()
        self.imbalance_history.clear()


# Global order book features calculator
order_book_calculator = OrderBookFeaturesCalculator()
