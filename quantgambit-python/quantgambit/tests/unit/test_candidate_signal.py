"""
Unit tests for CandidateSignal and CandidateArbitrator.

Tests the candidate generation architecture components:
- CandidateSignal dataclass with distance/price conversion
- CandidateArbitrator for selecting best candidate

Requirement 4: Candidate Generation Architecture with Arbitration
"""

import pytest
import time
from quantgambit.deeptrader_core.types import (
    CandidateSignal,
    CandidateArbitrator,
    StrategySignal,
)


class TestCandidateSignal:
    """Tests for CandidateSignal dataclass."""
    
    def test_create_with_required_fields(self):
        """Test creating CandidateSignal with required fields only."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
        )
        
        assert candidate.symbol == "BTCUSDT"
        assert candidate.side == "long"
        assert candidate.strategy_id == "mean_reversion_fade"
        assert candidate.profile_id == "default"
        assert candidate.entry_price == 50000.0
        # Check defaults
        assert candidate.sl_distance_bps is None
        assert candidate.tp_distance_bps is None
        assert candidate.sl_price is None
        assert candidate.tp_price is None
        assert candidate.setup_reason == ""
        assert candidate.setup_score == 0.5
        assert candidate.requires_flow_reversal is True
        assert candidate.max_adverse_trend_bias == 0.5
    
    def test_create_with_distance_based_sl_tp(self):
        """Test creating CandidateSignal with distance-based SL/TP."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_distance_bps=50.0,  # 50 bps = 0.5%
            tp_distance_bps=100.0,  # 100 bps = 1%
            setup_reason="poc_distance_35bps",
            setup_score=0.75,
        )
        
        assert candidate.sl_distance_bps == 50.0
        assert candidate.tp_distance_bps == 100.0
        assert candidate.sl_price is None
        assert candidate.tp_price is None
        assert candidate.setup_reason == "poc_distance_35bps"
        assert candidate.setup_score == 0.75
    
    def test_create_with_price_based_sl_tp(self):
        """Test creating CandidateSignal with price-based SL/TP."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_price=49750.0,  # 250 below entry
            tp_price=50500.0,  # 500 above entry
        )
        
        assert candidate.sl_price == 49750.0
        assert candidate.tp_price == 50500.0
        assert candidate.sl_distance_bps is None
        assert candidate.tp_distance_bps is None
    
    def test_normalize_distance_to_price_long(self):
        """Test normalize() converts distances to prices for long position."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_distance_bps=100.0,  # 100 bps = 1%
            tp_distance_bps=200.0,  # 200 bps = 2%
        )
        
        mid_price = 50000.0
        normalized = candidate.normalize(mid_price)
        
        # For long: SL is below entry, TP is above entry
        assert normalized.sl_distance_bps == 100.0
        assert normalized.tp_distance_bps == 200.0
        # SL: 50000 * (1 - 100/10000) = 50000 * 0.99 = 49500
        assert normalized.sl_price == pytest.approx(49500.0, rel=1e-6)
        # TP: 50000 * (1 + 200/10000) = 50000 * 1.02 = 51000
        assert normalized.tp_price == pytest.approx(51000.0, rel=1e-6)
    
    def test_normalize_distance_to_price_short(self):
        """Test normalize() converts distances to prices for short position."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="short",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_distance_bps=100.0,  # 100 bps = 1%
            tp_distance_bps=200.0,  # 200 bps = 2%
        )
        
        mid_price = 50000.0
        normalized = candidate.normalize(mid_price)
        
        # For short: SL is above entry, TP is below entry
        assert normalized.sl_distance_bps == 100.0
        assert normalized.tp_distance_bps == 200.0
        # SL: 50000 * (1 + 100/10000) = 50000 * 1.01 = 50500
        assert normalized.sl_price == pytest.approx(50500.0, rel=1e-6)
        # TP: 50000 * (1 - 200/10000) = 50000 * 0.98 = 49000
        assert normalized.tp_price == pytest.approx(49000.0, rel=1e-6)
    
    def test_normalize_price_to_distance(self):
        """Test normalize() converts prices to distances."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_price=49500.0,  # 500 below entry
            tp_price=51000.0,  # 1000 above entry
        )
        
        mid_price = 50000.0
        normalized = candidate.normalize(mid_price)
        
        # Distances calculated using canonical formula: |price - entry| / mid_price * 10000
        # SL distance: |50000 - 49500| / 50000 * 10000 = 500/50000 * 10000 = 100 bps
        assert normalized.sl_distance_bps == pytest.approx(100.0, rel=1e-6)
        # TP distance: |51000 - 50000| / 50000 * 10000 = 1000/50000 * 10000 = 200 bps
        assert normalized.tp_distance_bps == pytest.approx(200.0, rel=1e-6)
        # Original prices preserved
        assert normalized.sl_price == 49500.0
        assert normalized.tp_price == 51000.0
    
    def test_normalize_preserves_existing_values(self):
        """Test normalize() preserves values when both distance and price are set."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_distance_bps=100.0,
            sl_price=49500.0,  # Both set
            tp_distance_bps=200.0,
            tp_price=51000.0,  # Both set
        )
        
        mid_price = 50000.0
        normalized = candidate.normalize(mid_price)
        
        # When both are set, values should be preserved
        assert normalized.sl_distance_bps == 100.0
        assert normalized.sl_price == 49500.0
        assert normalized.tp_distance_bps == 200.0
        assert normalized.tp_price == 51000.0
    
    def test_normalize_handles_zero_mid_price(self):
        """Test normalize() handles zero mid_price gracefully."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_price=49500.0,
            tp_price=51000.0,
        )
        
        # Zero mid_price should result in 0 distance
        normalized = candidate.normalize(0.0)
        assert normalized.sl_distance_bps == 0.0
        assert normalized.tp_distance_bps == 0.0
    
    def test_to_strategy_signal(self):
        """Test converting CandidateSignal to StrategySignal."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_price=49500.0,
            tp_price=51000.0,
            setup_reason="poc_distance_35bps",
        )
        
        signal = candidate.to_strategy_signal(
            size=0.1,
            confirmation_reason="flow=1.5,trend=0.2",
        )
        
        assert isinstance(signal, StrategySignal)
        assert signal.strategy_id == "mean_reversion_fade"
        assert signal.symbol == "BTCUSDT"
        assert signal.side == "long"
        assert signal.size == 0.1
        assert signal.entry_price == 50000.0
        assert signal.stop_loss == 49500.0
        assert signal.take_profit == 51000.0
        assert signal.profile_id == "default"
        assert "poc_distance_35bps" in signal.meta_reason
        assert "flow=1.5,trend=0.2" in signal.meta_reason
    
    def test_to_strategy_signal_requires_sl_price(self):
        """Test to_strategy_signal raises error if sl_price not set."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_distance_bps=100.0,  # Only distance, no price
            tp_price=51000.0,
        )
        
        with pytest.raises(ValueError, match="sl_price must be set"):
            candidate.to_strategy_signal(size=0.1, confirmation_reason="test")
    
    def test_to_strategy_signal_requires_tp_price(self):
        """Test to_strategy_signal raises error if tp_price not set."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_price=49500.0,
            tp_distance_bps=200.0,  # Only distance, no price
        )
        
        with pytest.raises(ValueError, match="tp_price must be set"):
            candidate.to_strategy_signal(size=0.1, confirmation_reason="test")
    
    def test_to_dict(self):
        """Test converting CandidateSignal to dictionary."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            sl_distance_bps=100.0,
            tp_distance_bps=200.0,
            setup_reason="test_reason",
            setup_score=0.8,
        )
        
        d = candidate.to_dict()
        
        assert d["symbol"] == "BTCUSDT"
        assert d["side"] == "long"
        assert d["strategy_id"] == "mean_reversion_fade"
        assert d["profile_id"] == "default"
        assert d["entry_price"] == 50000.0
        assert d["sl_distance_bps"] == 100.0
        assert d["tp_distance_bps"] == 200.0
        assert d["setup_reason"] == "test_reason"
        assert d["setup_score"] == 0.8
    
    def test_confirmation_requirements(self):
        """Test confirmation requirements fields."""
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            requires_flow_reversal=True,
            flow_direction_required="positive",
            max_adverse_trend_bias=0.3,
        )
        
        assert candidate.requires_flow_reversal is True
        assert candidate.flow_direction_required == "positive"
        assert candidate.max_adverse_trend_bias == 0.3


class TestCandidateArbitrator:
    """Tests for CandidateArbitrator."""
    
    def test_select_best_empty_list(self):
        """Test select_best returns None for empty list."""
        arbitrator = CandidateArbitrator()
        result = arbitrator.select_best([])
        assert result is None
    
    def test_select_best_single_candidate(self):
        """Test select_best returns the only candidate."""
        arbitrator = CandidateArbitrator()
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="mean_reversion_fade",
            profile_id="default",
            entry_price=50000.0,
            setup_score=0.7,
        )
        
        result = arbitrator.select_best([candidate])
        assert result is candidate
    
    def test_select_best_by_setup_score(self):
        """Test select_best chooses highest setup_score."""
        arbitrator = CandidateArbitrator()
        
        low_score = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="strategy_a",
            profile_id="default",
            entry_price=50000.0,
            setup_score=0.5,
        )
        high_score = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="strategy_b",
            profile_id="default",
            entry_price=50000.0,
            setup_score=0.9,
        )
        
        result = arbitrator.select_best([low_score, high_score])
        assert result is high_score
    
    def test_select_best_by_priority_when_scores_equal(self):
        """Test select_best uses priority as tiebreaker."""
        arbitrator = CandidateArbitrator(
            strategy_priorities={
                "strategy_a": 1,
                "strategy_b": 10,  # Higher priority
            }
        )
        
        candidate_a = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="strategy_a",
            profile_id="default",
            entry_price=50000.0,
            setup_score=0.7,  # Same score
        )
        candidate_b = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="strategy_b",
            profile_id="default",
            entry_price=50000.0,
            setup_score=0.7,  # Same score
        )
        
        result = arbitrator.select_best([candidate_a, candidate_b])
        assert result is candidate_b  # Higher priority wins
    
    def test_select_best_score_beats_priority(self):
        """Test that setup_score is primary criterion over priority."""
        arbitrator = CandidateArbitrator(
            strategy_priorities={
                "strategy_a": 100,  # Very high priority
                "strategy_b": 1,    # Low priority
            }
        )
        
        high_priority_low_score = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="strategy_a",
            profile_id="default",
            entry_price=50000.0,
            setup_score=0.3,  # Low score
        )
        low_priority_high_score = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="strategy_b",
            profile_id="default",
            entry_price=50000.0,
            setup_score=0.9,  # High score
        )
        
        result = arbitrator.select_best([high_priority_low_score, low_priority_high_score])
        assert result is low_priority_high_score  # Score wins over priority
    
    def test_default_priority_is_zero(self):
        """Test that unknown strategies have default priority of 0."""
        arbitrator = CandidateArbitrator(
            strategy_priorities={"known_strategy": 5}
        )
        
        assert arbitrator.get_priority("known_strategy") == 5
        assert arbitrator.get_priority("unknown_strategy") == 0
    
    def test_set_priority(self):
        """Test setting priority for a strategy."""
        arbitrator = CandidateArbitrator()
        
        assert arbitrator.get_priority("my_strategy") == 0
        arbitrator.set_priority("my_strategy", 10)
        assert arbitrator.get_priority("my_strategy") == 10
    
    def test_select_best_multiple_candidates(self):
        """Test select_best with multiple candidates."""
        arbitrator = CandidateArbitrator(
            strategy_priorities={
                "strategy_a": 1,
                "strategy_b": 2,
                "strategy_c": 3,
            }
        )
        
        candidates = [
            CandidateSignal(
                symbol="BTCUSDT",
                side="long",
                strategy_id="strategy_a",
                profile_id="default",
                entry_price=50000.0,
                setup_score=0.6,
            ),
            CandidateSignal(
                symbol="BTCUSDT",
                side="long",
                strategy_id="strategy_b",
                profile_id="default",
                entry_price=50000.0,
                setup_score=0.8,  # Highest score
            ),
            CandidateSignal(
                symbol="BTCUSDT",
                side="long",
                strategy_id="strategy_c",
                profile_id="default",
                entry_price=50000.0,
                setup_score=0.7,
            ),
        ]
        
        result = arbitrator.select_best(candidates)
        assert result.strategy_id == "strategy_b"  # Highest score wins
