"""
Unit tests for fee-aware entry filtering (US-4)

Tests that strategies reject entries when expected profit < fees + buffer.
"""

import pytest
from unittest.mock import MagicMock
from quantgambit.deeptrader_core.strategies.mean_reversion_fade import MeanReversionFade
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal


class TestMeanReversionFadeFeeAwareEntry:
    """Tests for fee-aware entry filtering in mean_reversion_fade strategy"""
    
    @pytest.fixture
    def strategy(self):
        return MeanReversionFade()
    
    @pytest.fixture
    def account(self):
        return AccountState(
            equity=10000.0,
            daily_pnl=0.0,
            max_daily_loss=-500.0,
            open_positions=0,
            symbol_open_positions=0,
            symbol_daily_pnl=0.0,
        )
    
    @pytest.fixture
    def profile(self):
        return Profile(
            id="test_profile",
            trend="flat",
            volatility="low",
            value_location="below",
            session="us",
            risk_mode="normal",
        )
    
    def _make_features(
        self,
        price: float = 100.0,
        poc: float = 100.0,
        distance_to_poc: float = 0.0,
        rotation_factor: float = 0.0,
        spread: float = 0.0001,
        orderflow_imbalance: float = 0.0,
    ) -> Features:
        """Helper to create Features with required fields"""
        return Features(
            symbol="BTCUSDT",
            price=price,
            spread=spread,
            rotation_factor=rotation_factor,
            position_in_value="below" if distance_to_poc < 0 else "above",
            point_of_control=poc,
            distance_to_poc=distance_to_poc,
            orderflow_imbalance=orderflow_imbalance,
        )
    
    def test_rejects_entry_when_insufficient_edge(self, strategy, account, profile):
        """Test that entry is rejected when expected profit < min_edge_bps"""
        # Price at 100, POC at 100.05 (0.05% = 5 bps distance)
        # With 8 bps costs (6 fee + 2 slippage), expected profit = 5 - 8 = -3 bps
        # This should be rejected (< 8 bps min_edge)
        features = self._make_features(
            price=100.0,
            poc=100.05,
            distance_to_poc=-0.05,  # Below POC
            rotation_factor=1.0,  # Turning up (reversal signal)
        )
        
        params = {
            "min_distance_from_poc_pct": 0.0001,  # Very low threshold to pass distance check
            "min_edge_bps": 8.0,
            "fee_bps": 6.0,
            "slippage_bps": 2.0,
        }
        
        signal = strategy.generate_signal(features, account, profile, params)
        assert signal is None, "Should reject entry with insufficient edge"
    
    def test_allows_entry_when_sufficient_edge(self, strategy, account, profile):
        """Test that entry is allowed when expected profit >= min_edge_bps"""
        # Price at 100, POC at 102 (2% = 200 bps distance)
        # With 8 bps costs, expected profit = 200 - 8 = 192 bps
        # This should be allowed (>= 8 bps min_edge)
        features = self._make_features(
            price=100.0,
            poc=102.0,
            distance_to_poc=-2.0,  # Below POC
            rotation_factor=1.0,  # Turning up (reversal signal)
        )
        
        params = {
            "min_distance_from_poc_pct": 0.015,  # 1.5%
            "min_edge_bps": 8.0,
            "fee_bps": 6.0,
            "slippage_bps": 2.0,
        }
        
        signal = strategy.generate_signal(features, account, profile, params)
        assert signal is not None, "Should allow entry with sufficient edge"
        assert signal.side == "long"
    
    def test_edge_case_exactly_at_threshold(self, strategy, account, profile):
        """Test entry at exactly min_edge_bps threshold"""
        # Price at 100, POC at 100.16 (0.16% = 16 bps distance)
        # With 8 bps costs, expected profit = 16 - 8 = 8 bps
        # This should be allowed (== 8 bps min_edge)
        features = self._make_features(
            price=100.0,
            poc=100.16,
            distance_to_poc=-0.16,  # Below POC
            rotation_factor=1.0,  # Turning up
        )
        
        params = {
            "min_distance_from_poc_pct": 0.001,  # Low threshold
            "min_edge_bps": 8.0,
            "fee_bps": 6.0,
            "slippage_bps": 2.0,
        }
        
        signal = strategy.generate_signal(features, account, profile, params)
        assert signal is not None, "Should allow entry at exactly min_edge threshold"
    
    def test_custom_fee_parameters(self, strategy, account, profile):
        """Test with custom fee and slippage parameters"""
        # Price at 100, POC at 100.20 (0.20% = 20 bps distance)
        # With 15 bps costs (10 fee + 5 slippage), expected profit = 20 - 15 = 5 bps
        # With min_edge=10, this should be rejected
        features = self._make_features(
            price=100.0,
            poc=100.20,
            distance_to_poc=-0.20,  # Below POC
            rotation_factor=1.0,
        )
        
        params = {
            "min_distance_from_poc_pct": 0.001,
            "min_edge_bps": 10.0,  # Higher threshold
            "fee_bps": 10.0,  # Higher fees
            "slippage_bps": 5.0,  # Higher slippage
        }
        
        signal = strategy.generate_signal(features, account, profile, params)
        assert signal is None, "Should reject with custom high fee parameters"
    
    def test_short_entry_fee_aware(self, strategy, account, profile):
        """Test fee-aware filtering for short entries"""
        # Price at 102, POC at 100 (2% = 200 bps distance)
        # With 8 bps costs, expected profit = 200 - 8 = 192 bps
        features = self._make_features(
            price=102.0,
            poc=100.0,
            distance_to_poc=2.0,  # Above POC
            rotation_factor=-1.0,  # Turning down (reversal signal for short)
        )
        
        params = {
            "min_distance_from_poc_pct": 0.015,
            "min_edge_bps": 8.0,
            "fee_bps": 6.0,
            "slippage_bps": 2.0,
            "rotation_reversal_threshold": 0.0,
        }
        
        signal = strategy.generate_signal(features, account, profile, params)
        assert signal is not None, "Should allow short entry with sufficient edge"
        assert signal.side == "short"
    
    def test_short_entry_rejected_insufficient_edge(self, strategy, account, profile):
        """Test short entry rejected when insufficient edge"""
        # Price at 100.05, POC at 100 (0.05% = 5 bps distance)
        # With 8 bps costs, expected profit = 5 - 8 = -3 bps
        features = self._make_features(
            price=100.05,
            poc=100.0,
            distance_to_poc=0.05,  # Above POC
            rotation_factor=-1.0,  # Turning down
        )
        
        params = {
            "min_distance_from_poc_pct": 0.0001,  # Very low
            "min_edge_bps": 8.0,
            "fee_bps": 6.0,
            "slippage_bps": 2.0,
            "rotation_reversal_threshold": 0.0,
        }
        
        signal = strategy.generate_signal(features, account, profile, params)
        assert signal is None, "Should reject short entry with insufficient edge"
    
    def test_default_fee_parameters(self, strategy, account, profile):
        """Test that default fee parameters are used when not specified"""
        # Price at 100, POC at 102 (2% = 200 bps distance)
        # Default: 6 bps fee + 2 bps slippage = 8 bps costs
        # Expected profit = 200 - 8 = 192 bps (should pass default 8 bps min_edge)
        features = self._make_features(
            price=100.0,
            poc=102.0,
            distance_to_poc=-2.0,
            rotation_factor=1.0,
        )
        
        params = {
            "min_distance_from_poc_pct": 0.015,
            # No fee params - should use defaults
        }
        
        signal = strategy.generate_signal(features, account, profile, params)
        assert signal is not None, "Should use default fee parameters"


class TestAmtValueAreaRejectionScalpFeeAware:
    """Verify existing fee-aware filtering in amt_value_area_rejection_scalp"""
    
    @pytest.fixture
    def strategy(self):
        from quantgambit.deeptrader_core.strategies.amt_value_area_rejection_scalp import (
            AmtValueAreaRejectionScalp,
        )
        return AmtValueAreaRejectionScalp()
    
    @pytest.fixture
    def account(self):
        return AccountState(
            equity=10000.0,
            daily_pnl=0.0,
            max_daily_loss=-500.0,
            open_positions=0,
            symbol_open_positions=0,
            symbol_daily_pnl=0.0,
        )
    
    @pytest.fixture
    def profile(self):
        return Profile(
            id="test_profile",
            trend="flat",
            volatility="low",
            value_location="below",
            session="us",
            risk_mode="normal",
        )
    
    def test_rejects_low_edge_entry(self, strategy, account, profile):
        """Test that amt_value_area_rejection_scalp rejects low edge entries"""
        features = Features(
            symbol="BTCUSDT",
            price=100.0,
            spread=0.0001,
            rotation_factor=5.0,  # Strong rotation
            position_in_value="below",
            point_of_control=100.02,  # Only 2 bps away
            distance_to_poc=0.02,
            distance_to_val=0.0001,  # Very close to VAL
            distance_to_vah=0.05,
            orderflow_imbalance=0.0,
        )
        
        params = {
            "min_edge_bps": 8.0,
            "fee_bps": 2.0,
            "slippage_bps": 2.0,
            "rotation_threshold": 3.0,
            "value_margin": 0.001,
        }
        
        signal = strategy.generate_signal(features, account, profile, params)
        # With 2 bps distance and 4 bps costs, expected profit = -2 bps < 8 bps
        assert signal is None, "Should reject entry with insufficient edge"

    def test_accepts_below_poc_long_when_absolute_edge_exceeds_costs(self, strategy, account, profile):
        features = Features(
            symbol="BTCUSDT",
            price=100.0,
            spread=0.0001,
            rotation_factor=5.0,
            position_in_value="below",
            point_of_control=100.20,
            distance_to_poc=-0.20,
            distance_to_val=0.0001,
            distance_to_vah=0.30,
            orderflow_imbalance=0.0,
        )

        params = {
            "min_edge_bps": 8.0,
            "fee_bps": 2.0,
            "slippage_bps": 2.0,
            "rotation_threshold": 3.0,
            "value_margin": 0.001,
        }

        signal = strategy.generate_signal(features, account, profile, params)
        assert signal is not None
        assert signal.side == "long"
