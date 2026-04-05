#!/usr/bin/env python3
"""Run a backtest using the Profile Router v2 with real historical data.

This script fetches decision events from TimescaleDB and runs them through
the Profile Router v2 to test profile selection with real market data.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

# Add parent to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

import asyncpg

from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry
from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import register_canonical_profiles


async def fetch_decision_events(
    pool: asyncpg.Pool,
    symbol: str,
    start_time: datetime,
    end_time: datetime,
    sample_every: int = 100,
    limit: int = 10000,
) -> List[Dict[str, Any]]:
    """Fetch decision events from TimescaleDB."""
    query = """
        WITH numbered AS (
            SELECT ts, payload, ROW_NUMBER() OVER (ORDER BY ts) as rn
            FROM decision_events
            WHERE symbol = $1 AND ts >= $2 AND ts <= $3
        )
        SELECT ts, payload
        FROM numbered
        WHERE rn % $4 = 0
        ORDER BY ts
        LIMIT $5
    """
    
    rows = await pool.fetch(query, symbol, start_time, end_time, sample_every, limit)
    
    events = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        events.append({
            "ts": row["ts"],
            "payload": payload,
        })
    
    return events


def build_context_from_event(event: Dict[str, Any], symbol: str) -> Optional[ContextVector]:
    """Build a ContextVector from a decision event."""
    payload = event.get("payload", {})
    snapshot = payload.get("snapshot", {})
    metrics = payload.get("metrics", {})
    resolved_params = payload.get("resolved_params", {})
    
    # Extract price
    price = snapshot.get("mid_price") or metrics.get("price")
    if not price:
        return None
    
    ts = event["ts"]
    timestamp = ts.timestamp() if hasattr(ts, "timestamp") else float(ts)
    hour_utc = ts.hour if hasattr(ts, "hour") else 12
    
    # Determine session based on hour
    if 0 <= hour_utc < 8:
        session = "asia"
    elif 8 <= hour_utc < 14:
        session = "europe"
    elif 14 <= hour_utc < 21:
        session = "us"
    else:
        session = "overnight"
    
    # Extract market data
    spread_bps = snapshot.get("spread_bps", 5.0)
    bid_depth_usd = metrics.get("bid_depth_usd", 50000.0)
    ask_depth_usd = metrics.get("ask_depth_usd", 50000.0)
    
    # Extract trend/volatility data
    trend_direction = snapshot.get("trend_direction", "flat")
    trend_strength = snapshot.get("trend_strength", 0.001)
    vol_regime = snapshot.get("vol_regime", "normal")
    
    # Extract regime
    market_regime = snapshot.get("market_regime") or metrics.get("regime_label", "range")
    
    # Calculate liquidity score
    total_depth = bid_depth_usd + ask_depth_usd
    liquidity_score = min(1.0, total_depth / 200000.0)
    
    # Estimate expected cost
    expected_cost_bps = spread_bps / 2 + 5.5  # Half spread + taker fee
    
    return ContextVector(
        symbol=symbol,
        timestamp=timestamp,
        price=price,
        trend_direction=trend_direction,
        trend_strength=trend_strength,
        volatility_regime=vol_regime,
        atr_ratio=snapshot.get("atr_ratio", 1.0),
        position_in_value=snapshot.get("position_in_value", "inside"),
        rotation_factor=snapshot.get("rotation_factor", 0.0),
        spread_bps=spread_bps,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        trades_per_second=metrics.get("trades_per_second", 1.0),
        session=session,
        hour_utc=hour_utc,
        market_regime=market_regime,
        risk_mode="normal",
        expected_cost_bps=expected_cost_bps,
        liquidity_score=liquidity_score,
        data_completeness=snapshot.get("data_quality_score", 1.0),
    )


async def run_backtest():
    """Run the backtest."""
    print("\n" + "="*70)
    print("Profile Router v2 Backtest with Real Data")
    print("="*70)
    
    # Register canonical profiles
    print("\nRegistering canonical profiles...")
    register_canonical_profiles()
    
    registry = get_profile_registry()
    profile_count = len(registry.list_specs())
    print(f"Registered {profile_count} profiles")
    
    # Create router
    print("\nInitializing Profile Router v2...")
    router = ProfileRouter()
    
    # Connect to TimescaleDB
    print("\nConnecting to TimescaleDB...")
    db_url = os.getenv("BOT_TIMESCALE_URL", "postgresql://quantgambit:quantgambit_pw@localhost:5433/quantgambit_bot")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    
    # Fetch events for the last 24 hours
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=24)
    symbol = "BTCUSDT"
    
    print(f"\nFetching decision events for {symbol}...")
    print(f"  Start: {start_time}")
    print(f"  End: {end_time}")
    
    events = await fetch_decision_events(
        pool=pool,
        symbol=symbol,
        start_time=start_time,
        end_time=end_time,
        sample_every=100,  # Sample every 100th event
        limit=5000,
    )
    
    print(f"Fetched {len(events)} events")
    
    if not events:
        print("No events found!")
        await pool.close()
        return 1
    
    # Run profile selection on each event
    print("\n" + "-"*70)
    print("Running Profile Selection...")
    print("-"*70)
    
    results = {
        "total_events": len(events),
        "profiles_selected": 0,
        "no_profiles": 0,
        "context_build_failed": 0,
        "profile_distribution": {},
        "session_distribution": {},
        "regime_distribution": {},
        "stability_switches": 0,
    }
    
    last_profile = None
    
    for i, event in enumerate(events):
        # Build context
        context = build_context_from_event(event, symbol)
        if not context:
            results["context_build_failed"] += 1
            continue
        
        # Track session and regime distribution
        results["session_distribution"][context.session] = results["session_distribution"].get(context.session, 0) + 1
        results["regime_distribution"][context.market_regime] = results["regime_distribution"].get(context.market_regime, 0) + 1
        
        # Select profiles
        profiles = router.select_profiles(context, top_k=3, symbol=symbol)
        
        if profiles:
            results["profiles_selected"] += 1
            top_profile = profiles[0]
            profile_id = top_profile.profile_id
            
            # Track profile distribution
            results["profile_distribution"][profile_id] = results["profile_distribution"].get(profile_id, 0) + 1
            
            # Track stability
            if last_profile and last_profile != profile_id:
                results["stability_switches"] += 1
            last_profile = profile_id
        else:
            results["no_profiles"] += 1
            last_profile = None
        
        # Progress indicator
        if (i + 1) % 500 == 0:
            print(f"  Processed {i + 1}/{len(events)} events...")
    
    await pool.close()
    
    # Summary
    print("\n" + "="*70)
    print("Backtest Results Summary")
    print("="*70)
    
    valid_events = results["total_events"] - results["context_build_failed"]
    print(f"\nTotal Events: {results['total_events']}")
    print(f"Valid Events: {valid_events}")
    print(f"Context Build Failed: {results['context_build_failed']}")
    
    if valid_events > 0:
        selection_rate = results['profiles_selected'] / valid_events * 100
        print(f"\nProfiles Selected: {results['profiles_selected']} ({selection_rate:.1f}%)")
        print(f"No Profiles: {results['no_profiles']} ({results['no_profiles']/valid_events*100:.1f}%)")
        print(f"Profile Switches: {results['stability_switches']}")
        
        if results['stability_switches'] > 0:
            avg_duration = valid_events / results['stability_switches']
            print(f"Average Profile Duration: {avg_duration:.1f} events")
    
    print(f"\nSession Distribution:")
    for session, count in sorted(results["session_distribution"].items()):
        pct = count / valid_events * 100 if valid_events > 0 else 0
        print(f"  {session}: {count} ({pct:.1f}%)")
    
    print(f"\nRegime Distribution:")
    for regime, count in sorted(results["regime_distribution"].items()):
        pct = count / valid_events * 100 if valid_events > 0 else 0
        print(f"  {regime}: {count} ({pct:.1f}%)")
    
    print(f"\nProfile Distribution (top 10):")
    sorted_profiles = sorted(results["profile_distribution"].items(), key=lambda x: x[1], reverse=True)
    for profile_id, count in sorted_profiles[:10]:
        pct = count / results['profiles_selected'] * 100 if results['profiles_selected'] > 0 else 0
        print(f"  {profile_id}: {count} ({pct:.1f}%)")
    
    # Validation
    print("\n" + "="*70)
    print("Validation")
    print("="*70)
    
    issues = []
    
    if valid_events > 0:
        selection_rate = results['profiles_selected'] / valid_events
        if selection_rate < 0.5:
            issues.append(f"Low profile selection rate: {selection_rate*100:.1f}% (expected > 50%)")
        else:
            print(f"✓ Profile selection rate: {selection_rate*100:.1f}%")
        
        switch_rate = results['stability_switches'] / valid_events if valid_events > 0 else 0
        if switch_rate > 0.3:
            issues.append(f"High switch rate: {switch_rate*100:.1f}% (expected < 30%)")
        else:
            print(f"✓ Profile switch rate: {switch_rate*100:.1f}%")
        
        unique_profiles = len(results["profile_distribution"])
        if unique_profiles < 3:
            issues.append(f"Low profile diversity: {unique_profiles} unique profiles (expected > 3)")
        else:
            print(f"✓ Profile diversity: {unique_profiles} unique profiles")
    
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
    return asyncio.run(run_backtest())


if __name__ == "__main__":
    sys.exit(main())
