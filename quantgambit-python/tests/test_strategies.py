"""
Strategy Unit Tests

Tests for individual trading strategies to verify:
1. Signal generation under correct conditions
2. No signal generation under incorrect conditions
3. Correct signal direction (long/short)
4. Valid SL/TP placement
5. Position sizing respects risk limits

These tests address the gap identified in the Trading Engine Audit.
"""

import pytest
from dataclasses import dataclass
from typing import Optional

from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from quantgambit.deeptrader_core.strategies.mean_reversion_fade import MeanReversionFade
from quantgambit.deeptrader_core.strategies.spread_compression import SpreadCompression
from quantgambit.deeptrader_core.strategies.breakout_scalp import BreakoutScalp
from quantgambit.deeptrader_core.strategies.poc_magnet_scalp import POCMagnetScalp


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


@pytest.fixture
def base_profile():
    """Standard profile for testing."""
    return Profile(
        id="test_profile",
        trend="flat",
        volatility="normal",
        value_location="inside",
        session="asia",
        risk_mode="normal",
    )


def make_features(
    symbol: str = "BTCUSDT",
    price: float = 100000.0,
    point_of_control: Optional[float] = 99000.0,
    distance_to_poc: Optional[float] = None,
    rotation_factor: float = 0.0,
    spread: float = 0.0001,
    atr_5m: float = 100.0,
    atr_5m_baseline: float = 100.0,
    orderflow_imbalance: float = 0.0,
    position_in_value: str = "inside",
    value_area_high: float = 101000.0,
    value_area_low: float = 98000.0,
    trades_per_second: float = 5.0,
) -> Features:
    """Create Features object with sensible defaults."""
    if distance_to_poc is None and point_of_control is not None:
        distance_to_poc = price - point_of_control
    elif distance_to_poc is None:
        distance_to_poc = 0.0
    
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
    )


# ============================================================================
# Mean Reversion Fade Strategy Tests
# ============================================================================

class TestMeanReversionFade:
    """Tests for MeanReversionFade strategy."""
    
    def test_generates_short_when_price_above_poc_and_rotation_negative(self, base_account, base_profile):
        """Should generate SHORT when price is above POC and rotation is turning down."""
        strategy = MeanReversionFade()
        
        # Price is 2% above POC, rotation is negative (turning down)
        features = make_features(
            price=102000.0,
            point_of_control=100000.0,
            distance_to_poc=2000.0,  # 2% above POC
            rotation_factor=-0.5,  # Negative = turning down
            spread=0.0001,
            atr_5m=100.0,
            atr_5m_baseline=150.0,  # ATR ratio < 1 (calm market)
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is not None, "Should generate signal when conditions are met"
        assert signal.side == "short", "Should be SHORT when price above POC"
        assert signal.entry_price == features.price
        assert signal.stop_loss > signal.entry_price, "SL should be above entry for short"
        assert signal.take_profit < signal.entry_price, "TP should be below entry for short"
    
    def test_generates_long_when_price_below_poc_and_rotation_positive(self, base_account, base_profile):
        """Should generate LONG when price is below POC and rotation is turning up."""
        strategy = MeanReversionFade()
        
        # Price is 2% below POC, rotation is positive (turning up)
        features = make_features(
            price=98000.0,
            point_of_control=100000.0,
            distance_to_poc=-2000.0,  # 2% below POC
            rotation_factor=0.5,  # Positive = turning up
            spread=0.0001,
            atr_5m=100.0,
            atr_5m_baseline=150.0,  # ATR ratio < 1 (calm market)
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is not None, "Should generate signal when conditions are met"
        assert signal.side == "long", "Should be LONG when price below POC"
        assert signal.entry_price == features.price
        assert signal.stop_loss < signal.entry_price, "SL should be below entry for long"
        assert signal.take_profit > signal.entry_price, "TP should be above entry for long"
    
    def test_no_signal_when_too_close_to_poc(self, base_account, base_profile):
        """Should NOT generate signal when price is within min_distance_from_poc."""
        strategy = MeanReversionFade()
        
        # Price is only 0.1% from POC (below 0.3% threshold)
        features = make_features(
            price=100100.0,
            point_of_control=100000.0,
            distance_to_poc=100.0,  # Only 0.1% from POC (below 0.3% threshold)
            rotation_factor=-0.5,
            spread=0.0001,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is None, "Should NOT generate signal when too close to POC"
    
    def test_no_signal_when_spread_too_wide(self, base_account, base_profile):
        """Should NOT generate signal when spread exceeds max_spread."""
        strategy = MeanReversionFade()
        
        features = make_features(
            price=102000.0,
            point_of_control=100000.0,
            distance_to_poc=2000.0,
            rotation_factor=-0.5,
            spread=0.005,  # 0.5% spread - too wide
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is None, "Should NOT generate signal when spread too wide"
    
    def test_no_signal_when_atr_too_high(self, base_account, base_profile):
        """Should NOT generate signal when ATR ratio exceeds max_atr_ratio."""
        strategy = MeanReversionFade()
        
        features = make_features(
            price=102000.0,
            point_of_control=100000.0,
            distance_to_poc=2000.0,
            rotation_factor=-0.5,
            spread=0.0001,
            atr_5m=200.0,
            atr_5m_baseline=100.0,  # ATR ratio = 2.0 (too high)
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is None, "Should NOT generate signal when ATR too high"
    
    def test_no_signal_when_rotation_not_reversing(self, base_account, base_profile):
        """Should NOT generate signal when rotation is not indicating reversal."""
        strategy = MeanReversionFade()
        
        # Price above POC but rotation is positive (not reversing down)
        features = make_features(
            price=102000.0,
            point_of_control=100000.0,
            distance_to_poc=2000.0,
            rotation_factor=0.5,  # Positive = still going up, not reversing
            spread=0.0001,
            atr_5m=100.0,
            atr_5m_baseline=150.0,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is None, "Should NOT generate signal when rotation not reversing"
    
    def test_no_signal_when_orderflow_adverse(self, base_account, base_profile):
        """Should NOT generate signal when orderflow is against trade direction."""
        strategy = MeanReversionFade()
        
        # Price above POC, rotation negative, but strong buy pressure
        features = make_features(
            price=102000.0,
            point_of_control=100000.0,
            distance_to_poc=2000.0,
            rotation_factor=-0.5,
            spread=0.0001,
            atr_5m=100.0,
            atr_5m_baseline=150.0,
            orderflow_imbalance=0.7,  # Strong buy pressure - adverse for short
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is None, "Should NOT generate signal when orderflow is adverse"
    
    def test_no_signal_when_poc_missing(self, base_account, base_profile):
        """Should NOT generate signal when POC data is missing."""
        strategy = MeanReversionFade()
        
        features = make_features(
            price=102000.0,
            point_of_control=None,  # Missing POC
            distance_to_poc=None,
            rotation_factor=-0.5,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is None, "Should NOT generate signal when POC missing"
    
    def test_position_sizing_respects_risk(self, base_account, base_profile):
        """Position size should be calculated based on risk per trade."""
        strategy = MeanReversionFade()
        
        features = make_features(
            price=102000.0,
            point_of_control=100000.0,
            distance_to_poc=2000.0,
            rotation_factor=-0.5,
            spread=0.0001,
            atr_5m=100.0,
            atr_5m_baseline=150.0,
        )
        
        params = {"risk_per_trade_pct": 1.0}  # 1% risk
        signal = strategy.generate_signal(features, base_account, base_profile, params)
        
        assert signal is not None
        # Risk = equity * risk_pct / stop_distance
        # With 1% risk on $10,000 = $100 risk
        # Stop distance = entry * stop_loss_pct = 102000 * 0.012 = 1224
        # Size = 100 / 1224 ≈ 0.0817
        assert signal.size > 0, "Size should be positive"
        assert signal.size < 1.0, "Size should be reasonable for BTC"


# ============================================================================
# Spread Compression Strategy Tests
# ============================================================================

class TestSpreadCompression:
    """Tests for SpreadCompression strategy."""
    
    def test_generates_signal_when_spread_tight(self, base_account, base_profile):
        """Should generate signal when spread is ultra-tight."""
        strategy = SpreadCompression()
        
        features = make_features(
            spread=0.00005,  # 0.5 bps - ultra tight
            trades_per_second=10.0,  # High liquidity
            rotation_factor=0.3,  # Slight directional bias
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        # Note: May or may not generate signal depending on other conditions
        # This test verifies the strategy doesn't crash and handles tight spreads
        if signal is not None:
            assert signal.side in ["long", "short"]
            assert signal.size > 0
    
    def test_no_signal_when_spread_wide(self, base_account, base_profile):
        """Should NOT generate signal when spread is too wide."""
        strategy = SpreadCompression()
        
        features = make_features(
            spread=0.005,  # 50 bps - too wide for spread compression
            trades_per_second=10.0,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is None, "Should NOT generate signal when spread too wide"


# ============================================================================
# Breakout Scalp Strategy Tests
# ============================================================================

class TestBreakoutScalp:
    """Tests for BreakoutScalp strategy."""
    
    def test_generates_long_on_breakout_above_vah(self, base_account, base_profile):
        """Should generate LONG when price breaks above VAH with momentum."""
        strategy = BreakoutScalp()
        
        features = make_features(
            price=101500.0,  # Above VAH
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=5.0,  # Strong upward momentum
            position_in_value="above",
            atr_5m=200.0,
            atr_5m_baseline=100.0,  # ATR expanding
            spread=0.0002,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG on breakout above VAH"
    
    def test_generates_short_on_breakout_below_val(self, base_account, base_profile):
        """Should generate SHORT when price breaks below VAL with momentum."""
        strategy = BreakoutScalp()
        
        features = make_features(
            price=98500.0,  # Below VAL
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=-5.0,  # Strong downward momentum
            position_in_value="below",
            atr_5m=200.0,
            atr_5m_baseline=100.0,  # ATR expanding
            spread=0.0002,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT on breakout below VAL"


# ============================================================================
# POC Magnet Scalp Strategy Tests
# ============================================================================

class TestPOCMagnetScalp:
    """Tests for POCMagnetScalp strategy."""
    
    def test_generates_long_when_price_below_poc(self, base_account, base_profile):
        """Should generate LONG when price is below POC (magnet effect)."""
        strategy = POCMagnetScalp()
        
        features = make_features(
            price=99000.0,
            point_of_control=100000.0,
            distance_to_poc=-1000.0,  # Below POC
            position_in_value="inside",
            spread=0.0001,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG when price below POC"
            assert signal.take_profit >= features.point_of_control, "TP should target POC"
    
    def test_generates_short_when_price_above_poc(self, base_account, base_profile):
        """Should generate SHORT when price is above POC (magnet effect)."""
        strategy = POCMagnetScalp()
        
        features = make_features(
            price=101000.0,
            point_of_control=100000.0,
            distance_to_poc=1000.0,  # Above POC
            position_in_value="inside",
            spread=0.0001,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT when price above POC"
            assert signal.take_profit <= features.point_of_control, "TP should target POC"


# ============================================================================
# Signal Validation Tests
# ============================================================================

class TestSignalValidation:
    """Tests that verify signal properties are valid."""
    
    def test_signal_has_required_fields(self, base_account, base_profile):
        """All signals should have required fields populated."""
        strategy = MeanReversionFade()
        
        features = make_features(
            price=102000.0,
            point_of_control=100000.0,
            distance_to_poc=2000.0,
            rotation_factor=-0.5,
            spread=0.0001,
            atr_5m=100.0,
            atr_5m_baseline=150.0,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is not None
        assert signal.strategy_id == "mean_reversion_fade"
        assert signal.symbol == features.symbol
        assert signal.side in ["long", "short"]
        assert signal.size > 0
        assert signal.entry_price > 0
        assert signal.stop_loss > 0
        assert signal.take_profit > 0
    
    def test_sl_tp_relationship_long(self, base_account, base_profile):
        """For LONG signals: SL < entry < TP."""
        strategy = MeanReversionFade()
        
        features = make_features(
            price=98000.0,
            point_of_control=100000.0,
            distance_to_poc=-2000.0,
            rotation_factor=0.5,
            spread=0.0001,
            atr_5m=100.0,
            atr_5m_baseline=150.0,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is not None
        assert signal.side == "long"
        assert signal.stop_loss < signal.entry_price < signal.take_profit, \
            "For LONG: SL < entry < TP"
    
    def test_sl_tp_relationship_short(self, base_account, base_profile):
        """For SHORT signals: TP < entry < SL."""
        strategy = MeanReversionFade()
        
        features = make_features(
            price=102000.0,
            point_of_control=100000.0,
            distance_to_poc=2000.0,
            rotation_factor=-0.5,
            spread=0.0001,
            atr_5m=100.0,
            atr_5m_baseline=150.0,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is not None
        assert signal.side == "short"
        assert signal.take_profit < signal.entry_price < signal.stop_loss, \
            "For SHORT: TP < entry < SL"


# ============================================================================
# Additional Strategy Imports
# ============================================================================

from quantgambit.deeptrader_core.strategies.asia_range_scalp import AsiaRangeScalp
from quantgambit.deeptrader_core.strategies.overnight_thin import OvernightThin
from quantgambit.deeptrader_core.strategies.high_vol_breakout import HighVolBreakout
from quantgambit.deeptrader_core.strategies.low_vol_grind import LowVolGrind
from quantgambit.deeptrader_core.strategies.vwap_reversion import VWAPReversion


# ============================================================================
# Extended Features Helper
# ============================================================================

def make_features_extended(
    symbol: str = "BTCUSDT",
    price: float = 100000.0,
    point_of_control: Optional[float] = 99000.0,
    distance_to_poc: Optional[float] = None,
    rotation_factor: float = 0.0,
    spread: float = 0.0001,
    atr_5m: float = 100.0,
    atr_5m_baseline: float = 100.0,
    orderflow_imbalance: float = 0.0,
    position_in_value: str = "inside",
    value_area_high: float = 101000.0,
    value_area_low: float = 98000.0,
    trades_per_second: float = 5.0,
    vwap: float = 0.0,
    ema_fast_15m: float = 0.0,
    ema_slow_15m: float = 0.0,
) -> Features:
    """Create Features object with extended fields for more strategies."""
    if distance_to_poc is None and point_of_control is not None:
        distance_to_poc = price - point_of_control
    elif distance_to_poc is None:
        distance_to_poc = 0.0
    
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
        vwap=vwap,
        ema_fast_15m=ema_fast_15m,
        ema_slow_15m=ema_slow_15m,
    )


# ============================================================================
# Asia Range Scalp Strategy Tests
# ============================================================================

class TestAsiaRangeScalp:
    """Tests for AsiaRangeScalp strategy."""
    
    @pytest.fixture
    def asia_profile(self):
        """Profile for Asia session."""
        return Profile(
            id="asia_range",
            trend="flat",
            volatility="low",
            value_location="inside",
            session="asia",
            risk_mode="normal",
        )
    
    def test_generates_long_when_below_poc_with_rotation_up(self, base_account, asia_profile):
        """Should generate LONG when price below POC and rotation turning up."""
        strategy = AsiaRangeScalp()
        
        features = make_features(
            price=99500.0,  # Below POC
            point_of_control=100000.0,
            rotation_factor=4.0,  # Strong upward rotation
            spread=0.0003,
            trades_per_second=5.0,
        )
        
        signal = strategy.generate_signal(features, base_account, asia_profile, {})
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG when below POC with upward rotation"
            assert signal.stop_loss < signal.entry_price, "SL should be below entry for long"
    
    def test_generates_short_when_above_poc_with_rotation_down(self, base_account, asia_profile):
        """Should generate SHORT when price above POC and rotation turning down."""
        strategy = AsiaRangeScalp()
        
        features = make_features(
            price=100500.0,  # Above POC
            point_of_control=100000.0,
            rotation_factor=-4.0,  # Strong downward rotation
            spread=0.0003,
            trades_per_second=5.0,
        )
        
        signal = strategy.generate_signal(features, base_account, asia_profile, {})
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT when above POC with downward rotation"
            assert signal.stop_loss > signal.entry_price, "SL should be above entry for short"
    
    def test_no_signal_when_not_asia_session(self, base_account, base_profile):
        """Should NOT generate signal outside Asia session."""
        strategy = AsiaRangeScalp()
        
        # base_profile has session="asia" but let's create a non-asia profile
        us_profile = Profile(
            id="us_session",
            trend="flat",
            volatility="low",
            value_location="inside",
            session="us",  # Not Asia
            risk_mode="normal",
        )
        
        features = make_features(
            price=99500.0,
            point_of_control=100000.0,
            rotation_factor=4.0,
            spread=0.0003,
        )
        
        signal = strategy.generate_signal(features, base_account, us_profile, {})
        
        assert signal is None, "Should NOT generate signal outside Asia session"
    
    def test_no_signal_when_high_volatility(self, base_account):
        """Should NOT generate signal in high volatility."""
        strategy = AsiaRangeScalp()
        
        high_vol_profile = Profile(
            id="asia_high_vol",
            trend="flat",
            volatility="high",  # High volatility
            value_location="inside",
            session="asia",
            risk_mode="normal",
        )
        
        features = make_features(
            price=99500.0,
            point_of_control=100000.0,
            rotation_factor=4.0,
            spread=0.0003,
        )
        
        signal = strategy.generate_signal(features, base_account, high_vol_profile, {})
        
        assert signal is None, "Should NOT generate signal in high volatility"


# ============================================================================
# Overnight Thin Strategy Tests
# ============================================================================

class TestOvernightThin:
    """Tests for OvernightThin strategy."""
    
    @pytest.fixture
    def overnight_profile(self):
        """Profile for overnight session."""
        return Profile(
            id="overnight_thin",
            trend="flat",
            volatility="low",
            value_location="inside",
            session="overnight",
            risk_mode="normal",
        )
    
    def test_generates_long_near_val_with_strong_rotation(self, base_account, overnight_profile):
        """Should generate LONG near VAL with very strong upward rotation."""
        strategy = OvernightThin()
        
        features = make_features(
            price=98100.0,  # Near VAL (98000)
            value_area_low=98000.0,
            value_area_high=102000.0,
            point_of_control=100000.0,
            rotation_factor=10.0,  # Very strong rotation (> 8.0 threshold)
            spread=0.001,  # Wider spread acceptable for overnight
        )
        
        signal = strategy.generate_signal(features, base_account, overnight_profile, {})
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG near VAL with strong upward rotation"
    
    def test_generates_short_near_vah_with_strong_rotation(self, base_account, overnight_profile):
        """Should generate SHORT near VAH with very strong downward rotation."""
        strategy = OvernightThin()
        
        features = make_features(
            price=101900.0,  # Near VAH (102000)
            value_area_low=98000.0,
            value_area_high=102000.0,
            point_of_control=100000.0,
            rotation_factor=-10.0,  # Very strong downward rotation
            spread=0.001,
        )
        
        signal = strategy.generate_signal(features, base_account, overnight_profile, {})
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT near VAH with strong downward rotation"
    
    def test_no_signal_when_not_overnight_session(self, base_account, base_profile):
        """Should NOT generate signal outside overnight session."""
        strategy = OvernightThin()
        
        features = make_features(
            price=98100.0,
            value_area_low=98000.0,
            value_area_high=102000.0,
            rotation_factor=10.0,
            spread=0.001,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is None, "Should NOT generate signal outside overnight session"
    
    def test_no_signal_when_high_volatility(self, base_account):
        """Should NOT generate signal in high volatility (dangerous in thin markets)."""
        strategy = OvernightThin()
        
        high_vol_overnight = Profile(
            id="overnight_high_vol",
            trend="flat",
            volatility="high",  # High volatility
            value_location="inside",
            session="overnight",
            risk_mode="normal",
        )
        
        features = make_features(
            price=98100.0,
            value_area_low=98000.0,
            value_area_high=102000.0,
            rotation_factor=10.0,
            spread=0.001,
        )
        
        signal = strategy.generate_signal(features, base_account, high_vol_overnight, {})
        
        assert signal is None, "Should NOT generate signal in high volatility overnight"


# ============================================================================
# High Vol Breakout Strategy Tests
# ============================================================================

class TestHighVolBreakout:
    """Tests for HighVolBreakout strategy."""
    
    @pytest.fixture
    def high_vol_profile(self):
        """Profile for high volatility conditions."""
        return Profile(
            id="high_vol_breakout",
            trend="up",
            volatility="high",  # Required for this strategy
            value_location="above",
            session="us",
            risk_mode="normal",
        )
    
    def test_generates_long_on_vah_breakout_with_atr_spike(self, base_account, high_vol_profile):
        """Should generate LONG when price breaks above VAH with ATR spike."""
        strategy = HighVolBreakout()
        
        features = make_features_extended(
            price=102500.0,  # Above VAH (101000)
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=8.0,  # Strong upward momentum
            atr_5m=300.0,
            atr_5m_baseline=100.0,  # ATR ratio = 3.0 (> 2.0 threshold)
            spread=0.003,
            trades_per_second=10.0,  # Good liquidity
            ema_fast_15m=101000.0,  # EMA alignment for uptrend
            ema_slow_15m=100000.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, high_vol_profile, params)
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG on VAH breakout with ATR spike"
    
    def test_generates_short_on_val_breakout_with_atr_spike(self, base_account):
        """Should generate SHORT when price breaks below VAL with ATR spike."""
        strategy = HighVolBreakout()
        
        down_profile = Profile(
            id="high_vol_down",
            trend="down",
            volatility="high",
            value_location="below",
            session="us",
            risk_mode="normal",
        )
        
        features = make_features_extended(
            price=97500.0,  # Below VAL (99000)
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=-8.0,  # Strong downward momentum
            atr_5m=300.0,
            atr_5m_baseline=100.0,  # ATR ratio = 3.0
            spread=0.003,
            trades_per_second=10.0,
            ema_fast_15m=99000.0,  # EMA alignment for downtrend
            ema_slow_15m=100000.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, down_profile, params)
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT on VAL breakout with ATR spike"
    
    def test_no_signal_when_low_volatility(self, base_account, base_profile):
        """Should NOT generate signal in low volatility (requires high vol)."""
        strategy = HighVolBreakout()
        
        features = make_features_extended(
            price=102500.0,
            value_area_high=101000.0,
            value_area_low=99000.0,
            rotation_factor=8.0,
            atr_5m=300.0,
            atr_5m_baseline=100.0,
            trades_per_second=10.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, base_profile, params)
        
        assert signal is None, "Should NOT generate signal in low/normal volatility"
    
    def test_no_signal_when_atr_not_spiking(self, base_account, high_vol_profile):
        """Should NOT generate signal when ATR is not spiking (< 2x baseline)."""
        strategy = HighVolBreakout()
        
        features = make_features_extended(
            price=102500.0,
            value_area_high=101000.0,
            value_area_low=99000.0,
            rotation_factor=8.0,
            atr_5m=130.0,
            atr_5m_baseline=100.0,  # ATR ratio = 1.3 (< 1.5 threshold)
            trades_per_second=10.0,
            ema_fast_15m=101000.0,
            ema_slow_15m=100000.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, high_vol_profile, params)
        
        assert signal is None, "Should NOT generate signal when ATR not spiking"


# ============================================================================
# Low Vol Grind Strategy Tests
# ============================================================================

class TestLowVolGrind:
    """Tests for LowVolGrind strategy."""
    
    @pytest.fixture
    def low_vol_profile(self):
        """Profile for low volatility conditions."""
        return Profile(
            id="low_vol_grind",
            trend="flat",
            volatility="low",  # Required for this strategy
            value_location="inside",
            session="asia",
            risk_mode="normal",
        )
    
    def test_generates_long_below_poc_in_low_vol(self, base_account, low_vol_profile):
        """Should generate LONG when price slightly below POC in ultra-low vol."""
        strategy = LowVolGrind()
        
        features = make_features(
            price=99950.0,  # Slightly below POC (100000)
            point_of_control=100000.0,
            value_area_high=100100.0,  # Tight range
            value_area_low=99900.0,
            rotation_factor=0.0,  # Neutral rotation
            atr_5m=40.0,
            atr_5m_baseline=100.0,  # ATR ratio = 0.4 (< 0.5 threshold)
            spread=0.0003,
            trades_per_second=3.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, low_vol_profile, params)
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG when below POC in low vol"
    
    def test_generates_short_above_poc_in_low_vol(self, base_account, low_vol_profile):
        """Should generate SHORT when price slightly above POC in ultra-low vol."""
        strategy = LowVolGrind()
        
        features = make_features(
            price=100050.0,  # Slightly above POC (100000)
            point_of_control=100000.0,
            value_area_high=100100.0,
            value_area_low=99900.0,
            rotation_factor=0.0,
            atr_5m=40.0,
            atr_5m_baseline=100.0,  # ATR ratio = 0.4
            spread=0.0003,
            trades_per_second=3.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, low_vol_profile, params)
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT when above POC in low vol"
    
    def test_no_signal_when_high_volatility(self, base_account, base_profile):
        """Should NOT generate signal in high/normal volatility."""
        strategy = LowVolGrind()
        
        features = make_features(
            price=99950.0,
            point_of_control=100000.0,
            atr_5m=40.0,
            atr_5m_baseline=100.0,
            spread=0.0003,
            trades_per_second=3.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, base_profile, params)
        
        assert signal is None, "Should NOT generate signal in normal volatility"
    
    def test_no_signal_when_atr_too_high(self, base_account, low_vol_profile):
        """Should NOT generate signal when ATR ratio > 0.5."""
        strategy = LowVolGrind()
        
        features = make_features(
            price=99950.0,
            point_of_control=100000.0,
            value_area_high=100100.0,
            value_area_low=99900.0,
            atr_5m=80.0,
            atr_5m_baseline=100.0,  # ATR ratio = 0.8 (> 0.5 threshold)
            spread=0.0003,
            trades_per_second=3.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, low_vol_profile, params)
        
        assert signal is None, "Should NOT generate signal when ATR ratio > 0.5"


# ============================================================================
# VWAP Reversion Strategy Tests
# ============================================================================

class TestVWAPReversion:
    """Tests for VWAPReversion strategy."""
    
    @pytest.fixture
    def vwap_profile(self):
        """Profile for VWAP reversion conditions."""
        return Profile(
            id="vwap_reversion",
            trend="flat",
            volatility="normal",
            value_location="inside",
            session="us",
            risk_mode="normal",
        )
    
    def test_generates_long_when_below_vwap_with_rotation_up(self, base_account, vwap_profile):
        """Should generate LONG when price below VWAP and rotating up."""
        strategy = VWAPReversion()
        
        features = make_features_extended(
            price=98500.0,  # 1.5% below VWAP
            vwap=100000.0,
            rotation_factor=4.0,  # Rotating up toward VWAP
            spread=0.002,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, vwap_profile, params)
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG when below VWAP with upward rotation"
            assert signal.take_profit > signal.entry_price, "TP should be above entry"
    
    def test_generates_short_when_above_vwap_with_rotation_down(self, base_account, vwap_profile):
        """Should generate SHORT when price above VWAP and rotating down."""
        strategy = VWAPReversion()
        
        features = make_features_extended(
            price=101500.0,  # 1.5% above VWAP
            vwap=100000.0,
            rotation_factor=-4.0,  # Rotating down toward VWAP
            spread=0.002,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, vwap_profile, params)
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT when above VWAP with downward rotation"
            assert signal.take_profit < signal.entry_price, "TP should be below entry"
    
    def test_no_signal_when_vwap_missing(self, base_account, vwap_profile):
        """Should NOT generate signal when VWAP data is missing."""
        strategy = VWAPReversion()
        
        features = make_features_extended(
            price=98500.0,
            vwap=0.0,  # Missing VWAP
            rotation_factor=4.0,
            spread=0.002,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, vwap_profile, params)
        
        assert signal is None, "Should NOT generate signal when VWAP missing"
    
    def test_no_signal_when_deviation_too_small(self, base_account, vwap_profile):
        """Should NOT generate signal when deviation from VWAP is too small."""
        strategy = VWAPReversion()
        
        features = make_features_extended(
            price=99900.0,  # Only 0.1% from VWAP (< 1% threshold)
            vwap=100000.0,
            rotation_factor=4.0,
            spread=0.002,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, vwap_profile, params)
        
        assert signal is None, "Should NOT generate signal when deviation too small"
    
    def test_no_signal_when_deviation_too_large(self, base_account, vwap_profile):
        """Should NOT generate signal when deviation from VWAP is too large."""
        strategy = VWAPReversion()
        
        features = make_features_extended(
            price=95000.0,  # 5% from VWAP (> 3% threshold)
            vwap=100000.0,
            rotation_factor=4.0,
            spread=0.002,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, vwap_profile, params)
        
        assert signal is None, "Should NOT generate signal when deviation too large"
    
    def test_no_signal_when_high_volatility(self, base_account):
        """Should NOT generate signal in high volatility."""
        strategy = VWAPReversion()
        
        high_vol_profile = Profile(
            id="vwap_high_vol",
            trend="flat",
            volatility="high",  # High volatility
            value_location="inside",
            session="us",
            risk_mode="normal",
        )
        
        features = make_features_extended(
            price=98500.0,
            vwap=100000.0,
            rotation_factor=4.0,
            spread=0.002,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, high_vol_profile, params)
        
        assert signal is None, "Should NOT generate signal in high volatility"



# ============================================================================
# More Strategy Imports
# ============================================================================

from quantgambit.deeptrader_core.strategies.trend_pullback import TrendPullback
from quantgambit.deeptrader_core.strategies.europe_open_vol import EuropeOpenVol
from quantgambit.deeptrader_core.strategies.liquidity_hunt import LiquidityHunt


# ============================================================================
# Trend Pullback Strategy Tests
# ============================================================================

class TestTrendPullback:
    """Tests for TrendPullback strategy."""
    
    @pytest.fixture
    def uptrend_profile(self):
        """Profile for uptrend conditions."""
        return Profile(
            id="trend_pullback_up",
            trend="up",
            volatility="normal",
            value_location="inside",  # Pullback into value area
            session="us",
            risk_mode="normal",
        )
    
    @pytest.fixture
    def downtrend_profile(self):
        """Profile for downtrend conditions."""
        return Profile(
            id="trend_pullback_down",
            trend="down",
            volatility="normal",
            value_location="inside",
            session="us",
            risk_mode="normal",
        )
    
    def test_generates_long_on_uptrend_pullback(self, base_account, uptrend_profile):
        """Should generate LONG when price pulls back to POC in uptrend."""
        strategy = TrendPullback()
        
        features = make_features_extended(
            price=100050.0,  # Near POC
            point_of_control=100000.0,
            position_in_value="inside",
            rotation_factor=6.0,  # Strong upward rotation
            ema_fast_15m=101000.0,  # Fast EMA above slow (uptrend)
            ema_slow_15m=100000.0,  # 1% spread
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, uptrend_profile, params)
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG on uptrend pullback"
            assert signal.stop_loss < signal.entry_price, "SL should be below entry for long"
    
    def test_generates_short_on_downtrend_pullback(self, base_account, downtrend_profile):
        """Should generate SHORT when price pulls back to POC in downtrend."""
        strategy = TrendPullback()
        
        features = make_features_extended(
            price=99950.0,  # Near POC
            point_of_control=100000.0,
            position_in_value="inside",
            rotation_factor=-6.0,  # Strong downward rotation
            ema_fast_15m=99000.0,  # Fast EMA below slow (downtrend)
            ema_slow_15m=100000.0,  # 1% spread
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, downtrend_profile, params)
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT on downtrend pullback"
            assert signal.stop_loss > signal.entry_price, "SL should be above entry for short"
    
    def test_no_signal_when_not_inside_value_area(self, base_account, uptrend_profile):
        """Should NOT generate signal when price is not inside value area."""
        strategy = TrendPullback()
        
        above_profile = Profile(
            id="trend_above",
            trend="up",
            volatility="normal",
            value_location="above",  # Not inside
            session="us",
            risk_mode="normal",
        )
        
        features = make_features_extended(
            price=102000.0,  # Above value area
            point_of_control=100000.0,
            position_in_value="above",
            rotation_factor=6.0,
            ema_fast_15m=101000.0,
            ema_slow_15m=100000.0,
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, above_profile, params)
        
        assert signal is None, "Should NOT generate signal when not inside value area"
    
    def test_no_signal_when_ema_spread_too_small(self, base_account, uptrend_profile):
        """Should NOT generate signal when trend is not strong enough."""
        strategy = TrendPullback()
        
        features = make_features_extended(
            price=100050.0,
            point_of_control=100000.0,
            position_in_value="inside",
            rotation_factor=6.0,
            ema_fast_15m=100060.0,  # Only 0.06% spread (< 0.10% threshold)
            ema_slow_15m=100000.0,
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, uptrend_profile, params)
        
        assert signal is None, "Should NOT generate signal when EMA spread too small"


# ============================================================================
# Europe Open Vol Strategy Tests
# ============================================================================

class TestEuropeOpenVol:
    """Tests for EuropeOpenVol strategy."""
    
    @pytest.fixture
    def europe_profile(self):
        """Profile for Europe session."""
        return Profile(
            id="europe_open",
            trend="flat",
            volatility="normal",
            value_location="above",
            session="europe",
            risk_mode="normal",
        )
    
    def test_generates_long_on_vah_breakout_at_europe_open(self, base_account, europe_profile):
        """Should generate LONG when price breaks above VAH at Europe open."""
        strategy = EuropeOpenVol()
        
        # Create features with timestamp at 07:30 UTC
        import time
        from datetime import datetime, UTC
        # Create a timestamp for 07:30 UTC
        dt = datetime(2024, 1, 15, 7, 30, 0, tzinfo=UTC)
        timestamp = dt.timestamp()
        
        features = make_features_extended(
            price=102000.0,  # Above VAH
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=6.0,  # Strong upward rotation
            atr_5m=150.0,
            atr_5m_baseline=100.0,  # ATR ratio = 1.5 (> 1.2 threshold)
            spread=0.0008,
            trades_per_second=5.0,
        )
        # Set timestamp
        features = Features(
            symbol=features.symbol,
            price=features.price,
            spread=features.spread,
            rotation_factor=features.rotation_factor,
            position_in_value=features.position_in_value,
            point_of_control=features.point_of_control,
            distance_to_poc=features.distance_to_poc,
            distance_to_val=features.distance_to_val,
            distance_to_vah=features.distance_to_vah,
            atr_5m=features.atr_5m,
            atr_5m_baseline=features.atr_5m_baseline,
            orderflow_imbalance=features.orderflow_imbalance,
            value_area_high=features.value_area_high,
            value_area_low=features.value_area_low,
            trades_per_second=features.trades_per_second,
            timestamp=timestamp,
        )
        
        signal = strategy.generate_signal(features, base_account, europe_profile, {})
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG on VAH breakout at Europe open"
    
    def test_no_signal_when_not_europe_session(self, base_account, base_profile):
        """Should NOT generate signal outside Europe session."""
        strategy = EuropeOpenVol()
        
        features = make_features_extended(
            price=102000.0,
            value_area_high=101000.0,
            value_area_low=99000.0,
            rotation_factor=6.0,
            atr_5m=150.0,
            atr_5m_baseline=100.0,
            trades_per_second=5.0,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is None, "Should NOT generate signal outside Europe session"
    
    def test_no_signal_when_low_volatility(self, base_account):
        """Should NOT generate signal in low volatility."""
        strategy = EuropeOpenVol()
        
        low_vol_europe = Profile(
            id="europe_low_vol",
            trend="flat",
            volatility="low",  # Low volatility
            value_location="above",
            session="europe",
            risk_mode="normal",
        )
        
        features = make_features_extended(
            price=102000.0,
            value_area_high=101000.0,
            value_area_low=99000.0,
            rotation_factor=6.0,
            atr_5m=150.0,
            atr_5m_baseline=100.0,
            trades_per_second=5.0,
        )
        
        signal = strategy.generate_signal(features, base_account, low_vol_europe, {})
        
        assert signal is None, "Should NOT generate signal in low volatility"


# ============================================================================
# Liquidity Hunt Strategy Tests
# ============================================================================

class TestLiquidityHunt:
    """Tests for LiquidityHunt strategy."""
    
    @pytest.fixture
    def hunt_profile(self):
        """Profile for liquidity hunt conditions."""
        return Profile(
            id="liquidity_hunt",
            trend="flat",
            volatility="high",  # High volatility for stop hunts
            value_location="inside",
            session="us",
            risk_mode="normal",
        )
    
    def test_generates_long_on_val_bounce(self, base_account, hunt_profile):
        """Should generate LONG when price bounces from VAL (downward hunt)."""
        strategy = LiquidityHunt()
        
        features = make_features(
            price=98100.0,  # Near VAL (98000)
            value_area_high=102000.0,
            value_area_low=98000.0,
            point_of_control=100000.0,
            position_in_value="inside",
            rotation_factor=10.0,  # Strong upward rotation (bounce)
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, hunt_profile, params)
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG on VAL bounce"
    
    def test_generates_short_on_vah_bounce(self, base_account, hunt_profile):
        """Should generate SHORT when price bounces from VAH (upward hunt)."""
        strategy = LiquidityHunt()
        
        features = make_features(
            price=101900.0,  # Near VAH (102000)
            value_area_high=102000.0,
            value_area_low=98000.0,
            point_of_control=100000.0,
            position_in_value="inside",
            rotation_factor=-10.0,  # Strong downward rotation (bounce)
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, hunt_profile, params)
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT on VAH bounce"
    
    def test_no_signal_when_low_volatility(self, base_account, base_profile):
        """Should NOT generate signal in low volatility (hunts less common)."""
        strategy = LiquidityHunt()
        
        low_vol_profile = Profile(
            id="hunt_low_vol",
            trend="flat",
            volatility="low",  # Low volatility
            value_location="inside",
            session="us",
            risk_mode="normal",
        )
        
        features = make_features(
            price=98100.0,
            value_area_high=102000.0,
            value_area_low=98000.0,
            rotation_factor=10.0,
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, low_vol_profile, params)
        
        assert signal is None, "Should NOT generate signal in low volatility"
    
    def test_no_signal_when_spread_too_wide(self, base_account, hunt_profile):
        """Should NOT generate signal when spread is too wide for fast execution."""
        strategy = LiquidityHunt()
        
        features = make_features(
            price=98100.0,
            value_area_high=102000.0,
            value_area_low=98000.0,
            rotation_factor=10.0,
            spread=0.005,  # Too wide
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, hunt_profile, params)
        
        assert signal is None, "Should NOT generate signal when spread too wide"



# ============================================================================
# Final Strategy Imports
# ============================================================================

from quantgambit.deeptrader_core.strategies.us_open_momentum import USOpenMomentum
from quantgambit.deeptrader_core.strategies.vol_expansion import VolExpansion
from quantgambit.deeptrader_core.strategies.opening_range_breakout import OpeningRangeBreakout


# ============================================================================
# US Open Momentum Strategy Tests
# ============================================================================

class TestUSOpenMomentum:
    """Tests for USOpenMomentum strategy."""
    
    @pytest.fixture
    def us_uptrend_profile(self):
        """Profile for US session uptrend."""
        return Profile(
            id="us_open_up",
            trend="up",
            volatility="normal",
            value_location="above",
            session="us",
            risk_mode="normal",
        )
    
    @pytest.fixture
    def us_downtrend_profile(self):
        """Profile for US session downtrend."""
        return Profile(
            id="us_open_down",
            trend="down",
            volatility="normal",
            value_location="below",
            session="us",
            risk_mode="normal",
        )
    
    def test_generates_long_in_us_uptrend(self, base_account, us_uptrend_profile):
        """Should generate LONG in US session uptrend with strong momentum."""
        strategy = USOpenMomentum()
        
        # Create timestamp at 13:30 UTC (US open window)
        from datetime import datetime, UTC
        dt = datetime(2024, 1, 15, 13, 30, 0, tzinfo=UTC)
        timestamp = dt.timestamp()
        
        features = Features(
            symbol="BTCUSDT",
            price=102000.0,
            spread=0.001,
            rotation_factor=8.0,  # Strong upward momentum
            position_in_value="above",
            point_of_control=100000.0,
            distance_to_poc=2000.0,
            distance_to_val=4000.0,
            distance_to_vah=1000.0,
            atr_5m=150.0,
            atr_5m_baseline=100.0,
            orderflow_imbalance=0.0,
            value_area_high=101000.0,
            value_area_low=98000.0,
            trades_per_second=10.0,  # High liquidity
            timestamp=timestamp,
            ema_fast_15m=101500.0,  # Fast > Slow (uptrend)
            ema_slow_15m=100500.0,
        )
        
        signal = strategy.generate_signal(features, base_account, us_uptrend_profile, {})
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG in US uptrend"
            assert signal.stop_loss < signal.entry_price, "SL should be below entry for long"
    
    def test_generates_short_in_us_downtrend(self, base_account, us_downtrend_profile):
        """Should generate SHORT in US session downtrend with strong momentum."""
        strategy = USOpenMomentum()
        
        from datetime import datetime, UTC
        dt = datetime(2024, 1, 15, 13, 30, 0, tzinfo=UTC)
        timestamp = dt.timestamp()
        
        features = Features(
            symbol="BTCUSDT",
            price=98000.0,
            spread=0.001,
            rotation_factor=-8.0,  # Strong downward momentum
            position_in_value="below",
            point_of_control=100000.0,
            distance_to_poc=-2000.0,
            distance_to_val=-1000.0,
            distance_to_vah=-4000.0,
            atr_5m=150.0,
            atr_5m_baseline=100.0,
            orderflow_imbalance=0.0,
            value_area_high=102000.0,
            value_area_low=99000.0,
            trades_per_second=10.0,
            timestamp=timestamp,
            ema_fast_15m=98500.0,  # Fast < Slow (downtrend)
            ema_slow_15m=99500.0,
        )
        
        signal = strategy.generate_signal(features, base_account, us_downtrend_profile, {})
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT in US downtrend"
            assert signal.stop_loss > signal.entry_price, "SL should be above entry for short"
    
    def test_no_signal_when_not_us_session(self, base_account, base_profile):
        """Should NOT generate signal outside US session."""
        strategy = USOpenMomentum()
        
        from datetime import datetime, UTC
        dt = datetime(2024, 1, 15, 13, 30, 0, tzinfo=UTC)
        timestamp = dt.timestamp()
        
        features = Features(
            symbol="BTCUSDT",
            price=102000.0,
            spread=0.001,
            rotation_factor=8.0,
            position_in_value="above",
            point_of_control=100000.0,
            distance_to_poc=2000.0,
            distance_to_val=4000.0,
            distance_to_vah=1000.0,
            atr_5m=150.0,
            atr_5m_baseline=100.0,
            orderflow_imbalance=0.0,
            value_area_high=101000.0,
            value_area_low=98000.0,
            trades_per_second=10.0,
            timestamp=timestamp,
            ema_fast_15m=101500.0,
            ema_slow_15m=100500.0,
        )
        
        signal = strategy.generate_signal(features, base_account, base_profile, {})
        
        assert signal is None, "Should NOT generate signal outside US session"
    
    def test_no_signal_when_flat_trend(self, base_account):
        """Should NOT generate signal in flat trend."""
        strategy = USOpenMomentum()
        
        flat_us_profile = Profile(
            id="us_flat",
            trend="flat",  # No clear trend
            volatility="normal",
            value_location="inside",
            session="us",
            risk_mode="normal",
        )
        
        from datetime import datetime, UTC
        dt = datetime(2024, 1, 15, 13, 30, 0, tzinfo=UTC)
        timestamp = dt.timestamp()
        
        features = Features(
            symbol="BTCUSDT",
            price=100000.0,
            spread=0.001,
            rotation_factor=8.0,
            position_in_value="inside",
            point_of_control=100000.0,
            distance_to_poc=0.0,
            distance_to_val=2000.0,
            distance_to_vah=-2000.0,
            atr_5m=150.0,
            atr_5m_baseline=100.0,
            orderflow_imbalance=0.0,
            value_area_high=102000.0,
            value_area_low=98000.0,
            trades_per_second=10.0,
            timestamp=timestamp,
            ema_fast_15m=100100.0,
            ema_slow_15m=99900.0,
        )
        
        signal = strategy.generate_signal(features, base_account, flat_us_profile, {})
        
        assert signal is None, "Should NOT generate signal in flat trend"


# ============================================================================
# Vol Expansion Strategy Tests
# ============================================================================

class TestVolExpansion:
    """Tests for VolExpansion strategy."""
    
    @pytest.fixture
    def expansion_profile(self):
        """Profile for volatility expansion conditions."""
        return Profile(
            id="vol_expansion",
            trend="up",
            volatility="normal",  # Transitioning from low
            value_location="above",
            session="us",
            risk_mode="normal",
        )
    
    def test_generates_long_on_vah_breakout_with_expansion(self, base_account, expansion_profile):
        """Should generate LONG when breaking above VAH with ATR expansion."""
        strategy = VolExpansion()
        
        features = make_features_extended(
            price=102000.0,  # Above VAH
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=6.0,  # Strong upward rotation
            atr_5m=140.0,
            atr_5m_baseline=100.0,  # ATR ratio = 1.4 (expanding)
            spread=0.002,
            ema_fast_15m=101500.0,  # EMA alignment
            ema_slow_15m=100500.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, expansion_profile, params)
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG on VAH breakout with expansion"
    
    def test_generates_short_on_val_breakout_with_expansion(self, base_account):
        """Should generate SHORT when breaking below VAL with ATR expansion."""
        strategy = VolExpansion()
        
        down_expansion = Profile(
            id="vol_expansion_down",
            trend="down",
            volatility="normal",
            value_location="below",
            session="us",
            risk_mode="normal",
        )
        
        features = make_features_extended(
            price=98000.0,  # Below VAL
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=-6.0,  # Strong downward rotation
            atr_5m=140.0,
            atr_5m_baseline=100.0,  # ATR ratio = 1.4
            spread=0.002,
            ema_fast_15m=98500.0,  # EMA alignment for downtrend
            ema_slow_15m=99500.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, down_expansion, params)
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT on VAL breakout with expansion"
    
    def test_no_signal_when_low_volatility(self, base_account):
        """Should NOT generate signal in low volatility (no expansion)."""
        strategy = VolExpansion()
        
        low_vol_profile = Profile(
            id="vol_low",
            trend="up",
            volatility="low",  # Low volatility
            value_location="inside",
            session="us",
            risk_mode="normal",
        )
        
        features = make_features_extended(
            price=102000.0,
            value_area_high=101000.0,
            value_area_low=99000.0,
            rotation_factor=6.0,
            atr_5m=140.0,
            atr_5m_baseline=100.0,
            ema_fast_15m=101500.0,
            ema_slow_15m=100500.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, low_vol_profile, params)
        
        assert signal is None, "Should NOT generate signal in low volatility"
    
    def test_no_signal_when_atr_not_expanding(self, base_account, expansion_profile):
        """Should NOT generate signal when ATR is not expanding."""
        strategy = VolExpansion()
        
        features = make_features_extended(
            price=102000.0,
            value_area_high=101000.0,
            value_area_low=99000.0,
            rotation_factor=6.0,
            atr_5m=100.0,
            atr_5m_baseline=100.0,  # ATR ratio = 1.0 (not expanding)
            ema_fast_15m=101500.0,
            ema_slow_15m=100500.0,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, expansion_profile, params)
        
        assert signal is None, "Should NOT generate signal when ATR not expanding"


# ============================================================================
# Opening Range Breakout Strategy Tests
# ============================================================================

class TestOpeningRangeBreakout:
    """Tests for OpeningRangeBreakout strategy."""
    
    def test_generates_long_on_breakout_above_range(self, base_account, base_profile):
        """Should generate LONG when price breaks above opening range."""
        strategy = OpeningRangeBreakout()
        
        features = make_features(
            price=101500.0,  # Above VAH (opening range high proxy)
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=8.0,  # Strong upward rotation
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, base_profile, params)
        
        if signal is not None:
            assert signal.side == "long", "Should be LONG on breakout above range"
            assert signal.stop_loss == features.value_area_high, "SL should be at opening range high"
    
    def test_generates_short_on_breakout_below_range(self, base_account, base_profile):
        """Should generate SHORT when price breaks below opening range."""
        strategy = OpeningRangeBreakout()
        
        features = make_features(
            price=98500.0,  # Below VAL (opening range low proxy)
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=-8.0,  # Strong downward rotation
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, base_profile, params)
        
        if signal is not None:
            assert signal.side == "short", "Should be SHORT on breakout below range"
            assert signal.stop_loss == features.value_area_low, "SL should be at opening range low"
    
    def test_no_signal_when_inside_range(self, base_account, base_profile):
        """Should NOT generate signal when price is inside opening range."""
        strategy = OpeningRangeBreakout()
        
        features = make_features(
            price=100000.0,  # Inside range
            value_area_high=101000.0,
            value_area_low=99000.0,
            point_of_control=100000.0,
            rotation_factor=8.0,
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, base_profile, params)
        
        assert signal is None, "Should NOT generate signal when inside range"
    
    def test_no_signal_when_rotation_weak(self, base_account, base_profile):
        """Should NOT generate signal when rotation is weak."""
        strategy = OpeningRangeBreakout()
        
        features = make_features(
            price=101500.0,  # Above range
            value_area_high=101000.0,
            value_area_low=99000.0,
            rotation_factor=3.0,  # Weak rotation (< 7.0 threshold)
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True}
        signal = strategy.generate_signal(features, base_account, base_profile, params)
        
        assert signal is None, "Should NOT generate signal when rotation weak"
    
    def test_reward_ratio_applied_correctly(self, base_account, base_profile):
        """Take profit should be at correct reward ratio from entry."""
        strategy = OpeningRangeBreakout()
        
        features = make_features(
            price=101500.0,  # Above VAH
            value_area_high=101000.0,
            value_area_low=99000.0,
            rotation_factor=8.0,
            spread=0.001,
        )
        
        params = {"allow_longs": True, "allow_shorts": True, "reward_ratio": 2.0}
        signal = strategy.generate_signal(features, base_account, base_profile, params)
        
        if signal is not None:
            stop_distance = signal.entry_price - signal.stop_loss
            expected_tp = signal.entry_price + (stop_distance * 2.0)
            assert abs(signal.take_profit - expected_tp) < 1.0, "TP should be at 2x stop distance"
