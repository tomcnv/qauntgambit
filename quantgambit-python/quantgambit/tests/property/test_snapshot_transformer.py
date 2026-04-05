"""Property-based tests for SnapshotTransformer.

Feature: backtest-timescaledb-replay, Property 3: Transformation Field Completeness

Tests that for any valid OrderbookSnapshot with non-empty bids and asks, the
transformed feature snapshot SHALL contain:
- `symbol` (non-empty string)
- `timestamp` (valid Unix timestamp)
- `market_context` with keys: price, bid, ask, best_bid, best_ask, spread_bps,
  bid_depth_usd, ask_depth_usd, orderbook_imbalance
- `warmup_ready` set to True

**Validates: Requirements 2.1, 2.6**
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.storage.persistence import OrderbookSnapshot
from quantgambit.backtesting.snapshot_transformer import SnapshotTransformer, TradeContext


# =============================================================================
# Strategies for generating test data (from design.md)
# =============================================================================

# OrderbookSnapshot generator as specified in design.md
orderbook_level = st.tuples(
    st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0001, max_value=10000.0, allow_nan=False, allow_infinity=False),
)

# Symbol generator - non-empty alphanumeric strings
symbol_strategy = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=('L', 'N')),
)

# Exchange generator - sampled from common exchanges
exchange_strategy = st.sampled_from(["binance", "okx", "coinbase", "kraken"])

# Timestamp generator - realistic datetime range
timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 1, 1),
)

# Sequence number generator
seq_strategy = st.integers(min_value=1, max_value=1000000)

# Bids and asks generators - non-empty lists of levels
bids_strategy = st.lists(orderbook_level, min_size=1, max_size=20)
asks_strategy = st.lists(orderbook_level, min_size=1, max_size=20)

# Spread in basis points
spread_bps_strategy = st.floats(
    min_value=0.0,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Depth in USD
depth_usd_strategy = st.floats(
    min_value=0.0,
    max_value=100000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Orderbook imbalance (0 to 1)
imbalance_strategy = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)


def convert_levels_to_lists(levels: List[Tuple[float, float]]) -> List[List[float]]:
    """Convert tuples to lists for OrderbookSnapshot compatibility."""
    return [[price, size] for price, size in levels]


# Complete OrderbookSnapshot generator
@st.composite
def orderbook_snapshot_strategy(draw):
    """Generate a valid OrderbookSnapshot with non-empty bids and asks."""
    bids_tuples = draw(bids_strategy)
    asks_tuples = draw(asks_strategy)
    
    return OrderbookSnapshot(
        symbol=draw(symbol_strategy),
        exchange=draw(exchange_strategy),
        timestamp=draw(timestamp_strategy),
        seq=draw(seq_strategy),
        bids=convert_levels_to_lists(bids_tuples),
        asks=convert_levels_to_lists(asks_tuples),
        spread_bps=draw(spread_bps_strategy),
        bid_depth_usd=draw(depth_usd_strategy),
        ask_depth_usd=draw(depth_usd_strategy),
        orderbook_imbalance=draw(imbalance_strategy),
    )


# Trade context generator for optional trade data
@st.composite
def trade_context_strategy(draw):
    """Generate a valid TradeContext."""
    has_trades = draw(st.booleans())
    
    if has_trades:
        return TradeContext(
            last_trade_price=draw(st.floats(
                min_value=0.01,
                max_value=100000.0,
                allow_nan=False,
                allow_infinity=False,
            )),
            last_trade_side=draw(st.sampled_from(["buy", "sell"])),
            trade_count=draw(st.integers(min_value=1, max_value=1000)),
            total_volume=draw(st.floats(
                min_value=0.0,
                max_value=10000.0,
                allow_nan=False,
                allow_infinity=False,
            )),
            buy_volume=draw(st.floats(
                min_value=0.0,
                max_value=5000.0,
                allow_nan=False,
                allow_infinity=False,
            )),
            sell_volume=draw(st.floats(
                min_value=0.0,
                max_value=5000.0,
                allow_nan=False,
                allow_infinity=False,
            )),
        )
    else:
        return TradeContext(
            last_trade_price=None,
            last_trade_side=None,
            trade_count=0,
            total_volume=0.0,
            buy_volume=0.0,
            sell_volume=0.0,
        )


# =============================================================================
# Property 3: Transformation Field Completeness
# =============================================================================


class TestTransformationFieldCompleteness:
    """Property 3: Transformation Field Completeness

    For any valid OrderbookSnapshot with non-empty bids and asks, the
    transformed feature snapshot SHALL contain:
    - `symbol` (non-empty string)
    - `timestamp` (valid Unix timestamp)
    - `market_context` with keys: price, bid, ask, best_bid, best_ask,
      spread_bps, bid_depth_usd, ask_depth_usd, orderbook_imbalance
    - `warmup_ready` set to True

    **Validates: Requirements 2.1, 2.6**
    """

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_transformed_snapshot_contains_symbol(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that transformed snapshot contains non-empty symbol.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)

        assert "symbol" in result, "Transformed snapshot must contain 'symbol' field"
        assert isinstance(result["symbol"], str), "Symbol must be a string"
        assert len(result["symbol"]) > 0, "Symbol must be non-empty"
        assert result["symbol"] == orderbook.symbol, (
            f"Symbol should match input: expected {orderbook.symbol}, got {result['symbol']}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_transformed_snapshot_contains_valid_timestamp(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that transformed snapshot contains valid Unix timestamp.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)

        assert "timestamp" in result, "Transformed snapshot must contain 'timestamp' field"
        assert isinstance(result["timestamp"], (int, float)), "Timestamp must be numeric"
        
        # Verify it's a valid Unix timestamp (reasonable range)
        # Allow some buffer for timezone differences (24 hours = 86400 seconds)
        # Unix timestamp for 2020-01-01 UTC is ~1577836800
        # Unix timestamp for 2030-01-01 UTC is ~1893456000
        min_timestamp = 1577836800 - 86400  # Allow 1 day before 2020-01-01 UTC
        max_timestamp = 1893456000 + 86400  # Allow 1 day after 2030-01-01 UTC
        assert result["timestamp"] >= min_timestamp, (
            f"Timestamp {result['timestamp']} is too old (before 2020)"
        )
        assert result["timestamp"] <= max_timestamp, (
            f"Timestamp {result['timestamp']} is too far in future (after 2030)"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_transformed_snapshot_contains_market_context(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that transformed snapshot contains market_context dictionary.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)

        assert "market_context" in result, (
            "Transformed snapshot must contain 'market_context' field"
        )
        assert isinstance(result["market_context"], dict), (
            "market_context must be a dictionary"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_market_context_contains_price(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that market_context contains 'price' field.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        assert "price" in market_context, "market_context must contain 'price' field"
        assert isinstance(market_context["price"], (int, float)), "price must be numeric"
        assert market_context["price"] > 0, "price must be positive"

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_market_context_contains_bid(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that market_context contains 'bid' field.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        assert "bid" in market_context, "market_context must contain 'bid' field"
        assert isinstance(market_context["bid"], (int, float)), "bid must be numeric"

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_market_context_contains_ask(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that market_context contains 'ask' field.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        assert "ask" in market_context, "market_context must contain 'ask' field"
        assert isinstance(market_context["ask"], (int, float)), "ask must be numeric"

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_market_context_contains_best_bid(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that market_context contains 'best_bid' field.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        assert "best_bid" in market_context, "market_context must contain 'best_bid' field"
        assert isinstance(market_context["best_bid"], (int, float)), "best_bid must be numeric"

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_market_context_contains_best_ask(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that market_context contains 'best_ask' field.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        assert "best_ask" in market_context, "market_context must contain 'best_ask' field"
        assert isinstance(market_context["best_ask"], (int, float)), "best_ask must be numeric"

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_market_context_contains_spread_bps(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that market_context contains 'spread_bps' field.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        assert "spread_bps" in market_context, "market_context must contain 'spread_bps' field"
        assert isinstance(market_context["spread_bps"], (int, float)), "spread_bps must be numeric"

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_market_context_contains_bid_depth_usd(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that market_context contains 'bid_depth_usd' field.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        assert "bid_depth_usd" in market_context, (
            "market_context must contain 'bid_depth_usd' field"
        )
        assert isinstance(market_context["bid_depth_usd"], (int, float)), (
            "bid_depth_usd must be numeric"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_market_context_contains_ask_depth_usd(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that market_context contains 'ask_depth_usd' field.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        assert "ask_depth_usd" in market_context, (
            "market_context must contain 'ask_depth_usd' field"
        )
        assert isinstance(market_context["ask_depth_usd"], (int, float)), (
            "ask_depth_usd must be numeric"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_market_context_contains_orderbook_imbalance(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that market_context contains 'orderbook_imbalance' field.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        assert "orderbook_imbalance" in market_context, (
            "market_context must contain 'orderbook_imbalance' field"
        )
        assert isinstance(market_context["orderbook_imbalance"], (int, float)), (
            "orderbook_imbalance must be numeric"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_warmup_ready_is_true(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that warmup_ready is set to True for all snapshots.

        Historical data is always "ready" - no warmup period needed.

        **Validates: Requirements 2.6**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)

        assert "warmup_ready" in result, "Transformed snapshot must contain 'warmup_ready' field"
        assert result["warmup_ready"] is True, (
            f"warmup_ready must be True for historical data, got {result['warmup_ready']}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_all_required_market_context_keys_present(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that all required market_context keys are present.

        This is the comprehensive test that checks all required keys at once.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        required_keys = {
            "price",
            "bid",
            "ask",
            "best_bid",
            "best_ask",
            "spread_bps",
            "bid_depth_usd",
            "ask_depth_usd",
            "orderbook_imbalance",
        }

        missing_keys = required_keys - set(market_context.keys())
        assert len(missing_keys) == 0, (
            f"market_context is missing required keys: {missing_keys}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_complete_transformation_field_completeness(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Comprehensive test for Property 3: Transformation Field Completeness.

        For any valid OrderbookSnapshot with non-empty bids and asks, the
        transformed feature snapshot SHALL contain:
        - `symbol` (non-empty string)
        - `timestamp` (valid Unix timestamp)
        - `market_context` with all required keys
        - `warmup_ready` set to True

        **Validates: Requirements 2.1, 2.6**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)

        # Check symbol
        assert "symbol" in result, "Must contain 'symbol'"
        assert isinstance(result["symbol"], str), "symbol must be string"
        assert len(result["symbol"]) > 0, "symbol must be non-empty"

        # Check timestamp
        assert "timestamp" in result, "Must contain 'timestamp'"
        assert isinstance(result["timestamp"], (int, float)), "timestamp must be numeric"
        assert result["timestamp"] > 0, "timestamp must be positive"

        # Check market_context
        assert "market_context" in result, "Must contain 'market_context'"
        assert isinstance(result["market_context"], dict), "market_context must be dict"

        required_market_context_keys = {
            "price",
            "bid",
            "ask",
            "best_bid",
            "best_ask",
            "spread_bps",
            "bid_depth_usd",
            "ask_depth_usd",
            "orderbook_imbalance",
        }
        missing_keys = required_market_context_keys - set(result["market_context"].keys())
        assert len(missing_keys) == 0, f"market_context missing keys: {missing_keys}"

        # Check warmup_ready
        assert "warmup_ready" in result, "Must contain 'warmup_ready'"
        assert result["warmup_ready"] is True, "warmup_ready must be True"

    @given(
        orderbook=orderbook_snapshot_strategy(),
        trade_context=trade_context_strategy(),
    )
    @settings(max_examples=100)
    def test_field_completeness_with_trade_context(
        self,
        orderbook: OrderbookSnapshot,
        trade_context: TradeContext,
    ):
        """Verify field completeness when trade context is provided.

        The presence of trade context should not affect the required fields.

        **Validates: Requirements 2.1, 2.6**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context)

        # All required fields should still be present
        assert "symbol" in result
        assert "timestamp" in result
        assert "market_context" in result
        assert "warmup_ready" in result
        assert result["warmup_ready"] is True

        required_market_context_keys = {
            "price",
            "bid",
            "ask",
            "best_bid",
            "best_ask",
            "spread_bps",
            "bid_depth_usd",
            "ask_depth_usd",
            "orderbook_imbalance",
        }
        missing_keys = required_market_context_keys - set(result["market_context"].keys())
        assert len(missing_keys) == 0, f"market_context missing keys: {missing_keys}"

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_bid_ask_consistency(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that bid and best_bid are consistent, same for ask.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        # bid and best_bid should be the same value
        assert market_context["bid"] == market_context["best_bid"], (
            f"bid ({market_context['bid']}) should equal best_bid ({market_context['best_bid']})"
        )

        # ask and best_ask should be the same value
        assert market_context["ask"] == market_context["best_ask"], (
            f"ask ({market_context['ask']}) should equal best_ask ({market_context['best_ask']})"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_market_context_values_from_orderbook(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that market_context values are derived from orderbook.

        **Validates: Requirements 2.1**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)
        market_context = result["market_context"]

        # spread_bps should match orderbook
        assert market_context["spread_bps"] == orderbook.spread_bps, (
            f"spread_bps should match: expected {orderbook.spread_bps}, "
            f"got {market_context['spread_bps']}"
        )

        # bid_depth_usd should match orderbook
        assert market_context["bid_depth_usd"] == orderbook.bid_depth_usd, (
            f"bid_depth_usd should match: expected {orderbook.bid_depth_usd}, "
            f"got {market_context['bid_depth_usd']}"
        )

        # ask_depth_usd should match orderbook
        assert market_context["ask_depth_usd"] == orderbook.ask_depth_usd, (
            f"ask_depth_usd should match: expected {orderbook.ask_depth_usd}, "
            f"got {market_context['ask_depth_usd']}"
        )

        # orderbook_imbalance should match orderbook
        assert market_context["orderbook_imbalance"] == orderbook.orderbook_imbalance, (
            f"orderbook_imbalance should match: expected {orderbook.orderbook_imbalance}, "
            f"got {market_context['orderbook_imbalance']}"
        )


# =============================================================================
# Property 4: Mid-Price Calculation
# =============================================================================


class TestMidPriceCalculation:
    """Property 4: Mid-Price Calculation

    For any OrderbookSnapshot with best_bid B and best_ask A where B > 0 and A > 0,
    the transformed feature snapshot's `market_context.price` SHALL equal
    (B + A) / 2 within floating-point tolerance.

    **Validates: Requirements 2.2**
    """

    @given(
        best_bid=st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),
        best_ask=st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_mid_price_calculation_formula(
        self,
        best_bid: float,
        best_ask: float,
    ):
        """Verify that calculate_mid_price returns (best_bid + best_ask) / 2.

        **Validates: Requirements 2.2**
        """
        transformer = SnapshotTransformer()
        
        result = transformer.calculate_mid_price(best_bid, best_ask)
        expected = (best_bid + best_ask) / 2.0
        
        assert result == pytest.approx(expected, rel=1e-9), (
            f"Mid-price calculation incorrect: "
            f"expected ({best_bid} + {best_ask}) / 2 = {expected}, got {result}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_price_equals_mid_price_without_trade_context(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that price equals mid-price when no trade context is provided.

        When no trade records exist within the snapshot interval, the
        Snapshot_Transformer SHALL use the mid-price as the price field.

        **Validates: Requirements 2.2, 2.5**
        """
        # Ensure we have valid bid and ask prices
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)
        assume(orderbook.bids[0][0] > 0 and orderbook.asks[0][0] > 0)
        
        transformer = SnapshotTransformer()
        
        # Transform without trade context
        result = transformer.transform(orderbook, trade_context=None)
        
        # Extract best bid and ask from orderbook
        best_bid = orderbook.bids[0][0]
        best_ask = orderbook.asks[0][0]
        expected_mid_price = (best_bid + best_ask) / 2.0
        
        # Verify price equals mid-price
        actual_price = result["market_context"]["price"]
        assert actual_price == pytest.approx(expected_mid_price, rel=1e-9), (
            f"Price should equal mid-price when no trade context: "
            f"expected ({best_bid} + {best_ask}) / 2 = {expected_mid_price}, "
            f"got {actual_price}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_mid_price_is_between_bid_and_ask(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that mid-price is always between best_bid and best_ask.

        This is a mathematical property: (B + A) / 2 is always between B and A.

        **Validates: Requirements 2.2**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)
        assume(orderbook.bids[0][0] > 0 and orderbook.asks[0][0] > 0)
        
        transformer = SnapshotTransformer()
        
        best_bid = orderbook.bids[0][0]
        best_ask = orderbook.asks[0][0]
        mid_price = transformer.calculate_mid_price(best_bid, best_ask)
        
        # Mid-price should be between min and max of bid/ask
        min_price = min(best_bid, best_ask)
        max_price = max(best_bid, best_ask)
        
        assert mid_price >= min_price - 1e-9, (
            f"Mid-price {mid_price} should be >= min({best_bid}, {best_ask}) = {min_price}"
        )
        assert mid_price <= max_price + 1e-9, (
            f"Mid-price {mid_price} should be <= max({best_bid}, {best_ask}) = {max_price}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_mid_price_equals_bid_ask_when_equal(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that mid-price equals bid/ask when they are equal (zero spread).

        When best_bid == best_ask, mid-price should equal both.

        **Validates: Requirements 2.2**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)
        
        transformer = SnapshotTransformer()
        
        # Use the same price for both bid and ask
        price = orderbook.bids[0][0]
        assume(price > 0)
        
        mid_price = transformer.calculate_mid_price(price, price)
        
        assert mid_price == pytest.approx(price, rel=1e-9), (
            f"Mid-price should equal bid/ask when they are equal: "
            f"expected {price}, got {mid_price}"
        )

    @given(
        orderbook=orderbook_snapshot_strategy(),
        trade_context=trade_context_strategy(),
    )
    @settings(max_examples=100)
    def test_price_uses_trade_price_when_available(
        self,
        orderbook: OrderbookSnapshot,
        trade_context: TradeContext,
    ):
        """Verify that price uses last_trade_price when trade context is provided.

        When trade records exist within the snapshot interval, the
        Snapshot_Transformer SHALL include trade-derived features including
        last_trade_price as the price field.

        **Validates: Requirements 2.4**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)
        assume(orderbook.bids[0][0] > 0 and orderbook.asks[0][0] > 0)
        
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context)
        
        actual_price = result["market_context"]["price"]
        
        if trade_context.last_trade_price is not None:
            # When trade context has a price, use it
            assert actual_price == pytest.approx(trade_context.last_trade_price, rel=1e-9), (
                f"Price should equal last_trade_price when available: "
                f"expected {trade_context.last_trade_price}, got {actual_price}"
            )
        else:
            # When trade context has no price, use mid-price
            best_bid = orderbook.bids[0][0]
            best_ask = orderbook.asks[0][0]
            expected_mid_price = (best_bid + best_ask) / 2.0
            assert actual_price == pytest.approx(expected_mid_price, rel=1e-9), (
                f"Price should equal mid-price when no trade price: "
                f"expected {expected_mid_price}, got {actual_price}"
            )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_mid_price_symmetry(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that mid-price calculation is symmetric.

        calculate_mid_price(A, B) should equal calculate_mid_price(B, A).

        **Validates: Requirements 2.2**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)
        assume(orderbook.bids[0][0] > 0 and orderbook.asks[0][0] > 0)
        
        transformer = SnapshotTransformer()
        
        best_bid = orderbook.bids[0][0]
        best_ask = orderbook.asks[0][0]
        
        mid_price_1 = transformer.calculate_mid_price(best_bid, best_ask)
        mid_price_2 = transformer.calculate_mid_price(best_ask, best_bid)
        
        assert mid_price_1 == pytest.approx(mid_price_2, rel=1e-9), (
            f"Mid-price should be symmetric: "
            f"({best_bid} + {best_ask}) / 2 = {mid_price_1}, "
            f"({best_ask} + {best_bid}) / 2 = {mid_price_2}"
        )


# =============================================================================
# Property 5: Timestamp Preservation
# =============================================================================


class TestTimestampPreservation:
    """Property 5: Timestamp Preservation

    For any OrderbookSnapshot with timestamp T, the transformed feature
    snapshot's `timestamp` SHALL equal T (converted to Unix timestamp if
    necessary).

    **Validates: Requirements 2.3**
    """

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_timestamp_preserved_as_unix_timestamp(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that the original timestamp is preserved as Unix timestamp.

        The transformed snapshot's timestamp SHALL equal the original
        OrderbookSnapshot timestamp converted to Unix timestamp.

        **Validates: Requirements 2.3**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)

        # Convert original datetime to Unix timestamp
        expected_timestamp = orderbook.timestamp.timestamp()
        actual_timestamp = result["timestamp"]

        assert actual_timestamp == pytest.approx(expected_timestamp, rel=1e-9), (
            f"Timestamp should be preserved: "
            f"expected {expected_timestamp} (from {orderbook.timestamp}), "
            f"got {actual_timestamp}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_timestamp_is_numeric(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that the transformed timestamp is a numeric value.

        Unix timestamps should be represented as int or float.

        **Validates: Requirements 2.3**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)

        assert isinstance(result["timestamp"], (int, float)), (
            f"Timestamp must be numeric, got {type(result['timestamp'])}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_timestamp_is_positive(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that the transformed timestamp is positive.

        Unix timestamps for dates after 1970 should always be positive.

        **Validates: Requirements 2.3**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)

        assert result["timestamp"] > 0, (
            f"Timestamp must be positive, got {result['timestamp']}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_timestamp_in_valid_range(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that the transformed timestamp is in a valid range.

        The timestamp should be within the range of our test data
        (2020-01-01 to 2030-01-01).

        **Validates: Requirements 2.3**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)

        # Unix timestamp for 2020-01-01 UTC is ~1577836800
        # Unix timestamp for 2030-01-01 UTC is ~1893456000
        # Allow some buffer for timezone differences (24 hours = 86400 seconds)
        min_timestamp = 1577836800 - 86400
        max_timestamp = 1893456000 + 86400

        assert result["timestamp"] >= min_timestamp, (
            f"Timestamp {result['timestamp']} is too old (before 2020)"
        )
        assert result["timestamp"] <= max_timestamp, (
            f"Timestamp {result['timestamp']} is too far in future (after 2030)"
        )

    @given(
        orderbook=orderbook_snapshot_strategy(),
        trade_context=trade_context_strategy(),
    )
    @settings(max_examples=100)
    def test_timestamp_preserved_with_trade_context(
        self,
        orderbook: OrderbookSnapshot,
        trade_context: TradeContext,
    ):
        """Verify that timestamp is preserved regardless of trade context.

        The presence of trade context should not affect timestamp preservation.

        **Validates: Requirements 2.3**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context)

        expected_timestamp = orderbook.timestamp.timestamp()
        actual_timestamp = result["timestamp"]

        assert actual_timestamp == pytest.approx(expected_timestamp, rel=1e-9), (
            f"Timestamp should be preserved with trade context: "
            f"expected {expected_timestamp}, got {actual_timestamp}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_timestamp_conversion_is_deterministic(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that timestamp conversion is deterministic.

        Multiple transformations of the same orderbook should produce
        the same timestamp.

        **Validates: Requirements 2.3**
        """
        transformer = SnapshotTransformer()

        result1 = transformer.transform(orderbook)
        result2 = transformer.transform(orderbook)

        assert result1["timestamp"] == result2["timestamp"], (
            f"Timestamp conversion should be deterministic: "
            f"first call returned {result1['timestamp']}, "
            f"second call returned {result2['timestamp']}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_timestamp_can_be_converted_back_to_datetime(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that the Unix timestamp can be converted back to datetime.

        The transformation should be reversible - we should be able to
        convert the Unix timestamp back to a datetime that matches the
        original (within floating-point tolerance).

        **Validates: Requirements 2.3**
        """
        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook)

        # Convert Unix timestamp back to datetime
        from datetime import datetime as dt
        recovered_datetime = dt.fromtimestamp(result["timestamp"])

        # The recovered datetime should be very close to the original
        # Allow for floating-point precision issues (up to 1 microsecond)
        time_diff = abs(
            (recovered_datetime - orderbook.timestamp.replace(tzinfo=None)).total_seconds()
        )
        assert time_diff < 0.001, (
            f"Timestamp should be reversible: "
            f"original {orderbook.timestamp}, "
            f"recovered {recovered_datetime}, "
            f"difference {time_diff} seconds"
        )

    @given(
        orderbook1=orderbook_snapshot_strategy(),
        orderbook2=orderbook_snapshot_strategy(),
    )
    @settings(max_examples=100)
    def test_timestamp_ordering_preserved(
        self,
        orderbook1: OrderbookSnapshot,
        orderbook2: OrderbookSnapshot,
    ):
        """Verify that timestamp ordering is preserved after transformation.

        If orderbook1.timestamp < orderbook2.timestamp, then
        result1["timestamp"] < result2["timestamp"].

        **Validates: Requirements 2.3**
        """
        transformer = SnapshotTransformer()

        result1 = transformer.transform(orderbook1)
        result2 = transformer.transform(orderbook2)

        # Check that ordering is preserved
        if orderbook1.timestamp < orderbook2.timestamp:
            assert result1["timestamp"] < result2["timestamp"], (
                f"Timestamp ordering should be preserved: "
                f"{orderbook1.timestamp} < {orderbook2.timestamp} but "
                f"{result1['timestamp']} >= {result2['timestamp']}"
            )
        elif orderbook1.timestamp > orderbook2.timestamp:
            assert result1["timestamp"] > result2["timestamp"], (
                f"Timestamp ordering should be preserved: "
                f"{orderbook1.timestamp} > {orderbook2.timestamp} but "
                f"{result1['timestamp']} <= {result2['timestamp']}"
            )
        else:
            # Equal timestamps should produce equal Unix timestamps
            assert result1["timestamp"] == pytest.approx(result2["timestamp"], rel=1e-9), (
                f"Equal timestamps should produce equal Unix timestamps: "
                f"{orderbook1.timestamp} == {orderbook2.timestamp} but "
                f"{result1['timestamp']} != {result2['timestamp']}"
            )



# =============================================================================
# Property 6: Trade Features Inclusion
# =============================================================================


class TestTradeFeatureInclusion:
    """Property 6: Trade Features Inclusion

    For any OrderbookSnapshot with associated trade records, the transformed
    feature snapshot SHALL include `last_trade_price`, `last_trade_side`, and
    `trade_count` in market_context or features.

    For any OrderbookSnapshot with no associated trade records, the `price`
    field SHALL equal the mid-price.

    **Validates: Requirements 2.4, 2.5**
    """

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_no_trade_context_price_equals_mid_price(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that price equals mid-price when no trade context is provided.

        WHEN no trade records exist within the snapshot interval, THE
        Snapshot_Transformer SHALL use the mid-price as the price field.

        **Validates: Requirements 2.5**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)
        assume(orderbook.bids[0][0] > 0 and orderbook.asks[0][0] > 0)

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context=None)

        best_bid = orderbook.bids[0][0]
        best_ask = orderbook.asks[0][0]
        expected_mid_price = (best_bid + best_ask) / 2.0

        actual_price = result["market_context"]["price"]
        assert actual_price == pytest.approx(expected_mid_price, rel=1e-9), (
            f"Price should equal mid-price when no trade context: "
            f"expected ({best_bid} + {best_ask}) / 2 = {expected_mid_price}, "
            f"got {actual_price}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_empty_trade_context_price_equals_mid_price(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that price equals mid-price when trade context has no trades.

        A TradeContext with trade_count=0 and last_trade_price=None should
        result in the price field being set to mid-price.

        **Validates: Requirements 2.5**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)
        assume(orderbook.bids[0][0] > 0 and orderbook.asks[0][0] > 0)

        # Create empty trade context (no trades)
        empty_trade_context = TradeContext(
            last_trade_price=None,
            last_trade_side=None,
            trade_count=0,
            total_volume=0.0,
            buy_volume=0.0,
            sell_volume=0.0,
        )

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context=empty_trade_context)

        best_bid = orderbook.bids[0][0]
        best_ask = orderbook.asks[0][0]
        expected_mid_price = (best_bid + best_ask) / 2.0

        actual_price = result["market_context"]["price"]
        assert actual_price == pytest.approx(expected_mid_price, rel=1e-9), (
            f"Price should equal mid-price when trade context has no trades: "
            f"expected ({best_bid} + {best_ask}) / 2 = {expected_mid_price}, "
            f"got {actual_price}"
        )

    @given(
        orderbook=orderbook_snapshot_strategy(),
        last_trade_price=st.floats(
            min_value=0.01,
            max_value=100000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        last_trade_side=st.sampled_from(["buy", "sell"]),
        trade_count=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=100)
    def test_trade_context_includes_last_trade_price(
        self,
        orderbook: OrderbookSnapshot,
        last_trade_price: float,
        last_trade_side: str,
        trade_count: int,
    ):
        """Verify that last_trade_price is included when trade context exists.

        WHEN trade records exist within the snapshot interval, THE
        Snapshot_Transformer SHALL include trade-derived features:
        last_trade_price.

        **Validates: Requirements 2.4**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)

        trade_context = TradeContext(
            last_trade_price=last_trade_price,
            last_trade_side=last_trade_side,
            trade_count=trade_count,
            total_volume=100.0,
            buy_volume=50.0,
            sell_volume=50.0,
        )

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context)

        # last_trade_price should be in market_context
        assert "last_trade_price" in result["market_context"], (
            "market_context should include 'last_trade_price' when trades exist"
        )
        assert result["market_context"]["last_trade_price"] == pytest.approx(
            last_trade_price, rel=1e-9
        ), (
            f"last_trade_price should match: expected {last_trade_price}, "
            f"got {result['market_context']['last_trade_price']}"
        )

    @given(
        orderbook=orderbook_snapshot_strategy(),
        last_trade_price=st.floats(
            min_value=0.01,
            max_value=100000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        last_trade_side=st.sampled_from(["buy", "sell"]),
        trade_count=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=100)
    def test_trade_context_includes_last_trade_side(
        self,
        orderbook: OrderbookSnapshot,
        last_trade_price: float,
        last_trade_side: str,
        trade_count: int,
    ):
        """Verify that last_trade_side is included when trade context exists.

        WHEN trade records exist within the snapshot interval, THE
        Snapshot_Transformer SHALL include trade-derived features:
        last_trade_side.

        **Validates: Requirements 2.4**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)

        trade_context = TradeContext(
            last_trade_price=last_trade_price,
            last_trade_side=last_trade_side,
            trade_count=trade_count,
            total_volume=100.0,
            buy_volume=50.0,
            sell_volume=50.0,
        )

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context)

        # last_trade_side should be in market_context
        assert "last_trade_side" in result["market_context"], (
            "market_context should include 'last_trade_side' when trades exist"
        )
        assert result["market_context"]["last_trade_side"] == last_trade_side, (
            f"last_trade_side should match: expected {last_trade_side}, "
            f"got {result['market_context']['last_trade_side']}"
        )

    @given(
        orderbook=orderbook_snapshot_strategy(),
        last_trade_price=st.floats(
            min_value=0.01,
            max_value=100000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        last_trade_side=st.sampled_from(["buy", "sell"]),
        trade_count=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=100)
    def test_trade_context_includes_trade_count(
        self,
        orderbook: OrderbookSnapshot,
        last_trade_price: float,
        last_trade_side: str,
        trade_count: int,
    ):
        """Verify that trade_count is included when trade context exists.

        WHEN trade records exist within the snapshot interval, THE
        Snapshot_Transformer SHALL include trade-derived features:
        trade_count_in_interval (as trade_count in features).

        **Validates: Requirements 2.4**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)

        trade_context = TradeContext(
            last_trade_price=last_trade_price,
            last_trade_side=last_trade_side,
            trade_count=trade_count,
            total_volume=100.0,
            buy_volume=50.0,
            sell_volume=50.0,
        )

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context)

        # trade_count should be in features
        assert "features" in result, "Result should contain 'features' field"
        assert "trade_count" in result["features"], (
            "features should include 'trade_count' when trades exist"
        )
        assert result["features"]["trade_count"] == trade_count, (
            f"trade_count should match: expected {trade_count}, "
            f"got {result['features']['trade_count']}"
        )

    @given(
        orderbook=orderbook_snapshot_strategy(),
        last_trade_price=st.floats(
            min_value=0.01,
            max_value=100000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        last_trade_side=st.sampled_from(["buy", "sell"]),
        trade_count=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=100)
    def test_price_uses_last_trade_price_when_available(
        self,
        orderbook: OrderbookSnapshot,
        last_trade_price: float,
        last_trade_side: str,
        trade_count: int,
    ):
        """Verify that price field uses last_trade_price when trades exist.

        WHEN trade records exist within the snapshot interval, THE
        Snapshot_Transformer SHALL use last_trade_price as the price field.

        **Validates: Requirements 2.4**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)

        trade_context = TradeContext(
            last_trade_price=last_trade_price,
            last_trade_side=last_trade_side,
            trade_count=trade_count,
            total_volume=100.0,
            buy_volume=50.0,
            sell_volume=50.0,
        )

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context)

        actual_price = result["market_context"]["price"]
        assert actual_price == pytest.approx(last_trade_price, rel=1e-9), (
            f"Price should equal last_trade_price when trades exist: "
            f"expected {last_trade_price}, got {actual_price}"
        )

    @given(
        orderbook=orderbook_snapshot_strategy(),
        trade_context=trade_context_strategy(),
    )
    @settings(max_examples=100)
    def test_all_trade_features_included_when_trades_exist(
        self,
        orderbook: OrderbookSnapshot,
        trade_context: TradeContext,
    ):
        """Comprehensive test for trade features inclusion.

        For any OrderbookSnapshot with associated trade records, the
        transformed feature snapshot SHALL include `last_trade_price`,
        `last_trade_side`, and `trade_count` in market_context or features.

        **Validates: Requirements 2.4**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context)

        if trade_context.last_trade_price is not None:
            # When trades exist, all trade features should be included
            assert "last_trade_price" in result["market_context"], (
                "market_context should include 'last_trade_price' when trades exist"
            )
            assert result["market_context"]["last_trade_price"] == pytest.approx(
                trade_context.last_trade_price, rel=1e-9
            )

        if trade_context.last_trade_side is not None:
            assert "last_trade_side" in result["market_context"], (
                "market_context should include 'last_trade_side' when trades exist"
            )
            assert result["market_context"]["last_trade_side"] == trade_context.last_trade_side

        # trade_count should always be in features
        assert "trade_count" in result["features"], (
            "features should always include 'trade_count'"
        )
        assert result["features"]["trade_count"] == trade_context.trade_count

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_no_trade_features_in_market_context_without_trades(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that trade features are not in market_context without trades.

        When no trade context is provided, last_trade_price and last_trade_side
        should not be present in market_context.

        **Validates: Requirements 2.5**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context=None)

        # last_trade_price and last_trade_side should NOT be in market_context
        assert "last_trade_price" not in result["market_context"], (
            "market_context should not include 'last_trade_price' without trades"
        )
        assert "last_trade_side" not in result["market_context"], (
            "market_context should not include 'last_trade_side' without trades"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_trade_count_zero_without_trades(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that trade_count is 0 when no trade context is provided.

        **Validates: Requirements 2.5**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context=None)

        assert "features" in result, "Result should contain 'features' field"
        assert "trade_count" in result["features"], (
            "features should include 'trade_count'"
        )
        assert result["features"]["trade_count"] == 0, (
            f"trade_count should be 0 without trades, got {result['features']['trade_count']}"
        )

    @given(
        orderbook=orderbook_snapshot_strategy(),
        buy_volume=st.floats(
            min_value=0.0,
            max_value=5000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        sell_volume=st.floats(
            min_value=0.0,
            max_value=5000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    def test_volume_features_included_when_trades_exist(
        self,
        orderbook: OrderbookSnapshot,
        buy_volume: float,
        sell_volume: float,
    ):
        """Verify that volume features are included when trade context exists.

        **Validates: Requirements 2.4**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)

        trade_context = TradeContext(
            last_trade_price=100.0,
            last_trade_side="buy",
            trade_count=10,
            total_volume=buy_volume + sell_volume,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
        )

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context)

        assert "buy_volume" in result["features"], (
            "features should include 'buy_volume' when trades exist"
        )
        assert result["features"]["buy_volume"] == pytest.approx(buy_volume, rel=1e-9), (
            f"buy_volume should match: expected {buy_volume}, "
            f"got {result['features']['buy_volume']}"
        )

        assert "sell_volume" in result["features"], (
            "features should include 'sell_volume' when trades exist"
        )
        assert result["features"]["sell_volume"] == pytest.approx(sell_volume, rel=1e-9), (
            f"sell_volume should match: expected {sell_volume}, "
            f"got {result['features']['sell_volume']}"
        )

    @given(orderbook=orderbook_snapshot_strategy())
    @settings(max_examples=100)
    def test_volume_features_zero_without_trades(
        self,
        orderbook: OrderbookSnapshot,
    ):
        """Verify that volume features are 0 when no trade context is provided.

        **Validates: Requirements 2.5**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context=None)

        assert "buy_volume" in result["features"], (
            "features should include 'buy_volume'"
        )
        assert result["features"]["buy_volume"] == 0.0, (
            f"buy_volume should be 0 without trades, got {result['features']['buy_volume']}"
        )

        assert "sell_volume" in result["features"], (
            "features should include 'sell_volume'"
        )
        assert result["features"]["sell_volume"] == 0.0, (
            f"sell_volume should be 0 without trades, got {result['features']['sell_volume']}"
        )

    @given(
        orderbook=orderbook_snapshot_strategy(),
        last_trade_price=st.floats(
            min_value=0.01,
            max_value=100000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    def test_price_differs_from_mid_price_when_trades_exist(
        self,
        orderbook: OrderbookSnapshot,
        last_trade_price: float,
    ):
        """Verify that price can differ from mid-price when trades exist.

        When trade context is provided with a last_trade_price, the price
        field should use that value, which may differ from the mid-price.

        **Validates: Requirements 2.4, 2.5**
        """
        assume(len(orderbook.bids) > 0 and len(orderbook.asks) > 0)
        assume(orderbook.bids[0][0] > 0 and orderbook.asks[0][0] > 0)

        best_bid = orderbook.bids[0][0]
        best_ask = orderbook.asks[0][0]
        mid_price = (best_bid + best_ask) / 2.0

        # Ensure last_trade_price differs from mid_price
        assume(abs(last_trade_price - mid_price) > 0.01)

        trade_context = TradeContext(
            last_trade_price=last_trade_price,
            last_trade_side="buy",
            trade_count=1,
            total_volume=1.0,
            buy_volume=1.0,
            sell_volume=0.0,
        )

        transformer = SnapshotTransformer()
        result = transformer.transform(orderbook, trade_context)

        actual_price = result["market_context"]["price"]

        # Price should equal last_trade_price, not mid_price
        assert actual_price == pytest.approx(last_trade_price, rel=1e-9), (
            f"Price should equal last_trade_price ({last_trade_price}), "
            f"not mid_price ({mid_price}), got {actual_price}"
        )
        assert actual_price != pytest.approx(mid_price, rel=1e-9) or last_trade_price == pytest.approx(mid_price, rel=1e-9), (
            f"Price should differ from mid_price when last_trade_price differs"
        )
