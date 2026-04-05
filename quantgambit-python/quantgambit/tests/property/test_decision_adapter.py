"""Property-based tests for BacktestDecisionAdapter field mapping.

Feature: backtest-field-mapping-fix

Tests that:
- DecisionInput features dict contains bid, ask, best_bid, best_ask fields
- Field values are consistent (bid == best_bid, ask == best_ask)
- Market context contains best_bid and best_ask fields

Validates: Requirements 1.1, 1.2, 1.3, 4.1, 4.2
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from quantgambit.backtesting.decision_adapter import BacktestDecisionAdapter
from quantgambit.deeptrader_core.types import MarketSnapshot, Features, AccountState


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Generate realistic price values (positive, reasonable range)
price_strategy = st.floats(min_value=1000.0, max_value=200000.0, allow_nan=False, allow_infinity=False)

# Generate spread in basis points (positive)
spread_bps_strategy = st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)

# Generate depth in USD
depth_strategy = st.floats(min_value=0.0, max_value=10000000.0, allow_nan=False, allow_infinity=False)

# Generate imbalance values (-1 to 1)
imbalance_strategy = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Generate trend direction
trend_direction_strategy = st.sampled_from(["up", "down", "flat"])

# Generate volatility regime
vol_regime_strategy = st.sampled_from(["low", "normal", "high", "extreme"])

# Generate position in value
position_in_value_strategy = st.sampled_from(["above", "below", "inside"])

# Generate symbol
symbol_strategy = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])


@st.composite
def market_snapshot_strategy(draw):
    """Generate a MarketSnapshot with valid bid/ask prices.
    
    Ensures bid < ask (valid spread) and both are positive.
    """
    mid_price = draw(price_strategy)
    spread_bps = draw(spread_bps_strategy)
    
    # Calculate bid/ask from mid price and spread
    bid = mid_price * (1 - spread_bps / 20000)
    ask = mid_price * (1 + spread_bps / 20000)
    
    # Ensure bid < ask (valid market)
    assume(bid > 0)
    assume(ask > bid)
    
    return MarketSnapshot(
        symbol=draw(symbol_strategy),
        exchange="bybit",
        timestamp_ns=int(draw(st.integers(min_value=1000000000000000000, max_value=2000000000000000000))),
        snapshot_age_ms=draw(st.floats(min_value=0, max_value=5000, allow_nan=False)),
        mid_price=mid_price,
        bid=bid,
        ask=ask,
        spread_bps=spread_bps,
        bid_depth_usd=draw(depth_strategy),
        ask_depth_usd=draw(depth_strategy),
        depth_imbalance=draw(imbalance_strategy),
        imb_1s=draw(imbalance_strategy),
        imb_5s=draw(imbalance_strategy),
        imb_30s=draw(imbalance_strategy),
        orderflow_persistence_sec=0,
        rv_1s=0,
        rv_10s=0,
        rv_1m=0,
        vol_shock=draw(st.booleans()),
        vol_regime=draw(vol_regime_strategy),
        vol_regime_score=draw(st.floats(min_value=0, max_value=1, allow_nan=False)),
        trend_direction=draw(trend_direction_strategy),
        trend_strength=draw(st.floats(min_value=0, max_value=1, allow_nan=False)),
        poc_price=mid_price * draw(st.floats(min_value=0.95, max_value=1.05, allow_nan=False)),
        vah_price=mid_price * draw(st.floats(min_value=1.0, max_value=1.1, allow_nan=False)),
        val_price=mid_price * draw(st.floats(min_value=0.9, max_value=1.0, allow_nan=False)),
        position_in_value=draw(position_in_value_strategy),
        expected_fill_slippage_bps=draw(st.floats(min_value=0, max_value=10, allow_nan=False)),
        typical_spread_bps=spread_bps,
        data_quality_score=draw(st.floats(min_value=0, max_value=1, allow_nan=False)),
        ws_connected=True,
    )


@st.composite
def features_strategy(draw):
    """Generate a Features object with random but valid values."""
    price = draw(price_strategy)
    poc = price * draw(st.floats(min_value=0.95, max_value=1.05, allow_nan=False))
    
    return Features(
        symbol=draw(symbol_strategy),
        price=price,
        spread=draw(st.floats(min_value=0, max_value=0.01, allow_nan=False)),
        rotation_factor=draw(st.floats(min_value=-10, max_value=10, allow_nan=False)),
        position_in_value=draw(position_in_value_strategy),
        timestamp=draw(st.floats(min_value=1000000000, max_value=2000000000, allow_nan=False)),
        distance_to_val=draw(st.floats(min_value=-1000, max_value=1000, allow_nan=False)),
        distance_to_vah=draw(st.floats(min_value=-1000, max_value=1000, allow_nan=False)),
        distance_to_poc=price - poc,
        value_area_low=poc * 0.98,
        value_area_high=poc * 1.02,
        point_of_control=poc,
        atr_5m=price * 0.005,
        atr_5m_baseline=price * 0.005,
        bid_depth_usd=draw(depth_strategy),
        ask_depth_usd=draw(depth_strategy),
        orderbook_imbalance=draw(imbalance_strategy),
        orderflow_imbalance=draw(imbalance_strategy),
    )


@st.composite
def account_state_strategy(draw):
    """Generate an AccountState with random but valid values."""
    equity = draw(st.floats(min_value=1000, max_value=1000000, allow_nan=False))
    
    return AccountState(
        equity=equity,
        daily_pnl=draw(st.floats(min_value=-equity * 0.1, max_value=equity * 0.1, allow_nan=False)),
        max_daily_loss=equity * 0.02,
        open_positions=draw(st.integers(min_value=0, max_value=5)),
        symbol_open_positions=draw(st.integers(min_value=0, max_value=3)),
        symbol_daily_pnl=draw(st.floats(min_value=-1000, max_value=1000, allow_nan=False)),
    )


# =============================================================================
# Property Tests
# =============================================================================

class TestBacktestDecisionAdapterFieldCompleteness:
    """Property-based tests for BacktestDecisionAdapter field completeness.
    
    Feature: backtest-field-mapping-fix, Property 1: BacktestDecisionAdapter Field Completeness
    
    **Validates: Requirements 1.1, 1.3, 4.1, 4.2**
    """
    
    @given(
        snapshot=market_snapshot_strategy(),
        features=features_strategy(),
        account=account_state_strategy(),
    )
    @settings(max_examples=100)
    def test_decision_adapter_features_field_completeness(
        self,
        snapshot: MarketSnapshot,
        features: Features,
        account: AccountState,
    ):
        """Property 1: BacktestDecisionAdapter Field Completeness.
        
        *For any* MarketSnapshot with valid bid/ask prices, when BacktestDecisionAdapter
        builds a DecisionInput, the features dict SHALL contain `bid`, `ask`, `best_bid`,
        and `best_ask` fields, with `bid == best_bid` and `ask == best_ask`.
        
        **Validates: Requirements 1.1, 1.3, 4.1, 4.2**
        
        - 1.1: features dict SHALL contain both `bid`/`ask` AND `best_bid`/`best_ask` fields with the same values
        - 1.3: preserve existing `bid` and `ask` fields for backwards compatibility
        - 4.1: `best_bid` field SHALL have the same value as the `bid` field
        - 4.2: `best_ask` field SHALL have the same value as the `ask` field
        """
        # Create a mock DecisionEngine (we only need to test _build_decision_input)
        mock_engine = MagicMock()
        
        # Create adapter
        adapter = BacktestDecisionAdapter(decision_engine=mock_engine)
        
        # Build DecisionInput using the adapter's internal method
        decision_input = adapter._build_decision_input(
            symbol=snapshot.symbol,
            snapshot=snapshot,
            features=features,
            account_state=account,
            positions=None,
            profile_settings=None,
            ema_fast=None,
            ema_slow=None,
        )
        
        features_dict = decision_input.features
        
        # Property: features dict SHALL contain bid, ask, best_bid, best_ask fields
        assert "bid" in features_dict, "features dict missing 'bid' field (Requirement 1.3)"
        assert "ask" in features_dict, "features dict missing 'ask' field (Requirement 1.3)"
        assert "best_bid" in features_dict, "features dict missing 'best_bid' field (Requirement 1.1)"
        assert "best_ask" in features_dict, "features dict missing 'best_ask' field (Requirement 1.1)"
        
        # Property: bid == best_bid (Requirement 4.1)
        assert features_dict["bid"] == features_dict["best_bid"], (
            f"bid ({features_dict['bid']}) != best_bid ({features_dict['best_bid']}) - Requirement 4.1"
        )
        
        # Property: ask == best_ask (Requirement 4.2)
        assert features_dict["ask"] == features_dict["best_ask"], (
            f"ask ({features_dict['ask']}) != best_ask ({features_dict['best_ask']}) - Requirement 4.2"
        )
        
        # Property: values match snapshot bid/ask
        assert features_dict["bid"] == snapshot.bid, (
            f"features bid ({features_dict['bid']}) != snapshot.bid ({snapshot.bid})"
        )
        assert features_dict["ask"] == snapshot.ask, (
            f"features ask ({features_dict['ask']}) != snapshot.ask ({snapshot.ask})"
        )
        assert features_dict["best_bid"] == snapshot.bid, (
            f"features best_bid ({features_dict['best_bid']}) != snapshot.bid ({snapshot.bid})"
        )
        assert features_dict["best_ask"] == snapshot.ask, (
            f"features best_ask ({features_dict['best_ask']}) != snapshot.ask ({snapshot.ask})"
        )


class TestBacktestDecisionAdapterMarketContextFields:
    """Property-based tests for BacktestDecisionAdapter market_context fields.
    
    Feature: backtest-field-mapping-fix, Property 2: BacktestDecisionAdapter Market Context Fields
    
    **Validates: Requirements 1.2**
    """
    
    @given(
        snapshot=market_snapshot_strategy(),
        features=features_strategy(),
        account=account_state_strategy(),
    )
    @settings(max_examples=100)
    def test_decision_adapter_market_context_fields(
        self,
        snapshot: MarketSnapshot,
        features: Features,
        account: AccountState,
    ):
        """Property 2: BacktestDecisionAdapter Market Context Fields.
        
        *For any* MarketSnapshot with valid bid/ask prices, when BacktestDecisionAdapter
        builds a DecisionInput, the market_context dict SHALL contain `best_bid` and
        `best_ask` fields matching the snapshot's bid and ask values.
        
        **Validates: Requirements 1.2**
        
        - 1.2: WHEN the BacktestDecisionAdapter builds a DecisionInput THEN the
               market_context dict SHALL contain `best_bid` and `best_ask` fields
        """
        # Create a mock DecisionEngine (we only need to test _build_decision_input)
        mock_engine = MagicMock()
        
        # Create adapter
        adapter = BacktestDecisionAdapter(decision_engine=mock_engine)
        
        # Build DecisionInput using the adapter's internal method
        decision_input = adapter._build_decision_input(
            symbol=snapshot.symbol,
            snapshot=snapshot,
            features=features,
            account_state=account,
            positions=None,
            profile_settings=None,
            ema_fast=None,
            ema_slow=None,
        )
        
        market_context = decision_input.market_context
        
        # Property: market_context dict SHALL contain best_bid and best_ask fields
        assert "best_bid" in market_context, (
            "market_context dict missing 'best_bid' field (Requirement 1.2)"
        )
        assert "best_ask" in market_context, (
            "market_context dict missing 'best_ask' field (Requirement 1.2)"
        )
        
        # Property: best_bid and best_ask SHALL match snapshot's bid and ask values
        assert market_context["best_bid"] == snapshot.bid, (
            f"market_context best_bid ({market_context['best_bid']}) != snapshot.bid ({snapshot.bid}) - Requirement 1.2"
        )
        assert market_context["best_ask"] == snapshot.ask, (
            f"market_context best_ask ({market_context['best_ask']}) != snapshot.ask ({snapshot.ask}) - Requirement 1.2"
        )
        
        # Additional validation: best_bid and best_ask should be positive for valid inputs
        assert market_context["best_bid"] > 0, (
            f"market_context best_bid ({market_context['best_bid']}) should be positive"
        )
        assert market_context["best_ask"] > 0, (
            f"market_context best_ask ({market_context['best_ask']}) should be positive"
        )
        
        # Additional validation: best_ask should be greater than best_bid (valid spread)
        assert market_context["best_ask"] > market_context["best_bid"], (
            f"market_context best_ask ({market_context['best_ask']}) should be > best_bid ({market_context['best_bid']})"
        )
