"""
Integration test for mean reversion strategy cost logging.

Verifies that Phase 2 implementation correctly:
1. Uses ExecutionPolicy for execution assumptions
2. Calculates expected fees with maker/taker probabilities
3. Uses SlippageModel for market-state-adaptive slippage
4. Includes adverse selection costs
5. Logs comprehensive cost breakdown
"""

import pytest
from unittest.mock import Mock
from quantgambit.deeptrader_core.strategies.mean_reversion_fade import MeanReversionFade
from quantgambit.deeptrader_core.types import Features, AccountState, Profile


def test_mean_reversion_logs_costs_for_valid_signal(caplog):
    """Test that mean reversion strategy logs cost breakdown when generating signal."""
    strategy = MeanReversionFade()
    
    # Create mock features for a valid mean reversion setup
    features = Features(
        symbol="BTCUSDT",
        price=50000.0,
        point_of_control=49850.0,  # POC below price (price overextended high)
        distance_to_poc=150.0,  # 0.3% above POC
        rotation_factor=-0.5,  # Turning negative (reversal signal)
        atr_5m=50.0,
        atr_5m_baseline=60.0,  # ATR ratio = 0.83 (calm market)
        spread=0.00005,  # 0.5 bps (tight spread)
        orderflow_imbalance=0.2,  # Slight buy pressure (not adverse for short)
        position_in_value="above",  # Price above value area
        bid_depth_usd=500000.0,  # Phase 2: book depth
        ask_depth_usd=500000.0,
    )
    
    account = AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )
    
    profile = Profile(
        id="midvol_mean_reversion",
        trend="flat",
        volatility="normal",
        value_location="above",
        session="us",
        risk_mode="normal",
    )
    
    params = {
        "allow_shorts": True,
        "min_distance_from_poc_pct": 0.002,  # 0.2% (lower than actual 0.3%)
        "rotation_reversal_threshold": 0.0,
        "max_atr_ratio": 1.0,
        "risk_per_trade_pct": 0.6,
        "stop_loss_pct": 0.012,  # 1.2%
        "take_profit_target_pct": 0.0,  # Target POC
        "max_spread": 0.002,
        "max_adverse_orderflow": 0.5,
    }
    
    # Generate signal
    with caplog.at_level("INFO"):
        signal = strategy.generate_signal(features, account, profile, params)
    
    # Verify signal was generated
    assert signal is not None
    assert signal.side == "short"
    assert signal.symbol == "BTCUSDT"
    
    # Verify cost logging occurred
    cost_logs = [record for record in caplog.records if "cost breakdown" in record.message.lower()]
    assert len(cost_logs) > 0, "Cost breakdown should be logged"
    
    cost_log = cost_logs[0].message
    
    # Verify all cost components are logged (Phase 2)
    assert "expected_fee=" in cost_log
    assert "bps" in cost_log
    assert "p_entry_maker=" in cost_log
    assert "p_exit_maker=" in cost_log
    assert "spread=" in cost_log
    assert "slippage=" in cost_log
    assert "(adaptive)" in cost_log  # Phase 2: adaptive slippage
    assert "adverse_sel=" in cost_log  # Phase 2: adverse selection
    assert "total_cost=" in cost_log
    assert "SL_distance=" in cost_log
    assert "TP_distance=" in cost_log
    assert "R=" in cost_log  # Reward-to-risk ratio
    assert "C=" in cost_log  # Cost ratio
    assert "execution_plan=" in cost_log
    # vol_regime may be None if not in Features, so don't assert on it
    assert "profile_id=" in cost_log
    
    # Verify execution plan is mean reversion (10% maker entry, 60% maker exit)
    assert "p_entry_maker=10.0%" in cost_log or "p_entry_maker=0.1" in cost_log
    assert "p_exit_maker=60.0%" in cost_log or "p_exit_maker=0.6" in cost_log
    
    # Verify execution plan urgency
    assert "immediate/patient" in cost_log  # Mean reversion: immediate entry, patient exit


def test_mean_reversion_uses_execution_policy():
    """Test that mean reversion strategy uses ExecutionPolicy."""
    strategy = MeanReversionFade()
    
    # Verify strategy has execution_policy attribute
    assert hasattr(strategy, "execution_policy")
    assert strategy.execution_policy is not None
    
    # Verify execution policy returns correct plan for mean reversion
    plan = strategy.execution_policy.plan_execution(
        strategy_id="mean_reversion_fade",
        setup_type="mean_reversion",
    )
    
    assert plan.entry_urgency == "immediate"
    assert plan.exit_urgency == "patient"
    assert plan.p_entry_maker == 0.1  # 10% maker
    assert plan.p_exit_maker == 0.6   # 60% maker


def test_mean_reversion_uses_slippage_model():
    """Test that mean reversion strategy uses SlippageModel (Phase 2)."""
    strategy = MeanReversionFade()
    
    # Verify strategy has slippage_model attribute
    assert hasattr(strategy, "slippage_model")
    assert strategy.slippage_model is not None
    
    # Verify slippage model calculates adaptive slippage
    slippage_bps = strategy.slippage_model.calculate_slippage_bps(
        symbol="BTCUSDT",
        spread_bps=1.0,
        volatility_regime="normal",
        urgency="immediate",
    )
    
    assert slippage_bps > 0
    assert slippage_bps >= 0.5  # At least BTC floor


def test_mean_reversion_geometry_validation_only():
    """Test that mean reversion strategy only validates geometry, not economics."""
    strategy = MeanReversionFade()
    
    # Create features where POC distance is too small (geometry failure)
    features = Features(
        symbol="BTCUSDT",
        price=50000.0,
        point_of_control=49990.0,  # Only 0.02% from POC (too close)
        distance_to_poc=10.0,
        rotation_factor=-0.5,
        atr_5m=50.0,
        atr_5m_baseline=60.0,
        spread=0.00005,
        orderflow_imbalance=0.2,
        position_in_value="above",
    )
    
    account = AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )
    profile = Profile(
        id="test",
        trend="flat",
        volatility="normal",
        value_location="above",
        session="us",
        risk_mode="normal",
    )
    
    params = {
        "allow_shorts": True,
        "min_distance_from_poc_pct": 0.003,  # 0.3% minimum (actual is 0.02%)
        "rotation_reversal_threshold": 0.0,
        "max_atr_ratio": 1.0,
        "risk_per_trade_pct": 0.6,
        "stop_loss_pct": 0.012,
        "take_profit_target_pct": 0.0,
        "max_spread": 0.002,
        "max_adverse_orderflow": 0.5,
    }
    
    # Should reject due to geometry (POC too close)
    signal = strategy.generate_signal(features, account, profile, params)
    assert signal is None  # Rejected by geometry check
    
    # Note: Economics check (profitability after costs) is handled by EVGate,
    # not by the strategy. This is the correct separation of concerns.
