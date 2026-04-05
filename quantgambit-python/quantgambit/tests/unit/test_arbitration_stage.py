"""
Unit tests for ArbitrationStage.

Tests the arbitration stage that selects the best candidate when multiple
strategies emit signals.

Requirement 4.5: Candidate arbitration based on setup_score and priority
"""

import pytest
from unittest.mock import MagicMock

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.arbitration_stage import ArbitrationStage, ArbitrationConfig
from quantgambit.deeptrader_core.types import CandidateSignal


@pytest.fixture
def stage():
    """Create ArbitrationStage with default config."""
    return ArbitrationStage()


@pytest.fixture
def stage_with_priorities():
    """Create ArbitrationStage with strategy priorities."""
    config = ArbitrationConfig(
        strategy_priorities={
            "strategy_a": 1,
            "strategy_b": 10,
            "strategy_c": 5,
        }
    )
    return ArbitrationStage(config=config)


@pytest.fixture
def ctx():
    """Create a basic StageContext."""
    return StageContext(
        symbol="BTCUSDT",
        data={},
    )


def make_candidate(
    strategy_id: str = "test_strategy",
    setup_score: float = 0.5,
    side: str = "long",
) -> CandidateSignal:
    """Helper to create CandidateSignal."""
    return CandidateSignal(
        symbol="BTCUSDT",
        side=side,
        strategy_id=strategy_id,
        profile_id="default",
        entry_price=50000.0,
        setup_score=setup_score,
    )


class TestArbitrationStage:
    """Tests for ArbitrationStage."""
    
    @pytest.mark.asyncio
    async def test_no_candidates(self, stage, ctx):
        """Test stage continues when no candidates available."""
        ctx.data["candidates"] = []
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data.get("candidate_signal") is None
    
    @pytest.mark.asyncio
    async def test_no_candidates_key(self, stage, ctx):
        """Test stage continues when candidates key not in data."""
        # No "candidates" key in ctx.data
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data.get("candidate_signal") is None
    
    @pytest.mark.asyncio
    async def test_single_candidate(self, stage, ctx):
        """Test stage selects single candidate."""
        candidate = make_candidate(setup_score=0.7)
        ctx.data["candidates"] = [candidate]
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data["candidate_signal"] is candidate
    
    @pytest.mark.asyncio
    async def test_single_candidate_not_in_list(self, stage, ctx):
        """Test stage handles single candidate not in list."""
        candidate = make_candidate(setup_score=0.7)
        ctx.data["candidates"] = candidate  # Not a list
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data["candidate_signal"] is candidate
    
    @pytest.mark.asyncio
    async def test_select_by_setup_score(self, stage, ctx):
        """Test stage selects candidate with highest setup_score."""
        low_score = make_candidate(strategy_id="low", setup_score=0.3)
        high_score = make_candidate(strategy_id="high", setup_score=0.9)
        mid_score = make_candidate(strategy_id="mid", setup_score=0.6)
        
        ctx.data["candidates"] = [low_score, high_score, mid_score]
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data["candidate_signal"] is high_score
    
    @pytest.mark.asyncio
    async def test_select_by_priority_when_scores_equal(self, stage_with_priorities, ctx):
        """Test stage uses priority as tiebreaker."""
        # strategy_b has priority 10, strategy_a has priority 1
        candidate_a = make_candidate(strategy_id="strategy_a", setup_score=0.7)
        candidate_b = make_candidate(strategy_id="strategy_b", setup_score=0.7)
        
        ctx.data["candidates"] = [candidate_a, candidate_b]
        
        result = await stage_with_priorities.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data["candidate_signal"] is candidate_b  # Higher priority
    
    @pytest.mark.asyncio
    async def test_score_beats_priority(self, stage_with_priorities, ctx):
        """Test that setup_score is primary criterion over priority."""
        # strategy_b has higher priority but lower score
        candidate_a = make_candidate(strategy_id="strategy_a", setup_score=0.9)
        candidate_b = make_candidate(strategy_id="strategy_b", setup_score=0.5)
        
        ctx.data["candidates"] = [candidate_a, candidate_b]
        
        result = await stage_with_priorities.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data["candidate_signal"] is candidate_a  # Higher score wins
    
    @pytest.mark.asyncio
    async def test_filters_invalid_candidates(self, stage, ctx):
        """Test stage filters out non-CandidateSignal objects."""
        valid = make_candidate(setup_score=0.7)
        invalid = {"not": "a candidate"}
        
        ctx.data["candidates"] = [invalid, valid, None, "string"]
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data["candidate_signal"] is valid
    
    def test_set_priority(self, stage):
        """Test setting priority for a strategy."""
        assert stage.get_priority("new_strategy") == 0
        
        stage.set_priority("new_strategy", 15)
        
        assert stage.get_priority("new_strategy") == 15
    
    def test_get_priority_default(self, stage):
        """Test default priority is 0."""
        assert stage.get_priority("unknown_strategy") == 0
    
    @pytest.mark.asyncio
    async def test_never_rejects(self, stage, ctx):
        """Test stage never returns REJECT."""
        # Even with empty candidates, should CONTINUE
        ctx.data["candidates"] = []
        result = await stage.run(ctx)
        assert result == StageResult.CONTINUE
        
        # With invalid data, should CONTINUE
        ctx.data["candidates"] = None
        result = await stage.run(ctx)
        assert result == StageResult.CONTINUE
