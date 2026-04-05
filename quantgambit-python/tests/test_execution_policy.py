"""
Tests for ExecutionPolicy and expected fee calculation.

Requirements: V2 Proposal Section 5 - Execution Policy Integration
"""

import pytest
from quantgambit.execution.execution_policy import (
    ExecutionPolicy,
    ExecutionPlan,
    calculate_expected_fees_bps,
)
from quantgambit.risk.fee_model import FeeModel, FeeConfig


class TestExecutionPolicy:
    """Tests for ExecutionPolicy."""
    
    def test_mean_reversion_plan(self):
        """Test execution plan for mean reversion strategy."""
        policy = ExecutionPolicy()
        plan = policy.plan_execution(
            strategy_id="mean_reversion_fade",
            setup_type="mean_reversion",
        )
        
        assert plan.entry_urgency == "immediate"
        assert plan.exit_urgency == "patient"
        assert plan.p_entry_maker == 0.1  # 10% maker, 90% taker
        assert plan.p_exit_maker == 0.6   # 60% maker, 40% taker
        assert plan.entry_timeout_ms == 500
        assert plan.exit_timeout_ms == 30000
    
    def test_breakout_plan(self):
        """Test execution plan for breakout strategy."""
        policy = ExecutionPolicy()
        plan = policy.plan_execution(
            strategy_id="breakout_momentum",
            setup_type="breakout",
        )
        
        assert plan.entry_urgency == "immediate"
        assert plan.exit_urgency == "immediate"
        assert plan.p_entry_maker == 0.0  # Always taker
        # FIX #6: Reduced from 0.2 to 0.1 since exit is "immediate" (taker-biased)
        assert plan.p_exit_maker == 0.1   # 10% maker, 90% taker
    
    def test_trend_pullback_plan(self):
        """Test execution plan for trend pullback strategy."""
        policy = ExecutionPolicy()
        plan = policy.plan_execution(
            strategy_id="trend_pullback",
            setup_type="trend_pullback",
        )
        
        assert plan.entry_urgency == "patient"
        assert plan.exit_urgency == "immediate"
        assert plan.p_entry_maker == 0.4  # 40% maker, 60% taker
        assert plan.p_exit_maker == 0.1   # 10% maker, 90% taker
    
    def test_low_vol_grind_plan(self):
        """Test execution plan for low volatility grind strategy."""
        policy = ExecutionPolicy()
        plan = policy.plan_execution(
            strategy_id="low_vol_grind",
            setup_type="low_vol_grind",
        )
        
        assert plan.entry_urgency == "passive"
        assert plan.exit_urgency == "passive"
        assert plan.p_entry_maker == 0.7  # 70% maker, 30% taker
        assert plan.p_exit_maker == 0.7   # 70% maker, 30% taker
    
    def test_default_plan(self):
        """Test default execution plan for unknown strategy."""
        policy = ExecutionPolicy()
        plan = policy.plan_execution(
            strategy_id="unknown_strategy",
            setup_type="unknown",
        )
        
        assert plan.entry_urgency == "immediate"
        assert plan.exit_urgency == "patient"
        assert plan.p_entry_maker == 0.0  # Assume taker
        assert plan.p_exit_maker == 0.5   # 50/50 mix
    
    def test_infer_setup_type_from_strategy_id(self):
        """Test setup type inference from strategy_id."""
        policy = ExecutionPolicy()
        
        # Mean reversion
        plan = policy.plan_execution(strategy_id="mean_reversion_fade")
        assert plan.p_entry_maker == 0.1  # Mean reversion plan
        
        # Breakout
        plan = policy.plan_execution(strategy_id="breakout_momentum")
        assert plan.p_entry_maker == 0.0  # Breakout plan
        
        # Trend pullback
        plan = policy.plan_execution(strategy_id="trend_pullback_entry")
        assert plan.p_entry_maker == 0.4  # Trend pullback plan


class TestExpectedFeeCalculation:
    """Tests for expected fee calculation with maker/taker probabilities."""
    
    def test_expected_fee_all_taker(self):
        """Test expected fee when all orders are taker."""
        fee_model = FeeModel(FeeConfig.okx_regular())
        
        # All taker: p_maker = 0
        plan = ExecutionPlan(
            entry_urgency="immediate",
            exit_urgency="immediate",
            p_entry_maker=0.0,
            p_exit_maker=0.0,
            entry_timeout_ms=500,
            exit_timeout_ms=500,
        )
        
        expected_fee_bps = calculate_expected_fees_bps(
            fee_model=fee_model,
            execution_plan=plan,
            entry_price=50000.0,
            exit_price=50000.0,
            size=1.0,
        )
        
        # Taker both sides: 0.06% * 2 = 12 bps
        assert expected_fee_bps == pytest.approx(12.0, abs=0.1)
    
    def test_expected_fee_all_maker(self):
        """Test expected fee when all orders are maker."""
        fee_model = FeeModel(FeeConfig.okx_regular())
        
        # All maker: p_maker = 1
        plan = ExecutionPlan(
            entry_urgency="passive",
            exit_urgency="passive",
            p_entry_maker=1.0,
            p_exit_maker=1.0,
            entry_timeout_ms=5000,
            exit_timeout_ms=5000,
        )
        
        expected_fee_bps = calculate_expected_fees_bps(
            fee_model=fee_model,
            execution_plan=plan,
            entry_price=50000.0,
            exit_price=50000.0,
            size=1.0,
        )
        
        # Maker both sides: 0.04% * 2 = 8 bps
        assert expected_fee_bps == pytest.approx(8.0, abs=0.1)
    
    def test_expected_fee_mixed(self):
        """Test expected fee with mixed maker/taker probabilities."""
        fee_model = FeeModel(FeeConfig.okx_regular())
        
        # Mean reversion plan: 10% maker entry, 60% maker exit
        plan = ExecutionPlan(
            entry_urgency="immediate",
            exit_urgency="patient",
            p_entry_maker=0.1,
            p_exit_maker=0.6,
            entry_timeout_ms=500,
            exit_timeout_ms=30000,
        )
        
        expected_fee_bps = calculate_expected_fees_bps(
            fee_model=fee_model,
            execution_plan=plan,
            entry_price=50000.0,
            exit_price=50000.0,
            size=1.0,
        )
        
        # Entry: 0.1 * 4 + 0.9 * 6 = 0.4 + 5.4 = 5.8 bps
        # Exit:  0.6 * 4 + 0.4 * 6 = 2.4 + 2.4 = 4.8 bps
        # Total: 5.8 + 4.8 = 10.6 bps
        assert expected_fee_bps == pytest.approx(10.6, abs=0.1)
    
    def test_expected_fee_50_50_mix(self):
        """Test expected fee with 50/50 maker/taker mix."""
        fee_model = FeeModel(FeeConfig.okx_regular())
        
        # 50/50 mix
        plan = ExecutionPlan(
            entry_urgency="patient",
            exit_urgency="patient",
            p_entry_maker=0.5,
            p_exit_maker=0.5,
            entry_timeout_ms=2000,
            exit_timeout_ms=2000,
        )
        
        expected_fee_bps = calculate_expected_fees_bps(
            fee_model=fee_model,
            execution_plan=plan,
            entry_price=50000.0,
            exit_price=50000.0,
            size=1.0,
        )
        
        # Each side: 0.5 * 4 + 0.5 * 6 = 2 + 3 = 5 bps
        # Total: 5 + 5 = 10 bps
        assert expected_fee_bps == pytest.approx(10.0, abs=0.1)
    
    def test_expected_fee_different_entry_exit_prices(self):
        """Test expected fee with different entry and exit prices."""
        fee_model = FeeModel(FeeConfig.okx_regular())
        
        plan = ExecutionPlan(
            entry_urgency="immediate",
            exit_urgency="patient",
            p_entry_maker=0.0,
            p_exit_maker=1.0,
            entry_timeout_ms=500,
            exit_timeout_ms=30000,
        )
        
        expected_fee_bps = calculate_expected_fees_bps(
            fee_model=fee_model,
            execution_plan=plan,
            entry_price=50000.0,
            exit_price=51000.0,  # Different exit price
            size=1.0,
        )
        
        # FIX #2: Now each leg is normalized by its own notional
        # Entry (taker): 6 bps of entry notional = 6 bps
        # Exit (maker): 4 bps of exit notional = 4 bps
        # Total: 6 + 4 = 10 bps
        assert expected_fee_bps == pytest.approx(10.0, abs=0.1)
    
    def test_expected_fee_zero_size(self):
        """Test expected fee with zero size returns zero."""
        fee_model = FeeModel(FeeConfig.okx_regular())
        
        plan = ExecutionPlan(
            entry_urgency="immediate",
            exit_urgency="immediate",
            p_entry_maker=0.0,
            p_exit_maker=0.0,
            entry_timeout_ms=500,
            exit_timeout_ms=500,
        )
        
        expected_fee_bps = calculate_expected_fees_bps(
            fee_model=fee_model,
            execution_plan=plan,
            entry_price=50000.0,
            exit_price=50000.0,
            size=0.0,
        )
        
        assert expected_fee_bps == 0.0


class TestExecutionPlanValidation:
    """Tests for ExecutionPlan validation (FIX #3: defensive programming)."""
    
    def test_valid_plan_creation(self):
        """Test that valid plans can be created."""
        plan = ExecutionPlan(
            entry_urgency="immediate",
            exit_urgency="patient",
            p_entry_maker=0.5,
            p_exit_maker=0.5,
            entry_timeout_ms=1000,
            exit_timeout_ms=2000,
        )
        assert plan.p_entry_maker == 0.5
        assert plan.p_exit_maker == 0.5
    
    def test_invalid_p_entry_maker_negative(self):
        """Test that negative p_entry_maker raises ValueError."""
        with pytest.raises(ValueError, match="p_entry_maker must be in"):
            ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="patient",
                p_entry_maker=-0.1,
                p_exit_maker=0.5,
                entry_timeout_ms=1000,
                exit_timeout_ms=2000,
            )
    
    def test_invalid_p_entry_maker_above_one(self):
        """Test that p_entry_maker > 1 raises ValueError."""
        with pytest.raises(ValueError, match="p_entry_maker must be in"):
            ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="patient",
                p_entry_maker=1.1,
                p_exit_maker=0.5,
                entry_timeout_ms=1000,
                exit_timeout_ms=2000,
            )
    
    def test_invalid_p_exit_maker_negative(self):
        """Test that negative p_exit_maker raises ValueError."""
        with pytest.raises(ValueError, match="p_exit_maker must be in"):
            ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="patient",
                p_entry_maker=0.5,
                p_exit_maker=-0.1,
                entry_timeout_ms=1000,
                exit_timeout_ms=2000,
            )
    
    def test_invalid_p_exit_maker_above_one(self):
        """Test that p_exit_maker > 1 raises ValueError."""
        with pytest.raises(ValueError, match="p_exit_maker must be in"):
            ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="patient",
                p_entry_maker=0.5,
                p_exit_maker=1.5,
                entry_timeout_ms=1000,
                exit_timeout_ms=2000,
            )
    
    def test_invalid_entry_urgency(self):
        """Test that invalid entry_urgency raises ValueError."""
        with pytest.raises(ValueError, match="entry_urgency must be one of"):
            ExecutionPlan(
                entry_urgency="fast",  # Invalid
                exit_urgency="patient",
                p_entry_maker=0.5,
                p_exit_maker=0.5,
                entry_timeout_ms=1000,
                exit_timeout_ms=2000,
            )
    
    def test_invalid_exit_urgency(self):
        """Test that invalid exit_urgency raises ValueError."""
        with pytest.raises(ValueError, match="exit_urgency must be one of"):
            ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="slow",  # Invalid
                p_entry_maker=0.5,
                p_exit_maker=0.5,
                entry_timeout_ms=1000,
                exit_timeout_ms=2000,
            )
    
    def test_invalid_entry_timeout_zero(self):
        """Test that zero entry_timeout_ms raises ValueError."""
        with pytest.raises(ValueError, match="entry_timeout_ms must be > 0"):
            ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="patient",
                p_entry_maker=0.5,
                p_exit_maker=0.5,
                entry_timeout_ms=0,
                exit_timeout_ms=2000,
            )
    
    def test_invalid_entry_timeout_negative(self):
        """Test that negative entry_timeout_ms raises ValueError."""
        with pytest.raises(ValueError, match="entry_timeout_ms must be > 0"):
            ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="patient",
                p_entry_maker=0.5,
                p_exit_maker=0.5,
                entry_timeout_ms=-100,
                exit_timeout_ms=2000,
            )
    
    def test_invalid_exit_timeout_zero(self):
        """Test that zero exit_timeout_ms raises ValueError."""
        with pytest.raises(ValueError, match="exit_timeout_ms must be > 0"):
            ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="patient",
                p_entry_maker=0.5,
                p_exit_maker=0.5,
                entry_timeout_ms=1000,
                exit_timeout_ms=0,
            )
    
    def test_boundary_probabilities_valid(self):
        """Test that boundary probabilities (0.0 and 1.0) are valid."""
        # p = 0.0 is valid
        plan1 = ExecutionPlan(
            entry_urgency="immediate",
            exit_urgency="immediate",
            p_entry_maker=0.0,
            p_exit_maker=0.0,
            entry_timeout_ms=1000,
            exit_timeout_ms=1000,
        )
        assert plan1.p_entry_maker == 0.0
        
        # p = 1.0 is valid
        plan2 = ExecutionPlan(
            entry_urgency="passive",
            exit_urgency="passive",
            p_entry_maker=1.0,
            p_exit_maker=1.0,
            entry_timeout_ms=5000,
            exit_timeout_ms=5000,
        )
        assert plan2.p_entry_maker == 1.0
    
    def test_all_valid_urgencies(self):
        """Test that all valid urgency values work."""
        for urgency in ["immediate", "patient", "passive"]:
            plan = ExecutionPlan(
                entry_urgency=urgency,
                exit_urgency=urgency,
                p_entry_maker=0.5,
                p_exit_maker=0.5,
                entry_timeout_ms=1000,
                exit_timeout_ms=1000,
            )
            assert plan.entry_urgency == urgency
            assert plan.exit_urgency == urgency
