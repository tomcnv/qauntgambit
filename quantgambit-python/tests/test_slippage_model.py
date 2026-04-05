"""
Tests for SlippageModel - Market-state-adaptive slippage estimation.

Requirements: V2 Proposal Section 6 - Market-State-Adaptive Slippage
"""

import pytest
from quantgambit.risk.slippage_model import (
    SlippageModel,
    SlippageEstimate,
    calculate_adverse_selection_bps,
    CostBreakdown,
    calculate_stress_costs,
)


class TestSlippageModel:
    """Tests for SlippageModel."""
    
    def test_symbol_specific_floors(self):
        """Test that different symbols have different base slippage floors."""
        model = SlippageModel()
        
        # BTC should have lowest floor
        btc_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=2.0,
        )
        
        # ETH should have slightly higher floor
        eth_slippage = model.calculate_slippage_bps(
            symbol="ETHUSDT",
            spread_bps=2.0,
        )
        
        # SOL should have higher floor than BTC/ETH
        sol_slippage = model.calculate_slippage_bps(
            symbol="SOLUSDT",
            spread_bps=2.0,
        )
        
        assert btc_slippage < eth_slippage < sol_slippage
        assert btc_slippage == pytest.approx(0.5, abs=0.1)  # BTC floor
        assert eth_slippage == pytest.approx(0.8, abs=0.1)  # ETH floor
        assert sol_slippage == pytest.approx(2.0, abs=0.1)  # SOL floor
    
    def test_spread_factor_calculation(self):
        """Test that wider spreads increase slippage."""
        model = SlippageModel()
        
        # Tight spread (1 bps)
        tight_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=1.0,
        )
        
        # Normal spread (2 bps)
        normal_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=2.0,
        )
        
        # Wide spread (4 bps)
        wide_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=4.0,
        )
        
        # Wider spread should increase slippage
        assert tight_slippage <= normal_slippage <= wide_slippage
    
    def test_depth_factor_calculation(self):
        """Test that order size vs book depth affects slippage."""
        model = SlippageModel()
        
        # Small order relative to depth (1% of depth)
        small_order_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=2.0,
            book_depth_usd=100000.0,
            order_size_usd=1000.0,  # 1% of depth
        )
        
        # Large order relative to depth (10% of depth)
        large_order_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=2.0,
            book_depth_usd=100000.0,
            order_size_usd=10000.0,  # 10% of depth
        )
        
        # Larger order should have more slippage
        assert small_order_slippage < large_order_slippage
    
    def test_volatility_multipliers(self):
        """Test that volatility regime affects slippage."""
        model = SlippageModel()
        
        # Use wider spread to avoid floor clamping
        # Low volatility
        low_vol_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=4.0,  # Wider spread to see multiplier effect
            volatility_regime="low",
        )
        
        # Normal volatility
        normal_vol_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=4.0,
            volatility_regime="normal",
        )
        
        # High volatility
        high_vol_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=4.0,
            volatility_regime="high",
        )
        
        # Extreme volatility
        extreme_vol_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=4.0,
            volatility_regime="extreme",
        )
        
        # Higher volatility should increase slippage
        assert low_vol_slippage < normal_vol_slippage < high_vol_slippage < extreme_vol_slippage
    
    def test_urgency_multipliers(self):
        """Test that execution urgency affects slippage."""
        model = SlippageModel()
        
        # Use wider spread to avoid floor clamping
        # Passive (limit orders, willing to wait)
        passive_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=4.0,  # Wider spread to see multiplier effect
            urgency="passive",
        )
        
        # Patient (limit with timeout)
        patient_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=4.0,
            urgency="patient",
        )
        
        # Immediate (market orders)
        immediate_slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=4.0,
            urgency="immediate",
        )
        
        # More urgent execution should have more slippage
        assert passive_slippage < patient_slippage < immediate_slippage
    
    def test_slippage_never_below_floor(self):
        """Test that slippage never goes below symbol floor."""
        model = SlippageModel()
        
        # Even with best conditions, should not go below floor
        slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=0.5,  # Very tight spread
            volatility_regime="low",
            urgency="passive",
        )
        
        # Should be at or above BTC floor (0.5 bps)
        assert slippage >= 0.5
    
    def test_slippage_with_detail(self):
        """Test detailed slippage breakdown."""
        model = SlippageModel()
        
        estimate = model.calculate_slippage_with_detail(
            symbol="BTCUSDT",
            spread_bps=2.0,
            book_depth_usd=100000.0,
            order_size_usd=5000.0,
            volatility_regime="normal",
            urgency="immediate",
        )
        
        assert isinstance(estimate, SlippageEstimate)
        assert estimate.slippage_bps > 0
        assert estimate.base_bps == 0.5  # BTC floor
        assert estimate.spread_factor >= 1.0
        assert estimate.depth_factor >= 1.0
        assert estimate.volatility_multiplier == 1.0  # Normal
        assert estimate.urgency_multiplier == 1.2  # Immediate
    
    def test_unknown_symbol_uses_default_floor(self):
        """Test that unknown symbols use default floor."""
        model = SlippageModel()
        
        slippage = model.calculate_slippage_bps(
            symbol="UNKNOWNUSDT",
            spread_bps=2.0,
        )
        
        # Should use default floor (2.0 bps)
        assert slippage >= 2.0
    
    def test_none_optional_parameters(self):
        """Test that None optional parameters are handled correctly."""
        model = SlippageModel()
        
        # Should not crash with None values
        slippage = model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=2.0,
            spread_percentile=None,
            book_depth_usd=None,
            order_size_usd=None,
            volatility_regime=None,
            urgency=None,
        )
        
        assert slippage > 0


class TestAdverseSelection:
    """Tests for adverse selection calculation."""
    
    def test_symbol_specific_adverse_selection(self):
        """Test that different symbols have different adverse selection costs."""
        # BTC should have lower adverse selection
        btc_adverse = calculate_adverse_selection_bps(symbol="BTCUSDT")
        
        # SOL should have higher adverse selection
        sol_adverse = calculate_adverse_selection_bps(symbol="SOLUSDT")
        
        assert btc_adverse < sol_adverse
        assert btc_adverse == pytest.approx(1.0, abs=0.1)
        assert sol_adverse == pytest.approx(2.0, abs=0.1)
    
    def test_volatility_increases_adverse_selection(self):
        """Test that higher volatility increases adverse selection."""
        low_vol = calculate_adverse_selection_bps(
            symbol="BTCUSDT",
            volatility_regime="low",
        )
        
        normal_vol = calculate_adverse_selection_bps(
            symbol="BTCUSDT",
            volatility_regime="normal",
        )
        
        high_vol = calculate_adverse_selection_bps(
            symbol="BTCUSDT",
            volatility_regime="high",
        )
        
        extreme_vol = calculate_adverse_selection_bps(
            symbol="BTCUSDT",
            volatility_regime="extreme",
        )
        
        assert low_vol < normal_vol < high_vol < extreme_vol
    
    def test_hold_time_increases_adverse_selection(self):
        """Test that longer hold times increase adverse selection."""
        short_hold = calculate_adverse_selection_bps(
            symbol="BTCUSDT",
            hold_time_expected_sec=60.0,  # 1 minute
        )
        
        medium_hold = calculate_adverse_selection_bps(
            symbol="BTCUSDT",
            hold_time_expected_sec=300.0,  # 5 minutes
        )
        
        long_hold = calculate_adverse_selection_bps(
            symbol="BTCUSDT",
            hold_time_expected_sec=900.0,  # 15 minutes
        )
        
        assert short_hold < medium_hold < long_hold
    
    def test_unknown_symbol_uses_default(self):
        """Test that unknown symbols use default adverse selection."""
        adverse = calculate_adverse_selection_bps(symbol="UNKNOWNUSDT")
        assert adverse == pytest.approx(1.5, abs=0.1)  # Default
    
    def test_none_optional_parameters(self):
        """Test that None optional parameters are handled correctly."""
        # Should not crash with None values
        adverse = calculate_adverse_selection_bps(
            symbol="BTCUSDT",
            volatility_regime=None,
            hold_time_expected_sec=None,
        )
        assert adverse > 0


class TestCostBreakdown:
    """Tests for CostBreakdown dataclass."""
    
    def test_cost_breakdown_creation(self):
        """Test creating a CostBreakdown."""
        breakdown = CostBreakdown(
            fee_bps=10.0,
            spread_bps=0.5,
            slippage_bps=2.0,
            adverse_selection_bps=1.0,
            total_bps=13.5,
        )
        
        assert breakdown.fee_bps == 10.0
        assert breakdown.spread_bps == 0.5
        assert breakdown.slippage_bps == 2.0
        assert breakdown.adverse_selection_bps == 1.0
        assert breakdown.total_bps == 13.5
    
    def test_cost_breakdown_with_detail(self):
        """Test CostBreakdown with slippage detail."""
        slippage_detail = SlippageEstimate(
            slippage_bps=2.0,
            base_bps=0.5,
            spread_factor=1.0,
            depth_factor=1.0,
            volatility_multiplier=1.0,
            urgency_multiplier=1.0,
        )
        
        breakdown = CostBreakdown(
            fee_bps=10.0,
            spread_bps=0.5,
            slippage_bps=2.0,
            adverse_selection_bps=1.0,
            total_bps=13.5,
            slippage_detail=slippage_detail,
        )
        
        assert breakdown.slippage_detail is not None
        assert breakdown.slippage_detail.slippage_bps == 2.0


class TestStressCosts:
    """Tests for stress cost calculation."""
    
    def test_stress_costs_high_spread_percentile(self):
        """Test that high spread percentile increases stress costs."""
        normal_costs = CostBreakdown(
            fee_bps=10.0,
            spread_bps=0.5,
            slippage_bps=2.0,
            adverse_selection_bps=1.0,
            total_bps=13.5,
        )
        
        # High spread percentile (> 70%)
        stress_costs = calculate_stress_costs(
            normal_costs=normal_costs,
            spread_percentile=80.0,
        )
        
        # Fees should not change
        assert stress_costs.fee_bps == normal_costs.fee_bps
        
        # Other costs should increase
        assert stress_costs.spread_bps > normal_costs.spread_bps
        assert stress_costs.slippage_bps > normal_costs.slippage_bps
        assert stress_costs.adverse_selection_bps > normal_costs.adverse_selection_bps
        assert stress_costs.total_bps > normal_costs.total_bps
    
    def test_stress_costs_high_volatility(self):
        """Test that high volatility increases stress costs."""
        normal_costs = CostBreakdown(
            fee_bps=10.0,
            spread_bps=0.5,
            slippage_bps=2.0,
            adverse_selection_bps=1.0,
            total_bps=13.5,
        )
        
        # High volatility
        stress_costs = calculate_stress_costs(
            normal_costs=normal_costs,
            volatility_regime="high",
        )
        
        # Fees should not change
        assert stress_costs.fee_bps == normal_costs.fee_bps
        
        # Other costs should increase
        assert stress_costs.spread_bps > normal_costs.spread_bps
        assert stress_costs.slippage_bps > normal_costs.slippage_bps
        assert stress_costs.adverse_selection_bps > normal_costs.adverse_selection_bps
        assert stress_costs.total_bps > normal_costs.total_bps
    
    def test_stress_costs_extreme_volatility(self):
        """Test that extreme volatility increases stress costs."""
        normal_costs = CostBreakdown(
            fee_bps=10.0,
            spread_bps=0.5,
            slippage_bps=2.0,
            adverse_selection_bps=1.0,
            total_bps=13.5,
        )
        
        # Extreme volatility
        stress_costs = calculate_stress_costs(
            normal_costs=normal_costs,
            volatility_regime="extreme",
        )
        
        # Should have 1.8x multiplier for extreme volatility
        # Only non-fee costs are multiplied: (0.5 + 2.0 + 1.0) * 1.8 = 6.3
        # Total: 10.0 + 6.3 = 16.3
        assert stress_costs.total_bps == pytest.approx(16.3, abs=0.1)
    
    def test_stress_costs_combined_factors(self):
        """Test stress costs with both high spread and high volatility."""
        normal_costs = CostBreakdown(
            fee_bps=10.0,
            spread_bps=0.5,
            slippage_bps=2.0,
            adverse_selection_bps=1.0,
            total_bps=13.5,
        )
        
        # Both high spread percentile and high volatility
        stress_costs = calculate_stress_costs(
            normal_costs=normal_costs,
            spread_percentile=80.0,
            volatility_regime="high",
        )
        
        # Should have multiplicative effect (1.5 * 1.8 = 2.7x)
        # spread_bps: 0.5 * 2.7 = 1.35
        # slippage_bps: 2.0 * 2.7 = 5.4
        # adverse_selection_bps: 1.0 * 2.7 = 2.7
        # total: 10.0 + 1.35 + 5.4 + 2.7 = 19.45
        assert stress_costs.total_bps == pytest.approx(19.45, abs=0.1)
    
    def test_stress_costs_normal_conditions(self):
        """Test that normal conditions don't increase stress costs."""
        normal_costs = CostBreakdown(
            fee_bps=10.0,
            spread_bps=0.5,
            slippage_bps=2.0,
            adverse_selection_bps=1.0,
            total_bps=13.5,
        )
        
        # Normal conditions (low spread percentile, normal volatility)
        stress_costs = calculate_stress_costs(
            normal_costs=normal_costs,
            spread_percentile=50.0,
            volatility_regime="normal",
        )
        
        # Should be same as normal costs (multiplier = 1.0)
        assert stress_costs.total_bps == pytest.approx(normal_costs.total_bps, abs=0.01)
    
    def test_stress_costs_none_parameters(self):
        """Test stress costs with None parameters."""
        normal_costs = CostBreakdown(
            fee_bps=10.0,
            spread_bps=0.5,
            slippage_bps=2.0,
            adverse_selection_bps=1.0,
            total_bps=13.5,
        )
        
        # None parameters should not increase costs
        stress_costs = calculate_stress_costs(
            normal_costs=normal_costs,
            spread_percentile=None,
            volatility_regime=None,
        )
        
        assert stress_costs.total_bps == pytest.approx(normal_costs.total_bps, abs=0.01)


class TestIntegration:
    """Integration tests combining multiple components."""
    
    def test_complete_cost_calculation_btc(self):
        """Test complete cost calculation for BTC trade."""
        slippage_model = SlippageModel()
        
        # BTC trade in normal conditions
        slippage_bps = slippage_model.calculate_slippage_bps(
            symbol="BTCUSDT",
            spread_bps=1.0,
            book_depth_usd=500000.0,
            order_size_usd=10000.0,  # 2% of depth
            volatility_regime="normal",
            urgency="immediate",
        )
        
        adverse_selection_bps = calculate_adverse_selection_bps(
            symbol="BTCUSDT",
            volatility_regime="normal",
            hold_time_expected_sec=180.0,  # 3 minutes
        )
        
        # Assume fees from FeeModel: ~10 bps
        # Spread: 1.0 bps
        # Slippage: calculated above
        # Adverse selection: calculated above
        
        total_cost_bps = 10.0 + 1.0 + slippage_bps + adverse_selection_bps
        
        # Total should be reasonable (10-15 bps for BTC in normal conditions)
        assert 10.0 <= total_cost_bps <= 15.0
    
    def test_complete_cost_calculation_sol(self):
        """Test complete cost calculation for SOL trade."""
        slippage_model = SlippageModel()
        
        # SOL trade in high volatility
        slippage_bps = slippage_model.calculate_slippage_bps(
            symbol="SOLUSDT",
            spread_bps=3.0,
            book_depth_usd=100000.0,
            order_size_usd=5000.0,  # 5% of depth
            volatility_regime="high",
            urgency="immediate",
        )
        
        adverse_selection_bps = calculate_adverse_selection_bps(
            symbol="SOLUSDT",
            volatility_regime="high",
            hold_time_expected_sec=300.0,  # 5 minutes
        )
        
        # Assume fees: ~10 bps
        # Spread: 3.0 bps
        # Slippage: higher for SOL
        # Adverse selection: higher for SOL
        
        total_cost_bps = 10.0 + 3.0 + slippage_bps + adverse_selection_bps
        
        # Total should be higher for SOL in high vol (15-25 bps)
        assert 15.0 <= total_cost_bps <= 30.0
