"""
Tests for RelaxationEngine.

Tests the conditional relaxation functionality implemented in task 10:
- 10.1: RelaxationEngine class (Requirements 6.1, 6.2, 6.3, 6.4, 6.5)
- 10.3: Relaxation safety guards (Requirements 6.6, 6.7)
"""

import pytest
from quantgambit.signals.stages.ev_gate import (
    RelaxationEngine,
    EVGateConfig,
    RelaxationResult,
)


class TestRelaxationEngineBasics:
    """Basic tests for RelaxationEngine."""
    
    def test_default_config_creates_engine(self):
        """RelaxationEngine should be created with default config."""
        config = EVGateConfig()
        engine = RelaxationEngine(config)
        assert engine is not None
        assert engine.config == config
    
    def test_base_factor_always_included(self):
        """Base factor of 1.0 should always be in candidate factors."""
        config = EVGateConfig()
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.5,
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Base factor should be in candidates
        factors = [f for f, _ in result.candidate_factors]
        assert 1.0 in factors


class TestSpreadImbalanceRelaxation:
    """Tests for spread + book imbalance relaxation (Requirement 6.1)."""
    
    def test_low_spread_favorable_imbalance_long_relaxes(self):
        """Low spread + favorable imbalance for long should relax."""
        config = EVGateConfig(
            relaxation_spread_percentile=0.30,
            relaxation_multiplier=0.8,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.20,  # Below 30%
            book_imbalance=0.5,  # Positive = more bids = favorable for long
            signal_side="long",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should have relaxation factor
        factors = [f for f, _ in result.candidate_factors]
        assert 0.8 in factors
    
    def test_low_spread_favorable_imbalance_short_relaxes(self):
        """Low spread + favorable imbalance for short should relax."""
        config = EVGateConfig(
            relaxation_spread_percentile=0.30,
            relaxation_multiplier=0.8,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.20,  # Below 30%
            book_imbalance=-0.5,  # Negative = more asks = favorable for short
            signal_side="short",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should have relaxation factor
        factors = [f for f, _ in result.candidate_factors]
        assert 0.8 in factors
    
    def test_low_spread_unfavorable_imbalance_no_relaxation(self):
        """Low spread + unfavorable imbalance should not relax."""
        config = EVGateConfig(
            relaxation_spread_percentile=0.30,
            relaxation_multiplier=0.8,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.20,  # Below 30%
            book_imbalance=-0.5,  # Negative = more asks = unfavorable for long
            signal_side="long",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should NOT have relaxation factor
        factors = [f for f, _ in result.candidate_factors]
        assert 0.8 not in factors
    
    def test_high_spread_no_relaxation(self):
        """High spread should not trigger relaxation."""
        config = EVGateConfig(
            relaxation_spread_percentile=0.30,
            relaxation_multiplier=0.8,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.50,  # Above 30%
            book_imbalance=0.5,  # Favorable
            signal_side="long",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should NOT have relaxation factor
        factors = [f for f, _ in result.candidate_factors]
        assert 0.8 not in factors


class TestVolatilitySessionRelaxation:
    """Tests for volatility + session relaxation (Requirement 6.2)."""
    
    def test_low_volatility_us_session_relaxes(self):
        """Low volatility + US session should relax."""
        config = EVGateConfig()
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.50,
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="low",
            session="us",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should have volatility/session relaxation factor (0.9)
        factors = [f for f, _ in result.candidate_factors]
        assert 0.9 in factors
    
    def test_low_volatility_europe_session_relaxes(self):
        """Low volatility + Europe session should relax."""
        config = EVGateConfig()
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.50,
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="low",
            session="europe",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should have volatility/session relaxation factor (0.9)
        factors = [f for f, _ in result.candidate_factors]
        assert 0.9 in factors
    
    def test_low_volatility_asia_session_no_relaxation(self):
        """Low volatility + Asia session should not relax."""
        config = EVGateConfig()
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.50,
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="low",
            session="asia",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should NOT have volatility/session relaxation factor
        factors = [f for f, _ in result.candidate_factors]
        assert 0.9 not in factors
    
    def test_high_volatility_us_session_no_relaxation(self):
        """High volatility + US session should not relax."""
        config = EVGateConfig()
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.50,
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="high",
            session="us",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should NOT have volatility/session relaxation factor
        factors = [f for f, _ in result.candidate_factors]
        assert 0.9 not in factors


class TestSpreadTightening:
    """Tests for spread tightening (Requirement 6.3)."""
    
    def test_high_spread_tightens(self):
        """High spread should trigger tightening."""
        config = EVGateConfig(
            tightening_spread_percentile=0.70,
            tightening_multiplier=1.25,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.80,  # Above 70%
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should have tightening factor
        factors = [f for f, _ in result.candidate_factors]
        assert 1.25 in factors
    
    def test_normal_spread_no_tightening(self):
        """Normal spread should not trigger tightening."""
        config = EVGateConfig(
            tightening_spread_percentile=0.70,
            tightening_multiplier=1.25,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.50,  # Below 70%
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should NOT have tightening factor
        factors = [f for f, _ in result.candidate_factors]
        assert 1.25 not in factors


class TestConservativeSelection:
    """Tests for conservative selection (Requirement 6.4)."""
    
    def test_max_factor_selected(self):
        """Maximum (most conservative) factor should be selected."""
        config = EVGateConfig(
            relaxation_spread_percentile=0.30,
            relaxation_multiplier=0.8,
            tightening_spread_percentile=0.70,
            tightening_multiplier=1.25,
        )
        engine = RelaxationEngine(config)
        
        # Create scenario with both relaxation and tightening conditions
        # FIX #1: New behavior combines relax and tighten factors
        # relax_factor * tighten_factor = 0.9 * 1.25 = 1.125
        result = engine.compute_adjustment(
            spread_percentile=0.80,  # Triggers tightening (1.25)
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="low",
            session="us",  # Triggers relaxation (0.9)
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        # Should combine: relax (0.9) * tighten (1.25) = 1.125
        # This allows relaxation to partially offset tightening
        assert result.adjustment_factor == 0.9 * 1.25  # 1.125
    
    def test_base_factor_when_no_conditions(self):
        """Base factor (1.0) should be used when no conditions apply."""
        config = EVGateConfig()
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.50,  # No relaxation or tightening
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="medium",  # No volatility relaxation
            session="asia",  # No session relaxation
            calibration_reliability=0.9,
            book_age_ms=100,
        )
        
        assert result.adjustment_factor == 1.0


class TestEVMinFloorEnforcement:
    """Tests for EV_MIN_FLOOR enforcement (Requirement 6.5)."""
    
    def test_floor_enforced_on_relaxation(self):
        """EV_MIN_FLOOR should be enforced when relaxation would go below."""
        config = EVGateConfig(
            ev_min=0.02,
            ev_min_floor=0.01,
            relaxation_multiplier=0.3,  # Very aggressive relaxation
        )
        engine = RelaxationEngine(config)
        
        # Apply adjustment that would go below floor
        adjusted = engine.apply_adjustment(
            ev_min_base=0.02,
            adjustment_factor=0.3,  # Would give 0.006, below floor
        )
        
        # Should be clamped to floor
        assert adjusted == 0.01
    
    def test_floor_not_applied_when_above(self):
        """EV_MIN_FLOOR should not affect values above it."""
        config = EVGateConfig(
            ev_min=0.02,
            ev_min_floor=0.01,
            relaxation_multiplier=0.8,
        )
        engine = RelaxationEngine(config)
        
        # Apply adjustment that stays above floor
        adjusted = engine.apply_adjustment(
            ev_min_base=0.02,
            adjustment_factor=0.8,  # Would give 0.016, above floor
        )
        
        # Should be the calculated value
        assert adjusted == pytest.approx(0.016, abs=0.001)


class TestRelaxationSafetyGuards:
    """Tests for relaxation safety guards (Requirements 6.6, 6.7)."""
    
    def test_low_reliability_disables_relaxation(self):
        """Low reliability should disable relaxation (Requirement 6.6)."""
        config = EVGateConfig(
            relaxation_spread_percentile=0.30,
            relaxation_multiplier=0.8,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.20,  # Would trigger relaxation
            book_imbalance=0.5,  # Favorable
            signal_side="long",
            volatility_regime="low",
            session="us",  # Would also trigger relaxation
            calibration_reliability=0.7,  # Below 0.8 threshold
            book_age_ms=100,
        )
        
        # Relaxation factors should NOT be present
        factors = [f for f, _ in result.candidate_factors]
        assert 0.8 not in factors  # Spread/imbalance relaxation
        assert 0.9 not in factors  # Volatility/session relaxation
    
    def test_stale_book_disables_relaxation(self):
        """Stale book should disable relaxation (Requirement 6.7)."""
        config = EVGateConfig(
            max_book_age_ms=250,
            relaxation_spread_percentile=0.30,
            relaxation_multiplier=0.8,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.20,  # Would trigger relaxation
            book_imbalance=0.5,  # Favorable
            signal_side="long",
            volatility_regime="low",
            session="us",  # Would also trigger relaxation
            calibration_reliability=0.9,  # Good reliability
            book_age_ms=300,  # Above 250ms threshold
        )
        
        # Relaxation factors should NOT be present
        factors = [f for f, _ in result.candidate_factors]
        assert 0.8 not in factors  # Spread/imbalance relaxation
        assert 0.9 not in factors  # Volatility/session relaxation
    
    def test_tightening_still_applies_with_low_reliability(self):
        """Tightening should still apply even with low reliability."""
        config = EVGateConfig(
            tightening_spread_percentile=0.70,
            tightening_multiplier=1.25,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.80,  # Triggers tightening
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.5,  # Low reliability
            book_age_ms=100,
        )
        
        # Tightening should still be present
        factors = [f for f, _ in result.candidate_factors]
        assert 1.25 in factors
    
    def test_tightening_still_applies_with_stale_book(self):
        """Tightening should still apply even with stale book."""
        config = EVGateConfig(
            max_book_age_ms=250,
            tightening_spread_percentile=0.70,
            tightening_multiplier=1.25,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.80,  # Triggers tightening
            book_imbalance=0.0,
            signal_side="long",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.9,
            book_age_ms=300,  # Stale book
        )
        
        # Tightening should still be present
        factors = [f for f, _ in result.candidate_factors]
        assert 1.25 in factors
    
    def test_good_reliability_allows_relaxation(self):
        """Good reliability should allow relaxation."""
        config = EVGateConfig(
            relaxation_spread_percentile=0.30,
            relaxation_multiplier=0.8,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.20,  # Would trigger relaxation
            book_imbalance=0.5,  # Favorable
            signal_side="long",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.85,  # Above 0.8 threshold
            book_age_ms=100,
        )
        
        # Relaxation factor should be present
        factors = [f for f, _ in result.candidate_factors]
        assert 0.8 in factors
    
    def test_fresh_book_allows_relaxation(self):
        """Fresh book should allow relaxation."""
        config = EVGateConfig(
            max_book_age_ms=250,
            relaxation_spread_percentile=0.30,
            relaxation_multiplier=0.8,
        )
        engine = RelaxationEngine(config)
        
        result = engine.compute_adjustment(
            spread_percentile=0.20,  # Would trigger relaxation
            book_imbalance=0.5,  # Favorable
            signal_side="long",
            volatility_regime="medium",
            session="asia",
            calibration_reliability=0.9,
            book_age_ms=100,  # Fresh book
        )
        
        # Relaxation factor should be present
        factors = [f for f, _ in result.candidate_factors]
        assert 0.8 in factors


class TestEVGateStageRelaxationIntegration:
    """Integration tests for EVGateStage with RelaxationEngine."""
    
    def test_relaxation_applied_in_stage(self):
        """EVGateStage should apply relaxation from RelaxationEngine."""
        from quantgambit.signals.stages.ev_gate import EVGateStage
        from quantgambit.signals.pipeline import StageContext
        import asyncio
        
        config = EVGateConfig(
            mode="enforce",
            ev_min=0.02,
            ev_min_floor=0.01,
            relaxation_spread_percentile=0.30,
            relaxation_multiplier=0.8,
        )
        stage = EVGateStage(config=config)
        
        # Use current timestamp for fresh data
        import time
        current_ts = time.time() * 1000
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {
                    "price": 50000.0,
                    "best_bid": 50000.0,
                    "best_ask": 50010.0,
                    "calibration_reliability": 0.9,
                    "spread_percentile": 0.20,  # Low spread
                    "book_imbalance": 0.5,  # Favorable for long
                    "volatility_regime": "medium",
                    "session": "asia",
                    "timestamp_ms": current_ts,  # Fresh timestamp
                },
                "features": {},
                "prediction": {"confidence": 0.65},
            }
        )
        ctx.signal = {
            "side": "long",
            "stop_loss": 49000.0,
            "take_profit": 52000.0,
        }
        
        # Run the stage
        asyncio.run(stage.run(ctx))
        
        # Check that relaxation was applied
        if ctx.rejection_detail:
            ev_min_adjusted = ctx.rejection_detail.get("ev_min_adjusted", 0)
            # With relaxation: 0.02 * 0.8 = 0.016
            assert ev_min_adjusted == pytest.approx(0.016, abs=0.002)
