"""
Property-based tests for EVPositionSizer.

These tests validate the correctness properties of the EV-based position sizing
system using Hypothesis for property-based testing.

Feature: ev-position-sizer
Properties:
- Property 1: Multiplier Bounds
- Property 2: Edge Monotonicity  
- Property 3: Cost Monotonicity
- Property 4: Reliability Monotonicity
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.ev_position_sizer import (
    EVPositionSizerConfig,
    EVPositionSizerStage,
    EVSizingResult,
    compute_ev_multiplier,
    compute_cost_scale,
    compute_reliability_scale,
)


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Edge values: typically small positive numbers (EV - EV_Min)
edge_strategy = st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False)

# Cost ratio C: typically 0 to 1, but can exceed 1 in edge cases
cost_ratio_strategy = st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False)

# Reliability score: 0 to 1
reliability_strategy = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Config parameters
k_strategy = st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False)
min_mult_strategy = st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False)
max_mult_strategy = st.floats(min_value=1.1, max_value=2.0, allow_nan=False, allow_infinity=False)
alpha_strategy = st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False)
min_reliability_mult_strategy = st.floats(min_value=0.5, max_value=0.95, allow_nan=False, allow_infinity=False)


# =============================================================================
# Property 1: Multiplier Bounds
# For any valid input, the final multiplier SHALL be within bounds.
# Validates: Requirements 1.2, 1.4, 2.1, 3.1
# =============================================================================

class TestProperty1MultiplierBounds:
    """
    Property 1: Multiplier Bounds
    
    For any valid input, the final multiplier SHALL be within
    [min_mult × 0.5 × min_reliability_mult, max_mult × 1.0 × 1.0].
    
    **Validates: Requirements 1.2, 1.4, 2.1, 3.1**
    """
    
    @given(
        edge=edge_strategy,
        k=k_strategy,
        min_mult=min_mult_strategy,
        max_mult=max_mult_strategy,
    )
    @settings(max_examples=100)
    def test_ev_multiplier_within_bounds(self, edge, k, min_mult, max_mult):
        """EV multiplier should always be within [min_mult, max_mult]."""
        assume(min_mult < max_mult)
        
        mult, _ = compute_ev_multiplier(edge, k, min_mult, max_mult)
        
        assert min_mult <= mult <= max_mult, (
            f"EV multiplier {mult} outside bounds [{min_mult}, {max_mult}] "
            f"for edge={edge}, k={k}"
        )
    
    @given(
        C=cost_ratio_strategy,
        alpha=alpha_strategy,
    )
    @settings(max_examples=100)
    def test_cost_scale_within_bounds(self, C, alpha):
        """Cost scale should always be within [0.5, 1.0]."""
        scale = compute_cost_scale(C, alpha)
        
        assert 0.5 <= scale <= 1.0, (
            f"Cost scale {scale} outside bounds [0.5, 1.0] "
            f"for C={C}, alpha={alpha}"
        )
    
    @given(
        reliability_score=reliability_strategy,
        min_reliability_mult=min_reliability_mult_strategy,
    )
    @settings(max_examples=100)
    def test_reliability_scale_within_bounds(self, reliability_score, min_reliability_mult):
        """Reliability scale should always be within [min_reliability_mult, 1.0]."""
        scale = compute_reliability_scale(reliability_score, min_reliability_mult)
        
        assert min_reliability_mult <= scale <= 1.0, (
            f"Reliability scale {scale} outside bounds [{min_reliability_mult}, 1.0] "
            f"for reliability_score={reliability_score}"
        )
    
    @given(
        edge=edge_strategy,
        C=cost_ratio_strategy,
        reliability_score=reliability_strategy,
    )
    @settings(max_examples=100)
    def test_final_multiplier_within_bounds(self, edge, C, reliability_score):
        """Final multiplier (product of all three) should be within overall bounds."""
        config = EVPositionSizerConfig()
        
        ev_mult, _ = compute_ev_multiplier(
            edge, config.k, config.min_mult, config.max_mult
        )
        cost_mult = compute_cost_scale(C, config.cost_alpha)
        reliability_mult = compute_reliability_scale(
            reliability_score, config.min_reliability_mult
        )
        
        final_mult = ev_mult * cost_mult * reliability_mult
        
        # Theoretical bounds
        min_bound = config.min_mult * 0.5 * config.min_reliability_mult
        max_bound = config.max_mult * 1.0 * 1.0
        
        assert min_bound <= final_mult <= max_bound, (
            f"Final multiplier {final_mult} outside bounds [{min_bound}, {max_bound}]"
        )


# =============================================================================
# Property 2: Edge Monotonicity
# For any two signals with identical cost and reliability, the signal with
# higher edge SHALL have equal or higher ev_mult.
# Validates: Requirements 1.2, 1.3
# =============================================================================

class TestProperty2EdgeMonotonicity:
    """
    Property 2: Edge Monotonicity
    
    For any two signals with identical cost and reliability, the signal with
    higher edge SHALL have equal or higher ev_mult.
    
    **Validates: Requirements 1.2, 1.3**
    """
    
    @given(
        edge1=edge_strategy,
        edge2=edge_strategy,
        k=k_strategy,
        min_mult=min_mult_strategy,
        max_mult=max_mult_strategy,
    )
    @settings(max_examples=100)
    def test_higher_edge_gives_higher_or_equal_multiplier(
        self, edge1, edge2, k, min_mult, max_mult
    ):
        """Higher edge should result in higher or equal EV multiplier."""
        assume(min_mult < max_mult)
        
        mult1, _ = compute_ev_multiplier(edge1, k, min_mult, max_mult)
        mult2, _ = compute_ev_multiplier(edge2, k, min_mult, max_mult)
        
        if edge1 > edge2:
            assert mult1 >= mult2, (
                f"Edge monotonicity violated: edge1={edge1} > edge2={edge2} "
                f"but mult1={mult1} < mult2={mult2}"
            )
        elif edge2 > edge1:
            assert mult2 >= mult1, (
                f"Edge monotonicity violated: edge2={edge2} > edge1={edge1} "
                f"but mult2={mult2} < mult1={mult1}"
            )
        # If edges are equal, multipliers should be equal
        else:
            assert mult1 == mult2
    
    @given(
        edge_low=st.floats(min_value=-0.5, max_value=0.0, allow_nan=False, allow_infinity=False),
        edge_high=st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_positive_edge_beats_negative_edge(self, edge_low, edge_high):
        """Positive edge should always give higher multiplier than negative edge."""
        config = EVPositionSizerConfig()
        
        mult_low, _ = compute_ev_multiplier(
            edge_low, config.k, config.min_mult, config.max_mult
        )
        mult_high, _ = compute_ev_multiplier(
            edge_high, config.k, config.min_mult, config.max_mult
        )
        
        assert mult_high >= mult_low, (
            f"Positive edge {edge_high} should give higher mult than negative edge {edge_low}"
        )


# =============================================================================
# Property 3: Cost Monotonicity
# For any two signals with identical edge and reliability, the signal with
# higher C SHALL have equal or lower cost_mult.
# Validates: Requirements 2.1, 2.2
# =============================================================================

class TestProperty3CostMonotonicity:
    """
    Property 3: Cost Monotonicity
    
    For any two signals with identical edge and reliability, the signal with
    higher C SHALL have equal or lower cost_mult.
    
    **Validates: Requirements 2.1, 2.2**
    """
    
    @given(
        C1=cost_ratio_strategy,
        C2=cost_ratio_strategy,
        alpha=alpha_strategy,
    )
    @settings(max_examples=100)
    def test_higher_cost_gives_lower_or_equal_scale(self, C1, C2, alpha):
        """Higher cost ratio should result in lower or equal cost scale."""
        scale1 = compute_cost_scale(C1, alpha)
        scale2 = compute_cost_scale(C2, alpha)
        
        if C1 > C2:
            assert scale1 <= scale2, (
                f"Cost monotonicity violated: C1={C1} > C2={C2} "
                f"but scale1={scale1} > scale2={scale2}"
            )
        elif C2 > C1:
            assert scale2 <= scale1, (
                f"Cost monotonicity violated: C2={C2} > C1={C1} "
                f"but scale2={scale2} > scale1={scale1}"
            )
        else:
            assert scale1 == scale2
    
    @given(
        C_low=st.floats(min_value=0.0, max_value=0.3, allow_nan=False, allow_infinity=False),
        C_high=st.floats(min_value=0.7, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_low_cost_beats_high_cost(self, C_low, C_high):
        """Low cost environment should give higher scale than high cost."""
        config = EVPositionSizerConfig()
        
        scale_low = compute_cost_scale(C_low, config.cost_alpha)
        scale_high = compute_cost_scale(C_high, config.cost_alpha)
        
        assert scale_low >= scale_high, (
            f"Low cost {C_low} should give higher scale than high cost {C_high}"
        )


# =============================================================================
# Property 4: Reliability Monotonicity
# For any two signals with identical edge and cost, the signal with higher
# reliability_score SHALL have equal or higher reliability_mult.
# Validates: Requirements 3.1, 3.2, 3.3
# =============================================================================

class TestProperty4ReliabilityMonotonicity:
    """
    Property 4: Reliability Monotonicity
    
    For any two signals with identical edge and cost, the signal with higher
    reliability_score SHALL have equal or higher reliability_mult.
    
    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    
    @given(
        rel1=reliability_strategy,
        rel2=reliability_strategy,
        min_reliability_mult=min_reliability_mult_strategy,
    )
    @settings(max_examples=100)
    def test_higher_reliability_gives_higher_or_equal_scale(
        self, rel1, rel2, min_reliability_mult
    ):
        """Higher reliability should result in higher or equal reliability scale."""
        scale1 = compute_reliability_scale(rel1, min_reliability_mult)
        scale2 = compute_reliability_scale(rel2, min_reliability_mult)
        
        if rel1 > rel2:
            assert scale1 >= scale2, (
                f"Reliability monotonicity violated: rel1={rel1} > rel2={rel2} "
                f"but scale1={scale1} < scale2={scale2}"
            )
        elif rel2 > rel1:
            assert scale2 >= scale1, (
                f"Reliability monotonicity violated: rel2={rel2} > rel1={rel1} "
                f"but scale2={scale2} < scale1={scale1}"
            )
        else:
            assert scale1 == scale2
    
    @given(
        rel_low=st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
        rel_high=st.floats(min_value=0.9, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_high_reliability_beats_low_reliability(self, rel_low, rel_high):
        """High reliability should give higher scale than low reliability."""
        config = EVPositionSizerConfig()
        
        scale_low = compute_reliability_scale(rel_low, config.min_reliability_mult)
        scale_high = compute_reliability_scale(rel_high, config.min_reliability_mult)
        
        assert scale_high >= scale_low, (
            f"High reliability {rel_high} should give higher scale than low {rel_low}"
        )


# =============================================================================
# Additional Property Tests
# =============================================================================

class TestConfigValidation:
    """Test that config validation catches invalid parameters."""
    
    def test_negative_k_rejected(self):
        """Negative k should be rejected."""
        with pytest.raises(ValueError, match="k must be non-negative"):
            EVPositionSizerConfig(k=-1.0)
    
    def test_negative_min_mult_rejected(self):
        """Negative min_mult should be rejected."""
        with pytest.raises(ValueError, match="min_mult must be non-negative"):
            EVPositionSizerConfig(min_mult=-0.5)
    
    def test_max_mult_less_than_min_mult_rejected(self):
        """max_mult < min_mult should be rejected."""
        with pytest.raises(ValueError, match="max_mult.*must be >= min_mult"):
            EVPositionSizerConfig(min_mult=1.5, max_mult=1.0)
    
    def test_negative_cost_alpha_rejected(self):
        """Negative cost_alpha should be rejected."""
        with pytest.raises(ValueError, match="cost_alpha must be non-negative"):
            EVPositionSizerConfig(cost_alpha=-0.5)
    
    def test_min_reliability_mult_out_of_range_rejected(self):
        """min_reliability_mult outside [0, 1] should be rejected."""
        with pytest.raises(ValueError, match="min_reliability_mult must be in"):
            EVPositionSizerConfig(min_reliability_mult=1.5)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_zero_edge_gives_base_multiplier(self):
        """Zero edge should give multiplier of 1.0 (before clamping)."""
        config = EVPositionSizerConfig()
        mult, _ = compute_ev_multiplier(0.0, config.k, config.min_mult, config.max_mult)
        
        # 1.0 + k * 0 = 1.0, which is within [0.5, 1.25]
        assert mult == 1.0
    
    def test_zero_cost_gives_full_scale(self):
        """Zero cost should give scale of 1.0."""
        scale = compute_cost_scale(0.0, 0.5)
        assert scale == 1.0
    
    def test_perfect_reliability_gives_full_scale(self):
        """Reliability of 1.0 should give scale of 1.0."""
        scale = compute_reliability_scale(1.0, 0.8)
        assert scale == 1.0
    
    def test_very_high_edge_capped_at_max(self):
        """Very high edge should be capped at max_mult."""
        config = EVPositionSizerConfig()
        mult, cap = compute_ev_multiplier(1.0, config.k, config.min_mult, config.max_mult)
        
        assert mult == config.max_mult
        assert cap == "ev_max_mult"
    
    def test_very_negative_edge_capped_at_min(self):
        """Very negative edge should be capped at min_mult."""
        config = EVPositionSizerConfig()
        mult, cap = compute_ev_multiplier(-1.0, config.k, config.min_mult, config.max_mult)
        
        assert mult == config.min_mult
        assert cap == "ev_min_mult"
