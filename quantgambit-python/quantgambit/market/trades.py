"""Trade statistics cache for microstructure features."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

from quantgambit.ingest.time_utils import in_window_us


@dataclass
class TradeRecord:
    ts_us: int
    price: float
    size: float
    side: str


class TradeStatsCache:
    def __init__(
        self,
        window_sec: float = 60.0,
        profile_window_sec: float = 300.0,
        bucket_size: float = 5.0,
        max_trades: int = 10000,
    ) -> None:
        self.window_sec = window_sec
        self.profile_window_sec = profile_window_sec
        self.bucket_size = bucket_size
        self.max_trades = max_trades
        self._trades: Dict[str, Deque[TradeRecord]] = {}

    def _calculate_adaptive_bucket_size(self, median_price: float) -> float:
        """
        Calculate adaptive bucket size based on price level.
        
        Algorithm:
        - Use a percentage of median price based on accuracy requirements:
          - Price < $200: 0.5% accuracy → use 0.25% bucket size (half of threshold)
          - Price $200-$1000: 0.25% accuracy → use 0.125% bucket size
          - Price > $1000: 0.1% accuracy → use 0.05% bucket size
        - Ensure minimum of 0.001 for very low-priced assets
        - Use configured bucket_size * 0.1 as an alternative minimum
        
        This ensures the POC is always within the accuracy threshold for each price level.
        """
        # Determine the bucket size percentage based on price level
        # Use half the accuracy threshold to ensure we're well within bounds
        if median_price < 200.0:
            # 0.5% accuracy threshold → 0.25% bucket size
            pct_based = median_price * 0.0025
        elif median_price <= 1000.0:
            # 0.25% accuracy threshold → 0.125% bucket size
            pct_based = median_price * 0.00125
        else:
            # 0.1% accuracy threshold → 0.05% bucket size
            pct_based = median_price * 0.0005
        
        # Minimum bucket size for very low prices (absolute floor)
        # Also consider the configured bucket_size as a factor
        min_bucket = max(0.001, self.bucket_size * 0.01)
        
        return max(min_bucket, pct_based)

    def update_trade(self, symbol: str, timestamp_us: int, price: float, size: float, side: str) -> None:
        if not symbol:
            return
        try:
            ts_us = int(timestamp_us)
        except (TypeError, ValueError):
            return
        trades = self._trades.setdefault(symbol, deque())
        trades.append(TradeRecord(ts_us, price, size, side))
        while len(trades) > self.max_trades:
            trades.popleft()
        self._prune(trades, ts_us)

    def snapshot(self, symbol: str, now_ts_us: Optional[int] = None) -> dict:
        trades = self._trades.get(symbol)
        if not trades:
            return {}
        if now_ts_us is None:
            raise ValueError("now_ts_required")
        now_us = int(now_ts_us)
        self._prune(trades, now_us)
        window_us = int(self.window_sec * 1_000_000)
        profile_window_us = int(self.profile_window_sec * 1_000_000)
        recent = [t for t in trades if in_window_us(t.ts_us, now_us, window_us)]
        profile = [t for t in trades if in_window_us(t.ts_us, now_us, profile_window_us)]
        if not recent:
            return {}
        total_volume = sum(t.size for t in recent)
        vwap = sum(t.price * t.size for t in recent) / total_volume if total_volume else 0.0
        tps = len(recent) / self.window_sec if self.window_sec else 0.0
        buy_vol = sum(t.size for t in recent if t.side.lower() == "buy")
        sell_vol = sum(t.size for t in recent if t.side.lower() == "sell")
        imbalance = (buy_vol - sell_vol) / (buy_vol + sell_vol) if (buy_vol + sell_vol) else 0.0
        poc, val, vah = self._volume_profile(profile)
        return {
            "trades_per_second": tps,
            "vwap": vwap,
            "point_of_control": poc,
            "value_area_low": val,
            "value_area_high": vah,
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "orderflow_imbalance": imbalance,
        }

    def _prune(self, trades: Deque[TradeRecord], now_us: int) -> None:
        cutoff = now_us - int(self.profile_window_sec * 1_000_000)
        while trades and trades[0].ts_us < cutoff:
            trades.popleft()

    def _volume_profile(self, trades: list[TradeRecord]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        if not trades:
            return None, None, None
        
        # Get price range for adaptive bucket sizing
        prices = [t.price for t in trades if t.price > 0]  # Filter out invalid prices
        if not prices:
            return None, None, None
        median_price = sorted(prices)[len(prices) // 2]
        
        # Use adaptive bucket sizing based on price level
        dynamic_bucket = self._calculate_adaptive_bucket_size(median_price)
        
        bins: Dict[float, float] = {}
        for trade in trades:
            if trade.price <= 0:  # Skip invalid prices
                continue
            bucket = float(int(trade.price / dynamic_bucket) * dynamic_bucket)
            bins[bucket] = bins.get(bucket, 0.0) + trade.size
        if not bins:
            return None, None, None
        poc = max(bins.items(), key=lambda x: x[1])[0]
        total = sum(bins.values())
        target = total * 0.7
        sorted_bins = sorted(bins.items(), key=lambda x: x[1], reverse=True)
        picked = []
        cum = 0.0
        for bucket, vol in sorted_bins:
            picked.append(bucket)
            cum += vol
            if cum >= target:
                break
        val = min(picked) if picked else poc
        vah = max(picked) if picked else poc
        
        # If value area is collapsed to single bucket, expand it slightly
        # This happens when volume is concentrated in one price level
        if val == vah and poc is not None:
            # Expand by one bucket in each direction
            val = poc - dynamic_bucket
            vah = poc + dynamic_bucket
            
        return poc, val, vah
