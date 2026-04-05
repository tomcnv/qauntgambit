"""
Integration tests for Candidate Generation Architecture.

Tests the full flow from strategy generating CandidateSignal through
ArbitrationStage and ConfirmationStage to produce StrategySignal.

Requirement 4: Candidate Generation Architecture with Arbitration
"""

import pytest
from dataclasses import dataclass
from unittest.mock import MagicMock

from quantgambit.deeptrader_core.types import (
    Features,
    AccountState,
    Profile,
    CandidateSignal,
    StrategySignal,
)
from quantgambit.deeptrader_core.strategies.mean_reversion_fade import MeanReversionFade
from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.arbitration_stage import ArbitrationStage, ArbitrationConfig
from quantgambit.signals.stages.confirmation_stage import ConfirmationStage, ConfirmationConfig


@dataclass
class MockAMTLevels:
    """Mock AMT levels for testing."""
    flow_rotation: float = 0.0
    trend_bias: float = 0.0
    rotation_factor: float = 0.0


@pytest.fixture
def features_long_setup():
    """Features for a long setup (price below POC).
    
    Updated for dual threshold architecture:
    - VA width = (50100 - 49900) / 49700 * 10000 = 40.24 bps
    - setup_threshold = max(0.25 * 40.24, 12) = max(10.06, 12) = 12 bps
    - distance = 300 / 49700 * 10000 = 60.36 bps > 12 bps
    """
    return Features(
        symbol="BTCUSDT",
        price=49700.0,  # Below POC
        spread=0.0001,  # Tight spread
        rotation_factor=0.5,  # Positive rotation
        position_in_value="below",
        distance_to_poc=-300.0,  # 300 below POC (negative = below)
        point_of_control=50000.0,
        value_area_low=49900.0,  # Tighter VA for lower threshold
        value_area_high=50100.0,
        atr_5m=100.0,
        atr_5m_baseline=150.0,  # ATR ratio = 0.67 (calm)
        orderflow_imbalance=0.3,  # Slight buy pressure
    )


@pytest.fixture
def features_short_setup():
    """Features for a short setup (price above POC).
    
    Updated for dual threshold architecture:
    - VA width = (50100 - 49900) / 50300 * 10000 = 39.76 bps
    - setup_threshold = max(0.25 * 39.76, 12) = max(9.94, 12) = 12 bps
    - distance = 300 / 50300 * 10000 = 59.64 bps > 12 bps
    """
    return Features(
        symbol="BTCUSDT",
        price=50300.0,  # Above POC
        spread=0.0001,  # Tight spread
        rotation_factor=-0.5,  # Negative rotation
        position_in_value="above",
        distance_to_poc=300.0,  # 300 above POC (positive = above)
        point_of_control=50000.0,
        value_area_low=49900.0,  # Tighter VA for lower threshold
        value_area_high=50100.0,
        atr_5m=100.0,
        atr_5m_baseline=150.0,  # ATR ratio = 0.67 (calm)
        orderflow_imbalance=-0.3,  # Slight sell pressure
    )


@pytest.fixture
def account():
    """Account state for testing."""
    return AccountState(
        equity=100000.0,
        daily_pnl=0.0,
        max_daily_loss=1000.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )


@pytest.fixture
def profile():
    """Profile for testing."""
    return Profile(
        id="test_profile",
        trend="flat",
        volatility="normal",
        value_location="below",
        session="us",
        risk_mode="normal",
    )


class TestMeanReversionFadeCandidateGeneration:
    """Tests for MeanReversionFade.generate_candidate()."""
    
    def test_generates_long_candidate(self, features_long_setup, account, profile):
        """Test strategy generates long CandidateSignal when price below POC."""
        strategy = MeanReversionFade()
        
        candidate = strategy.generate_candidate(
            features=features_long_setup,
            account=account,
            profile=profile,
            params={},
        )
        
        assert candidate is not None
        assert isinstance(candidate, CandidateSignal)
        assert candidate.side == "long"
        assert candidate.symbol == "BTCUSDT"
        assert candidate.strategy_id == "mean_reversion_fade"
        assert candidate.entry_price == 49700.0  # Updated for new fixture
        assert candidate.sl_distance_bps > 0
        assert candidate.tp_distance_bps > 0
        assert candidate.requires_flow_reversal is True
        assert candidate.flow_direction_required == "positive"
        # Verify profitability_threshold_bps is set (Requirement 2.11)
        assert candidate.profitability_threshold_bps is not None
        assert candidate.profitability_threshold_bps > 0
    
    def test_generates_short_candidate(self, features_short_setup, account, profile):
        """Test strategy generates short CandidateSignal when price above POC."""
        strategy = MeanReversionFade()
        
        candidate = strategy.generate_candidate(
            features=features_short_setup,
            account=account,
            profile=profile,
            params={},
        )
        
        assert candidate is not None
        assert isinstance(candidate, CandidateSignal)
        assert candidate.side == "short"
        assert candidate.symbol == "BTCUSDT"
        assert candidate.strategy_id == "mean_reversion_fade"
        assert candidate.entry_price == 50300.0  # Updated for new fixture
        assert candidate.requires_flow_reversal is True
        assert candidate.flow_direction_required == "negative"
        # Verify profitability_threshold_bps is set (Requirement 2.11)
        assert candidate.profitability_threshold_bps is not None
        assert candidate.profitability_threshold_bps > 0
    
    def test_rejects_when_poc_distance_too_small(self, features_long_setup, account, profile):
        """Test strategy rejects when POC distance is too small."""
        strategy = MeanReversionFade()
        
        # Modify features to have small POC distance
        features_long_setup.distance_to_poc = -10.0  # Only 10 below POC
        features_long_setup.price = 49990.0
        
        candidate = strategy.generate_candidate(
            features=features_long_setup,
            account=account,
            profile=profile,
            params={},
        )
        
        assert candidate is None
    
    def test_setup_score_increases_with_distance(self, features_long_setup, account, profile):
        """Test setup_score increases with POC distance.
        
        Updated for dual threshold architecture:
        - VA width = (50100 - 49900) / price * 10000 ≈ 40 bps
        - setup_threshold = max(0.25 * 40, 12) = 12 bps
        - Both distances must be above 12 bps
        """
        strategy = MeanReversionFade()
        
        # Medium distance (above threshold)
        features_long_setup.distance_to_poc = -300.0  # ~60 bps
        features_long_setup.price = 49700.0
        candidate_medium = strategy.generate_candidate(
            features=features_long_setup,
            account=account,
            profile=profile,
            params={},
        )
        
        # Large distance
        features_long_setup.distance_to_poc = -500.0  # ~100 bps
        features_long_setup.price = 49500.0
        candidate_large = strategy.generate_candidate(
            features=features_long_setup,
            account=account,
            profile=profile,
            params={},
        )
        
        assert candidate_medium is not None
        assert candidate_large is not None
        assert candidate_large.setup_score > candidate_medium.setup_score


class TestCandidateGenerationPipeline:
    """Integration tests for the full candidate generation pipeline."""
    
    @pytest.mark.asyncio
    async def test_full_pipeline_long_confirmed(self, features_long_setup, account, profile):
        """Test full pipeline: strategy -> arbitration -> confirmation for long."""
        # Generate candidate
        strategy = MeanReversionFade()
        candidate = strategy.generate_candidate(
            features=features_long_setup,
            account=account,
            profile=profile,
            params={},
        )
        assert candidate is not None
        
        # Arbitration stage
        arbitration = ArbitrationStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candidates": [candidate],
            },
        )
        
        result = await arbitration.run(ctx)
        assert result == StageResult.CONTINUE
        assert ctx.data["candidate_signal"] is candidate
        
        # Confirmation stage with positive flow (confirms long)
        confirmation = ConfirmationStage()
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=1.0, trend_bias=0.0)
        ctx.data["mid_price"] = 49800.0
        
        result = await confirmation.run(ctx)
        assert result == StageResult.CONTINUE
        assert ctx.signal is not None
        assert isinstance(ctx.signal, StrategySignal)
        assert ctx.signal.side == "long"
        assert ctx.signal.strategy_id == "mean_reversion_fade"
    
    @pytest.mark.asyncio
    async def test_full_pipeline_short_confirmed(self, features_short_setup, account, profile):
        """Test full pipeline: strategy -> arbitration -> confirmation for short."""
        # Generate candidate
        strategy = MeanReversionFade()
        candidate = strategy.generate_candidate(
            features=features_short_setup,
            account=account,
            profile=profile,
            params={},
        )
        assert candidate is not None
        
        # Arbitration stage
        arbitration = ArbitrationStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candidates": [candidate],
            },
        )
        
        result = await arbitration.run(ctx)
        assert result == StageResult.CONTINUE
        assert ctx.data["candidate_signal"] is candidate
        
        # Confirmation stage with negative flow (confirms short)
        confirmation = ConfirmationStage()
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=-1.0, trend_bias=0.0)
        ctx.data["mid_price"] = 50200.0
        
        result = await confirmation.run(ctx)
        assert result == StageResult.CONTINUE
        assert ctx.signal is not None
        assert ctx.signal.side == "short"
    
    @pytest.mark.asyncio
    async def test_full_pipeline_long_rejected_wrong_flow(self, features_long_setup, account, profile):
        """Test long candidate rejected when flow is negative."""
        # Generate candidate
        strategy = MeanReversionFade()
        candidate = strategy.generate_candidate(
            features=features_long_setup,
            account=account,
            profile=profile,
            params={},
        )
        assert candidate is not None
        
        # Arbitration stage
        arbitration = ArbitrationStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candidates": [candidate],
            },
        )
        
        result = await arbitration.run(ctx)
        assert result == StageResult.CONTINUE
        
        # Confirmation stage with negative flow (rejects long)
        confirmation = ConfirmationStage()
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=-1.0, trend_bias=0.0)
        ctx.data["mid_price"] = 49800.0
        
        result = await confirmation.run(ctx)
        assert result == StageResult.REJECT
        assert "flow_not_positive" in ctx.rejection_reason
    
    @pytest.mark.asyncio
    async def test_arbitration_selects_best_candidate(self, features_long_setup, account, profile):
        """Test arbitration selects candidate with highest setup_score."""
        strategy = MeanReversionFade()
        
        # Create two candidates with different scores
        candidate1 = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="strategy_a",
            profile_id="default",
            entry_price=49800.0,
            sl_distance_bps=100.0,
            tp_distance_bps=200.0,
            setup_score=0.6,
        )
        candidate2 = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="strategy_b",
            profile_id="default",
            entry_price=49800.0,
            sl_distance_bps=100.0,
            tp_distance_bps=200.0,
            setup_score=0.9,  # Higher score
        )
        
        # Arbitration stage
        arbitration = ArbitrationStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candidates": [candidate1, candidate2],
            },
        )
        
        result = await arbitration.run(ctx)
        assert result == StageResult.CONTINUE
        assert ctx.data["candidate_signal"] is candidate2  # Higher score wins
    
    @pytest.mark.asyncio
    async def test_signal_has_correct_sl_tp_prices(self, features_long_setup, account, profile):
        """Test confirmed signal has correct SL/TP prices from normalization."""
        strategy = MeanReversionFade()
        candidate = strategy.generate_candidate(
            features=features_long_setup,
            account=account,
            profile=profile,
            params={},
        )
        assert candidate is not None
        
        # Run through pipeline
        arbitration = ArbitrationStage()
        confirmation = ConfirmationStage()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candidates": [candidate],
                "amt_levels": MockAMTLevels(flow_rotation=1.0, trend_bias=0.0),
                "mid_price": 49800.0,
            },
        )
        
        await arbitration.run(ctx)
        await confirmation.run(ctx)
        
        signal = ctx.signal
        assert signal is not None
        
        # Verify SL is below entry for long
        assert signal.stop_loss < signal.entry_price
        # Verify TP is above entry for long (towards POC)
        assert signal.take_profit > signal.entry_price
