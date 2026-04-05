"""
Unit tests for feature correctness.

These tests verify:
1. Consistent bps vs pct conversions
2. Sign conventions (imbalance + = buy pressure everywhere)
3. Spread calculations use mid price consistently
4. No unit mismatches (decimals vs percentages)
"""

import pytest
from dataclasses import dataclass
from typing import Optional


# ============================================================================
# TEST: Spread calculations
# ============================================================================

def calculate_spread_bps_correct(bid: float, ask: float) -> Optional[float]:
    """
    Correct way to calculate spread in basis points.
    
    Uses mid price as denominator (not bid or ask alone).
    spread_bps = ((ask - bid) / mid) * 10000
    
    Example:
        bid=100, ask=100.10 -> mid=100.05, spread=0.10
        spread_bps = (0.10 / 100.05) * 10000 = 9.995 bps
    """
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    spread = ask - bid
    return (spread / mid) * 10000


def calculate_spread_bps_wrong_bid(bid: float, ask: float) -> Optional[float]:
    """
    WRONG: Using bid as denominator (slightly inflates spread).
    """
    if bid is None or ask is None or bid <= 0:
        return None
    spread = ask - bid
    return (spread / bid) * 10000


def calculate_spread_bps_wrong_pct(bid: float, ask: float) -> Optional[float]:
    """
    WRONG: Returns percentage instead of basis points.
    """
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    spread = ask - bid
    return spread / mid  # Missing * 10000!


class TestSpreadCalculation:
    """Test spread_bps calculation consistency."""
    
    def test_spread_bps_basic(self):
        """Basic spread calculation."""
        bid, ask = 100.0, 100.10
        spread_bps = calculate_spread_bps_correct(bid, ask)
        
        # 10 cent spread on $100.05 mid = ~10 bps
        assert spread_bps is not None
        assert 9.9 < spread_bps < 10.1
    
    def test_spread_bps_tight(self):
        """Tight spread (1 bps)."""
        bid, ask = 10000.0, 10001.0
        spread_bps = calculate_spread_bps_correct(bid, ask)
        
        # $1 spread on $10000.50 mid = ~1 bps
        assert spread_bps is not None
        assert 0.99 < spread_bps < 1.01
    
    def test_spread_bps_wide(self):
        """Wide spread (100 bps = 1%)."""
        bid, ask = 100.0, 101.0
        spread_bps = calculate_spread_bps_correct(bid, ask)
        
        # $1 spread on $100.50 mid = ~100 bps
        assert spread_bps is not None
        assert 99 < spread_bps < 101
    
    def test_spread_bps_vs_wrong_bid(self):
        """Verify using bid as denominator gives slightly different result."""
        bid, ask = 100.0, 100.10
        correct = calculate_spread_bps_correct(bid, ask)
        wrong = calculate_spread_bps_wrong_bid(bid, ask)
        
        # Using bid as denominator inflates spread slightly
        assert wrong > correct
        # Difference is small but measurable
        assert abs(wrong - correct) < 0.5  # Less than 0.5 bps difference
    
    def test_spread_pct_vs_bps_unit_mismatch(self):
        """Verify pct vs bps unit mismatch would be catastrophic."""
        bid, ask = 100.0, 100.10
        correct_bps = calculate_spread_bps_correct(bid, ask)
        wrong_pct = calculate_spread_bps_wrong_pct(bid, ask)
        
        # BPS should be 10000x larger than pct
        assert correct_bps is not None
        assert wrong_pct is not None
        assert correct_bps / wrong_pct == pytest.approx(10000, rel=0.01)
    
    def test_spread_bps_crypto_btc(self):
        """Real crypto example: BTC spread."""
        bid, ask = 90000.0, 90002.0  # $2 spread on BTC
        spread_bps = calculate_spread_bps_correct(bid, ask)
        
        # $2 / $90001 * 10000 = 0.22 bps
        assert spread_bps is not None
        assert 0.2 < spread_bps < 0.3
    
    def test_spread_bps_edge_cases(self):
        """Edge cases."""
        # Zero bid
        assert calculate_spread_bps_correct(0, 100) is None
        # Zero ask
        assert calculate_spread_bps_correct(100, 0) is None
        # Negative bid (shouldn't happen)
        assert calculate_spread_bps_correct(-100, 100) is None
        # None values
        assert calculate_spread_bps_correct(None, 100) is None
        assert calculate_spread_bps_correct(100, None) is None


# ============================================================================
# TEST: Orderflow imbalance sign convention
# ============================================================================

def calculate_orderflow_imbalance(buy_volume: float, sell_volume: float) -> float:
    """
    Calculate orderflow imbalance.
    
    Convention:
        - Positive (+) = Buy pressure (more buying than selling)
        - Negative (-) = Sell pressure (more selling than buying)
        - Range: -1.0 to +1.0
    
    Formula: (buy_volume - sell_volume) / (buy_volume + sell_volume)
    """
    total = buy_volume + sell_volume
    if total == 0:
        return 0.0
    return (buy_volume - sell_volume) / total


def calculate_orderbook_imbalance(bid_depth: float, ask_depth: float) -> float:
    """
    Calculate orderbook imbalance.
    
    Convention:
        - Positive (+) = More bid depth (buyers waiting)
        - Negative (-) = More ask depth (sellers waiting)
        - Range: -1.0 to +1.0
    
    Formula: (bid_depth - ask_depth) / (bid_depth + ask_depth)
    """
    total = bid_depth + ask_depth
    if total == 0:
        return 0.0
    return (bid_depth - ask_depth) / total


class TestImbalanceSignConvention:
    """Test imbalance sign conventions."""
    
    def test_orderflow_positive_is_buy_pressure(self):
        """Positive orderflow = buy pressure."""
        imb = calculate_orderflow_imbalance(buy_volume=100, sell_volume=50)
        assert imb > 0
        assert 0.3 < imb < 0.4  # (100-50)/150 = 0.33
    
    def test_orderflow_negative_is_sell_pressure(self):
        """Negative orderflow = sell pressure."""
        imb = calculate_orderflow_imbalance(buy_volume=50, sell_volume=100)
        assert imb < 0
        assert -0.4 < imb < -0.3  # (50-100)/150 = -0.33
    
    def test_orderflow_balanced(self):
        """Equal volume = neutral."""
        imb = calculate_orderflow_imbalance(buy_volume=100, sell_volume=100)
        assert imb == 0.0
    
    def test_orderflow_extreme_buy(self):
        """All buys = +1.0."""
        imb = calculate_orderflow_imbalance(buy_volume=100, sell_volume=0)
        assert imb == 1.0
    
    def test_orderflow_extreme_sell(self):
        """All sells = -1.0."""
        imb = calculate_orderflow_imbalance(buy_volume=0, sell_volume=100)
        assert imb == -1.0
    
    def test_orderbook_positive_is_bid_heavy(self):
        """Positive orderbook imbalance = more bids."""
        imb = calculate_orderbook_imbalance(bid_depth=100, ask_depth=50)
        assert imb > 0
    
    def test_orderbook_negative_is_ask_heavy(self):
        """Negative orderbook imbalance = more asks."""
        imb = calculate_orderbook_imbalance(bid_depth=50, ask_depth=100)
        assert imb < 0
    
    def test_orderflow_matches_orderbook_convention(self):
        """Both imbalance measures use same sign convention."""
        # Both positive when buying pressure
        of_imb = calculate_orderflow_imbalance(buy_volume=100, sell_volume=50)
        ob_imb = calculate_orderbook_imbalance(bid_depth=100, ask_depth=50)
        
        assert of_imb > 0
        assert ob_imb > 0
        
        # Both negative when selling pressure
        of_imb = calculate_orderflow_imbalance(buy_volume=50, sell_volume=100)
        ob_imb = calculate_orderbook_imbalance(bid_depth=50, ask_depth=100)
        
        assert of_imb < 0
        assert ob_imb < 0


# ============================================================================
# TEST: Percentage vs decimal consistency
# ============================================================================

@dataclass
class RiskParameters:
    """Example risk parameters to test unit consistency."""
    stop_loss_pct: float  # Should be decimal (0.01 = 1%)
    take_profit_pct: float  # Should be decimal (0.02 = 2%)
    max_position_pct: float  # Should be decimal (0.1 = 10%)


def apply_stop_loss_correct(entry_price: float, stop_loss_pct: float, side: str) -> float:
    """
    Apply stop loss correctly (pct as decimal).
    
    Args:
        entry_price: Entry price
        stop_loss_pct: Stop loss as decimal (0.01 = 1%)
        side: 'long' or 'short'
    """
    if side == 'long':
        return entry_price * (1 - stop_loss_pct)
    else:
        return entry_price * (1 + stop_loss_pct)


def apply_stop_loss_wrong(entry_price: float, stop_loss_pct: float, side: str) -> float:
    """
    WRONG: Treating pct as already multiplied by 100.
    """
    if side == 'long':
        return entry_price * (1 - stop_loss_pct / 100)  # Wrong!
    else:
        return entry_price * (1 + stop_loss_pct / 100)


class TestPercentageConsistency:
    """Test percentage/decimal unit consistency."""
    
    def test_stop_loss_decimal_convention(self):
        """Stop loss pct should be decimal (0.01 = 1%)."""
        entry = 100.0
        sl_pct = 0.01  # 1% stop loss
        
        # Long: stop below entry
        sl_price_long = apply_stop_loss_correct(entry, sl_pct, 'long')
        assert sl_price_long == 99.0  # 100 * (1 - 0.01) = 99
        
        # Short: stop above entry
        sl_price_short = apply_stop_loss_correct(entry, sl_pct, 'short')
        assert sl_price_short == 101.0  # 100 * (1 + 0.01) = 101
    
    def test_wrong_percentage_interpretation(self):
        """Verify wrong interpretation gives wildly different result."""
        entry = 100.0
        sl_pct = 0.01  # 1% stop loss
        
        correct = apply_stop_loss_correct(entry, sl_pct, 'long')
        wrong = apply_stop_loss_wrong(entry, sl_pct, 'long')
        
        # Correct: 99.0 (1% down from 100)
        # Wrong: 99.99 (0.01% down from 100)
        assert correct == 99.0
        assert wrong == pytest.approx(99.99, rel=0.001)
        
        # The difference is 0.99 - almost 1% error!
        assert abs(correct - wrong) > 0.9
    
    def test_take_profit_decimal_convention(self):
        """Take profit pct should be decimal."""
        entry = 100.0
        tp_pct = 0.02  # 2% take profit
        
        # Long: target above entry
        tp_price_long = entry * (1 + tp_pct)
        assert tp_price_long == 102.0
        
        # Short: target below entry
        tp_price_short = entry * (1 - tp_pct)
        assert tp_price_short == 98.0


# ============================================================================
# TEST: BPS to decimal conversions
# ============================================================================

def bps_to_decimal(bps: float) -> float:
    """Convert basis points to decimal."""
    return bps / 10000


def decimal_to_bps(decimal: float) -> float:
    """Convert decimal to basis points."""
    return decimal * 10000


def pct_to_decimal(pct: float) -> float:
    """Convert percentage to decimal."""
    return pct / 100


def decimal_to_pct(decimal: float) -> float:
    """Convert decimal to percentage."""
    return decimal * 100


class TestUnitConversions:
    """Test unit conversion functions."""
    
    def test_bps_to_decimal(self):
        """1 bps = 0.0001 = 0.01%"""
        assert bps_to_decimal(1) == 0.0001
        assert bps_to_decimal(10) == 0.001
        assert bps_to_decimal(100) == 0.01
        assert bps_to_decimal(10000) == 1.0
    
    def test_decimal_to_bps(self):
        """0.0001 = 1 bps"""
        assert decimal_to_bps(0.0001) == 1
        assert decimal_to_bps(0.001) == 10
        assert decimal_to_bps(0.01) == 100
        assert decimal_to_bps(1.0) == 10000
    
    def test_pct_to_decimal(self):
        """1% = 0.01"""
        assert pct_to_decimal(1) == 0.01
        assert pct_to_decimal(50) == 0.5
        assert pct_to_decimal(100) == 1.0
    
    def test_decimal_to_pct(self):
        """0.01 = 1%"""
        assert decimal_to_pct(0.01) == 1
        assert decimal_to_pct(0.5) == 50
        assert decimal_to_pct(1.0) == 100
    
    def test_roundtrip_conversions(self):
        """Verify roundtrip conversions are lossless."""
        original_bps = 42.5
        assert decimal_to_bps(bps_to_decimal(original_bps)) == pytest.approx(original_bps)
        
        original_pct = 3.14159
        assert decimal_to_pct(pct_to_decimal(original_pct)) == pytest.approx(original_pct)
    
    def test_bps_pct_relationship(self):
        """1 bps = 0.01%"""
        bps_value = 100  # 100 bps
        pct_value = 1.0  # 1%
        
        # Both should equal 0.01 in decimal
        assert bps_to_decimal(bps_value) == pct_to_decimal(pct_value)


# ============================================================================
# TEST: Fee calculations
# ============================================================================

def calculate_fee_from_bps(notional: float, fee_bps: float) -> float:
    """Calculate fee from basis points."""
    return notional * (fee_bps / 10000)


def calculate_fee_from_pct(notional: float, fee_pct: float) -> float:
    """Calculate fee from percentage."""
    return notional * (fee_pct / 100)


class TestFeeCalculations:
    """Test fee calculation consistency."""
    
    def test_fee_bps_basic(self):
        """5 bps on $10,000 = $5"""
        fee = calculate_fee_from_bps(10000, 5)
        assert fee == 5.0
    
    def test_fee_pct_basic(self):
        """0.05% on $10,000 = $5"""
        fee = calculate_fee_from_pct(10000, 0.05)
        assert fee == 5.0
    
    def test_fee_bps_equals_pct(self):
        """5 bps = 0.05%"""
        notional = 10000
        fee_from_bps = calculate_fee_from_bps(notional, 5)
        fee_from_pct = calculate_fee_from_pct(notional, 0.05)
        
        assert fee_from_bps == fee_from_pct
    
    def test_fee_maker_taker_typical(self):
        """Typical crypto fees: 2bps maker, 5bps taker"""
        notional = 50000  # $50k order
        
        maker_fee = calculate_fee_from_bps(notional, 2)  # 2 bps
        taker_fee = calculate_fee_from_bps(notional, 5)  # 5 bps
        
        assert maker_fee == 10.0  # $10
        assert taker_fee == 25.0  # $25
        
        # Taker is 2.5x maker
        assert taker_fee / maker_fee == 2.5
