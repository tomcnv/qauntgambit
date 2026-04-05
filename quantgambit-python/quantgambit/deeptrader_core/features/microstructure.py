"""
Microstructure features calculator
Combines order book and trade flow analysis for high-frequency insights
"""
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from config.config import config


class MicrostructureFeaturesCalculator:
    """Calculates advanced microstructure features for trading decisions"""

    def __init__(self):
        self.trade_buffer = defaultdict(list)  # symbol -> recent trades
        self.orderbook_buffer = defaultdict(dict)  # symbol -> recent orderbooks
        self.max_buffer_size = 1000

    def calculate_comprehensive_microstructure(
        self,
        symbol: str,
        exchange: str,
        current_orderbook: Dict[str, Any],
        recent_trades: List[Dict[str, Any]],
        lookback_seconds: int = 60
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive microstructure features

        Args:
            symbol: Trading symbol
            exchange: Exchange name
            current_orderbook: Current order book snapshot
            recent_trades: Recent trades (last N trades)
            lookback_seconds: How far back to look for analysis

        Returns:
            Dictionary of microstructure features
        """
        try:
            # Update buffers
            self._update_buffers(symbol, current_orderbook, recent_trades)

            # Basic order book features
            orderbook_features = self._calculate_orderbook_features(current_orderbook)

            # Trade flow analysis
            trade_flow_features = self._calculate_trade_flow_features(symbol, lookback_seconds)

            # Market impact analysis
            impact_features = self._calculate_market_impact_features(symbol, current_orderbook)

            # Liquidity analysis
            liquidity_features = self._calculate_liquidity_features(symbol, current_orderbook)

            # Price discovery metrics
            discovery_features = self._calculate_price_discovery_features(symbol)

            # Volatility microstructure
            volatility_features = self._calculate_volatility_microstructure(symbol, lookback_seconds)

            # Combine all features
            features = {
                "symbol": symbol,
                "exchange": exchange,
                "timestamp": datetime.utcnow(),
                "lookback_seconds": lookback_seconds,

                # Order book features
                **orderbook_features,

                # Trade flow features
                **trade_flow_features,

                # Market impact
                **impact_features,

                # Liquidity
                **liquidity_features,

                # Price discovery
                **discovery_features,

                # Volatility
                **volatility_features,

                # Derived signals
                "high_aggressive_buying": trade_flow_features.get("buy_aggression_ratio", 0) > 0.7,
                "high_aggressive_selling": trade_flow_features.get("sell_aggression_ratio", 0) > 0.7,
                "liquidity_dry_up": liquidity_features.get("liquidity_dry_up_signal", False),
                "price_manipulation_risk": discovery_features.get("manipulation_probability", 0) > 0.8,
                "high_market_impact": impact_features.get("market_impact_1000_usd", 0) > 0.001,  # >0.1%

                # Overall market health
                "microstructure_health_score": self._calculate_health_score(
                    orderbook_features, trade_flow_features, liquidity_features
                )
            }

            return features

        except Exception as e:
            return {"error": f"Failed to calculate microstructure features: {e}"}

    def _update_buffers(self, symbol: str, orderbook: Dict, trades: List[Dict]):
        """Update internal buffers with new data"""
        # Update orderbook buffer
        self.orderbook_buffer[symbol] = {
            "data": orderbook,
            "timestamp": datetime.utcnow()
        }

        # Update trade buffer
        current_trades = self.trade_buffer[symbol]
        current_trades.extend(trades)

        # Keep only recent trades (last 24 hours worth)
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        self.trade_buffer[symbol] = [
            trade for trade in current_trades
            if trade.get("timestamp", datetime.min) > cutoff_time
        ][:self.max_buffer_size]

    def _calculate_orderbook_features(self, orderbook: Dict) -> Dict[str, Any]:
        """Calculate detailed order book features"""
        try:
            bids = np.array(orderbook.get("bids", []))
            asks = np.array(orderbook.get("asks", []))

            if len(bids) == 0 or len(asks) == 0:
                return {"error": "Insufficient order book data"}

            # Shape analysis
            bid_shape = self._analyze_book_shape(bids[:, 0], bids[:, 1])  # prices, volumes
            ask_shape = self._analyze_book_shape(asks[:, 0], asks[:, 1])

            # Concentration analysis
            bid_concentration = self._calculate_level_concentration(bids[:, 1])
            ask_concentration = self._calculate_level_concentration(asks[:, 1])

            # Resilience metrics
            bid_resilience = self._calculate_book_resilience(bids)
            ask_resilience = self._calculate_book_resilience(asks)

            return {
                "bid_shape_factor": bid_shape["shape_factor"],
                "ask_shape_factor": ask_shape["shape_factor"],
                "bid_concentration_hhi": bid_concentration,
                "ask_concentration_hhi": ask_concentration,
                "bid_resilience_score": bid_resilience,
                "ask_resilience_score": ask_resilience,
                "orderbook_imbalance_ratio": orderbook.get("imbalance", 0),
                "spread_efficiency": self._calculate_spread_efficiency(orderbook)
            }

        except Exception as e:
            return {"error": f"Order book analysis failed: {e}"}

    def _calculate_trade_flow_features(self, symbol: str, lookback_seconds: int) -> Dict[str, Any]:
        """Calculate trade flow and aggression features"""
        try:
            recent_trades = self.trade_buffer[symbol]
            cutoff_time = datetime.utcnow() - timedelta(seconds=lookback_seconds)

            # Filter trades by time
            relevant_trades = [
                trade for trade in recent_trades
                if trade.get("timestamp", datetime.min) > cutoff_time
            ]

            if len(relevant_trades) < 10:
                return {"insufficient_trade_data": True}

            # Classify trade aggression
            aggressive_buys = []
            aggressive_sells = []
            passive_trades = []

            for trade in relevant_trades:
                if trade.get("aggression_type") == "aggressive":
                    if trade["side"] == "buy":
                        aggressive_buys.append(trade)
                    elif trade["side"] == "sell":
                        aggressive_sells.append(trade)
                else:
                    passive_trades.append(trade)

            # Calculate aggression ratios
            total_trades = len(relevant_trades)
            buy_aggression_ratio = len(aggressive_buys) / total_trades if total_trades > 0 else 0
            sell_aggression_ratio = len(aggressive_sells) / total_trades if total_trades > 0 else 0

            # Volume analysis
            aggressive_buy_volume = sum(t["volume"] for t in aggressive_buys)
            aggressive_sell_volume = sum(t["volume"] for t in aggressive_sells)
            total_volume = sum(t["volume"] for t in relevant_trades)

            volume_imbalance = (aggressive_buy_volume - aggressive_sell_volume) / total_volume if total_volume > 0 else 0

            # Trade clustering analysis
            trade_timestamps = [t["timestamp"] for t in relevant_trades if "timestamp" in t]
            clustering_score = self._calculate_trade_clustering(trade_timestamps)

            return {
                "total_trades": total_trades,
                "aggressive_buy_count": len(aggressive_buys),
                "aggressive_sell_count": len(aggressive_sells),
                "buy_aggression_ratio": buy_aggression_ratio,
                "sell_aggression_ratio": sell_aggression_ratio,
                "aggressive_buy_volume": aggressive_buy_volume,
                "aggressive_sell_volume": aggressive_sell_volume,
                "volume_imbalance": volume_imbalance,
                "trade_clustering_score": clustering_score,
                "average_trade_size": total_volume / total_trades if total_trades > 0 else 0
            }

        except Exception as e:
            return {"error": f"Trade flow analysis failed: {e}"}

    def _calculate_market_impact_features(self, symbol: str, orderbook: Dict) -> Dict[str, Any]:
        """Calculate market impact estimates"""
        try:
            bids = np.array(orderbook.get("bids", []))
            asks = np.array(orderbook.get("asks", []))

            if len(bids) == 0 or len(asks) == 0:
                return {"error": "Insufficient order book data"}

            # Estimate impact for various trade sizes
            impact_100 = self._estimate_price_impact(bids, asks, 100)
            impact_1000 = self._estimate_price_impact(bids, asks, 1000)
            impact_10000 = self._estimate_price_impact(bids, asks, 10000)

            # Kyle's lambda (price impact coefficient)
            kyles_lambda = self._calculate_kyles_lambda(symbol)

            return {
                "market_impact_100_usd": impact_100,
                "market_impact_1000_usd": impact_1000,
                "market_impact_10000_usd": impact_10000,
                "kyles_lambda": kyles_lambda,
                "price_impact_elasticity": self._calculate_impact_elasticity(impact_100, impact_1000, impact_10000)
            }

        except Exception as e:
            return {"error": f"Market impact calculation failed: {e}"}

    def _calculate_liquidity_features(self, symbol: str, orderbook: Dict) -> Dict[str, Any]:
        """Calculate liquidity-related features"""
        try:
            bids = np.array(orderbook.get("bids", []))
            asks = np.array(orderbook.get("asks", []))

            # Quoted spread
            best_bid = bids[0, 0] if len(bids) > 0 else 0
            best_ask = asks[0, 0] if len(asks) > 0 else 0
            quoted_spread = best_ask - best_bid if best_ask > best_bid else 0
            quoted_spread_bps = (quoted_spread / best_bid) * 10000 if best_bid > 0 else 0

            # Effective spread (using recent trades)
            effective_spread = self._calculate_effective_spread(symbol)

            # Depth at different levels
            depth_1pct = self._calculate_depth_at_percentage(bids, asks, 0.01)  # 1% from mid
            depth_5pct = self._calculate_depth_at_percentage(bids, asks, 0.05)  # 5% from mid

            # Liquidity ratio
            bid_depth = sum(bids[:10, 1]) if len(bids) >= 10 else sum(bids[:, 1])
            ask_depth = sum(asks[:10, 1]) if len(asks) >= 10 else sum(asks[:, 1])
            liquidity_ratio = bid_depth / ask_depth if ask_depth > 0 else float('inf')

            return {
                "quoted_spread_bps": quoted_spread_bps,
                "effective_spread_bps": effective_spread,
                "depth_1pct": depth_1pct,
                "depth_5pct": depth_5pct,
                "liquidity_ratio": liquidity_ratio,
                "liquidity_dry_up_signal": self._detect_liquidity_dry_up(orderbook)
            }

        except Exception as e:
            return {"error": f"Liquidity analysis failed: {e}"}

    def _calculate_price_discovery_features(self, symbol: str) -> Dict[str, Any]:
        """Calculate price discovery and manipulation detection features"""
        try:
            recent_trades = self.trade_buffer[symbol][-100:]  # Last 100 trades

            if len(recent_trades) < 20:
                return {"insufficient_data": True}

            # Price momentum analysis
            prices = [t["price"] for t in recent_trades]
            price_momentum = self._calculate_price_momentum(prices)

            # Trade size distribution analysis
            volumes = [t["volume"] for t in recent_trades]
            size_distribution = self._analyze_trade_size_distribution(volumes)

            # Spoofing detection
            spoofing_probability = self._detect_spoofing_patterns(recent_trades)

            # Layering detection
            layering_probability = self._detect_layering_patterns(recent_trades)

            return {
                "price_momentum_20_trades": price_momentum,
                "large_trade_ratio": size_distribution["large_trade_ratio"],
                "trade_size_entropy": size_distribution["entropy"],
                "spoofing_probability": spoofing_probability,
                "layering_probability": layering_probability,
                "manipulation_probability": max(spoofing_probability, layering_probability)
            }

        except Exception as e:
            return {"error": f"Price discovery analysis failed: {e}"}

    def _calculate_volatility_microstructure(self, symbol: str, lookback_seconds: int) -> Dict[str, Any]:
        """Calculate microstructure-based volatility measures"""
        try:
            recent_trades = self.trade_buffer[symbol]
            cutoff_time = datetime.utcnow() - timedelta(seconds=lookback_seconds)

            relevant_trades = [
                trade for trade in recent_trades
                if trade.get("timestamp", datetime.min) > cutoff_time
            ]

            if len(relevant_trades) < 10:
                return {"insufficient_data": True}

            # Realized volatility from trades
            prices = [t["price"] for t in relevant_trades]
            returns = np.diff(np.log(prices))
            realized_volatility = np.std(returns) * np.sqrt(252)  # Annualized

            # Bid-ask bounce volatility
            bab_volatility = self._calculate_bab_volatility(symbol)

            # Trade-induced volatility
            trade_volatility = self._calculate_trade_volatility(relevant_trades)

            return {
                "realized_volatility": float(realized_volatility),
                "bid_ask_bounce_volatility": bab_volatility,
                "trade_induced_volatility": trade_volatility,
                "microstructure_volatility_ratio": bab_volatility / realized_volatility if realized_volatility > 0 else 0
            }

        except Exception as e:
            return {"error": f"Volatility analysis failed: {e}"}

    def _analyze_book_shape(self, prices: np.ndarray, volumes: np.ndarray) -> Dict[str, float]:
        """Analyze the shape of the order book"""
        try:
            if len(prices) < 5 or len(volumes) < 5:
                return {"shape_factor": 0.0}

            # Calculate price elasticity (slope)
            price_changes = np.diff(prices)
            volume_changes = np.diff(volumes)
            elasticity = np.corrcoef(price_changes, volume_changes)[0, 1] if len(price_changes) > 1 else 0

            # Shape factor: how evenly distributed volume is
            volume_std = np.std(volumes)
            volume_mean = np.mean(volumes)
            shape_factor = 1 - (volume_std / volume_mean) if volume_mean > 0 else 0

            return {
                "shape_factor": float(shape_factor),
                "elasticity": float(elasticity)
            }

        except:
            return {"shape_factor": 0.0}

    def _calculate_level_concentration(self, volumes: np.ndarray) -> float:
        """Calculate Herfindahl-Hirschman Index for volume concentration"""
        try:
            if len(volumes) == 0:
                return 0.0

            total_volume = np.sum(volumes)
            if total_volume == 0:
                return 0.0

            proportions = volumes / total_volume
            hhi = np.sum(proportions ** 2)

            return float(hhi)

        except:
            return 0.0

    def _calculate_book_resilience(self, book_side: np.ndarray) -> float:
        """Calculate how resilient the order book is to large orders"""
        try:
            if len(book_side) < 5:
                return 0.0

            # Resilience = average volume / cumulative volume ratio
            cumulative_volume = np.cumsum(book_side[:, 1])
            average_volume = np.mean(book_side[:, 1])

            # Higher ratio means more evenly distributed volume (more resilient)
            resilience = average_volume / cumulative_volume[-1] if cumulative_volume[-1] > 0 else 0

            return float(resilience)

        except:
            return 0.0

    def _calculate_spread_efficiency(self, orderbook: Dict) -> float:
        """Calculate how efficiently the spread represents true liquidity"""
        try:
            spread = orderbook.get("spread", 0)
            mid_price = orderbook.get("mid_price", 0)

            if spread <= 0 or mid_price <= 0:
                return 0.0

            # Efficiency = 1 / (spread percentage)
            spread_pct = spread / mid_price
            efficiency = 1 / spread_pct if spread_pct > 0 else 0

            # Cap at reasonable maximum
            return min(efficiency, 1000.0)

        except:
            return 0.0

    def _estimate_price_impact(self, bids: np.ndarray, asks: np.ndarray, trade_size: float) -> float:
        """Estimate price impact of a market order"""
        try:
            remaining_size = trade_size
            total_cost = 0
            total_executed = 0

            # Simulate market buy order
            for price, volume in asks:
                if remaining_size <= 0:
                    break

                fill_size = min(remaining_size, volume)
                total_cost += fill_size * price
                total_executed += fill_size
                remaining_size -= fill_size

            if total_executed > 0:
                avg_fill_price = total_cost / total_executed
                mid_price = (bids[0, 0] + asks[0, 0]) / 2 if len(bids) > 0 and len(asks) > 0 else asks[0, 0]
                impact = (avg_fill_price - mid_price) / mid_price
                return float(impact)

            return 0.0

        except:
            return 0.0

    def _calculate_kyles_lambda(self, symbol: str) -> float:
        """Calculate Kyle's lambda (price impact coefficient)"""
        try:
            # Simplified calculation using recent trade and order book data
            recent_trades = self.trade_buffer[symbol][-50:]
            current_ob = self.orderbook_buffer[symbol]

            if len(recent_trades) < 10 or not current_ob:
                return 0.0

            # Estimate from order book depth and trade volumes
            # This is a simplified version - full implementation would use regression
            avg_trade_size = np.mean([t["volume"] for t in recent_trades])

            # Estimate lambda from spread and depth
            ob_data = current_ob["data"]
            spread = ob_data.get("spread", 0)
            depth = ob_data.get("depth_5", {}).get("total_depth", 0)

            if spread > 0 and depth > 0 and avg_trade_size > 0:
                lambda_est = (spread / 2) / (avg_trade_size / depth)
                return float(lambda_est)

            return 0.0

        except:
            return 0.0

    def _calculate_impact_elasticity(self, impact_100: float, impact_1000: float, impact_10000: float) -> float:
        """Calculate how price impact scales with trade size"""
        try:
            if impact_100 <= 0 or impact_1000 <= 0 or impact_10000 <= 0:
                return 0.0

            # Elasticity = % change in impact / % change in size
            size_ratio_1 = impact_1000 / impact_100  # 10x size
            size_ratio_2 = impact_10000 / impact_1000  # 10x size again

            # Average elasticity
            elasticity = (size_ratio_1 + size_ratio_2) / 2

            return float(elasticity)

        except:
            return 0.0

    def _calculate_effective_spread(self, symbol: str) -> float:
        """Calculate effective spread using recent trades"""
        try:
            recent_trades = self.trade_buffer[symbol][-20:]  # Last 20 trades

            if len(recent_trades) < 5:
                return 0.0

            # Effective spread = 2 * |price - mid_price|
            # Simplified: use average absolute deviation from midpoint
            prices = [t["price"] for t in recent_trades]
            midpoint = (min(prices) + max(prices)) / 2

            deviations = [abs(price - midpoint) for price in prices]
            effective_spread = 2 * np.mean(deviations)

            return float(effective_spread)

        except:
            return 0.0

    def _calculate_depth_at_percentage(self, bids: np.ndarray, asks: np.ndarray, percentage: float) -> Dict[str, float]:
        """Calculate available depth within X% of mid price"""
        try:
            if len(bids) == 0 or len(asks) == 0:
                return {"bid_depth": 0, "ask_depth": 0, "total_depth": 0}

            mid_price = (bids[0, 0] + asks[0, 0]) / 2
            price_range = mid_price * percentage

            # Find levels within range
            bid_depth = 0
            ask_depth = 0

            for price, volume in bids:
                if price >= mid_price - price_range:
                    bid_depth += volume
                else:
                    break

            for price, volume in asks:
                if price <= mid_price + price_range:
                    ask_depth += volume
                else:
                    break

            return {
                "bid_depth": float(bid_depth),
                "ask_depth": float(ask_depth),
                "total_depth": float(bid_depth + ask_depth)
            }

        except:
            return {"bid_depth": 0, "ask_depth": 0, "total_depth": 0}

    def _detect_liquidity_dry_up(self, orderbook: Dict) -> bool:
        """Detect if liquidity is drying up"""
        try:
            spread = orderbook.get("spread", 0)
            mid_price = orderbook.get("mid_price", 0)

            if spread <= 0 or mid_price <= 0:
                return True

            spread_pct = spread / mid_price

            # Liquidity dry-up indicators
            wide_spread = spread_pct > 0.001  # >0.1%
            low_depth = orderbook.get("depth_5", {}).get("total_depth", 0) < 1000

            return wide_spread and low_depth

        except:
            return False

    def _calculate_price_momentum(self, prices: List[float]) -> float:
        """Calculate short-term price momentum"""
        try:
            if len(prices) < 5:
                return 0.0

            # Simple momentum as rate of change
            recent_change = (prices[-1] - prices[0]) / prices[0] if prices[0] != 0 else 0
            return float(recent_change)

        except:
            return 0.0

    def _analyze_trade_size_distribution(self, volumes: List[float]) -> Dict[str, float]:
        """Analyze distribution of trade sizes"""
        try:
            if len(volumes) < 10:
                return {"large_trade_ratio": 0.0, "entropy": 0.0}

            # Calculate statistics
            median_volume = np.median(volumes)
            large_trades = [v for v in volumes if v > median_volume * 3]
            large_trade_ratio = len(large_trades) / len(volumes)

            # Entropy of size distribution (simplified)
            # Bin the volumes and calculate entropy
            bins = np.histogram(volumes, bins=10)[0]
            bins = bins[bins > 0]  # Remove zero bins
            proportions = bins / np.sum(bins)
            entropy = -np.sum(proportions * np.log(proportions))

            return {
                "large_trade_ratio": float(large_trade_ratio),
                "entropy": float(entropy)
            }

        except:
            return {"large_trade_ratio": 0.0, "entropy": 0.0}

    def _detect_spoofing_patterns(self, trades: List[Dict]) -> float:
        """Detect potential spoofing patterns"""
        try:
            if len(trades) < 20:
                return 0.0

            # Look for rapid order cancellations followed by price moves
            # This is a simplified detection - real implementation would be more sophisticated

            # For now, return a random low probability
            # In practice, this would analyze order book patterns and trade sequences
            return 0.05  # 5% probability

        except:
            return 0.0

    def _detect_layering_patterns(self, trades: List[Dict]) -> float:
        """Detect potential layering patterns"""
        try:
            # Similar to spoofing detection but for layering
            return 0.03  # 3% probability

        except:
            return 0.0

    def _calculate_trade_clustering(self, timestamps: List[datetime]) -> float:
        """Calculate how clustered trades are in time"""
        try:
            if len(timestamps) < 5:
                return 0.0

            # Convert to seconds since first trade
            base_time = timestamps[0]
            time_diffs = [(t - base_time).total_seconds() for t in timestamps]

            # Calculate coefficient of variation of time differences
            mean_diff = np.mean(time_diffs)
            std_diff = np.std(time_diffs)

            cv = std_diff / mean_diff if mean_diff > 0 else 0

            # Higher CV means more clustered (bursty) trading
            return float(cv)

        except:
            return 0.0

    def _calculate_bab_volatility(self, symbol: str) -> float:
        """Calculate bid-ask bounce volatility"""
        try:
            # This would analyze price movements within the spread
            # Simplified placeholder
            return 0.001  # 0.1%

        except:
            return 0.0

    def _calculate_trade_volatility(self, trades: List[Dict]) -> float:
        """Calculate volatility induced by trade flow"""
        try:
            if len(trades) < 5:
                return 0.0

            prices = [t["price"] for t in trades]
            returns = np.diff(np.log(prices))

            return float(np.std(returns))

        except:
            return 0.0

    def _calculate_health_score(self, orderbook_features: Dict, trade_flow_features: Dict, liquidity_features: Dict) -> float:
        """Calculate overall microstructure health score"""
        try:
            scores = []

            # Order book health (0-1)
            if "bid_resilience_score" in orderbook_features:
                scores.append(orderbook_features["bid_resilience_score"])
            if "ask_resilience_score" in orderbook_features:
                scores.append(orderbook_features["ask_resilience_score"])

            # Trade flow health
            if "buy_aggression_ratio" in trade_flow_features:
                # Balanced aggression is healthier
                balance = 1 - abs(trade_flow_features["buy_aggression_ratio"] - 0.5) * 2
                scores.append(balance)

            # Liquidity health
            if "liquidity_ratio" in liquidity_features:
                ratio = liquidity_features["liquidity_ratio"]
                # Ratio close to 1.0 is healthy
                health = 1 - abs(ratio - 1.0) / max(ratio, 1.0)
                scores.append(min(health, 1.0))

            return float(np.mean(scores)) if scores else 0.0

        except:
            return 0.0


# Global microstructure calculator
microstructure_calculator = MicrostructureFeaturesCalculator()
