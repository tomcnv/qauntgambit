"""
Integration tests for Dual Threshold behavior.

Tests the end-to-end behavior of regime-relative dual thresholds
in the strategy signal architecture.

Requirements: 2.1-2.12 (Regime-Relative Thresholds with Setup vs Profitability Split)
"""

import pytest
from dataclasses import dataclass
from typing import Optional

from quantgambit.signals.services.threshold_calculator import (
    ThresholdCalculator,
    ThresholdConfig,
    DualThreshold,
)
from quantgambit.deeptrader_core.types import (
    Features,
    AccountState,
    Profile,
    CandidateSignal,
)
from quantgambit.deeptrader_core.strategies.mean_reversion_fade import MeanReversionFade


@pytest.fixture
def threshold_calculator():
    """Create a ThresholdCalculator with default config."""
    return ThresholdCalculator()


@pytest.fixture
def mean_reversion_strategy():
    """Create a MeanReversionFade strategy instance."""
    return MeanReversionFade()


@pytest.fixture
def base_features():
    """Create base Features for testing."""
    return Features(
        symbol="BTCUSDT",
        price=50000.0,
        spread=0.0001,  # 1 bps spread
        rotation_factor=0.5,
        position_in_value="above",
        distance_to_poc=100.0,  # $100 above POC
        distance_to_vah=50.0,
        distance_to_val=200.0,
        value_area_high=50050.0,
        value_area_low=49950.0,
        point_of_control=49900.0,
        atr_5m=50.0,
        atr_5m_baseline=50.0,
        orderflow_imbalance=0.3,
    )


@pytest.fixture
def account_state():
    """Create AccountState for testing."""
    return AccountState(
        equity=100000.0,
        daily_pnl=0.0,
        max_daily_loss=5000.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )


@pytest.fixture
def profile():
    """Create Profile for testing."""
    return Profile(
        id="test_profile",
        trend="flat",
        volatility="normal",
        value_location="above",
        session="us",
        risk_mode="normal",
    )


class TestDualThresholdCalculation:
    """Tests for dual threshold calculation in various market conditions."""
    
    def test_tight_va_high_cost_scenario(self, threshold_calculator):
        """Test dual threshold with tight VA and high costs.
        
        Scenario: Tight market with high costs
        - VA width = 50 bps (tight)
        - Expected cost = 20 bps (high)
        
        Expected:
        - va_component = 0.25 * 50 = 12.5 bps
        - setup = max(12.5, 12) = 12.5 bps (va_width binding)
        - cost_component = 3.0 * 20 = 60 bps
        - profitability = max(60, 12.5) = 60 bps (cost binding)
        
        Validates: Requirements 2.1, 2.2, 2.3
        """
        result = threshold_calculator.calculate_dual_threshold(
            expected_cost_bps=20.0,
            va_width_bps=50.0,
        )
        
        assert result.setup_threshold_bps == 12.5
        assert result.profitability_threshold_bps == 60.0
        assert result.setup_binding_constraint == "va_width"
        assert result.profit_binding_constraint == "cost"
    
    def test_wide_va_low_cost_scenario(self, threshold_calculator):
        """Test dual threshold with wide VA and low costs.
        
        Scenario: Wide market with low costs
        - VA width = 200 bps (wide)
        - Expected cost = 8 bps (low)
        
        Expected:
        - va_component = 0.25 * 200 = 50 bps
        - setup = max(50, 12) = 50 bps (va_width binding)
        - cost_component = 3.0 * 8 = 24 bps
        - profitability = max(24, 50) = 50 bps (setup binding)
        
        Validates: Requirements 2.1, 2.2, 2.3
        """
        result = threshold_calculator.calculate_dual_threshold(
            expected_cost_bps=8.0,
            va_width_bps=200.0,
        )
        
        assert result.setup_threshold_bps == 50.0
        assert result.profitability_threshold_bps == 50.0
        assert result.setup_binding_constraint == "va_width"
        assert result.profit_binding_constraint == "setup"
    
    def test_floor_binding_scenario(self, threshold_calculator):
        """Test dual threshold when floor is binding.
        
        Scenario: Very tight market
        - VA width = 30 bps (very tight)
        - Expected cost = 10 bps
        
        Expected:
        - va_component = 0.25 * 30 = 7.5 bps
        - setup = max(7.5, 12) = 12 bps (floor binding)
        - cost_component = 3.0 * 10 = 30 bps
        - profitability = max(30, 12) = 30 bps (cost binding)
        
        Validates: Requirements 2.2, 2.7
        """
        result = threshold_calculator.calculate_dual_threshold(
            expected_cost_bps=10.0,
            va_width_bps=30.0,
        )
        
        assert result.setup_threshold_bps == 12.0
        assert result.profitability_threshold_bps == 30.0
        assert result.setup_binding_constraint == "floor"
        assert result.profit_binding_constraint == "cost"
    
    def test_custom_config_scenario(self, threshold_calculator):
        """Test dual threshold with custom configuration.
        
        Custom config: k=2.0, b=0.3, floor_bps=15.0
        - VA width = 100 bps
        - Expected cost = 12 bps
        
        Expected:
        - va_component = 0.3 * 100 = 30 bps
        - setup = max(30, 15) = 30 bps (va_width binding)
        - cost_component = 2.0 * 12 = 24 bps
        - profitability = max(24, 30) = 30 bps (setup binding)
        
        Validates: Requirements 2.6
        """
        config = ThresholdConfig(k=2.0, b=0.3, floor_bps=15.0)
        
        result = threshold_calculator.calculate_dual_threshold(
            expected_cost_bps=12.0,
            va_width_bps=100.0,
            config=config,
        )
        
        assert result.setup_threshold_bps == 30.0
        assert result.profitability_threshold_bps == 30.0
        assert result.setup_binding_constraint == "va_width"
        assert result.profit_binding_constraint == "setup"


class TestStrategyDualThresholdIntegration:
    """Tests for strategy integration with dual thresholds."""
    
    def test_candidate_generated_above_setup_threshold(
        self,
        mean_reversion_strategy,
        base_features,
        account_state,
        profile,
    ):
        """Test that candidate is generated when distance > setup_threshold.
        
        Validates: Requirements 2.10
        """
        # Set up features with distance above setup threshold
        # VA width = (50050 - 49950) / 50000 * 10000 = 20 bps
        # setup_threshold = max(0.25 * 20, 12) = 12 bps
        # distance = 100 / 50000 * 10000 = 20 bps > 12 bps
        features = Features(
            symbol="BTCUSDT",
            price=50000.0,
            spread=0.0001,
            rotation_factor=0.5,
            position_in_value="above",
            distance_to_poc=100.0,  # 20 bps
            distance_to_vah=50.0,
            distance_to_val=200.0,
            value_area_high=50050.0,
            value_area_low=49950.0,
            point_of_control=49900.0,
            atr_5m=50.0,
            atr_5m_baseline=50.0,
            orderflow_imbalance=0.3,
        )
        
        params = {
            "allow_shorts": True,
            "max_spread": 0.01,
            "max_atr_ratio": 2.0,
        }
        
        candidate = mean_reversion_strategy.generate_candidate(
            features=features,
            account=account_state,
            profile=profile,
            params=params,
        )
        
        assert candidate is not None
        assert candidate.side == "short"  # Price above POC -> short
        assert candidate.profitability_threshold_bps is not None
        assert candidate.profitability_threshold_bps > 0
    
    def test_candidate_rejected_below_setup_threshold(
        self,
        mean_reversion_strategy,
        base_features,
        account_state,
        profile,
    ):
        """Test that candidate is rejected when distance < setup_threshold.
        
        Validates: Requirements 2.10
        """
        # Set up features with distance below setup threshold
        # VA width = (50050 - 49950) / 50000 * 10000 = 20 bps
        # setup_threshold = max(0.25 * 20, 12) = 12 bps
        # distance = 25 / 50000 * 10000 = 5 bps < 12 bps
        features = Features(
            symbol="BTCUSDT",
            price=50000.0,
            spread=0.0001,
            rotation_factor=0.5,
            position_in_value="above",
            distance_to_poc=25.0,  # 5 bps - below threshold
            distance_to_vah=50.0,
            distance_to_val=200.0,
            value_area_high=50050.0,
            value_area_low=49950.0,
            point_of_control=49975.0,  # Close to price
            atr_5m=50.0,
            atr_5m_baseline=50.0,
            orderflow_imbalance=0.3,
        )
        
        params = {
            "allow_shorts": True,
            "max_spread": 0.01,
            "max_atr_ratio": 2.0,
        }
        
        candidate = mean_reversion_strategy.generate_candidate(
            features=features,
            account=account_state,
            profile=profile,
            params=params,
        )
        
        assert candidate is None
    
    def test_profitability_threshold_passed_to_candidate(
        self,
        mean_reversion_strategy,
        base_features,
        account_state,
        profile,
    ):
        """Test that profitability_threshold_bps is included in CandidateSignal.
        
        Validates: Requirements 2.11
        """
        # Set up features with sufficient distance
        features = Features(
            symbol="BTCUSDT",
            price=50000.0,
            spread=0.0001,
            rotation_factor=0.5,
            position_in_value="above",
            distance_to_poc=200.0,  # 40 bps - well above threshold
            distance_to_vah=50.0,
            distance_to_val=200.0,
            value_area_high=50100.0,
            value_area_low=49900.0,  # 40 bps VA width
            point_of_control=49800.0,
            atr_5m=50.0,
            atr_5m_baseline=50.0,
            orderflow_imbalance=0.3,
        )
        
        params = {
            "allow_shorts": True,
            "max_spread": 0.01,
            "max_atr_ratio": 2.0,
            "expected_cost_bps": 13.0,  # Explicit cost
        }
        
        candidate = mean_reversion_strategy.generate_candidate(
            features=features,
            account=account_state,
            profile=profile,
            params=params,
        )
        
        assert candidate is not None
        assert candidate.profitability_threshold_bps is not None
        
        # Verify profitability threshold calculation
        # VA width = (50100 - 49900) / 50000 * 10000 = 40 bps
        # setup = max(0.25 * 40, 12) = max(10, 12) = 12 bps
        # cost_component = 3.0 * 13 = 39 bps
        # profitability = max(39, 12) = 39 bps
        assert candidate.profitability_threshold_bps == pytest.approx(39.0, rel=0.1)
    
    def test_custom_threshold_config_in_params(
        self,
        mean_reversion_strategy,
        base_features,
        account_state,
        profile,
    ):
        """Test that custom threshold config from params is used.
        
        Validates: Requirements 2.6
        """
        features = Features(
            symbol="BTCUSDT",
            price=50000.0,
            spread=0.0001,
            rotation_factor=0.5,
            position_in_value="above",
            distance_to_poc=200.0,  # 40 bps
            distance_to_vah=50.0,
            distance_to_val=200.0,
            value_area_high=50100.0,
            value_area_low=49900.0,  # 40 bps VA width
            point_of_control=49800.0,
            atr_5m=50.0,
            atr_5m_baseline=50.0,
            orderflow_imbalance=0.3,
        )
        
        # Custom threshold params
        params = {
            "allow_shorts": True,
            "max_spread": 0.01,
            "max_atr_ratio": 2.0,
            "expected_cost_bps": 10.0,
            "threshold_k": 2.0,  # Lower cost multiplier
            "threshold_b": 0.3,  # Higher VA multiplier
            "threshold_floor_bps": 15.0,  # Higher floor
        }
        
        candidate = mean_reversion_strategy.generate_candidate(
            features=features,
            account=account_state,
            profile=profile,
            params=params,
        )
        
        assert candidate is not None
        
        # Verify custom config was used
        # VA width = 40 bps
        # setup = max(0.3 * 40, 15) = max(12, 15) = 15 bps
        # cost_component = 2.0 * 10 = 20 bps
        # profitability = max(20, 15) = 20 bps
        assert candidate.profitability_threshold_bps == pytest.approx(20.0, rel=0.1)


class TestDualThresholdEdgeCases:
    """Tests for edge cases in dual threshold calculation."""
    
    def test_zero_va_width_uses_floor(self, threshold_calculator):
        """Test that zero VA width falls back to floor.
        
        Validates: Requirements 2.7
        """
        result = threshold_calculator.calculate_dual_threshold(
            expected_cost_bps=10.0,
            va_width_bps=0.0,
        )
        
        assert result.setup_threshold_bps == 12.0  # floor
        assert result.setup_binding_constraint == "floor"
    
    def test_zero_cost_uses_setup_threshold(self, threshold_calculator):
        """Test that zero cost uses setup threshold for profitability.
        
        Validates: Requirements 2.3
        """
        result = threshold_calculator.calculate_dual_threshold(
            expected_cost_bps=0.0,
            va_width_bps=100.0,
        )
        
        # setup = max(0.25 * 100, 12) = 25 bps
        # profitability = max(0, 25) = 25 bps
        assert result.setup_threshold_bps == 25.0
        assert result.profitability_threshold_bps == 25.0
        assert result.profit_binding_constraint == "setup"
    
    def test_very_high_cost_dominates(self, threshold_calculator):
        """Test that very high costs dominate the profitability threshold.
        
        Validates: Requirements 2.3
        """
        result = threshold_calculator.calculate_dual_threshold(
            expected_cost_bps=50.0,  # Very high cost
            va_width_bps=100.0,
        )
        
        # setup = max(0.25 * 100, 12) = 25 bps
        # cost_component = 3.0 * 50 = 150 bps
        # profitability = max(150, 25) = 150 bps
        assert result.setup_threshold_bps == 25.0
        assert result.profitability_threshold_bps == 150.0
        assert result.profit_binding_constraint == "cost"
    
    def test_very_wide_va_dominates(self, threshold_calculator):
        """Test that very wide VA dominates both thresholds.
        
        Validates: Requirements 2.2, 2.3
        """
        result = threshold_calculator.calculate_dual_threshold(
            expected_cost_bps=10.0,
            va_width_bps=500.0,  # Very wide VA
        )
        
        # setup = max(0.25 * 500, 12) = 125 bps
        # cost_component = 3.0 * 10 = 30 bps
        # profitability = max(30, 125) = 125 bps
        assert result.setup_threshold_bps == 125.0
        assert result.profitability_threshold_bps == 125.0
        assert result.setup_binding_constraint == "va_width"
        assert result.profit_binding_constraint == "setup"


class TestVAWidthCalculation:
    """Tests for VA width calculation from prices."""
    
    def test_va_width_from_prices(self, threshold_calculator):
        """Test VA width calculation from VAH, VAL, and mid_price.
        
        Validates: Requirements 2.5
        """
        # BTC at $50,000 with $100 VA width
        va_width = threshold_calculator.calculate_va_width_bps(
            vah=50050.0,
            val=49950.0,
            mid_price=50000.0,
        )
        
        # (50050 - 49950) / 50000 * 10000 = 20 bps
        assert va_width == pytest.approx(20.0)
    
    def test_va_width_percentage_of_price(self, threshold_calculator):
        """Test VA width as percentage of price.
        
        Validates: Requirements 2.5
        """
        # 1% VA width
        va_width = threshold_calculator.calculate_va_width_bps(
            vah=50500.0,
            val=49500.0,
            mid_price=50000.0,
        )
        
        # (50500 - 49500) / 50000 * 10000 = 200 bps = 2%
        assert va_width == pytest.approx(200.0)
    
    def test_va_width_handles_zero_mid_price(self, threshold_calculator):
        """Test VA width calculation with zero mid price.
        
        Validates: Requirements 2.5
        """
        va_width = threshold_calculator.calculate_va_width_bps(
            vah=50050.0,
            val=49950.0,
            mid_price=0.0,
        )
        
        assert va_width == 0.0
