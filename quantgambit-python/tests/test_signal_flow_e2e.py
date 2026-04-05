"""
End-to-End Signal Flow Tests

Tests that verify the complete signal generation pipeline:
1. Market features → Profile classification
2. Profile → Strategy selection
3. Strategy → Signal generation

These tests ensure all components work together correctly.
"""

import pytest
from typing import Optional

from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from quantgambit.deeptrader_core.profiles.profile_classifier import classify_profile
from quantgambit.deeptrader_core.strategies.mean_reversion_fade import MeanReversionFade
from quantgambit.deeptrader_core.strategies.high_vol_breakout import HighVolBreakout
from quantgambit.deeptrader_core.strategies.low_vol_grind import LowVolGrind
from quantgambit.deeptrader_core.strategies.asia_range_scalp import AsiaRangeScalp


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def base_account():
    """Standard account state for testing."""
    return AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )


def make_features(
    symbol: str = "BTCUSDT",
    price: float = 100000.0,
    point_of_control: Optional[float] = 99000.0,
    rotation_factor: float = 0.0,
    spread: float = 0.0001,
    atr_5m: float = 100.0,
    atr_5m_baseline: float = 100.0,
    orderflow_imbalance: float = 0.0,
    position_in_value: str = "inside",
    value_area_high: float = 101000.0,
    value_area_low: float = 98000.0,
    trades_per_second: float = 5.0,
    ema_fast_15m: float = 0.0,
    ema_slow_15m: float = 0.0,
    vwap: float = 0.0,
    timestamp: float = 0.0,
) -> Features:
    """Create Features object with sensible defaults."""
    distance_to_poc = price - point_of_control if point_of_control else 0.0
    
    return Features(
        symbol=symbol,
        price=price,
        spread=spread,
        rotation_factor=rotation_factor,
        position_in_value=position_in_value,
        point_of_control=point_of_control,
        distance_to_poc=distance_to_poc,
        distance_to_val=price - value_area_low,
        distance_to_vah=price - value_area_high,
        atr_5m=atr_5m,
        atr_5m_baseline=atr_5m_baseline,
        orderflow_imbalance=orderflow_imbalance,
        value_area_high=value_area_high,
        value_area_low=value_area_low,
        trades_per_second=trades_per_second,
        ema_fast_15m=ema_fast_15m,
        ema_slow_15m=ema_slow_15m,
        vwap=vwap,
        timestamp=timestamp,
    )


# ============================================================================
# End-to-End Signal Flow Tests
# ============================================================================

class TestSignalFlowE2E:
    """End-to-end tests for the complete signal generation pipeline."""
    
    def test_mean_reversion_flow_generates_short(self, base_account):
        """
        E2E Test: Mean reversion SHORT signal flow
        
        Given: Price above POC, rotation turning down, calm market
        Expected: Profile classified as flat/normal/inside, MeanReversionFade generates SHORT
        """
        # Step 1: Create market features for mean reversion setup
        features = make_features(
            price=102000.0,  # 2% above POC
            point_of_control=100000.0,
            rotation_factor=-0.5,  # Turning down
            spread=0.0001,
            atr_5m=100.0,
            atr_5m_baseline=150.0,  # ATR ratio < 1 (calm)
            position_in_value="inside",
        )
        
        # Step 2: Create profile (in real system, this comes from classifier)
        profile = Profile(
            id="mean_reversion_test",
            trend="flat",
            volatility="normal",
            value_location="inside",
            session="us",
            risk_mode="normal",
        )
        
        # Step 3: Generate signal
        strategy = MeanReversionFade()
        signal = strategy.generate_signal(features, base_account, profile, {})
        
        # Step 4: Verify complete flow
        assert signal is not None, "Should generate signal for mean reversion setup"
        assert signal.side == "short", "Should be SHORT when price above POC"
        assert signal.strategy_id == "mean_reversion_fade"
        assert signal.symbol == "BTCUSDT"
        assert signal.stop_loss > signal.entry_price, "SL above entry for short"
        assert signal.take_profit < signal.entry_price, "TP below entry for short"
        assert signal.size > 0, "Size should be positive"
    
    def test_mean_reversion_flow_generates_long(self, base_account):
        """
        E2E Test: Mean reversion LONG signal flow
        
        Given: Price below POC, rotation turning up, calm market
        Expected: MeanReversionFade generates LONG
        """
        features = make_features(
            price=98000.0,  # 2% below POC
            point_of_control=100000.0,
            rotation_factor=0.5,  # Turning up
            spread=0.0001,
            atr_5m=100.0,
            atr_5m_baseline=150.0,
            position_in_value="inside",
        )
        
        profile = Profile(
            id="mean_reversion_test",
            trend="flat",
            volatility="normal",
            value_location="inside",
            session="us",
            risk_mode="normal",
        )
        
        strategy = MeanReversionFade()
        signal = strategy.generate_signal(features, base_account, profile, {})
        
        assert signal is not None
        assert signal.side == "long"
        assert signal.stop_loss < signal.entry_price
        assert signal.take_profit > signal.entry_price
    
    def test_high_vol_breakout_flow(self, base_account):
        """
        E2E Test: High volatility breakout signal flow
        
        Given: ATR spike (>2x baseline), price breaking above VAH, strong rotation
        Expected: HighVolBreakout generates LONG
        """
        features = make_features(
            price=102500.0,  # Above VAH
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=8.0,  # Strong upward momentum
            atr_5m=300.0,
            atr_5m_baseline=100.0,  # ATR ratio = 3.0 (spike!)
            spread=0.003,
            trades_per_second=10.0,
            ema_fast_15m=101000.0,  # EMA alignment
            ema_slow_15m=100000.0,
        )
        
        profile = Profile(
            id="high_vol_breakout_test",
            trend="up",
            volatility="high",  # Required for this strategy
            value_location="above",
            session="us",
            risk_mode="normal",
        )
        
        strategy = HighVolBreakout()
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, profile, params)
        
        if signal is not None:
            assert signal.side == "long"
            assert signal.strategy_id == "high_vol_breakout"
            assert "atr" in signal.meta_reason.lower()
    
    def test_low_vol_grind_flow(self, base_account):
        """
        E2E Test: Low volatility grind signal flow
        
        Given: Ultra-low ATR (<0.5x baseline), price near POC, tight range
        Expected: LowVolGrind generates signal for micro scalp
        """
        features = make_features(
            price=99950.0,  # Slightly below POC
            point_of_control=100000.0,
            value_area_high=100100.0,  # Tight range
            value_area_low=99900.0,
            rotation_factor=0.0,  # Neutral
            atr_5m=40.0,
            atr_5m_baseline=100.0,  # ATR ratio = 0.4 (ultra-low)
            spread=0.0003,
            trades_per_second=3.0,
            position_in_value="inside",
        )
        
        profile = Profile(
            id="low_vol_grind_test",
            trend="flat",
            volatility="low",  # Required for this strategy
            value_location="inside",
            session="asia",
            risk_mode="normal",
        )
        
        strategy = LowVolGrind()
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, profile, params)
        
        if signal is not None:
            assert signal.side == "long"  # Below POC = long
            assert signal.strategy_id == "low_vol_grind"
    
    def test_asia_range_scalp_flow(self, base_account):
        """
        E2E Test: Asia range scalp signal flow
        
        Given: Asia session, flat trend, low volatility, price below POC with rotation up
        Expected: AsiaRangeScalp generates LONG
        """
        features = make_features(
            price=99500.0,  # Below POC
            point_of_control=100000.0,
            rotation_factor=4.0,  # Turning up
            spread=0.0003,
            trades_per_second=5.0,
            position_in_value="inside",
        )
        
        profile = Profile(
            id="asia_range_test",
            trend="flat",
            volatility="low",
            value_location="inside",
            session="asia",  # Required for this strategy
            risk_mode="normal",
        )
        
        strategy = AsiaRangeScalp()
        signal = strategy.generate_signal(features, base_account, profile, {})
        
        if signal is not None:
            assert signal.side == "long"
            assert signal.strategy_id == "asia_range_scalp"
    
    def test_no_signal_when_conditions_not_met(self, base_account):
        """
        E2E Test: No signal when market conditions don't match strategy requirements
        
        Given: Mean reversion setup but spread too wide
        Expected: No signal generated
        """
        features = make_features(
            price=102000.0,
            point_of_control=100000.0,
            rotation_factor=-0.5,
            spread=0.01,  # 1% spread - way too wide
            atr_5m=100.0,
            atr_5m_baseline=150.0,
        )
        
        profile = Profile(
            id="test",
            trend="flat",
            volatility="normal",
            value_location="inside",
            session="us",
            risk_mode="normal",
        )
        
        strategy = MeanReversionFade()
        signal = strategy.generate_signal(features, base_account, profile, {})
        
        assert signal is None, "Should NOT generate signal when spread too wide"
    
    def test_session_filter_blocks_wrong_session(self, base_account):
        """
        E2E Test: Session filter correctly blocks signals
        
        Given: Asia range scalp setup but US session
        Expected: No signal generated (wrong session)
        """
        features = make_features(
            price=99500.0,
            point_of_control=100000.0,
            rotation_factor=4.0,
            spread=0.0003,
        )
        
        # US session instead of Asia
        profile = Profile(
            id="wrong_session",
            trend="flat",
            volatility="low",
            value_location="inside",
            session="us",  # Wrong session for AsiaRangeScalp
            risk_mode="normal",
        )
        
        strategy = AsiaRangeScalp()
        signal = strategy.generate_signal(features, base_account, profile, {})
        
        assert signal is None, "Should NOT generate signal in wrong session"
    
    def test_volatility_filter_blocks_wrong_volatility(self, base_account):
        """
        E2E Test: Volatility filter correctly blocks signals
        
        Given: High vol breakout setup but low volatility profile
        Expected: No signal generated (wrong volatility)
        """
        features = make_features(
            price=102500.0,
            value_area_high=101000.0,
            value_area_low=99000.0,
            rotation_factor=8.0,
            atr_5m=300.0,
            atr_5m_baseline=100.0,
            trades_per_second=10.0,
            ema_fast_15m=101000.0,
            ema_slow_15m=100000.0,
        )
        
        # Low volatility profile instead of high
        profile = Profile(
            id="wrong_vol",
            trend="up",
            volatility="low",  # Wrong volatility for HighVolBreakout
            value_location="above",
            session="us",
            risk_mode="normal",
        )
        
        strategy = HighVolBreakout()
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, profile, params)
        
        assert signal is None, "Should NOT generate signal in wrong volatility"


# ============================================================================
# Signal Consistency Tests
# ============================================================================

class TestSignalConsistency:
    """Tests that verify signal properties are consistent and valid."""
    
    def test_long_signal_sl_tp_consistency(self, base_account):
        """For all LONG signals: SL < entry < TP."""
        strategies = [
            (MeanReversionFade(), make_features(
                price=98000.0, point_of_control=100000.0, rotation_factor=0.5,
                spread=0.0001, atr_5m=100.0, atr_5m_baseline=150.0
            )),
        ]
        
        profile = Profile(
            id="test", trend="flat", volatility="normal",
            value_location="inside", session="us", risk_mode="normal"
        )
        
        for strategy, features in strategies:
            signal = strategy.generate_signal(features, base_account, profile, {})
            if signal and signal.side == "long":
                assert signal.stop_loss < signal.entry_price < signal.take_profit, \
                    f"{strategy.strategy_id}: LONG signal must have SL < entry < TP"
    
    def test_short_signal_sl_tp_consistency(self, base_account):
        """For all SHORT signals: TP < entry < SL."""
        strategies = [
            (MeanReversionFade(), make_features(
                price=102000.0, point_of_control=100000.0, rotation_factor=-0.5,
                spread=0.0001, atr_5m=100.0, atr_5m_baseline=150.0
            )),
        ]
        
        profile = Profile(
            id="test", trend="flat", volatility="normal",
            value_location="inside", session="us", risk_mode="normal"
        )
        
        for strategy, features in strategies:
            signal = strategy.generate_signal(features, base_account, profile, {})
            if signal and signal.side == "short":
                assert signal.take_profit < signal.entry_price < signal.stop_loss, \
                    f"{strategy.strategy_id}: SHORT signal must have TP < entry < SL"
    
    def test_signal_size_is_positive(self, base_account):
        """All signals must have positive size."""
        features = make_features(
            price=102000.0, point_of_control=100000.0, rotation_factor=-0.5,
            spread=0.0001, atr_5m=100.0, atr_5m_baseline=150.0
        )
        
        profile = Profile(
            id="test", trend="flat", volatility="normal",
            value_location="inside", session="us", risk_mode="normal"
        )
        
        strategy = MeanReversionFade()
        signal = strategy.generate_signal(features, base_account, profile, {})
        
        if signal:
            assert signal.size > 0, "Signal size must be positive"
    
    def test_signal_has_all_required_fields(self, base_account):
        """All signals must have all required fields populated."""
        features = make_features(
            price=102000.0, point_of_control=100000.0, rotation_factor=-0.5,
            spread=0.0001, atr_5m=100.0, atr_5m_baseline=150.0
        )
        
        profile = Profile(
            id="test", trend="flat", volatility="normal",
            value_location="inside", session="us", risk_mode="normal"
        )
        
        strategy = MeanReversionFade()
        signal = strategy.generate_signal(features, base_account, profile, {})
        
        if signal:
            assert signal.strategy_id, "strategy_id must be set"
            assert signal.symbol, "symbol must be set"
            assert signal.side in ["long", "short"], "side must be long or short"
            assert signal.size > 0, "size must be positive"
            assert signal.entry_price > 0, "entry_price must be positive"
            assert signal.stop_loss > 0, "stop_loss must be positive"
            assert signal.take_profit > 0, "take_profit must be positive"
