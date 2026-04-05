"""
Technical indicators calculator
Implements common technical analysis indicators for trading signals
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from collections import deque
import talib  # Technical Analysis Library


class TechnicalIndicatorsCalculator:
    """Calculates technical analysis indicators from price data"""

    def __init__(self, max_history: int = 1000):
        self.price_history = deque(maxlen=max_history)
        self.volume_history = deque(maxlen=max_history)

    def calculate_all_indicators(
        self,
        candles: List[Dict[str, Any]],
        include_volume: bool = True
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive set of technical indicators

        Args:
            candles: List of OHLCV candle data
            include_volume: Whether to include volume-based indicators

        Returns:
            Dictionary of all calculated indicators
        """
        try:
            if len(candles) < 20:  # Minimum for most indicators
                return {"error": "Insufficient candle data for technical analysis"}

            # Extract price data
            opens = np.array([c["open"] for c in candles])
            highs = np.array([c["high"] for c in candles])
            lows = np.array([c["low"] for c in candles])
            closes = np.array([c["close"] for c in candles])
            volumes = np.array([c.get("volume", 0) for c in candles]) if include_volume else None

            # Moving averages
            sma_20 = self._calculate_sma(closes, 20)
            sma_50 = self._calculate_sma(closes, 50)
            ema_9 = self._calculate_ema(closes, 9)
            ema_21 = self._calculate_ema(closes, 21)
            ema_50 = self._calculate_ema(closes, 50)

            # MACD
            macd_result = self._calculate_macd(closes)

            # RSI
            rsi = self._calculate_rsi(closes, 14)

            # Bollinger Bands
            bb_result = self._calculate_bollinger_bands(closes, 20, 2)

            # Stochastic Oscillator
            stoch_result = self._calculate_stochastic(highs, lows, closes, 14, 3)

            # Williams %R
            williams_r = self._calculate_williams_r(highs, lows, closes, 14)

            # Commodity Channel Index (CCI)
            cci = self._calculate_cci(highs, lows, closes, 20)

            # Average True Range (ATR)
            atr = self._calculate_atr(highs, lows, closes, 14)

            # Volume indicators (if volume available)
            volume_indicators = {}
            if volumes is not None and include_volume:
                volume_indicators = self._calculate_volume_indicators(volumes, closes)

            # Support and resistance levels
            support_resistance = self._calculate_support_resistance(highs, lows, closes)

            # Trend analysis
            trend_analysis = self._analyze_trend(closes, sma_20, sma_50)

            # Momentum indicators
            momentum_indicators = self._calculate_momentum_indicators(closes)

            # Current values (most recent)
            current_indicators = {
                "rsi": float(rsi[-1]) if len(rsi) > 0 else None,
                "ema_9": float(ema_9[-1]) if len(ema_9) > 0 else None,
                "ema_21": float(ema_21[-1]) if len(ema_21) > 0 else None,
                "ema_50": float(ema_50[-1]) if len(ema_50) > 0 else None,
                "sma_20": float(sma_20[-1]) if len(sma_20) > 0 else None,
                "sma_50": float(sma_50[-1]) if len(sma_50) > 0 else None,

                "macd_line": float(macd_result["macd"][-1]) if len(macd_result["macd"]) > 0 else None,
                "macd_signal": float(macd_result["signal"][-1]) if len(macd_result["signal"]) > 0 else None,
                "macd_histogram": float(macd_result["histogram"][-1]) if len(macd_result["histogram"]) > 0 else None,

                "bollinger_upper": float(bb_result["upper"][-1]) if len(bb_result["upper"]) > 0 else None,
                "bollinger_middle": float(bb_result["middle"][-1]) if len(bb_result["middle"]) > 0 else None,
                "bollinger_lower": float(bb_result["lower"][-1]) if len(bb_result["lower"]) > 0 else None,
                "bollinger_width": float(bb_result["width"][-1]) if len(bb_result["width"]) > 0 else None,

                "stochastic_k": float(stoch_result["k"][-1]) if len(stoch_result["k"]) > 0 else None,
                "stochastic_d": float(stoch_result["d"][-1]) if len(stoch_result["d"]) > 0 else None,

                "williams_r": float(williams_r[-1]) if len(williams_r) > 0 else None,
                "cci": float(cci[-1]) if len(cci) > 0 else None,
                "atr": float(atr[-1]) if len(atr) > 0 else None,
            }

            # Update internal history
            self.price_history.append(closes[-1])
            if volumes is not None:
                self.volume_history.append(volumes[-1])

            result = {
                "symbol": candles[-1]["symbol"],
                "exchange": candles[-1]["exchange"],
                "timeframe": candles[-1]["timeframe"],
                "timestamp": candles[-1]["timestamp"],
                "data_points": len(candles),

                # Current indicator values
                **current_indicators,

                # Volume indicators
                **volume_indicators,

                # Support/resistance
                **support_resistance,

                # Trend analysis
                **trend_analysis,

                # Momentum
                **momentum_indicators,

                # Derived signals
                "rsi_oversold": current_indicators["rsi"] is not None and current_indicators["rsi"] < 30,
                "rsi_overbought": current_indicators["rsi"] is not None and current_indicators["rsi"] > 70,
                "ema_bullish": (current_indicators["ema_9"] and current_indicators["ema_21"] and
                               current_indicators["ema_9"] > current_indicators["ema_21"]),
                "macd_bullish": (current_indicators["macd_histogram"] is not None and
                                current_indicators["macd_histogram"] > 0),
                "bollinger_squeeze": current_indicators["bollinger_width"] is not None and current_indicators["bollinger_width"] < 0.01,
                "stochastic_oversold": current_indicators["stochastic_k"] is not None and current_indicators["stochastic_k"] < 20,

                # Data quality
                "indicator_completeness": self._calculate_completeness(current_indicators)
            }

            return result

        except Exception as e:
            return {"error": f"Failed to calculate technical indicators: {e}"}

    def _calculate_sma(self, prices: np.ndarray, period: int) -> np.ndarray:
        """Simple Moving Average"""
        if len(prices) < period:
            return np.array([])
        return pd.Series(prices).rolling(window=period).mean().values[period-1:]

    def _calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """Exponential Moving Average"""
        if len(prices) < period:
            return np.array([])
        return pd.Series(prices).ewm(span=period).mean().values[period-1:]

    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> np.ndarray:
        """Relative Strength Index"""
        if len(prices) < period + 1:
            return np.array([])

        try:
            return talib.RSI(prices, timeperiod=period)
        except:
            # Fallback implementation
            return self._calculate_rsi_manual(prices, period)

    def _calculate_rsi_manual(self, prices: np.ndarray, period: int) -> np.ndarray:
        """Manual RSI calculation"""
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gains = pd.Series(gains).rolling(window=period).mean()
        avg_losses = pd.Series(losses).rolling(window=period).mean()

        rs = avg_gains / avg_losses
        rsi = 100 - (100 / (1 + rs))

        return rsi.values[period:]

    def _calculate_macd(self, prices: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, np.ndarray]:
        """MACD (Moving Average Convergence Divergence)"""
        if len(prices) < slow + signal:
            return {"macd": np.array([]), "signal": np.array([]), "histogram": np.array([])}

        try:
            macd, macd_signal, macd_histogram = talib.MACD(prices, fastperiod=fast, slowperiod=slow, signalperiod=signal)
            return {
                "macd": macd,
                "signal": macd_signal,
                "histogram": macd_histogram
            }
        except:
            # Fallback implementation
            ema_fast = self._calculate_ema(prices, fast)
            ema_slow = self._calculate_ema(prices, slow)
            macd_line = ema_fast - ema_slow
            signal_line = self._calculate_ema(macd_line, signal)
            histogram = macd_line - signal_line

            return {
                "macd": macd_line,
                "signal": signal_line,
                "histogram": histogram
            }

    def _calculate_bollinger_bands(self, prices: np.ndarray, period: int = 20, std_dev: float = 2) -> Dict[str, np.ndarray]:
        """Bollinger Bands"""
        if len(prices) < period:
            return {"upper": np.array([]), "middle": np.array([]), "lower": np.array([]), "width": np.array([])}

        try:
            upper, middle, lower = talib.BBANDS(prices, timeperiod=period, nbdevup=std_dev, nbdevdn=std_dev, matype=0)
            width = (upper - lower) / middle

            return {
                "upper": upper,
                "middle": middle,
                "lower": lower,
                "width": width
            }
        except:
            # Fallback implementation
            sma = self._calculate_sma(prices, period)
            std = pd.Series(prices).rolling(window=period).std()

            upper = sma + (std * std_dev)
            lower = sma - (std * std_dev)
            width = (upper - lower) / sma

            return {
                "upper": upper.values,
                "middle": sma,
                "lower": lower.values,
                "width": width.values
            }

    def _calculate_stochastic(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                            k_period: int = 14, d_period: int = 3) -> Dict[str, np.ndarray]:
        """Stochastic Oscillator"""
        if len(closes) < k_period + d_period:
            return {"k": np.array([]), "d": np.array([])}

        try:
            k, d = talib.STOCH(highs, lows, closes, fastk_period=k_period, slowk_period=3, slowd_period=d_period)
            return {"k": k, "d": d}
        except:
            # Fallback implementation
            return {"k": np.array([]), "d": np.array([])}

    def _calculate_williams_r(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
        """Williams %R"""
        if len(closes) < period:
            return np.array([])

        try:
            return talib.WILLR(highs, lows, closes, timeperiod=period)
        except:
            return np.array([])

    def _calculate_cci(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 20) -> np.ndarray:
        """Commodity Channel Index"""
        if len(closes) < period:
            return np.array([])

        try:
            return talib.CCI(highs, lows, closes, timeperiod=period)
        except:
            return np.array([])

    def _calculate_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
        """Average True Range"""
        if len(closes) < period + 1:
            return np.array([])

        try:
            return talib.ATR(highs, lows, closes, timeperiod=period)
        except:
            return np.array([])

    def _calculate_volume_indicators(self, volumes: np.ndarray, closes: np.ndarray) -> Dict[str, float]:
        """Calculate volume-based indicators"""
        try:
            # On Balance Volume (OBV)
            obv = talib.OBV(closes, volumes)

            # Volume Weighted Average Price (VWAP) - simplified
            vwap = np.sum(volumes * closes) / np.sum(volumes) if np.sum(volumes) > 0 else 0

            # Volume Rate of Change
            volume_roc = talib.ROC(volumes, timeperiod=10)

            return {
                "obv": float(obv[-1]) if len(obv) > 0 else None,
                "vwap": float(vwap),
                "volume_roc": float(volume_roc[-1]) if len(volume_roc) > 0 else None,
                "avg_volume": float(np.mean(volumes)),
                "volume_trend": "increasing" if len(volume_roc) > 0 and volume_roc[-1] > 0 else "decreasing"
            }
        except:
            return {}

    def _calculate_support_resistance(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> Dict[str, float]:
        """Calculate support and resistance levels"""
        try:
            # Simple pivot points
            current_high = highs[-1]
            current_low = lows[-1]
            current_close = closes[-1]

            pivot = (current_high + current_low + current_close) / 3
            resistance1 = (2 * pivot) - current_low
            support1 = (2 * pivot) - current_high

            return {
                "pivot_point": float(pivot),
                "resistance_1": float(resistance1),
                "support_1": float(support1),
                "resistance_2": float(pivot + (current_high - current_low)),
                "support_2": float(pivot - (current_high - current_low))
            }
        except:
            return {}

    def _analyze_trend(self, closes: np.ndarray, sma_20: np.ndarray, sma_50: np.ndarray) -> Dict[str, Any]:
        """Analyze trend direction and strength"""
        try:
            # Trend direction
            trend_direction = "sideways"
            if len(closes) >= 50:
                long_term_trend = closes[-1] > closes[-50]  # Price up over last 50 periods
                short_term_trend = closes[-1] > closes[-20]  # Price up over last 20 periods

                if long_term_trend and short_term_trend:
                    trend_direction = "bullish"
                elif not long_term_trend and not short_term_trend:
                    trend_direction = "bearish"

            # Moving average alignment
            ma_alignment = "neutral"
            if (len(sma_20) > 0 and len(sma_50) > 0 and
                sma_20[-1] > sma_50[-1]):
                ma_alignment = "bullish"
            elif (len(sma_20) > 0 and len(sma_50) > 0 and
                  sma_20[-1] < sma_50[-1]):
                ma_alignment = "bearish"

            # Trend strength (ADX-like)
            if len(closes) >= 14:
                high_low_range = highs[-14:] - lows[-14:] if 'highs' in locals() else np.diff(closes[-15:])
                trend_strength = np.mean(high_low_range) / np.mean(np.abs(np.diff(closes[-15:]))) if len(high_low_range) > 0 else 0
            else:
                trend_strength = 0

            return {
                "trend_direction": trend_direction,
                "ma_alignment": ma_alignment,
                "trend_strength": float(trend_strength),
                "is_trending": trend_direction in ["bullish", "bearish"]
            }
        except:
            return {"trend_direction": "unknown", "ma_alignment": "unknown", "trend_strength": 0, "is_trending": False}

    def _calculate_momentum_indicators(self, closes: np.ndarray) -> Dict[str, float]:
        """Calculate momentum-based indicators"""
        try:
            # Rate of Change (ROC)
            roc = talib.ROC(closes, timeperiod=10)

            # Momentum
            momentum = talib.MOM(closes, timeperiod=10)

            # Williams %R (already calculated above, but adding here for completeness)
            # TSI (True Strength Index) - simplified
            momentum_smooth = pd.Series(momentum).ewm(span=25).mean() if len(momentum) > 0 else pd.Series([])
            price_smooth = pd.Series(closes).ewm(span=13).mean()
            tsi = 100 * (momentum_smooth / price_smooth) if len(momentum_smooth) > 0 and len(price_smooth) > 0 else pd.Series([])

            return {
                "roc_10": float(roc[-1]) if len(roc) > 0 else None,
                "momentum_10": float(momentum[-1]) if len(momentum) > 0 else None,
                "tsi": float(tsi.iloc[-1]) if len(tsi) > 0 else None
            }
        except:
            return {}

    def _calculate_completeness(self, indicators: Dict[str, Any]) -> float:
        """Calculate how complete the indicator set is"""
        required_indicators = ["rsi", "ema_9", "ema_21", "macd_line", "bollinger_upper"]
        total_indicators = len(required_indicators)
        complete_indicators = sum(1 for ind in required_indicators if indicators.get(ind) is not None)

        return complete_indicators / total_indicators

    def get_indicator_history(self) -> Dict[str, List]:
        """Get historical indicator data"""
        return {
            "price_history": list(self.price_history),
            "volume_history": list(self.volume_history)
        }

    def reset_history(self):
        """Reset historical data"""
        self.price_history.clear()
        self.volume_history.clear()


# Global technical indicators calculator
technical_calculator = TechnicalIndicatorsCalculator()
