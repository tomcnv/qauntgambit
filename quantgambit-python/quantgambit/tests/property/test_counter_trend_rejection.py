"""Property-based tests for counter-trend signal rejection.

Feature: backtest-pipeline-unification, Property 3: Counter-Trend Signal Rejection

Tests that:
- mean_reversion short in uptrend → rejected
- mean_reversion long in downtrend → rejected

Validates: Requirements 2.3
"""

import pytest
from hypothesis import given, strategies as st, settings

from quantgambit.signals.stages.strategy_trend_alignment import (
    StrategyTrendAlignmentStage,
    StrategyTrendAlignmentConfig,
    STRATEGY_TREND_RULES,
)
from quantgambit.signals.pipeline import StageContext, StageResult


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Generate price values
price_strategy = st.floats(min_value=1000.0, max_value=200000.0, allow_nan=False, allow_infinity=False)

# Generate signal sides
side_strategy = st.sampled_from(["long", "short"])

# Generate trend directions
trend_strategy = st.sampled_from(["up", "down", "flat"])

# Generate strategy IDs
strategy_id_strategy = st.sampled_from(["mean_reversion_fade", "trend_following", "unknown_strategy"])


def create_stage_context(
    symbol: str,
    strategy_id: str,
    signal_side: str,
    trend_direction: str,
    trend_strength: float = 0.5,
) -> StageContext:
    """Create a StageContext with the given parameters."""
    ctx = StageContext(
        symbol=symbol,
        data={
            "features": {
                "symbol": symbol,
                "price": 50000.0,
            },
            "market_context": {
                "trend_direction": trend_direction,
                "trend_strength": trend_strength,
                "volatility_regime": "normal",
            },
            "strategy_id": strategy_id,
        },
    )
    
    # Set signal with strategy_id and side
    ctx.signal = {
        "strategy_id": strategy_id,
        "side": signal_side,
        "symbol": symbol,
        "size": 0.1,
        "entry_price": 50000.0,
    }
    
    return ctx


# =============================================================================
# Property Tests
# =============================================================================

class TestCounterTrendRejectionProperties:
    """Property-based tests for counter-trend signal rejection.
    
    Feature: backtest-pipeline-unification, Property 3: Counter-Trend Signal Rejection
    """
    
    @given(
        price=price_strategy,
        trend_strength=st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_mean_reversion_short_rejected_in_uptrend(
        self,
        price: float,
        trend_strength: float,
    ):
        """Property: mean_reversion short in uptrend → rejected.
        
        For any mean_reversion_fade strategy signal with side="short" in a market
        with trend_direction="up", the StrategyTrendAlignmentStage SHALL reject.
        
        Validates: Requirements 2.3
        """
        stage = StrategyTrendAlignmentStage()
        
        ctx = create_stage_context(
            symbol="BTCUSDT",
            strategy_id="mean_reversion_fade",
            signal_side="short",
            trend_direction="up",
            trend_strength=trend_strength,
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.REJECT, (
            f"Expected REJECT for mean_reversion short in uptrend, got {result}"
        )
        assert ctx.rejection_reason == "strategy_trend_mismatch"
        assert "mean_reversion_short_in_uptrend" in str(ctx.rejection_detail)
    
    @given(
        price=price_strategy,
        trend_strength=st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_mean_reversion_long_rejected_in_downtrend(
        self,
        price: float,
        trend_strength: float,
    ):
        """Property: mean_reversion long in downtrend → rejected.
        
        For any mean_reversion_fade strategy signal with side="long" in a market
        with trend_direction="down", the StrategyTrendAlignmentStage SHALL reject.
        
        Validates: Requirements 2.3
        """
        stage = StrategyTrendAlignmentStage()
        
        ctx = create_stage_context(
            symbol="BTCUSDT",
            strategy_id="mean_reversion_fade",
            signal_side="long",
            trend_direction="down",
            trend_strength=trend_strength,
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.REJECT, (
            f"Expected REJECT for mean_reversion long in downtrend, got {result}"
        )
        assert ctx.rejection_reason == "strategy_trend_mismatch"
        assert "mean_reversion_long_in_downtrend" in str(ctx.rejection_detail)
    
    @given(
        price=price_strategy,
        trend_strength=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_mean_reversion_allowed_in_flat_market(
        self,
        price: float,
        trend_strength: float,
    ):
        """Property: mean_reversion signals allowed in flat market.
        
        For any mean_reversion_fade strategy signal in a flat market,
        the StrategyTrendAlignmentStage SHALL allow (CONTINUE).
        
        Validates: Requirements 2.3
        """
        stage = StrategyTrendAlignmentStage()
        
        # Test both long and short in flat market
        for side in ["long", "short"]:
            ctx = create_stage_context(
                symbol="BTCUSDT",
                strategy_id="mean_reversion_fade",
                signal_side=side,
                trend_direction="flat",
                trend_strength=trend_strength,
            )
            
            result = await stage.run(ctx)
            
            assert result == StageResult.CONTINUE, (
                f"Expected CONTINUE for mean_reversion {side} in flat market, got {result}"
            )
    
    @given(
        price=price_strategy,
        trend_strength=st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_mean_reversion_long_allowed_in_uptrend(
        self,
        price: float,
        trend_strength: float,
    ):
        """Property: mean_reversion long allowed in uptrend.
        
        Mean reversion long in uptrend is not counter-trend (buying dips in uptrend).
        
        Validates: Requirements 2.3
        """
        stage = StrategyTrendAlignmentStage()
        
        ctx = create_stage_context(
            symbol="BTCUSDT",
            strategy_id="mean_reversion_fade",
            signal_side="long",
            trend_direction="up",
            trend_strength=trend_strength,
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE, (
            f"Expected CONTINUE for mean_reversion long in uptrend, got {result}"
        )
    
    @given(
        price=price_strategy,
        trend_strength=st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_mean_reversion_short_allowed_in_downtrend(
        self,
        price: float,
        trend_strength: float,
    ):
        """Property: mean_reversion short allowed in downtrend.
        
        Mean reversion short in downtrend is not counter-trend (selling rallies in downtrend).
        
        Validates: Requirements 2.3
        """
        stage = StrategyTrendAlignmentStage()
        
        ctx = create_stage_context(
            symbol="BTCUSDT",
            strategy_id="mean_reversion_fade",
            signal_side="short",
            trend_direction="down",
            trend_strength=trend_strength,
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE, (
            f"Expected CONTINUE for mean_reversion short in downtrend, got {result}"
        )
    
    @given(
        price=price_strategy,
        side=side_strategy,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trend_following_rejected_in_flat_market(
        self,
        price: float,
        side: str,
    ):
        """Property: trend_following signals rejected in flat market.
        
        For any trend_following strategy signal in a flat market,
        the StrategyTrendAlignmentStage SHALL reject.
        
        Validates: Requirements 2.3
        """
        stage = StrategyTrendAlignmentStage()
        
        ctx = create_stage_context(
            symbol="BTCUSDT",
            strategy_id="trend_following",
            signal_side=side,
            trend_direction="flat",
            trend_strength=0.0,
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.REJECT, (
            f"Expected REJECT for trend_following {side} in flat market, got {result}"
        )
    
    @given(
        price=price_strategy,
        side=side_strategy,
        trend=st.sampled_from(["up", "down"]),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_unknown_strategy_allowed(
        self,
        price: float,
        side: str,
        trend: str,
    ):
        """Property: Unknown strategies are allowed through.
        
        For any strategy not in STRATEGY_TREND_RULES, signals SHALL be allowed.
        """
        stage = StrategyTrendAlignmentStage()
        
        ctx = create_stage_context(
            symbol="BTCUSDT",
            strategy_id="unknown_strategy",
            signal_side=side,
            trend_direction=trend,
            trend_strength=0.5,
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE, (
            f"Expected CONTINUE for unknown strategy, got {result}"
        )


# =============================================================================
# Unit Tests for Edge Cases
# =============================================================================

class TestCounterTrendRejectionEdgeCases:
    """Unit tests for edge cases."""
    
    @pytest.mark.asyncio
    async def test_no_signal_continues(self):
        """No signal should continue without rejection."""
        stage = StrategyTrendAlignmentStage()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": {"symbol": "BTCUSDT", "price": 50000.0},
                "market_context": {"trend_direction": "up"},
            },
        )
        ctx.signal = None
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
    
    @pytest.mark.asyncio
    async def test_no_strategy_id_continues(self):
        """Signal without strategy_id should continue."""
        stage = StrategyTrendAlignmentStage()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": {"symbol": "BTCUSDT", "price": 50000.0},
                "market_context": {"trend_direction": "up"},
            },
        )
        ctx.signal = {"side": "short", "size": 0.1}  # No strategy_id
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
    
    @pytest.mark.asyncio
    async def test_rejection_detail_contains_info(self):
        """Rejection should include detailed information."""
        stage = StrategyTrendAlignmentStage()
        
        ctx = create_stage_context(
            symbol="BTCUSDT",
            strategy_id="mean_reversion_fade",
            signal_side="short",
            trend_direction="up",
            trend_strength=0.8,
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.REJECT
        assert ctx.rejection_detail is not None
        assert ctx.rejection_detail["strategy_id"] == "mean_reversion_fade"
        assert ctx.rejection_detail["signal_side"] == "short"
        assert ctx.rejection_detail["trend"] == "up"
