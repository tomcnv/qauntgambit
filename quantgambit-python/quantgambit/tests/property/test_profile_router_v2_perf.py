"""
Property-based tests for Profile Router v2 Performance Adjustment.

Feature: profile-router-v2, Properties 14-15: Performance Adjustment Safety
Validates: Requirements 7.1, 7.2, 7.3, 7.5

Tests that:
- Property 14: Performance multiplier is bounded to [0.7, 1.3] for profiles with
  sufficient history, and exactly 1.0 for profiles with < 20 trades.
- Property 15: Older trades have exponentially decaying weight with half-life of
  50 trades. A trade 50 trades ago has approximately half the weight of the most
  recent trade.
"""

import math
import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import List, Tuple

from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Symbol names
symbols = st.sampled_from(["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT"])

# Profile IDs
profile_ids = st.sampled_from([
    "momentum_btc_high_vol",
    "mean_revert_eth_low_vol",
    "breakout_sol_normal",
    "fade_doge_asia",
    "trend_follow_btc_us",
])

# Sessions
sessions = st.sampled_from(["asia", "europe", "us", "overnight"])

# PnL values (positive = win, negative = loss)
pnl_values = st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# Trade counts
trade_counts = st.integers(min_value=0, max_value=100)

# Win rates (0.0 to 1.0)
win_rates = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@st.composite
def trade_sequences(draw, min_trades: int = 0, max_trades: int = 100) -> List[Tuple[float, bool]]:
    """
    Generate a sequence of trades as (pnl, is_win) tuples.
    """
    num_trades = draw(st.integers(min_value=min_trades, max_value=max_trades))
    trades = []
    for _ in range(num_trades):
        is_win = draw(st.booleans())
        if is_win:
            pnl = draw(st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False))
        else:
            pnl = draw(st.floats(min_value=-100.0, max_value=-0.01, allow_nan=False, allow_infinity=False))
        trades.append((pnl, is_win))
    return trades


@st.composite
def router_configs_for_perf(draw) -> RouterConfig:
    """Generate RouterConfig with valid performance adjustment parameters."""
    min_trades = draw(st.integers(min_value=5, max_value=50))
    min_mult = draw(st.floats(min_value=0.3, max_value=0.9, allow_nan=False, allow_infinity=False))
    max_mult = draw(st.floats(min_value=min_mult + 0.1, max_value=2.0, allow_nan=False, allow_infinity=False))
    half_life = draw(st.integers(min_value=10, max_value=100))
    
    return RouterConfig(
        min_trades_for_perf_adjustment=min_trades,
        perf_multiplier_range=(min_mult, max_mult),
        perf_decay_half_life_trades=half_life,
    )


# ============================================================================
# Property Tests
# ============================================================================

class TestPerformanceMultiplierBounds:
    """
    Property 14: Performance Multiplier Bounds
    
    For any profile with performance history, the performance multiplier SHALL be
    in range [0.7, 1.3]. For profiles with fewer than 20 trades, the multiplier
    SHALL be exactly 1.0.
    
    **Feature: profile-router-v2, Property 14: Performance Multiplier Bounds**
    **Validates: Requirements 7.1, 7.2, 7.5**
    """
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
        session=sessions,
        trades=trade_sequences(min_trades=0, max_trades=19),
    )
    @settings(max_examples=100)
    def test_neutral_multiplier_for_insufficient_trades(
        self,
        profile_id: str,
        symbol: str,
        session: str,
        trades: List[Tuple[float, bool]],
    ):
        """
        Property 14: Performance Multiplier Bounds
        
        For any profile with fewer than 20 trades, the multiplier SHALL be exactly 1.0.
        
        **Validates: Requirements 7.1, 7.5**
        """
        config = RouterConfig()  # Default: min_trades=20
        router = ProfileRouter(config=config)
        
        # Record trades
        for pnl, _ in trades:
            router.record_trade(profile_id, symbol, pnl, session)
        
        # Get multiplier
        multiplier = router._get_performance_multiplier(profile_id, symbol, session)
        
        # Should be exactly 1.0 for < 20 trades
        assert multiplier == 1.0, \
            f"Expected 1.0 for {len(trades)} trades (< 20), got {multiplier}"
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
        session=sessions,
        trades=trade_sequences(min_trades=20, max_trades=100),
    )
    @settings(max_examples=100)
    def test_multiplier_bounded_for_sufficient_trades(
        self,
        profile_id: str,
        symbol: str,
        session: str,
        trades: List[Tuple[float, bool]],
    ):
        """
        Property 14: Performance Multiplier Bounds
        
        For any profile with >= 20 trades, the multiplier SHALL be in [0.7, 1.3].
        
        **Validates: Requirements 7.2**
        """
        config = RouterConfig()  # Default: range=(0.7, 1.3)
        router = ProfileRouter(config=config)
        
        # Record trades
        for pnl, _ in trades:
            router.record_trade(profile_id, symbol, pnl, session)
        
        # Get multiplier
        multiplier = router._get_performance_multiplier(profile_id, symbol, session)
        
        # Should be in [0.7, 1.3]
        min_mult, max_mult = config.perf_multiplier_range
        assert min_mult <= multiplier <= max_mult, \
            f"Multiplier {multiplier} outside bounds [{min_mult}, {max_mult}] for {len(trades)} trades"
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
        session=sessions,
        num_trades=st.integers(min_value=25, max_value=100),
    )
    @settings(max_examples=100)
    def test_all_wins_gives_high_multiplier(
        self,
        profile_id: str,
        symbol: str,
        session: str,
        num_trades: int,
    ):
        """
        Property 14: Performance Multiplier Bounds
        
        For any profile with all winning trades, the multiplier SHALL be at or near
        the upper bound.
        
        **Validates: Requirements 7.2**
        """
        config = RouterConfig()
        router = ProfileRouter(config=config)
        
        # Record all winning trades
        for _ in range(num_trades):
            router.record_trade(profile_id, symbol, 10.0, session)  # All wins
        
        # Get multiplier
        multiplier = router._get_performance_multiplier(profile_id, symbol, session)
        
        # Should be at or near upper bound (1.3)
        # Allow some tolerance for PnL bonus
        min_mult, max_mult = config.perf_multiplier_range
        assert multiplier >= max_mult - 0.1, \
            f"All wins should give high multiplier, got {multiplier}"
        assert multiplier <= max_mult, \
            f"Multiplier {multiplier} exceeds upper bound {max_mult}"
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
        session=sessions,
        num_trades=st.integers(min_value=25, max_value=100),
    )
    @settings(max_examples=100)
    def test_all_losses_gives_low_multiplier(
        self,
        profile_id: str,
        symbol: str,
        session: str,
        num_trades: int,
    ):
        """
        Property 14: Performance Multiplier Bounds
        
        For any profile with all losing trades, the multiplier SHALL be at or near
        the lower bound.
        
        **Validates: Requirements 7.2**
        """
        config = RouterConfig()
        router = ProfileRouter(config=config)
        
        # Record all losing trades
        for _ in range(num_trades):
            router.record_trade(profile_id, symbol, -10.0, session)  # All losses
        
        # Get multiplier
        multiplier = router._get_performance_multiplier(profile_id, symbol, session)
        
        # Should be at or near lower bound (0.7)
        min_mult, max_mult = config.perf_multiplier_range
        assert multiplier <= min_mult + 0.1, \
            f"All losses should give low multiplier, got {multiplier}"
        assert multiplier >= min_mult, \
            f"Multiplier {multiplier} below lower bound {min_mult}"
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
        session=sessions,
        config=router_configs_for_perf(),
        trades=trade_sequences(min_trades=50, max_trades=100),
    )
    @settings(max_examples=100)
    def test_multiplier_respects_config_bounds(
        self,
        profile_id: str,
        symbol: str,
        session: str,
        config: RouterConfig,
        trades: List[Tuple[float, bool]],
    ):
        """
        Property 14: Performance Multiplier Bounds
        
        For any RouterConfig, the multiplier SHALL respect the configured bounds.
        
        **Validates: Requirements 7.2**
        """
        router = ProfileRouter(config=config)
        
        # Record trades
        for pnl, _ in trades:
            router.record_trade(profile_id, symbol, pnl, session)
        
        # Get multiplier
        multiplier = router._get_performance_multiplier(profile_id, symbol, session)
        
        # Check if we have enough trades
        min_trades = config.min_trades_for_perf_adjustment
        if len(trades) < min_trades:
            assert multiplier == 1.0, \
                f"Expected 1.0 for {len(trades)} trades < {min_trades}"
        else:
            min_mult, max_mult = config.perf_multiplier_range
            assert min_mult <= multiplier <= max_mult, \
                f"Multiplier {multiplier} outside configured bounds [{min_mult}, {max_mult}]"


class TestPerformanceDecay:
    """
    Property 15: Performance Decay
    
    For any profile with performance history, older trades SHALL have exponentially
    decaying weight with half-life of 50 trades. A trade 50 trades ago SHALL have
    approximately half the weight of the most recent trade.
    
    **Feature: profile-router-v2, Property 15: Performance Decay**
    **Validates: Requirements 7.3**
    """
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
        session=sessions,
    )
    @settings(max_examples=100)
    def test_recent_trades_have_more_weight(
        self,
        profile_id: str,
        symbol: str,
        session: str,
    ):
        """
        Property 15: Performance Decay
        
        Recent trades SHALL have more weight than older trades.
        
        **Validates: Requirements 7.3**
        """
        config = RouterConfig()
        
        # Both scenarios have the same total wins (25) and losses (25)
        # but in different order
        
        # Scenario 1: 25 losses first (older), then 25 wins (more recent)
        router1 = ProfileRouter(config=config)
        for _ in range(25):
            router1.record_trade(profile_id, symbol, -10.0, session)  # Old losses
        for _ in range(25):
            router1.record_trade(profile_id, symbol, 10.0, session)  # Recent wins
        mult1 = router1._get_performance_multiplier(profile_id, symbol, session)
        
        # Scenario 2: 25 wins first (older), then 25 losses (more recent)
        router2 = ProfileRouter(config=config)
        for _ in range(25):
            router2.record_trade(profile_id, symbol, 10.0, session)  # Old wins
        for _ in range(25):
            router2.record_trade(profile_id, symbol, -10.0, session)  # Recent losses
        mult2 = router2._get_performance_multiplier(profile_id, symbol, session)
        
        # Scenario 1 (recent wins) should give higher multiplier than Scenario 2 (recent losses)
        # because recent trades have more weight due to exponential decay
        assert mult1 > mult2, \
            f"Recent wins scenario ({mult1}) should give higher multiplier than recent losses scenario ({mult2})"
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
        session=sessions,
        half_life=st.integers(min_value=20, max_value=100),
    )
    @settings(max_examples=100)
    def test_decay_half_life_effect(
        self,
        profile_id: str,
        symbol: str,
        session: str,
        half_life: int,
    ):
        """
        Property 15: Performance Decay
        
        A trade half_life trades ago SHALL have approximately half the weight
        of the most recent trade.
        
        **Validates: Requirements 7.3**
        """
        config = RouterConfig(
            min_trades_for_perf_adjustment=20,
            perf_decay_half_life_trades=half_life,
        )
        
        # Both scenarios have the same total wins and losses
        # but in different order to test decay effect
        num_trades = half_life + 20  # Ensure enough trades
        
        # Scenario 1: Half wins (older), then half losses (recent)
        router1 = ProfileRouter(config=config)
        for _ in range(num_trades // 2):
            router1.record_trade(profile_id, symbol, 10.0, session)  # Old wins
        for _ in range(num_trades - num_trades // 2):
            router1.record_trade(profile_id, symbol, -10.0, session)  # Recent losses
        
        # Scenario 2: Half losses (older), then half wins (recent)
        router2 = ProfileRouter(config=config)
        for _ in range(num_trades // 2):
            router2.record_trade(profile_id, symbol, -10.0, session)  # Old losses
        for _ in range(num_trades - num_trades // 2):
            router2.record_trade(profile_id, symbol, 10.0, session)  # Recent wins
        
        mult1 = router1._get_performance_multiplier(profile_id, symbol, session)
        mult2 = router2._get_performance_multiplier(profile_id, symbol, session)
        
        # Scenario 2 (recent wins) should have higher multiplier than Scenario 1 (recent losses)
        # because recent trades have more weight due to exponential decay
        assert mult2 > mult1, \
            f"Recent wins scenario ({mult2}) should have higher multiplier than recent losses scenario ({mult1})"
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
        session=sessions,
    )
    @settings(max_examples=100)
    def test_very_old_trades_have_minimal_weight(
        self,
        profile_id: str,
        symbol: str,
        session: str,
    ):
        """
        Property 15: Performance Decay
        
        Very old trades (many half-lives ago) SHALL have minimal weight.
        
        **Validates: Requirements 7.3**
        """
        config = RouterConfig(
            min_trades_for_perf_adjustment=20,
            perf_decay_half_life_trades=50,
        )
        
        # Scenario 1: 20 old losses, then 100 wins
        router1 = ProfileRouter(config=config)
        for _ in range(20):
            router1.record_trade(profile_id, symbol, -10.0, session)  # Old losses
        for _ in range(100):
            router1.record_trade(profile_id, symbol, 10.0, session)  # Recent wins
        
        # Scenario 2: 120 wins (no old losses)
        router2 = ProfileRouter(config=config)
        for _ in range(120):
            router2.record_trade(profile_id, symbol, 10.0, session)  # All wins
        
        mult1 = router1._get_performance_multiplier(profile_id, symbol, session)
        mult2 = router2._get_performance_multiplier(profile_id, symbol, session)
        
        # Old losses should have minimal impact after 100 trades (2 half-lives)
        # Multipliers should be close
        assert abs(mult1 - mult2) < 0.15, \
            f"Old losses should have minimal impact: mult1={mult1}, mult2={mult2}, diff={abs(mult1 - mult2)}"


class TestPerSessionTracking:
    """
    Tests for per-session performance tracking (Requirement 7.4).
    """
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
        session1=sessions,
        session2=sessions,
        trades1=trade_sequences(min_trades=25, max_trades=50),
        trades2=trade_sequences(min_trades=25, max_trades=50),
    )
    @settings(max_examples=100)
    def test_sessions_tracked_independently(
        self,
        profile_id: str,
        symbol: str,
        session1: str,
        session2: str,
        trades1: List[Tuple[float, bool]],
        trades2: List[Tuple[float, bool]],
    ):
        """
        Property 14: Performance Multiplier Bounds
        
        Performance SHALL be tracked independently per (profile_id, symbol, session).
        
        **Validates: Requirements 7.4**
        """
        assume(session1 != session2)
        
        config = RouterConfig()
        router = ProfileRouter(config=config)
        
        # Record different trades for different sessions
        for pnl, _ in trades1:
            router.record_trade(profile_id, symbol, pnl, session1)
        
        for pnl, _ in trades2:
            router.record_trade(profile_id, symbol, pnl, session2)
        
        # Get multipliers
        mult1 = router._get_performance_multiplier(profile_id, symbol, session1)
        mult2 = router._get_performance_multiplier(profile_id, symbol, session2)
        
        # Calculate expected win rates
        wins1 = sum(1 for _, is_win in trades1 if is_win)
        wins2 = sum(1 for _, is_win in trades2 if is_win)
        win_rate1 = wins1 / len(trades1) if trades1 else 0
        win_rate2 = wins2 / len(trades2) if trades2 else 0
        
        # If win rates are significantly different, multipliers should differ
        if abs(win_rate1 - win_rate2) > 0.3:
            # Multipliers should reflect the difference
            if win_rate1 > win_rate2:
                assert mult1 >= mult2 - 0.1, \
                    f"Session1 (win_rate={win_rate1:.2f}) should have higher mult than session2 (win_rate={win_rate2:.2f})"
            else:
                assert mult2 >= mult1 - 0.1, \
                    f"Session2 (win_rate={win_rate2:.2f}) should have higher mult than session1 (win_rate={win_rate1:.2f})"
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
        session=sessions,
    )
    @settings(max_examples=100)
    def test_untracked_session_returns_neutral(
        self,
        profile_id: str,
        symbol: str,
        session: str,
    ):
        """
        Property 14: Performance Multiplier Bounds
        
        For any session with no recorded trades, the multiplier SHALL be 1.0.
        
        **Validates: Requirements 7.4, 7.5**
        """
        config = RouterConfig()
        router = ProfileRouter(config=config)
        
        # Record trades for a different session
        other_session = "asia" if session != "asia" else "us"
        for _ in range(30):
            router.record_trade(profile_id, symbol, 10.0, other_session)
        
        # Get multiplier for untracked session
        multiplier = router._get_performance_multiplier(profile_id, symbol, session)
        
        assert multiplier == 1.0, \
            f"Untracked session should return 1.0, got {multiplier}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
