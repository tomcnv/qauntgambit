#!/usr/bin/env python3
"""
Diagnostic script to analyze why strategies aren't firing.

Analyzes the exported snapshot data to:
1. Compute percentile distributions for key metrics (ATR ratio, rotation, spread)
2. Identify the "dead zone" gaps in strategy coverage
3. Suggest threshold adjustments

Usage:
    python scripts/diagnose_strategy_gaps.py /tmp/last_12h_full.jsonl
"""

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional
import statistics


@dataclass
class MetricStats:
    """Statistics for a single metric."""
    count: int = 0
    values: list = None
    
    def __post_init__(self):
        if self.values is None:
            self.values = []
    
    def add(self, value: Optional[float]):
        if value is not None:
            self.values.append(value)
            self.count += 1
    
    def percentiles(self) -> dict:
        if not self.values:
            return {}
        sorted_vals = sorted(self.values)
        n = len(sorted_vals)
        return {
            "min": sorted_vals[0],
            "p10": sorted_vals[int(n * 0.10)],
            "p25": sorted_vals[int(n * 0.25)],
            "p50": sorted_vals[int(n * 0.50)],
            "p75": sorted_vals[int(n * 0.75)],
            "p90": sorted_vals[int(n * 0.90)],
            "p95": sorted_vals[int(n * 0.95)],
            "p99": sorted_vals[int(n * 0.99)],
            "max": sorted_vals[-1],
            "mean": statistics.mean(sorted_vals),
            "stdev": statistics.stdev(sorted_vals) if n > 1 else 0,
        }


def analyze_snapshots(filepath: str):
    """Analyze snapshot file and compute metric distributions."""
    
    # Per-symbol metrics
    metrics_by_symbol = defaultdict(lambda: {
        "atr_ratio": MetricStats(),
        "rotation_factor": MetricStats(),
        "rotation_abs": MetricStats(),
        "spread_bps": MetricStats(),
        "trend_strength": MetricStats(),
        "ema_spread_pct": MetricStats(),
        "distance_to_poc_pct": MetricStats(),
        "price_change_5s": MetricStats(),
        "price_change_30s": MetricStats(),
        "trades_per_second": MetricStats(),
        "orderflow_imbalance": MetricStats(),
    })
    
    # Strategy condition counters
    condition_hits = defaultdict(lambda: defaultdict(int))
    
    total_snapshots = 0
    
    print(f"Reading {filepath}...")
    
    with open(filepath, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                snapshot = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            total_snapshots += 1
            
            # Extract features
            features = snapshot.get("features") or snapshot.get("payload", {}).get("features", {})
            market_ctx = snapshot.get("market_context") or snapshot.get("payload", {}).get("market_context", {})
            
            symbol = features.get("symbol") or market_ctx.get("symbol") or snapshot.get("symbol")
            if not symbol:
                continue
            
            m = metrics_by_symbol[symbol]
            
            # ATR ratio
            atr = features.get("atr_5m")
            atr_baseline = features.get("atr_5m_baseline")
            if atr and atr_baseline and atr_baseline > 0:
                atr_ratio = atr / atr_baseline
                m["atr_ratio"].add(atr_ratio)
                
                # Check strategy conditions
                if atr_ratio < 0.5:
                    condition_hits[symbol]["atr_ratio < 0.5 (low_vol_grind)"] += 1
                if atr_ratio < 1.0:
                    condition_hits[symbol]["atr_ratio < 1.0 (mean_reversion)"] += 1
                if 1.0 <= atr_ratio < 1.2:
                    condition_hits[symbol]["1.0 <= atr_ratio < 1.2 (DEAD ZONE)"] += 1
                if 1.2 <= atr_ratio < 2.0:
                    condition_hits[symbol]["1.2 <= atr_ratio < 2.0 (vol_expansion)"] += 1
                if atr_ratio >= 2.0:
                    condition_hits[symbol]["atr_ratio >= 2.0 (high_vol_breakout)"] += 1
            
            # Rotation factor
            rotation = features.get("rotation_factor")
            if rotation is not None:
                m["rotation_factor"].add(rotation)
                m["rotation_abs"].add(abs(rotation))
                
                # Check rotation thresholds
                abs_rot = abs(rotation)
                if abs_rot >= 7.0:
                    condition_hits[symbol]["rotation >= 7.0 (breakout_scalp)"] += 1
                if abs_rot >= 5.0:
                    condition_hits[symbol]["rotation >= 5.0 (vol_expansion)"] += 1
                if abs_rot >= 4.0:
                    condition_hits[symbol]["rotation >= 4.0 (momentum)"] += 1
                if abs_rot >= 3.0:
                    condition_hits[symbol]["rotation >= 3.0 (trend)"] += 1
                if abs_rot < 3.0:
                    condition_hits[symbol]["rotation < 3.0 (ranging)"] += 1
            
            # Spread
            spread_bps = features.get("spread_bps")
            if spread_bps is not None:
                m["spread_bps"].add(spread_bps)
                
                if spread_bps <= 2.0:
                    condition_hits[symbol]["spread <= 2 bps (ultra tight)"] += 1
                if spread_bps <= 5.0:
                    condition_hits[symbol]["spread <= 5 bps (tight)"] += 1
                if spread_bps <= 10.0:
                    condition_hits[symbol]["spread <= 10 bps (normal)"] += 1
            
            # Trend strength (EMA spread)
            trend_strength = features.get("trend_strength") or features.get("ema_spread_pct")
            if trend_strength is not None:
                m["trend_strength"].add(trend_strength)
                m["ema_spread_pct"].add(trend_strength * 100)  # Convert to %
                
                if trend_strength >= 0.005:
                    condition_hits[symbol]["trend_strength >= 0.5% (strong)"] += 1
                if trend_strength >= 0.002:
                    condition_hits[symbol]["trend_strength >= 0.2% (moderate)"] += 1
                
                # Trend direction classification (matches context_vector.py logic)
                if trend_strength <= 0.001:
                    condition_hits[symbol]["trend_direction = flat"] += 1
                else:
                    condition_hits[symbol]["trend_direction = up/down"] += 1
            
            # Distance to POC
            price = features.get("price")
            poc = features.get("point_of_control")
            vah = features.get("value_area_high")
            val = features.get("value_area_low")
            
            if price and poc and price > 0:
                dist_pct = abs(price - poc) / price
                m["distance_to_poc_pct"].add(dist_pct * 100)
                
                if dist_pct >= 0.015:
                    condition_hits[symbol]["POC dist >= 1.5% (mean_rev)"] += 1
                if dist_pct >= 0.008:
                    condition_hits[symbol]["POC dist >= 0.8% (relaxed)"] += 1
            
            # Value location classification
            if price and vah and val:
                if val <= price <= vah:
                    condition_hits[symbol]["value_location = inside"] += 1
                elif price > vah:
                    condition_hits[symbol]["value_location = above"] += 1
                elif price < val:
                    condition_hits[symbol]["value_location = below"] += 1
            elif price and poc:
                # Fallback: estimate value area as POC +/- 0.5%
                est_vah = poc * 1.005
                est_val = poc * 0.995
                if est_val <= price <= est_vah:
                    condition_hits[symbol]["value_location = inside (est)"] += 1
                else:
                    condition_hits[symbol]["value_location = outside (est)"] += 1
            
            # Price changes
            m["price_change_5s"].add(features.get("price_change_5s"))
            m["price_change_30s"].add(features.get("price_change_30s"))
            m["trades_per_second"].add(features.get("trades_per_second"))
            m["orderflow_imbalance"].add(features.get("orderflow_imbalance"))
    
    print(f"\nAnalyzed {total_snapshots:,} snapshots\n")
    
    # Print results per symbol
    for symbol in sorted(metrics_by_symbol.keys()):
        print(f"\n{'='*60}")
        print(f"SYMBOL: {symbol}")
        print(f"{'='*60}")
        
        m = metrics_by_symbol[symbol]
        
        print("\n--- ATR Ratio Distribution ---")
        p = m["atr_ratio"].percentiles()
        if p:
            print(f"  Min: {p['min']:.3f}  P10: {p['p10']:.3f}  P25: {p['p25']:.3f}  P50: {p['p50']:.3f}")
            print(f"  P75: {p['p75']:.3f}  P90: {p['p90']:.3f}  P95: {p['p95']:.3f}  Max: {p['max']:.3f}")
            print(f"  Mean: {p['mean']:.3f}  StdDev: {p['stdev']:.3f}")
        
        print("\n--- Rotation Factor Distribution ---")
        p = m["rotation_abs"].percentiles()
        if p:
            print(f"  |Rotation| - Min: {p['min']:.2f}  P50: {p['p50']:.2f}  P75: {p['p75']:.2f}")
            print(f"  P90: {p['p90']:.2f}  P95: {p['p95']:.2f}  P99: {p['p99']:.2f}  Max: {p['max']:.2f}")
        
        print("\n--- Spread (bps) Distribution ---")
        p = m["spread_bps"].percentiles()
        if p:
            print(f"  Min: {p['min']:.1f}  P50: {p['p50']:.1f}  P75: {p['p75']:.1f}  P90: {p['p90']:.1f}  Max: {p['max']:.1f}")
        
        print("\n--- Trend Strength (EMA Spread %) ---")
        p = m["ema_spread_pct"].percentiles()
        if p:
            print(f"  Min: {p['min']:.4f}%  P50: {p['p50']:.4f}%  P90: {p['p90']:.4f}%  Max: {p['max']:.4f}%")
        
        print("\n--- Distance to POC (%) ---")
        p = m["distance_to_poc_pct"].percentiles()
        if p:
            print(f"  Min: {p['min']:.3f}%  P50: {p['p50']:.3f}%  P90: {p['p90']:.3f}%  Max: {p['max']:.3f}%")
        
        print("\n--- Strategy Condition Hit Rates ---")
        hits = condition_hits[symbol]
        total = m["atr_ratio"].count or 1
        for condition, count in sorted(hits.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            print(f"  {condition}: {count:,} ({pct:.1f}%)")
    
    # Summary recommendations
    print("\n" + "="*60)
    print("RECOMMENDATIONS")
    print("="*60)
    
    # Check for dead zones
    for symbol in metrics_by_symbol:
        hits = condition_hits[symbol]
        total = metrics_by_symbol[symbol]["atr_ratio"].count or 1
        
        dead_zone = hits.get("1.0 <= atr_ratio < 1.2 (DEAD ZONE)", 0)
        if dead_zone > 0:
            pct = dead_zone / total * 100
            print(f"\n{symbol}: {pct:.1f}% of snapshots in ATR dead zone (1.0-1.2)")
            print("  → Consider: Extend mean_reversion to atr_ratio <= 1.4")
            print("  → Consider: Lower vol_expansion threshold to 1.1")
        
        # Check rotation thresholds
        rot_stats = metrics_by_symbol[symbol]["rotation_abs"].percentiles()
        if rot_stats:
            p90 = rot_stats.get("p90", 0)
            p95 = rot_stats.get("p95", 0)
            print(f"\n{symbol}: Rotation P90={p90:.2f}, P95={p95:.2f}")
            if p95 < 5.0:
                print("  → WARNING: rotation >= 5.0 is above P95!")
                print("  → Consider: Use percentile-based thresholds (e.g., P75)")
            if p90 < 7.0:
                print("  → WARNING: rotation >= 7.0 is above P90!")
                print("  → Consider: Lower breakout_scalp threshold to 4.0-5.0")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python diagnose_strategy_gaps.py <snapshot_file.jsonl>")
        sys.exit(1)
    
    analyze_snapshots(sys.argv[1])
