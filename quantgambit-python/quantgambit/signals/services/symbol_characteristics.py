"""
Symbol Characteristics Service - Tracks rolling statistics per symbol.

Implements Requirements 1.1-1.8 for symbol-adaptive parameters:
- Tracks typical_spread_bps as EMA of recent spreads (1.1)
- Tracks typical_depth_usd as EMA of min orderbook depth (1.2)
- Tracks typical_daily_range_pct from ATR normalized by price (1.3)
- Tracks typical_volatility_regime as mode of recent regimes (1.4)
- Updates on each market tick (1.5)
- Persists to Redis for recovery (1.6)
- Uses conservative defaults on cold start (1.7)
- Exposes get_characteristics() method (1.8)
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Dict, Optional, Any

from quantgambit.deeptrader_core.types import SymbolCharacteristics


logger = logging.getLogger(__name__)


class SymbolCharacteristicsService:
    """
    Tracks rolling statistics for each symbol.
    
    Uses exponential moving averages for smooth adaptation.
    Persists to Redis for recovery after restart.
    
    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 1.8
    """
    
    # Default EMA decay factor (slow adaptation for stability)
    DEFAULT_EMA_DECAY = 0.01
    
    # Window size for volatility regime mode tracking
    REGIME_WINDOW_SIZE = 100
    
    # Minimum samples before considering data reliable
    MIN_WARMUP_SAMPLES = 100
    
    def __init__(
        self,
        redis_client: Optional[Any] = None,
        ema_decay: float = DEFAULT_EMA_DECAY,
        key_prefix: str = "quantgambit:symbol_chars",
    ):
        """
        Initialize the service.
        
        Args:
            redis_client: Async Redis client for persistence (optional)
            ema_decay: EMA decay factor (default 0.01 for slow adaptation)
            key_prefix: Redis key prefix for persistence
        """
        self._redis = redis_client
        self._ema_decay = ema_decay
        self._key_prefix = key_prefix
        self._cache: Dict[str, SymbolCharacteristics] = {}
        
        # Track recent volatility regimes for mode calculation
        self._regime_history: Dict[str, deque] = {}
        
        # Track last persisted values for change detection
        self._last_persisted: Dict[str, SymbolCharacteristics] = {}
    
    def update(
        self,
        symbol: str,
        spread_bps: float,
        min_depth_usd: float,
        atr: float,
        price: float,
        volatility_regime: str,
    ) -> SymbolCharacteristics:
        """
        Update characteristics with new market data.
        
        Called on each market tick to update rolling statistics.
        Uses EMA for smooth adaptation: EMA_new = α × value + (1 - α) × EMA_old
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            spread_bps: Current spread in basis points
            min_depth_usd: Minimum of bid/ask depth in USD
            atr: Current ATR value
            price: Current price for normalizing ATR to daily range
            volatility_regime: Current regime ("low", "normal", "high")
            
        Returns:
            Updated SymbolCharacteristics
            
        Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
        """
        # Get or create characteristics
        if symbol not in self._cache:
            self._cache[symbol] = SymbolCharacteristics.default(symbol)
            self._regime_history[symbol] = deque(maxlen=self.REGIME_WINDOW_SIZE)
        elif symbol not in self._regime_history:
            self._regime_history[symbol] = deque(maxlen=self.REGIME_WINDOW_SIZE)
        
        chars = self._cache[symbol]
        alpha = self._ema_decay
        
        # Calculate daily range from ATR (ATR is typically 14-period on 5-min bars)
        # ATR / price gives the 5-min range as percentage
        # Scale to daily: multiply by sqrt(288) ≈ 17 for 5-min bars per day
        # This converts 5-min ATR to approximate daily range
        DAILY_SCALE_FACTOR = 17.0  # sqrt(288) for 5-min bars
        MIN_DAILY_RANGE_PCT = 0.005  # Minimum 0.5% daily range (safety floor)
        if price > 0 and atr > 0:
            five_min_range_pct = atr / price
            daily_range_pct = five_min_range_pct * DAILY_SCALE_FACTOR
            # Apply minimum bound to prevent unrealistically tight parameters
            daily_range_pct = max(daily_range_pct, MIN_DAILY_RANGE_PCT)
        else:
            daily_range_pct = 0.03  # Default 3% daily range
        
        # Update EMAs (Requirement 1.1, 1.2, 1.3)
        if chars.sample_count == 0:
            # First sample - initialize directly
            new_spread = spread_bps
            new_depth = min_depth_usd
            new_daily_range = daily_range_pct
            new_atr = atr
        else:
            # EMA update: EMA_new = α × value + (1 - α) × EMA_old
            new_spread = alpha * spread_bps + (1 - alpha) * chars.typical_spread_bps
            new_depth = alpha * min_depth_usd + (1 - alpha) * chars.typical_depth_usd
            new_daily_range = alpha * daily_range_pct + (1 - alpha) * chars.typical_daily_range_pct
            new_atr = alpha * atr + (1 - alpha) * chars.typical_atr
        
        # Track volatility regime for mode calculation (Requirement 1.4)
        self._regime_history[symbol].append(volatility_regime)
        new_regime = self._calculate_regime_mode(symbol)
        
        # Create updated characteristics
        updated = SymbolCharacteristics(
            symbol=symbol,
            typical_spread_bps=new_spread,
            typical_depth_usd=new_depth,
            typical_daily_range_pct=new_daily_range,
            typical_atr=new_atr,
            typical_volatility_regime=new_regime,
            sample_count=chars.sample_count + 1,
            last_updated_ns=time.time_ns(),
        )
        
        self._cache[symbol] = updated
        return updated
    
    def _calculate_regime_mode(self, symbol: str) -> str:
        """
        Calculate the mode (most common) volatility regime.
        
        Requirement 1.4: Track typical_volatility_regime as mode of recent regimes.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Most common regime in the window ("low", "normal", or "high")
        """
        history = self._regime_history.get(symbol, deque())
        if not history:
            return "normal"
        
        # Count occurrences
        counts = {"low": 0, "normal": 0, "high": 0}
        for regime in history:
            if regime in counts:
                counts[regime] += 1
        
        # Return mode (most common)
        return max(counts, key=counts.get)
    
    def get_characteristics(self, symbol: str) -> SymbolCharacteristics:
        """
        Get current characteristics for symbol.
        
        Returns defaults if no data available (Requirement 1.7).
        
        Args:
            symbol: Trading symbol
            
        Returns:
            SymbolCharacteristics (cached or default)
            
        Requirement 1.8
        """
        if symbol in self._cache:
            return self._cache[symbol]
        
        # Return conservative defaults (Requirement 1.7)
        logger.info(
            "symbol_characteristics_default",
            extra={"symbol": symbol, "reason": "no_cached_data"},
        )
        return SymbolCharacteristics.default(symbol)
    
    def has_characteristics(self, symbol: str) -> bool:
        """Check if we have cached characteristics for a symbol."""
        return symbol in self._cache
    
    def is_warmed_up(self, symbol: str, min_samples: int = MIN_WARMUP_SAMPLES) -> bool:
        """
        Check if symbol has enough samples for reliable estimates.
        
        Args:
            symbol: Trading symbol
            min_samples: Minimum samples required
            
        Returns:
            True if warmed up
        """
        if symbol not in self._cache:
            return False
        return self._cache[symbol].is_warmed_up(min_samples)
    
    async def persist(self, symbol: str) -> None:
        """
        Persist characteristics to Redis.
        
        Requirement 1.6: Persist statistics to Redis for recovery after restart.
        
        Args:
            symbol: Trading symbol to persist
        """
        if self._redis is None:
            logger.debug("symbol_characteristics_persist_skip", extra={"reason": "no_redis"})
            return
        
        if symbol not in self._cache:
            return
        
        chars = self._cache[symbol]
        key = f"{self._key_prefix}:{symbol}"
        
        try:
            # Use Redis hash for structured storage
            data = chars.to_dict()
            # Convert all values to strings for Redis hash
            hash_data = {k: str(v) for k, v in data.items()}
            await self._redis.hset(key, mapping=hash_data)
            
            self._last_persisted[symbol] = chars
            logger.debug(
                "symbol_characteristics_persisted",
                extra={"symbol": symbol, "sample_count": chars.sample_count},
            )
        except Exception as exc:
            logger.warning(
                "symbol_characteristics_persist_error",
                extra={"symbol": symbol, "error": str(exc)},
            )
    
    async def load(self, symbol: str) -> Optional[SymbolCharacteristics]:
        """
        Load characteristics from Redis.
        
        Requirement 1.6: Persist statistics to Redis for recovery after restart.
        
        Args:
            symbol: Trading symbol to load
            
        Returns:
            SymbolCharacteristics if found, None otherwise
        """
        if self._redis is None:
            return None
        
        key = f"{self._key_prefix}:{symbol}"
        
        try:
            data = await self._redis.hgetall(key)
            if not data:
                return None
            
            # Convert bytes to strings if needed (redis-py returns bytes)
            str_data = {}
            for k, v in data.items():
                key_str = k.decode("utf-8") if isinstance(k, bytes) else k
                val_str = v.decode("utf-8") if isinstance(v, bytes) else v
                str_data[key_str] = val_str
            
            # Parse the data
            chars = SymbolCharacteristics(
                symbol=str_data["symbol"],
                typical_spread_bps=float(str_data["typical_spread_bps"]),
                typical_depth_usd=float(str_data["typical_depth_usd"]),
                typical_daily_range_pct=float(str_data["typical_daily_range_pct"]),
                typical_atr=float(str_data["typical_atr"]),
                typical_volatility_regime=str_data["typical_volatility_regime"],
                sample_count=int(str_data["sample_count"]),
                last_updated_ns=int(str_data["last_updated_ns"]),
            )
            
            # Cache the loaded data
            self._cache[symbol] = chars
            self._last_persisted[symbol] = chars
            if symbol not in self._regime_history:
                self._regime_history[symbol] = deque(maxlen=self.REGIME_WINDOW_SIZE)
            
            logger.info(
                "symbol_characteristics_loaded",
                extra={"symbol": symbol, "sample_count": chars.sample_count},
            )
            return chars
            
        except Exception as exc:
            logger.warning(
                "symbol_characteristics_load_error",
                extra={"symbol": symbol, "error": str(exc)},
            )
            return None
    
    async def persist_if_changed(self, symbol: str, threshold_pct: float = 0.20) -> bool:
        """
        Persist to Redis if characteristics changed significantly.
        
        Auto-persist on significant changes (>threshold_pct change in any metric).
        
        Args:
            symbol: Trading symbol
            threshold_pct: Percentage change threshold (default 20%)
            
        Returns:
            True if persisted, False otherwise
        """
        if symbol not in self._cache:
            return False
        
        current = self._cache[symbol]
        last = self._last_persisted.get(symbol)
        
        if last is None:
            # Never persisted - persist now
            await self.persist(symbol)
            return True
        
        # Check for significant changes
        def pct_change(old: float, new: float) -> float:
            if old == 0:
                return 1.0 if new != 0 else 0.0
            return abs(new - old) / abs(old)
        
        spread_change = pct_change(last.typical_spread_bps, current.typical_spread_bps)
        depth_change = pct_change(last.typical_depth_usd, current.typical_depth_usd)
        range_change = pct_change(last.typical_daily_range_pct, current.typical_daily_range_pct)
        
        if spread_change > threshold_pct or depth_change > threshold_pct or range_change > threshold_pct:
            logger.info(
                "symbol_characteristics_significant_change",
                extra={
                    "symbol": symbol,
                    "spread_change_pct": spread_change,
                    "depth_change_pct": depth_change,
                    "range_change_pct": range_change,
                },
            )
            await self.persist(symbol)
            return True
        
        return False
    
    def get_all_symbols(self) -> list[str]:
        """Get list of all symbols with cached characteristics."""
        return list(self._cache.keys())
    
    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """
        Clear cached characteristics.
        
        Args:
            symbol: Specific symbol to clear, or None to clear all
        """
        if symbol:
            self._cache.pop(symbol, None)
            self._regime_history.pop(symbol, None)
            self._last_persisted.pop(symbol, None)
        else:
            self._cache.clear()
            self._regime_history.clear()
            self._last_persisted.clear()
