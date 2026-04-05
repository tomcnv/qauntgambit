#!/usr/bin/env python3
"""Replay test for Profile Router v2 with synthetic market data.

This script generates realistic market scenarios and tests the Profile Router v2
through the full decision pipeline to verify it works correctly in production-like
conditions.
"""

import asyncio
import json
import sys
import time
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter, get_profile_router
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry
from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import register_canonical_profiles


@dataclass
class MarketScenario:
    """A market scenario for generating snapshots."""
    name: str
    duration_minutes: int
    regime: str
    trend_direction: str
    trend_strength_range: tuple
    volatility_regime: str
    session: str
    spread_bps_range: tuple
    depth_usd_range: tuple
    tps_range: tuple
    cost_bps_range: tuple


def generate_market_scenarios() -> List[MarketScenario]:
    """Generate a sequence of market scenarios simulating a trading day."""
    return [
        # Asia session - typically range-bound
        MarketScenario(
            name="Asia Range",
            duration_minutes=30,
            regime="range",
            trend_direction="flat",
            trend_strength_range=(0.0005, 0.002),
            volatility_regime="low",
            session="asia",
            spread_bps_range=(3.0, 6.0),
            depth_usd_range=(40000, 80000),
            tps_range=(0.5, 1.5),
            cost_bps_range=(4.0, 7.0),
        ),
        # Europe open - volatility expansion
        MarketScenario(
            name="Europe Open Vol",
            duration_minutes=20,
            regime="breakout",
            trend_direction="up",
            trend_strength_range=(0.003, 0.006),
            volatility_regime="high",
            session="europe",
            spread_bps_range=(4.0, 8.0),
            depth_usd_range=(30000, 60000),
            tps_range=(2.0, 4.0),
            cost_bps_range=(6.0, 10.0),
        ),
        # Europe mid-session - trending
        MarketScenario(
            name="Europe Trend",
            duration_minutes=40,
            regime="breakout",
            trend_direction="up",
            trend_strength_range=(0.002, 0.004),
            volatility_regime="normal",
            session="europe",
            spread_bps_range=(3.0, 5.0),
            depth_usd_range=(50000, 100000),
            tps_range=(1.5, 3.0),
            cost_bps_range=(5.0, 8.0),
        ),
        # US open - high activity
        MarketScenario(
            name="US Open Momentum",
            duration_minutes=30,
            regime="breakout",
            trend_direction="up",
            trend_strength_range=(0.004, 0.007),
            volatility_regime="high",
            session="us",
            spread_bps_range=(2.0, 5.0),
            depth_usd_range=(80000, 150000),
            tps_range=(3.0, 6.0),
            cost_bps_range=(4.0, 7.0),
        ),
        # US mid-session - consolidation
        MarketScenario(
            name="US Consolidation",
            duration_minutes=40,
            regime="range",
            trend_direction="flat",
            trend_strength_range=(0.001, 0.003),
            volatility_regime="normal",
            session="us",
            spread_bps_range=(2.0, 4.0),
            depth_usd_range=(100000, 200000),
            tps_range=(2.0, 4.0),
            cost_bps_range=(3.0, 6.0),
        ),
        # US close - choppy
        MarketScenario(
            name="US Close Chop",
            duration_minutes=20,
            regime="chop",
            trend_direction="flat",
            trend_strength_range=(0.0005, 0.002),
            volatility_regime="normal",
            session="us",
            spread_bps_range=(3.0, 6.0),
            depth_usd_range=(60000, 100000),
            tps_range=(1.0, 2.0),
            cost_bps_range=(5.0, 9.0),
        ),
        # Overnight - thin liquidity
        MarketScenario(
            name="Overnight Thin",
            duration_minutes=30,
            regime="range",
            trend_direction="down",
            trend_strength_range=(0.001, 0.003),
            volatility_regime="low",
            session="overnight",
            spread_bps_range=(5.0, 10.0),
            depth_usd_range=(20000, 50000),
            tps_range=(0.2, 0.8),
            cost_bps_range=(7.0, 12.0),
        ),
    ]


def generate_snapshots(scenarios: List[MarketScenario], symbol: str = "BTC-USDT") -> List[Dict[str, Any]]:
    """Generate market snapshots from scenarios."""
    snapshots = []
    base_time = time.time() - 3600 * 4  # Start 4 hours ago
    base_price = 50000.0
    current_time = base_time
    current_price = base_price
    
    for scenario in scenarios:
        num_snapshots = scenario.duration_minutes  # One per minute
        
        for i in range(num_snapshots):
            # Generate random values within scenario ranges
            trend_strength = random.uniform(*scenario.trend_strength_range)
            spread_bps = random.uniform(*scenario.spread_bps_range)
            depth_usd = random.uniform(*scenario.depth_usd_range)
            tps = random.uniform(*scenario.tps_range)
            cost_bps = random.uniform(*scenario.cost_bps_range)
            
            # Evolve price based on trend
            if scenario.trend_direction == "up":
                price_change = current_price * trend_strength * random.uniform(0.5, 1.5)
            elif scenario.trend_direction == "down":
                price_change = -current_price * trend_strength * random.uniform(0.5, 1.5)
            else:
                price_change = current_price * trend_strength * random.uniform(-1, 1)
            
            current_price += price_change
            current_time += 60  # 1 minute intervals
            
            # Determine position in value (simplified)
            if random.random() < 0.3:
                position_in_value = "above"
            elif random.random() < 0.5:
                position_in_value = "below"
            else:
                position_in_value = "inside"
            
            # Calculate rotation factor
            rotation_factor = random.uniform(-5, 5)
            if scenario.trend_direction == "up":
                rotation_factor = abs(rotation_factor)
            elif scenario.trend_direction == "down":
                rotation_factor = -abs(rotation_factor)
            
            # Determine hour_utc based on session
            session_hours = {
                "asia": random.randint(0, 7),
                "europe": random.randint(8, 13),
                "us": random.randint(14, 20),
                "overnight": random.randint(21, 23),
            }
            hour_utc = session_hours.get(scenario.session, 12)
            
            snapshot = {
                "symbol": symbol,
                "timestamp": current_time,
                "scenario": scenario.name,
                "market_context": {
                    "price": current_price,
                    "regime_label": scenario.regime,
                    "market_regime": scenario.regime,
                    "session": scenario.session,
                    "volatility_regime": scenario.volatility_regime,
                    "trend_direction": scenario.trend_direction,
                    "trend_strength": trend_strength,
                    "spread_bps": spread_bps,
                    "bid_depth_usd": depth_usd,
                    "ask_depth_usd": depth_usd * random.uniform(0.8, 1.2),
                    "trades_per_second": tps,
                    "expected_cost_bps": cost_bps,
                    "liquidity_score": min(1.0, depth_usd / 100000),
                    "position_in_value": position_in_value,
                    "rotation_factor": rotation_factor,
                    "hour_utc": hour_utc,
                    "atr_ratio": random.uniform(0.7, 1.5),
                    "data_completeness": random.uniform(0.9, 1.0),
                },
                "features": {
                    "price": current_price,
                    "bid": current_price - (current_price * spread_bps / 20000),
                    "ask": current_price + (current_price * spread_bps / 20000),
                    "spread_bps": spread_bps,
                    "bid_depth_usd": depth_usd,
                    "ask_depth_usd": depth_usd * random.uniform(0.8, 1.2),
                    "volatility_regime": scenario.volatility_regime,
                    "atr_5m": current_price * 0.005,
                    "atr_5m_baseline": current_price * 0.005,
                    "timestamp": current_time,
                },
                "warmup_ready": True,
            }
            
            snapshots.append(snapshot)
    
    return snapshots


def build_context_from_snapshot(snapshot: Dict[str, Any]) -> ContextVector:
    """Build a ContextVector from a snapshot."""
    mc = snapshot.get("market_context", {})
    features = snapshot.get("features", {})
    
    return ContextVector(
        symbol=snapshot["symbol"],
        timestamp=snapshot["timestamp"],
        price=mc.get("price") or features.get("price", 50000.0),
        trend_direction=mc.get("trend_direction", "flat"),
        trend_strength=mc.get("trend_strength", 0.001),
        volatility_regime=mc.get("volatility_regime", "normal"),
        atr_ratio=mc.get("atr_ratio", 1.0),
        position_in_value=mc.get("position_in_value", "inside"),
        rotation_factor=mc.get("rotation_factor", 0.0),
        spread_bps=mc.get("spread_bps") or features.get("spread_bps", 5.0),
        bid_depth_usd=mc.get("bid_depth_usd") or features.get("bid_depth_usd", 50000.0),
        ask_depth_usd=mc.get("ask_depth_usd") or features.get("ask_depth_usd", 50000.0),
        trades_per_second=mc.get("trades_per_second", 1.0),
        session=mc.get("session", "us"),
        hour_utc=mc.get("hour_utc", 12),
        market_regime=mc.get("market_regime") or mc.get("regime_label", "range"),
        risk_mode="normal",
        expected_cost_bps=mc.get("expected_cost_bps", 5.0),
        liquidity_score=mc.get("liquidity_score", 0.5),
        data_completeness=mc.get("data_completeness", 1.0),
    )


async def run_replay_test():
    """Run the replay test."""
    print("\n" + "="*70)
    print("Profile Router v2 Replay Test")
    print("="*70)
    
    # Register canonical profiles
    print("\nRegistering canonical profiles...")
    register_canonical_profiles()
    
    registry = get_profile_registry()
    profile_count = len(registry.list_specs())
    print(f"Registered {profile_count} profiles")
    
    # Create router with shorter TTL for testing diversity
    print("\nInitializing Profile Router v2 (with shorter TTL for testing)...")
    config = RouterConfig(
        min_profile_ttl_sec=30.0,  # Shorter TTL for testing
        switch_margin=0.05,  # Lower margin for testing
    )
    router = ProfileRouter(config=config)
    
    # Generate market scenarios
    print("\nGenerating market scenarios...")
    scenarios = generate_market_scenarios()
    snapshots = generate_snapshots(scenarios)
    print(f"Generated {len(snapshots)} snapshots across {len(scenarios)} scenarios")
    
    # Run replay
    print("\n" + "-"*70)
    print("Running Replay...")
    print("-"*70)
    
    results = {
        "total_snapshots": len(snapshots),
        "profiles_selected": 0,
        "no_profiles": 0,
        "hard_filter_rejections": 0,
        "profile_distribution": {},
        "scenario_results": {},
        "stability_switches": 0,
    }
    
    last_profile = None
    current_scenario = None
    scenario_stats = {}
    
    for i, snapshot in enumerate(snapshots):
        scenario_name = snapshot.get("scenario", "unknown")
        
        # Track scenario changes - reset stability manager for new scenario
        if scenario_name != current_scenario:
            if current_scenario:
                print(f"\n  Scenario '{current_scenario}' complete: {scenario_stats.get(current_scenario, {})}")
                # Reset stability manager for new scenario to test profile selection
                router.stability_manager.reset_all()
            current_scenario = scenario_name
            print(f"\n📊 Scenario: {scenario_name}")
            scenario_stats[scenario_name] = {
                "snapshots": 0,
                "profiles_selected": 0,
                "no_profiles": 0,
                "unique_profiles": set(),
            }
        
        # Build context and select profiles
        context = build_context_from_snapshot(snapshot)
        profiles = router.select_profiles(context, top_k=3, symbol=snapshot["symbol"])
        
        scenario_stats[scenario_name]["snapshots"] += 1
        
        if profiles:
            results["profiles_selected"] += 1
            scenario_stats[scenario_name]["profiles_selected"] += 1
            
            top_profile = profiles[0]
            profile_id = top_profile.profile_id
            
            # Track profile distribution
            results["profile_distribution"][profile_id] = results["profile_distribution"].get(profile_id, 0) + 1
            scenario_stats[scenario_name]["unique_profiles"].add(profile_id)
            
            # Track stability (profile switches)
            if last_profile and last_profile != profile_id:
                results["stability_switches"] += 1
            last_profile = profile_id
            
            # Track hard filter rejections
            if not top_profile.hard_filter_passed:
                results["hard_filter_rejections"] += 1
        else:
            results["no_profiles"] += 1
            scenario_stats[scenario_name]["no_profiles"] += 1
            last_profile = None
        
        # Progress indicator
        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(snapshots)} snapshots...")
    
    # Final scenario stats
    if current_scenario:
        print(f"\n  Scenario '{current_scenario}' complete: {scenario_stats.get(current_scenario, {})}")
    
    # Summary
    print("\n" + "="*70)
    print("Replay Results Summary")
    print("="*70)
    
    print(f"\nTotal Snapshots: {results['total_snapshots']}")
    print(f"Profiles Selected: {results['profiles_selected']} ({results['profiles_selected']/results['total_snapshots']*100:.1f}%)")
    print(f"No Profiles: {results['no_profiles']} ({results['no_profiles']/results['total_snapshots']*100:.1f}%)")
    print(f"Profile Switches: {results['stability_switches']}")
    
    avg_duration = results['total_snapshots'] / max(1, results['stability_switches'])
    print(f"Average Profile Duration: {avg_duration:.1f} snapshots")
    
    print(f"\nProfile Distribution (top 10):")
    sorted_profiles = sorted(results["profile_distribution"].items(), key=lambda x: x[1], reverse=True)
    for profile_id, count in sorted_profiles[:10]:
        pct = count / results['profiles_selected'] * 100 if results['profiles_selected'] > 0 else 0
        print(f"  {profile_id}: {count} ({pct:.1f}%)")
    
    print(f"\nScenario Results:")
    for scenario_name, stats in scenario_stats.items():
        unique_count = len(stats["unique_profiles"])
        print(f"  {scenario_name}:")
        print(f"    - Snapshots: {stats['snapshots']}")
        print(f"    - Profiles Selected: {stats['profiles_selected']}")
        print(f"    - Unique Profiles: {unique_count}")
        if stats["unique_profiles"]:
            print(f"    - Profiles: {', '.join(list(stats['unique_profiles'])[:5])}")
    
    # Validation
    print("\n" + "="*70)
    print("Validation")
    print("="*70)
    
    issues = []
    
    # Check profile selection rate
    selection_rate = results['profiles_selected'] / results['total_snapshots']
    if selection_rate < 0.5:
        issues.append(f"Low profile selection rate: {selection_rate*100:.1f}% (expected > 50%)")
    else:
        print(f"✓ Profile selection rate: {selection_rate*100:.1f}%")
    
    # Check stability (not too many switches)
    switch_rate = results['stability_switches'] / results['total_snapshots']
    if switch_rate > 0.3:
        issues.append(f"High switch rate: {switch_rate*100:.1f}% (expected < 30%)")
    else:
        print(f"✓ Profile switch rate: {switch_rate*100:.1f}%")
    
    # Check profile diversity
    unique_profiles = len(results["profile_distribution"])
    if unique_profiles < 5:
        issues.append(f"Low profile diversity: {unique_profiles} unique profiles (expected > 5)")
    else:
        print(f"✓ Profile diversity: {unique_profiles} unique profiles")
    
    # Check scenario coverage
    for scenario_name, stats in scenario_stats.items():
        if stats["profiles_selected"] == 0:
            issues.append(f"No profiles selected for scenario: {scenario_name}")
    
    if not issues:
        print("\n✓ All validations passed!")
        return 0
    else:
        print(f"\n✗ {len(issues)} validation issue(s):")
        for issue in issues:
            print(f"  - {issue}")
        return 1


def main():
    """Main entry point."""
    return asyncio.run(run_replay_test())


if __name__ == "__main__":
    sys.exit(main())
