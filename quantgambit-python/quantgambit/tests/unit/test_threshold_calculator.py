"""
Unit tests for ThresholdCalculator - Regime-Relative Dual Thresholds

Tests the dual threshold calculation for strategy signal architecture.

Requirements: 2.1-2.12 (Regime-Relative Thresholds with Setup vs Profitability Split)
"""

import pytest
from quantgambit.signals.services.threshold_calculator import (
    ThresholdConfig,
    DualThreshold,
    ThresholdCalculator,
    get_threshold_calculator,
)


class TestThresholdConfig:
    """Tests for ThresholdConfig dataclass."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = ThresholdConfig()
        assert config.k == 3.0
        assert config.b == 0.25
        assert config.floor_bps == 12.0
    
    def test_custom_values(self):
        """Test custom configuration values."""
        config = ThresholdConfig(k=2.5, b=0.3, floor_bps=15.0)
        assert config.k == 2.5
        assert config.b == 0.3
        assert config.floor_bps == 15.0
    
    def test_invalid_k_raises_error(self):
        """Test that non-positive k raises ValueError."""
        with pytest.raises(ValueError, match="k must be positive"):
            ThresholdConfig(k=0)
        with pytest.raises(ValueError, match="k must be positive"):
            ThresholdConfig(k=-1.0)
    
    def test_invalid_b_raises_error(self):
        """Test that negative b raises ValueError."""
        with pytest.raises(ValueError, match="b must be non-negative"):
            ThresholdConfig(b=-0.1)
    
    def test_invalid_floor_bps_raises_error(self):
        """Test that negative floor_bps raises ValueError."""
        with pytest.raises(ValueError, match="floor_bps must be non-negative"):
            ThresholdConfig(floor_bps=-5.0)


class TestDualThreshold:
    """Tests for DualThreshold dataclass."""
    
    def test_valid_dual_threshold(self):
        """Test creating a valid DualThreshold."""
        dt = DualThreshold(
            setup_threshold_bps=15.0,
            profitability_threshold_bps=30.0,
            va_component_bps=15.0,
            cost_component_bps=30.0,
            floor_component_bps=12.0,
            setup_binding_constraint="va_width",
            profit_binding_constraint="cost",
        )
        assert dt.setup_threshold_bps == 15.0
        assert dt.profitability_threshold_bps == 30.0
        assert dt.setup_binding_constraint == "va_width"
        assert dt.profit_binding_constraint == "cost"
    
    def test_negative_setup_threshold_raises_error(self):
        """Test that negative setup_threshold_bps raises ValueError."""
        with pytest.raises(ValueError, match="setup_threshold_bps must be non-negative"):
            DualThreshold(
                setup_threshold_bps=-1.0,
                profitability_threshold_bps=30.0,
                va_component_bps=15.0,
                cost_component_bps=30.0,
                floor_component_bps=12.0,
                setup_binding_constraint="va_width",
                profit_binding_constraint="cost",
            )
    
    def test_profitability_less_than_setup_raises_error(self):
        """Test that profitability < setup raises ValueError."""
        with pytest.raises(ValueError, match="profitability_threshold_bps .* must be >= setup_threshold_bps"):
            DualThreshold(
                setup_threshold_bps=30.0,
                profitability_threshold_bps=15.0,  # Less than setup
                va_component_bps=30.0,
                cost_component_bps=15.0,
                floor_component_bps=12.0,
                setup_binding_constraint="va_width",
                profit_binding_constraint="setup",
            )
    
    def test_invalid_setup_binding_constraint_raises_error(self):
        """Test that invalid setup_binding_constraint raises ValueError."""
        with pytest.raises(ValueError, match="setup_binding_constraint must be"):
            DualThreshold(
                setup_threshold_bps=15.0,
                profitability_threshold_bps=30.0,
                va_component_bps=15.0,
                cost_component_bps=30.0,
                floor_component_bps=12.0,
                setup_binding_constraint="invalid",
                profit_binding_constraint="cost",
            )
    
    def test_invalid_profit_binding_constraint_raises_error(self):
        """Test that invalid profit_binding_constraint raises ValueError."""
        with pytest.raises(ValueError, match="profit_binding_constraint must be"):
            DualThreshold(
                setup_threshold_bps=15.0,
                profitability_threshold_bps=30.0,
                va_component_bps=15.0,
                cost_component_bps=30.0,
                floor_component_bps=12.0,
                setup_binding_constraint="va_width",
                profit_binding_constraint="invalid",
            )


class TestThresholdCalculator:
    """Tests for ThresholdCalculator class."""
    
    @pytest.fixture
    def calculator(self):
        """Create a ThresholdCalculator with default config."""
        return ThresholdCalculator()
    
    @pytest.fixture
    def custom_calculator(self):
        """Create a ThresholdCalculator with custom config."""
        config = ThresholdConfig(k=2.0, b=0.2, floor_bps=10.0)
        return ThresholdCalculator(default_config=config)
    
    # =========================================================================
    # calculate_setup_threshold tests
    # =========================================================================
    
    def test_setup_threshold_va_width_binding(self, calculator):
        """Test setup threshold when VA width component is binding.
        
        Validates: Requirements 2.2, 2.8
        """
        # VA width = 100 bps, b = 0.25 -> va_component = 25 bps
        # floor = 12 bps
        # max(25, 12) = 25 -> va_width binding
        threshold, binding = calculator.calculate_setup_threshold(
            va_width_bps=100.0,
            b=0.25,
            floor_bps=12.0,
        )
        assert threshold == 25.0
        assert binding == "va_width"
    
    def test_setup_threshold_floor_binding(self, calculator):
        """Test setup threshold when floor is binding.
        
        Validates: Requirements 2.2, 2.8
        """
        # VA width = 40 bps, b = 0.25 -> va_component = 10 bps
        # floor = 12 bps
        # max(10, 12) = 12 -> floor binding
        threshold, binding = calculator.calculate_setup_threshold(
            va_width_bps=40.0,
            b=0.25,
            floor_bps=12.0,
        )
        assert threshold == 12.0
        assert binding == "floor"
    
    def test_setup_threshold_equal_components(self, calculator):
        """Test setup threshold when components are equal.
        
        When equal, va_width should be the binding constraint.
        """
        # VA width = 48 bps, b = 0.25 -> va_component = 12 bps
        # floor = 12 bps
        # max(12, 12) = 12 -> va_width binding (>= comparison)
        threshold, binding = calculator.calculate_setup_threshold(
            va_width_bps=48.0,
            b=0.25,
            floor_bps=12.0,
        )
        assert threshold == 12.0
        assert binding == "va_width"
    
    def test_setup_threshold_zero_va_width(self, calculator):
        """Test setup threshold with zero VA width."""
        threshold, binding = calculator.calculate_setup_threshold(
            va_width_bps=0.0,
            b=0.25,
            floor_bps=12.0,
        )
        assert threshold == 12.0
        assert binding == "floor"
    
    # =========================================================================
    # calculate_profitability_threshold tests
    # =========================================================================
    
    def test_profitability_threshold_cost_binding(self, calculator):
        """Test profitability threshold when cost component is binding.
        
        Validates: Requirements 2.3, 2.9
        """
        # expected_cost = 15 bps, k = 3.0 -> cost_component = 45 bps
        # setup_threshold = 20 bps
        # max(45, 20) = 45 -> cost binding
        threshold, binding = calculator.calculate_profitability_threshold(
            expected_cost_bps=15.0,
            setup_threshold_bps=20.0,
            k=3.0,
        )
        assert threshold == 45.0
        assert binding == "cost"
    
    def test_profitability_threshold_setup_binding(self, calculator):
        """Test profitability threshold when setup threshold is binding.
        
        Validates: Requirements 2.3, 2.9
        """
        # expected_cost = 5 bps, k = 3.0 -> cost_component = 15 bps
        # setup_threshold = 25 bps
        # max(15, 25) = 25 -> setup binding
        threshold, binding = calculator.calculate_profitability_threshold(
            expected_cost_bps=5.0,
            setup_threshold_bps=25.0,
            k=3.0,
        )
        assert threshold == 25.0
        assert binding == "setup"
    
    def test_profitability_threshold_equal_components(self, calculator):
        """Test profitability threshold when components are equal.
        
        When equal, cost should be the binding constraint.
        """
        # expected_cost = 10 bps, k = 3.0 -> cost_component = 30 bps
        # setup_threshold = 30 bps
        # max(30, 30) = 30 -> cost binding (>= comparison)
        threshold, binding = calculator.calculate_profitability_threshold(
            expected_cost_bps=10.0,
            setup_threshold_bps=30.0,
            k=3.0,
        )
        assert threshold == 30.0
        assert binding == "cost"
    
    def test_profitability_threshold_zero_cost(self, calculator):
        """Test profitability threshold with zero cost."""
        threshold, binding = calculator.calculate_profitability_threshold(
            expected_cost_bps=0.0,
            setup_threshold_bps=20.0,
            k=3.0,
        )
        assert threshold == 20.0
        assert binding == "setup"
    
    # =========================================================================
    # calculate_dual_threshold tests
    # =========================================================================
    
    def test_dual_threshold_cost_binding_scenario(self, calculator):
        """Test dual threshold calculation with cost binding.
        
        Scenario: Wide VA, high costs
        - VA width = 100 bps, b = 0.25 -> va_component = 25 bps
        - floor = 12 bps -> setup = max(25, 12) = 25 bps (va_width binding)
        - expected_cost = 15 bps, k = 3.0 -> cost_component = 45 bps
        - profitability = max(45, 25) = 45 bps (cost binding)
        
        Validates: Requirements 2.1, 2.2, 2.3
        """
        result = calculator.calculate_dual_threshold(
            expected_cost_bps=15.0,
            va_width_bps=100.0,
        )
        
        assert result.setup_threshold_bps == 25.0
        assert result.profitability_threshold_bps == 45.0
        assert result.va_component_bps == 25.0
        assert result.cost_component_bps == 45.0
        assert result.floor_component_bps == 12.0
        assert result.setup_binding_constraint == "va_width"
        assert result.profit_binding_constraint == "cost"
    
    def test_dual_threshold_setup_binding_scenario(self, calculator):
        """Test dual threshold calculation with setup binding.
        
        Scenario: Wide VA, low costs
        - VA width = 200 bps, b = 0.25 -> va_component = 50 bps
        - floor = 12 bps -> setup = max(50, 12) = 50 bps (va_width binding)
        - expected_cost = 10 bps, k = 3.0 -> cost_component = 30 bps
        - profitability = max(30, 50) = 50 bps (setup binding)
        
        Validates: Requirements 2.1, 2.2, 2.3
        """
        result = calculator.calculate_dual_threshold(
            expected_cost_bps=10.0,
            va_width_bps=200.0,
        )
        
        assert result.setup_threshold_bps == 50.0
        assert result.profitability_threshold_bps == 50.0
        assert result.va_component_bps == 50.0
        assert result.cost_component_bps == 30.0
        assert result.floor_component_bps == 12.0
        assert result.setup_binding_constraint == "va_width"
        assert result.profit_binding_constraint == "setup"
    
    def test_dual_threshold_floor_binding_scenario(self, calculator):
        """Test dual threshold calculation with floor binding.
        
        Scenario: Tight VA, moderate costs
        - VA width = 40 bps, b = 0.25 -> va_component = 10 bps
        - floor = 12 bps -> setup = max(10, 12) = 12 bps (floor binding)
        - expected_cost = 10 bps, k = 3.0 -> cost_component = 30 bps
        - profitability = max(30, 12) = 30 bps (cost binding)
        
        Validates: Requirements 2.1, 2.2, 2.3
        """
        result = calculator.calculate_dual_threshold(
            expected_cost_bps=10.0,
            va_width_bps=40.0,
        )
        
        assert result.setup_threshold_bps == 12.0
        assert result.profitability_threshold_bps == 30.0
        assert result.va_component_bps == 10.0
        assert result.cost_component_bps == 30.0
        assert result.floor_component_bps == 12.0
        assert result.setup_binding_constraint == "floor"
        assert result.profit_binding_constraint == "cost"
    
    def test_dual_threshold_with_custom_config(self, custom_calculator):
        """Test dual threshold with custom configuration.
        
        Custom config: k=2.0, b=0.2, floor_bps=10.0
        - VA width = 100 bps, b = 0.2 -> va_component = 20 bps
        - floor = 10 bps -> setup = max(20, 10) = 20 bps
        - expected_cost = 15 bps, k = 2.0 -> cost_component = 30 bps
        - profitability = max(30, 20) = 30 bps
        """
        result = custom_calculator.calculate_dual_threshold(
            expected_cost_bps=15.0,
            va_width_bps=100.0,
        )
        
        assert result.setup_threshold_bps == 20.0
        assert result.profitability_threshold_bps == 30.0
        assert result.va_component_bps == 20.0
        assert result.cost_component_bps == 30.0
        assert result.floor_component_bps == 10.0
    
    def test_dual_threshold_with_explicit_config(self, calculator):
        """Test dual threshold with explicitly passed config."""
        config = ThresholdConfig(k=4.0, b=0.3, floor_bps=15.0)
        
        result = calculator.calculate_dual_threshold(
            expected_cost_bps=10.0,
            va_width_bps=100.0,
            config=config,
        )
        
        # va_component = 0.3 * 100 = 30 bps
        # setup = max(30, 15) = 30 bps
        # cost_component = 4.0 * 10 = 40 bps
        # profitability = max(40, 30) = 40 bps
        assert result.setup_threshold_bps == 30.0
        assert result.profitability_threshold_bps == 40.0
        assert result.va_component_bps == 30.0
        assert result.cost_component_bps == 40.0
        assert result.floor_component_bps == 15.0
    
    def test_dual_threshold_zero_inputs(self, calculator):
        """Test dual threshold with zero inputs."""
        result = calculator.calculate_dual_threshold(
            expected_cost_bps=0.0,
            va_width_bps=0.0,
        )
        
        # va_component = 0.25 * 0 = 0 bps
        # setup = max(0, 12) = 12 bps (floor binding)
        # cost_component = 3.0 * 0 = 0 bps
        # profitability = max(0, 12) = 12 bps (setup binding)
        assert result.setup_threshold_bps == 12.0
        assert result.profitability_threshold_bps == 12.0
        assert result.setup_binding_constraint == "floor"
        assert result.profit_binding_constraint == "setup"
    
    # =========================================================================
    # calculate_va_width_bps tests
    # =========================================================================
    
    def test_calculate_va_width_bps(self, calculator):
        """Test VA width calculation in bps.
        
        Validates: Requirements 2.5
        """
        # VAH = 100.50, VAL = 99.50, mid = 100.00
        # VA width = (100.50 - 99.50) / 100.00 * 10000 = 100 bps
        va_width = calculator.calculate_va_width_bps(
            vah=100.50,
            val=99.50,
            mid_price=100.00,
        )
        assert va_width == pytest.approx(100.0)
    
    def test_calculate_va_width_bps_tight_market(self, calculator):
        """Test VA width calculation for tight market."""
        # VAH = 100.10, VAL = 99.90, mid = 100.00
        # VA width = (100.10 - 99.90) / 100.00 * 10000 = 20 bps
        va_width = calculator.calculate_va_width_bps(
            vah=100.10,
            val=99.90,
            mid_price=100.00,
        )
        assert va_width == pytest.approx(20.0)
    
    def test_calculate_va_width_bps_wide_market(self, calculator):
        """Test VA width calculation for wide market."""
        # VAH = 102.00, VAL = 98.00, mid = 100.00
        # VA width = (102.00 - 98.00) / 100.00 * 10000 = 400 bps
        va_width = calculator.calculate_va_width_bps(
            vah=102.00,
            val=98.00,
            mid_price=100.00,
        )
        assert va_width == pytest.approx(400.0)
    
    def test_calculate_va_width_bps_zero_mid_price(self, calculator):
        """Test VA width calculation with zero mid price."""
        va_width = calculator.calculate_va_width_bps(
            vah=100.50,
            val=99.50,
            mid_price=0.0,
        )
        assert va_width == 0.0
    
    # =========================================================================
    # Singleton tests
    # =========================================================================
    
    def test_get_threshold_calculator_singleton(self):
        """Test that get_threshold_calculator returns a singleton."""
        calc1 = get_threshold_calculator()
        calc2 = get_threshold_calculator()
        assert calc1 is calc2


class TestDualThresholdIntegration:
    """Integration tests for dual threshold calculation."""
    
    def test_realistic_btc_scenario(self):
        """Test with realistic BTC market conditions.
        
        BTC at $100,000:
        - VAH = $100,500, VAL = $99,500 -> VA width = 100 bps
        - Expected cost = 13 bps (7 bps fees + 3 bps spread + 3 bps slippage)
        
        With default config (k=3.0, b=0.25, floor=12):
        - va_component = 0.25 * 100 = 25 bps
        - setup = max(25, 12) = 25 bps
        - cost_component = 3.0 * 13 = 39 bps
        - profitability = max(39, 25) = 39 bps
        """
        calculator = ThresholdCalculator()
        
        va_width = calculator.calculate_va_width_bps(
            vah=100500.0,
            val=99500.0,
            mid_price=100000.0,
        )
        assert va_width == pytest.approx(100.0)
        
        result = calculator.calculate_dual_threshold(
            expected_cost_bps=13.0,
            va_width_bps=va_width,
        )
        
        assert result.setup_threshold_bps == 25.0
        assert result.profitability_threshold_bps == 39.0
        assert result.setup_binding_constraint == "va_width"
        assert result.profit_binding_constraint == "cost"
    
    def test_tight_spread_low_cost_scenario(self):
        """Test with tight spread and low cost conditions.
        
        Tight market:
        - VA width = 50 bps
        - Expected cost = 8 bps (low fees, tight spread)
        
        With default config:
        - va_component = 0.25 * 50 = 12.5 bps
        - setup = max(12.5, 12) = 12.5 bps (va_width binding)
        - cost_component = 3.0 * 8 = 24 bps
        - profitability = max(24, 12.5) = 24 bps (cost binding)
        """
        calculator = ThresholdCalculator()
        
        result = calculator.calculate_dual_threshold(
            expected_cost_bps=8.0,
            va_width_bps=50.0,
        )
        
        assert result.setup_threshold_bps == 12.5
        assert result.profitability_threshold_bps == 24.0
        assert result.setup_binding_constraint == "va_width"
        assert result.profit_binding_constraint == "cost"
    
    def test_wide_va_low_cost_scenario(self):
        """Test with wide VA and low cost conditions.
        
        Wide market:
        - VA width = 300 bps
        - Expected cost = 10 bps
        
        With default config:
        - va_component = 0.25 * 300 = 75 bps
        - setup = max(75, 12) = 75 bps (va_width binding)
        - cost_component = 3.0 * 10 = 30 bps
        - profitability = max(30, 75) = 75 bps (setup binding)
        
        In this case, the setup threshold is so high that it also
        becomes the profitability threshold.
        """
        calculator = ThresholdCalculator()
        
        result = calculator.calculate_dual_threshold(
            expected_cost_bps=10.0,
            va_width_bps=300.0,
        )
        
        assert result.setup_threshold_bps == 75.0
        assert result.profitability_threshold_bps == 75.0
        assert result.setup_binding_constraint == "va_width"
        assert result.profit_binding_constraint == "setup"
