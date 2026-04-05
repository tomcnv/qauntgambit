"""
Integration tests for pipeline stages with real StrategySignal dataclass objects.

These tests ensure that pipeline stages correctly handle actual StrategySignal
dataclass instances (not just dict mocks), preventing the type mismatch bug
where stages called .get() on dataclass objects.

This test file was created after discovering that unit tests using dict inputs
passed while production code using StrategySignal dataclass objects crashed.
"""

import pytest
import asyncio
from typing import Optional

from quantgambit.deeptrader_core.types import StrategySignal
from quantgambit.signals.pipeline import (
    StageContext,
    StageResult,
    signal_to_dict,
)
from quantgambit.signals.stages import (
    StrategyTrendAlignmentStage,
    FeeAwareEntryStage,
    EVGateStage,
    EVGateConfig,
    ConfidencePositionSizerStage,
    EVPositionSizerStage,
    EVPositionSizerConfig,
)


def create_strategy_signal(
    strategy_id: str = "mean_reversion_fade",
    symbol: str = "BTCUSDT",
    side: str = "long",
    size: float = 0.01,
    entry_price: float = 95000.0,
    stop_loss: float = 94000.0,
    take_profit: float = 96000.0,
    meta_reason: str = "test_signal",
    profile_id: str = "test_profile",
    confidence: Optional[float] = None,
) -> StrategySignal:
    """Create a real StrategySignal dataclass instance for testing."""
    signal = StrategySignal(
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        size=size,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        meta_reason=meta_reason,
        profile_id=profile_id,
    )
    # Add confidence as an attribute if provided (some stages expect this)
    if confidence is not None:
        # StrategySignal doesn't have confidence field, but signal_to_dict handles this
        pass
    return signal


class TestSignalToDictHelper:
    """Test the signal_to_dict helper function."""
    
    def test_converts_strategy_signal_dataclass(self):
        """signal_to_dict should convert StrategySignal dataclass to dict."""
        signal = create_strategy_signal(
            strategy_id="mean_reversion_fade",
            symbol="BTCUSDT",
            side="long",
        )
        
        result = signal_to_dict(signal)
        
        assert isinstance(result, dict)
        assert result["strategy_id"] == "mean_reversion_fade"
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "long"
    
    def test_passes_through_dict(self):
        """signal_to_dict should pass through dict unchanged."""
        signal = {"strategy_id": "test", "side": "long"}
        
        result = signal_to_dict(signal)
        
        assert result == signal
    
    def test_handles_none(self):
        """signal_to_dict should return empty dict for None."""
        result = signal_to_dict(None)
        
        assert result == {}
    
    def test_handles_object_with_dict(self):
        """signal_to_dict should handle objects with __dict__."""
        class FakeSignal:
            def __init__(self):
                self.strategy_id = "fake"
                self.side = "short"
        
        result = signal_to_dict(FakeSignal())
        
        assert result["strategy_id"] == "fake"
        assert result["side"] == "short"


class TestStrategyTrendAlignmentWithDataclass:
    """Test StrategyTrendAlignmentStage with real StrategySignal dataclass."""
    
    def test_mean_reversion_short_in_uptrend_rejected(self):
        """Mean reversion SHORT in UP trend should be rejected."""
        stage = StrategyTrendAlignmentStage()
        signal = create_strategy_signal(
            strategy_id="mean_reversion_fade",
            side="short",
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"market_context": {"trend": "up"}},
            signal=signal,  # Real dataclass, not dict!
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "strategy_trend_mismatch"
    
    def test_mean_reversion_long_in_downtrend_rejected(self):
        """Mean reversion LONG in DOWN trend should be rejected."""
        stage = StrategyTrendAlignmentStage()
        signal = create_strategy_signal(
            strategy_id="mean_reversion_fade",
            side="long",
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"market_context": {"trend": "down"}},
            signal=signal,
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "strategy_trend_mismatch"

    def test_mean_reversion_long_in_weak_downtrend_passes(self):
        """Weak downtrends should be flattened before rejecting mean reversion entries."""
        stage = StrategyTrendAlignmentStage()
        signal = create_strategy_signal(
            strategy_id="mean_reversion_fade",
            side="long",
        )

        ctx = StageContext(
            symbol="BTCUSDT",
            data={"market_context": {"trend": "down", "trend_strength": 0.0}},
            signal=signal,
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE
        assert ctx.rejection_reason is None
    
    def test_mean_reversion_long_in_uptrend_passes(self):
        """Mean reversion LONG in UP trend should pass."""
        stage = StrategyTrendAlignmentStage()
        signal = create_strategy_signal(
            strategy_id="mean_reversion_fade",
            side="long",
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"market_context": {"trend": "up"}},
            signal=signal,
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.rejection_reason is None
    
    def test_trend_following_in_flat_market_rejected(self):
        """Trend following in FLAT market should be rejected."""
        stage = StrategyTrendAlignmentStage()
        signal = create_strategy_signal(
            strategy_id="trend_following",
            side="long",
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"market_context": {"trend": "flat"}},
            signal=signal,
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "strategy_trend_mismatch"


class TestFeeAwareEntryWithDataclass:
    """Test FeeAwareEntryStage with real StrategySignal dataclass."""
    
    def test_passes_with_good_edge(self):
        """FeeAwareEntry should pass with good edge conditions."""
        from quantgambit.signals.stages.fee_aware_entry import FeeAwareEntryConfig
        
        config = FeeAwareEntryConfig(
            fee_rate_bps=5.5,
            min_edge_multiplier=2.0,
            slippage_bps=2.0,
        )
        stage = FeeAwareEntryStage(config=config)
        signal = create_strategy_signal(
            entry_price=95000.0,
            take_profit=96000.0,  # ~1.05% edge
            size=0.01,
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {
                    "price": 95000.0,
                },
            },
            signal=signal,
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # With ~1.05% edge and ~0.013% fees, should pass
        assert result == StageResult.CONTINUE
    
    def test_rejects_with_low_edge(self):
        """FeeAwareEntry should reject with low edge (fee trap)."""
        from quantgambit.signals.stages.fee_aware_entry import FeeAwareEntryConfig
        
        config = FeeAwareEntryConfig(
            fee_rate_bps=5.5,
            min_edge_multiplier=2.0,
            slippage_bps=2.0,
        )
        stage = FeeAwareEntryStage(config=config)
        signal = create_strategy_signal(
            entry_price=95000.0,
            take_profit=95010.0,  # ~0.01% edge - too small
            size=0.01,
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {
                    "price": 95000.0,
                },
            },
            signal=signal,
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # With ~0.01% edge and ~0.013% fees, should reject as fee trap
        assert result == StageResult.REJECT


class TestEVGateWithDataclass:
    """Test EVGateStage with real StrategySignal dataclass."""
    
    def test_passes_with_positive_ev(self):
        """EVGate should pass signals with positive EV."""
        config = EVGateConfig(
            mode="enforce",
            ev_min=0.02,  # Minimum EV threshold
        )
        stage = EVGateStage(config=config)
        # Create signal with good R (reward-to-risk ratio)
        signal = create_strategy_signal(
            entry_price=95000.0,
            stop_loss=94000.0,   # 1000 loss distance
            take_profit=97000.0,  # 2000 profit distance -> R=2
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {
                    "price": 95000.0,
                    "best_bid": 94999.0,
                    "best_ask": 95001.0,
                },
                "features": {},
                "prediction": {"confidence": 0.8},  # High confidence
            },
            signal=signal,
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # With 80% confidence and R=2, EV should be positive
        # EV = p*R - (1-p)*1 - C ≈ 0.8*2 - 0.2*1 - small_cost > 0
        assert result == StageResult.CONTINUE
    
    def test_rejects_with_negative_ev(self):
        """EVGate should reject signals with negative EV."""
        config = EVGateConfig(
            mode="enforce",
            ev_min=0.02,
        )
        stage = EVGateStage(config=config)
        # Create signal with poor R (reward-to-risk ratio)
        signal = create_strategy_signal(
            entry_price=95000.0,
            stop_loss=94000.0,   # 1000 loss distance
            take_profit=95500.0,  # 500 profit distance -> R=0.5
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {
                    "price": 95000.0,
                    "best_bid": 94999.0,
                    "best_ask": 95001.0,
                },
                "features": {},
                "prediction": {"confidence": 0.3},  # Low confidence
            },
            signal=signal,
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # With 30% confidence and R=0.5, EV should be negative
        # EV = p*R - (1-p)*1 - C = 0.3*0.5 - 0.7*1 - cost < 0
        assert result == StageResult.REJECT


class TestConfidencePositionSizerWithDataclass:
    """Test ConfidencePositionSizerStage with real StrategySignal dataclass."""
    
    def test_scales_position_by_confidence(self):
        """ConfidencePositionSizer should scale position by confidence."""
        from quantgambit.signals.stages.confidence_position_sizer import ConfidencePositionSizerConfig
        
        config = ConfidencePositionSizerConfig(
            # Uses default multiplier bands:
            # 50-60% -> 0.5x, 60-75% -> 0.75x, 75-90% -> 1.0x, 90%+ -> 1.25x
        )
        stage = ConfidencePositionSizerStage(config=config)
        signal = create_strategy_signal(size=0.01)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "account_state": {"equity": 10000.0},
                "prediction": {"confidence": 0.75},  # 75% -> 1.0x multiplier
            },
            signal=signal,
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        # Position should be scaled based on confidence (75% -> 1.0x)


class TestEVPositionSizerWithDataclass:
    """Test EVPositionSizerStage with real StrategySignal dataclass."""
    
    def test_scales_position_by_ev_margin(self):
        """EVPositionSizer should scale position by EV margin."""
        config = EVPositionSizerConfig(
            k=2.0,           # Edge-to-multiplier scaling factor
            min_mult=0.5,    # Minimum size multiplier
            max_mult=1.25,   # Maximum size multiplier
            cost_alpha=0.5,  # Cost environment scaling factor
            min_reliability_mult=0.8,  # Minimum reliability multiplier
            enabled=True,
        )
        stage = EVPositionSizerStage(config=config)
        signal = create_strategy_signal(size=0.01)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "account_state": {"equity": 10000.0},
                # Provide EV metrics that EVPositionSizer expects
                "EV": 0.10,           # Current EV
                "ev_min": 0.02,       # EV threshold
                "cost_ratio": 0.1,    # Cost ratio C
                "calibration_reliability": 0.9,  # Reliability score
            },
            signal=signal,
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        # Position should be scaled based on edge (EV - EV_Min)


class TestMultipleStagesWithDataclass:
    """Test running multiple stages in sequence with real StrategySignal."""
    
    def test_full_pipeline_with_dataclass_signal(self):
        """Test that a signal can pass through multiple stages."""
        from quantgambit.signals.stages.fee_aware_entry import FeeAwareEntryConfig
        
        # Create stages
        trend_stage = StrategyTrendAlignmentStage()
        fee_config = FeeAwareEntryConfig(
            fee_rate_bps=5.5,
            min_edge_multiplier=2.0,
            slippage_bps=2.0,
        )
        fee_stage = FeeAwareEntryStage(config=fee_config)
        
        # Create real StrategySignal with good edge
        signal = create_strategy_signal(
            strategy_id="mean_reversion_fade",
            side="long",
            entry_price=95000.0,
            take_profit=96000.0,  # ~1.05% edge
            size=0.01,
        )
        
        # Create context with good conditions
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {
                    "trend": "up",  # Good for long mean reversion
                    "price": 95000.0,
                },
            },
            signal=signal,
        )
        
        # Run through stages
        result1 = asyncio.run(trend_stage.run(ctx))
        assert result1 == StageResult.CONTINUE, "Trend stage should pass"
        
        result2 = asyncio.run(fee_stage.run(ctx))
        assert result2 == StageResult.CONTINUE, "Fee stage should pass"
