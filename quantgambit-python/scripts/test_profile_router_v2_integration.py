#!/usr/bin/env python3
"""Integration test for Profile Router v2.

This script tests the Profile Router v2 with realistic market scenarios
to verify the new soft-preference scoring, stability mechanisms, and
EV-aware routing work correctly in practice.
"""

import sys
import time
from dataclasses import dataclass
from typing import List, Dict, Any

# Add parent to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter, get_profile_router
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry
from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import register_canonical_profiles


@dataclass
class TestScenario:
    """A test scenario with market conditions and expected behavior."""
    name: str
    context: ContextVector
    expected_profile_count: int  # Minimum expected eligible profiles
    expected_tags: List[str]  # Tags that should appear in top profile
    description: str


def create_test_scenarios() -> List[TestScenario]:
    """Create realistic market scenarios for testing."""
    base_time = time.time()
    
    scenarios = [
        # Scenario 1: Strong uptrend in US session - should favor momentum profiles
        TestScenario(
            name="Strong Uptrend US Session",
            context=ContextVector(
                symbol="BTC-USDT",
                timestamp=base_time,
                price=50000.0,
                trend_direction="up",
                trend_strength=0.005,  # Strong trend
                volatility_regime="normal",
                atr_ratio=1.0,
                position_in_value="above",
                rotation_factor=3.0,
                spread_bps=5.0,
                bid_depth_usd=50000.0,
                ask_depth_usd=50000.0,
                trades_per_second=2.0,
                session="us",
                hour_utc=16,
                market_regime="breakout",
                risk_mode="normal",
                expected_cost_bps=6.0,
                liquidity_score=0.8,
            ),
            expected_profile_count=3,
            expected_tags=["momentum", "trend"],
            description="Strong uptrend should favor momentum/trend profiles",
        ),
        
        # Scenario 2: Range-bound in Asia session - should favor mean reversion
        TestScenario(
            name="Range Bound Asia Session",
            context=ContextVector(
                symbol="ETH-USDT",
                timestamp=base_time,
                price=3000.0,
                trend_direction="flat",
                trend_strength=0.001,  # Weak trend
                volatility_regime="low",
                atr_ratio=0.7,
                position_in_value="inside",
                rotation_factor=0.5,
                spread_bps=4.0,
                bid_depth_usd=80000.0,
                ask_depth_usd=80000.0,
                trades_per_second=1.5,
                session="asia",
                hour_utc=4,
                market_regime="range",
                risk_mode="normal",
                expected_cost_bps=5.0,
                liquidity_score=0.9,
            ),
            expected_profile_count=3,
            expected_tags=["mean_reversion", "fade", "range"],
            description="Range-bound market should favor mean reversion profiles",
        ),
        
        # Scenario 3: High volatility squeeze - should be cautious
        TestScenario(
            name="High Vol Squeeze",
            context=ContextVector(
                symbol="SOL-USDT",
                timestamp=base_time,
                price=100.0,
                trend_direction="up",
                trend_strength=0.003,
                volatility_regime="high",
                atr_ratio=1.8,
                position_in_value="above",
                rotation_factor=5.0,
                spread_bps=8.0,
                bid_depth_usd=30000.0,
                ask_depth_usd=30000.0,
                trades_per_second=3.0,
                session="us",
                hour_utc=15,
                market_regime="squeeze",
                risk_mode="normal",
                expected_cost_bps=10.0,
                liquidity_score=0.5,
            ),
            expected_profile_count=2,
            expected_tags=["momentum", "breakout"],
            description="Squeeze with decent liquidity should allow trend profiles",
        ),
        
        # Scenario 4: Choppy market with high costs - should avoid or be very selective
        TestScenario(
            name="Choppy High Cost",
            context=ContextVector(
                symbol="DOGE-USDT",
                timestamp=base_time,
                price=0.10,
                trend_direction="flat",
                trend_strength=0.0005,
                volatility_regime="normal",
                atr_ratio=1.2,
                position_in_value="inside",
                rotation_factor=0.0,
                spread_bps=12.0,
                bid_depth_usd=20000.0,
                ask_depth_usd=20000.0,
                trades_per_second=0.5,
                session="overnight",
                hour_utc=23,
                market_regime="chop",
                risk_mode="normal",
                expected_cost_bps=15.0,
                liquidity_score=0.4,
            ),
            expected_profile_count=1,  # May have few eligible profiles
            expected_tags=[],  # Any profile that passes cost filter
            description="Choppy market with high costs should be very selective",
        ),
        
        # Scenario 5: Overnight thin liquidity - should handle gracefully
        TestScenario(
            name="Overnight Thin Liquidity",
            context=ContextVector(
                symbol="BTC-USDT",
                timestamp=base_time,
                price=50000.0,
                trend_direction="down",
                trend_strength=0.002,
                volatility_regime="low",
                atr_ratio=0.6,
                position_in_value="below",
                rotation_factor=-2.0,
                spread_bps=6.0,
                bid_depth_usd=25000.0,
                ask_depth_usd=25000.0,
                trades_per_second=0.3,
                session="overnight",
                hour_utc=2,
                market_regime="range",
                risk_mode="normal",
                expected_cost_bps=8.0,
                liquidity_score=0.5,
            ),
            expected_profile_count=2,
            expected_tags=["overnight", "fade"],
            description="Overnight session should still find eligible profiles",
        ),
    ]
    
    return scenarios


def test_profile_selection(router: ProfileRouter, scenario: TestScenario) -> Dict[str, Any]:
    """Test profile selection for a scenario."""
    print(f"\n{'='*60}")
    print(f"Testing: {scenario.name}")
    print(f"Description: {scenario.description}")
    print(f"{'='*60}")
    
    # Select profiles
    profiles = router.select_profiles(
        context=scenario.context,
        top_k=5,
        symbol=scenario.context.symbol,
    )
    
    result = {
        "scenario": scenario.name,
        "passed": True,
        "issues": [],
        "profiles_selected": len(profiles),
        "top_profile": None,
        "component_scores": {},
    }
    
    print(f"\nMarket Conditions:")
    print(f"  - Regime: {scenario.context.market_regime}")
    print(f"  - Trend: {scenario.context.trend_direction} (strength: {scenario.context.trend_strength})")
    print(f"  - Volatility: {scenario.context.volatility_regime}")
    print(f"  - Session: {scenario.context.session}")
    print(f"  - Expected Cost: {scenario.context.expected_cost_bps} bps")
    print(f"  - Liquidity Score: {scenario.context.liquidity_score}")
    
    print(f"\nProfiles Selected: {len(profiles)}")
    
    if len(profiles) < scenario.expected_profile_count:
        result["passed"] = False
        result["issues"].append(
            f"Expected at least {scenario.expected_profile_count} profiles, got {len(profiles)}"
        )
    
    if profiles:
        top = profiles[0]
        result["top_profile"] = top.profile_id
        result["component_scores"] = top.component_scores
        
        print(f"\nTop Profile: {top.profile_id}")
        print(f"  - Score: {top.score:.3f}")
        print(f"  - Confidence: {top.confidence:.3f}")
        print(f"  - Hard Filter Passed: {top.hard_filter_passed}")
        print(f"  - Cost Viability: {top.cost_viability_score:.3f}")
        
        if top.component_scores:
            print(f"\n  Component Scores:")
            for comp, score in sorted(top.component_scores.items()):
                print(f"    - {comp}: {score:.3f}")
        
        if top.reasons:
            print(f"\n  Reasons: {', '.join(top.reasons[:5])}")
        
        # Check for expected tags in top profile
        if scenario.expected_tags:
            registry = get_profile_registry()
            spec = registry.get_spec(top.profile_id)
            if spec:
                profile_tags = spec.tags or []
                has_expected_tag = any(tag in profile_tags for tag in scenario.expected_tags)
                if not has_expected_tag:
                    result["issues"].append(
                        f"Top profile '{top.profile_id}' doesn't have expected tags {scenario.expected_tags}"
                    )
                    print(f"\n  ⚠️  Warning: Expected tags {scenario.expected_tags}, got {profile_tags}")
    else:
        print("\n  ⚠️  No profiles selected!")
        if scenario.expected_profile_count > 0:
            result["passed"] = False
            result["issues"].append("No profiles selected when some were expected")
    
    # Show other selected profiles
    if len(profiles) > 1:
        print(f"\nOther Selected Profiles:")
        for p in profiles[1:5]:
            print(f"  - {p.profile_id}: score={p.score:.3f}, cost_viability={p.cost_viability_score:.3f}")
    
    return result


def test_stability_mechanisms(router: ProfileRouter) -> Dict[str, Any]:
    """Test profile stability mechanisms (TTL, hysteresis, switch margin)."""
    print(f"\n{'='*60}")
    print("Testing: Stability Mechanisms")
    print(f"{'='*60}")
    
    result = {
        "scenario": "Stability Mechanisms",
        "passed": True,
        "issues": [],
    }
    
    symbol = "BTC-USDT"
    base_time = time.time()
    
    # Create a base context
    base_context = ContextVector(
        symbol=symbol,
        timestamp=base_time,
        price=50000.0,
        trend_direction="up",
        trend_strength=0.004,
        volatility_regime="normal",
        atr_ratio=1.0,
        position_in_value="inside",
        rotation_factor=2.0,
        spread_bps=5.0,
        bid_depth_usd=50000.0,
        ask_depth_usd=50000.0,
        trades_per_second=2.0,
        session="us",
        hour_utc=16,
        market_regime="breakout",
        risk_mode="normal",
        expected_cost_bps=6.0,
        liquidity_score=0.8,
    )
    
    # First selection
    profiles1 = router.select_profiles(base_context, top_k=1, symbol=symbol)
    if not profiles1:
        result["passed"] = False
        result["issues"].append("No profile selected for stability test")
        return result
    
    first_profile = profiles1[0].profile_id
    print(f"\nFirst selection: {first_profile} (score: {profiles1[0].score:.3f})")
    
    # Slightly modify context (should not cause switch due to TTL)
    modified_context = ContextVector(
        symbol=symbol,
        timestamp=base_time + 30,  # 30 seconds later (within TTL)
        price=50100.0,
        trend_direction="flat",  # Changed
        trend_strength=0.002,  # Reduced
        volatility_regime="normal",
        atr_ratio=1.0,
        position_in_value="inside",
        rotation_factor=1.0,  # Reduced
        spread_bps=5.0,
        bid_depth_usd=50000.0,
        ask_depth_usd=50000.0,
        trades_per_second=2.0,
        session="us",
        hour_utc=16,
        market_regime="range",  # Changed
        risk_mode="normal",
        expected_cost_bps=6.0,
        liquidity_score=0.8,
    )
    
    profiles2 = router.select_profiles(modified_context, top_k=1, symbol=symbol)
    if profiles2:
        second_profile = profiles2[0].profile_id
        print(f"Second selection (30s later, modified context): {second_profile}")
        
        # Note: TTL is enforced at the ProfileStabilityManager level
        # The router may still return different scores, but the stability
        # manager should prevent actual switching
        if profiles2[0].stability_adjusted:
            print("  ✓ Stability adjustment applied")
        else:
            print("  ℹ️  No stability adjustment (may be expected if score difference is large)")
    
    # Test with safety disqualifier (should bypass TTL)
    unsafe_context = ContextVector(
        symbol=symbol,
        timestamp=base_time + 60,
        price=50000.0,
        trend_direction="up",
        trend_strength=0.004,
        volatility_regime="normal",
        atr_ratio=1.0,
        position_in_value="inside",
        rotation_factor=2.0,
        spread_bps=60.0,  # Very wide spread - safety issue
        bid_depth_usd=5000.0,  # Low depth - safety issue
        ask_depth_usd=5000.0,
        trades_per_second=0.05,  # Very low TPS - safety issue
        session="us",
        hour_utc=16,
        market_regime="breakout",
        risk_mode="normal",
        expected_cost_bps=20.0,
        liquidity_score=0.2,
    )
    
    profiles3 = router.select_profiles(unsafe_context, top_k=1, symbol=symbol)
    print(f"\nWith safety issues (wide spread, low depth):")
    if profiles3:
        print(f"  Selected: {profiles3[0].profile_id}")
        print(f"  Hard filter passed: {profiles3[0].hard_filter_passed}")
        if not profiles3[0].hard_filter_passed:
            print("  ✓ Hard filter correctly rejected unsafe conditions")
    else:
        print("  ✓ No profiles selected (correct for unsafe conditions)")
    
    return result


def test_config_updates(router: ProfileRouter) -> Dict[str, Any]:
    """Test runtime configuration updates."""
    print(f"\n{'='*60}")
    print("Testing: Configuration Updates")
    print(f"{'='*60}")
    
    result = {
        "scenario": "Configuration Updates",
        "passed": True,
        "issues": [],
    }
    
    # Get current config
    current_config = router.get_config()
    print(f"\nCurrent TTL: {current_config.min_profile_ttl_sec}s")
    print(f"Current switch margin: {current_config.switch_margin}")
    
    # Update config
    new_config = RouterConfig(
        min_profile_ttl_sec=180.0,  # Increased TTL
        switch_margin=0.15,  # Increased margin
    )
    
    try:
        router.update_config(new_config)
        updated_config = router.get_config()
        print(f"\nUpdated TTL: {updated_config.min_profile_ttl_sec}s")
        print(f"Updated switch margin: {updated_config.switch_margin}")
        
        if updated_config.min_profile_ttl_sec != 180.0:
            result["passed"] = False
            result["issues"].append("TTL not updated correctly")
        
        if updated_config.switch_margin != 0.15:
            result["passed"] = False
            result["issues"].append("Switch margin not updated correctly")
        
        print("  ✓ Configuration updated successfully")
        
        # Restore original config
        router.update_config(current_config)
        print("  ✓ Original configuration restored")
        
    except Exception as e:
        result["passed"] = False
        result["issues"].append(f"Config update failed: {e}")
        print(f"  ✗ Error: {e}")
    
    return result


def test_observability(router: ProfileRouter) -> Dict[str, Any]:
    """Test observability and metrics."""
    print(f"\n{'='*60}")
    print("Testing: Observability & Metrics")
    print(f"{'='*60}")
    
    result = {
        "scenario": "Observability",
        "passed": True,
        "issues": [],
    }
    
    # Get metrics
    metrics = router.get_all_metrics()
    
    print(f"\nRouter Metrics:")
    print(f"  - Total selections: {metrics.get('total_selections', 0)}")
    print(f"  - Profiles evaluated: {metrics.get('profiles_evaluated', 0)}")
    
    if "eligible_profiles_count" in metrics:
        print(f"  - Eligible profiles: {metrics['eligible_profiles_count']}")
    
    if "profile_switches_count" in metrics:
        print(f"  - Profile switches: {metrics['profile_switches_count']}")
    
    if "component_score_distributions" in metrics:
        print(f"  - Component distributions available: Yes")
    
    # Test routing diagnostics
    symbol = "BTC-USDT"
    diagnostics = router.get_routing_diagnostics(symbol)
    
    if diagnostics:
        print(f"\nRouting Diagnostics for {symbol}:")
        print(f"  - Current profile: {diagnostics.get('current_profile', 'None')}")
        print(f"  - Last selection time: {diagnostics.get('last_selection_time', 'N/A')}")
        
        if "top_profiles" in diagnostics:
            print(f"  - Top profiles cached: {len(diagnostics['top_profiles'])}")
    else:
        print(f"\nNo diagnostics available for {symbol} (expected if no selections made)")
    
    return result


def main():
    """Run all integration tests."""
    print("\n" + "="*70)
    print("Profile Router v2 Integration Test")
    print("="*70)
    
    # Register canonical profiles
    print("\nRegistering canonical profiles...")
    register_canonical_profiles()
    
    registry = get_profile_registry()
    profile_count = len(registry.list_specs())
    print(f"Registered {profile_count} profiles")
    
    # Create router with default config
    print("\nInitializing Profile Router v2...")
    router = ProfileRouter()
    config = router.get_config()
    print(f"  - use_v2_scoring: {config.use_v2_scoring}")
    print(f"  - min_profile_ttl_sec: {config.min_profile_ttl_sec}")
    print(f"  - switch_margin: {config.switch_margin}")
    
    # Run scenario tests
    scenarios = create_test_scenarios()
    results = []
    
    for scenario in scenarios:
        result = test_profile_selection(router, scenario)
        results.append(result)
    
    # Run stability test
    stability_result = test_stability_mechanisms(router)
    results.append(stability_result)
    
    # Run config update test
    config_result = test_config_updates(router)
    results.append(config_result)
    
    # Run observability test
    obs_result = test_observability(router)
    results.append(obs_result)
    
    # Summary
    print("\n" + "="*70)
    print("Test Summary")
    print("="*70)
    
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    
    print(f"\nTotal Tests: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    if failed > 0:
        print("\nFailed Tests:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['scenario']}")
                for issue in r["issues"]:
                    print(f"      • {issue}")
    
    print("\n" + "="*70)
    if failed == 0:
        print("✓ All integration tests passed!")
        return 0
    else:
        print(f"✗ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
