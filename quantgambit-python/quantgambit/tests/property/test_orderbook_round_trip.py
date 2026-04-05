"""Property tests for orderbook round-trip replay.

Feature: live-orderbook-data-storage, Property 14: Orderbook Round-Trip Replay

This module tests that storing an OrderbookState as a snapshot and then
replaying from the stored snapshot produces an equivalent OrderbookState.

**Validates: Requirements 6.5**
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List

from hypothesis import given, settings, strategies as st

from quantgambit.market.orderbooks import OrderbookState
from quantgambit.storage.orderbook_snapshot_reader import OrderbookSnapshotReader
from quantgambit.storage.persistence import OrderbookSnapshot
from quantgambit.market.derived_metrics import (
    calculate_depth_usd,
    calculate_orderbook_imbalance,
    calculate_spread_bps,
)


# Generator strategies for orderbook data
orderbook_level = st.tuples(
    st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),  # price
    st.floats(min_value=0.0001, max_value=10000.0, allow_nan=False, allow_infinity=False),  # size
)

# Orderbook generator (up to 20 levels)
orderbook_bids = st.lists(orderbook_level, min_size=1, max_size=20)
orderbook_asks = st.lists(orderbook_level, min_size=1, max_size=20)


def create_orderbook_state(
    symbol: str,
    bids: List[tuple[float, float]],
    asks: List[tuple[float, float]],
    seq: int,
) -> OrderbookState:
    """Create an OrderbookState from bid/ask tuples."""
    state = OrderbookState(symbol=symbol)
    # Convert tuples to lists for apply_snapshot
    bid_levels = [[p, s] for p, s in bids]
    ask_levels = [[p, s] for p, s in asks]
    state.apply_snapshot(bid_levels, ask_levels, seq)
    return state


def create_snapshot_from_state(
    state: OrderbookState,
    exchange: str,
    timestamp: datetime,
) -> OrderbookSnapshot:
    """Create an OrderbookSnapshot from an OrderbookState."""
    bids, asks = state.as_levels(depth=20)
    
    best_bid = bids[0][0] if bids else 0.0
    best_ask = asks[0][0] if asks else 0.0
    
    spread_bps = calculate_spread_bps(best_bid, best_ask)
    bid_depth_usd = calculate_depth_usd(bids)
    ask_depth_usd = calculate_depth_usd(asks)
    orderbook_imbalance = calculate_orderbook_imbalance(bid_depth_usd, ask_depth_usd)
    
    return OrderbookSnapshot(
        symbol=state.symbol,
        exchange=exchange,
        timestamp=timestamp,
        seq=state.seq,
        bids=bids,
        asks=asks,
        spread_bps=spread_bps,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        orderbook_imbalance=orderbook_imbalance,
    )


def states_are_equivalent(
    original: OrderbookState,
    reconstructed: OrderbookState,
    tolerance: float = 1e-9,
) -> bool:
    """Check if two OrderbookState objects are equivalent within tolerance.
    
    Compares bids, asks, and sequence numbers. Floating-point values are
    compared with a tolerance to account for serialization/deserialization.
    """
    if original.symbol != reconstructed.symbol:
        return False
    
    if original.seq != reconstructed.seq:
        return False
    
    if original.valid != reconstructed.valid:
        return False
    
    # Compare bids
    if len(original.bids) != len(reconstructed.bids):
        return False
    
    for price in original.bids:
        if price not in reconstructed.bids:
            return False
        if not math.isclose(original.bids[price], reconstructed.bids[price], rel_tol=tolerance):
            return False
    
    # Compare asks
    if len(original.asks) != len(reconstructed.asks):
        return False
    
    for price in original.asks:
        if price not in reconstructed.asks:
            return False
        if not math.isclose(original.asks[price], reconstructed.asks[price], rel_tol=tolerance):
            return False
    
    return True


def derived_metrics_are_equivalent(
    original_snapshot: OrderbookSnapshot,
    reconstructed_snapshot: OrderbookSnapshot,
    tolerance: float = 1e-6,
) -> bool:
    """Check if derived metrics are equivalent within tolerance."""
    if not math.isclose(
        original_snapshot.spread_bps,
        reconstructed_snapshot.spread_bps,
        rel_tol=tolerance,
        abs_tol=tolerance,
    ):
        return False
    
    if not math.isclose(
        original_snapshot.bid_depth_usd,
        reconstructed_snapshot.bid_depth_usd,
        rel_tol=tolerance,
        abs_tol=tolerance,
    ):
        return False
    
    if not math.isclose(
        original_snapshot.ask_depth_usd,
        reconstructed_snapshot.ask_depth_usd,
        rel_tol=tolerance,
        abs_tol=tolerance,
    ):
        return False
    
    if not math.isclose(
        original_snapshot.orderbook_imbalance,
        reconstructed_snapshot.orderbook_imbalance,
        rel_tol=tolerance,
        abs_tol=tolerance,
    ):
        return False
    
    return True


class TestOrderbookRoundTrip:
    """Property tests for orderbook round-trip replay.
    
    **Property 14: Orderbook Round-Trip Replay**
    
    *For any* valid OrderbookState, storing it as a snapshot and then
    replaying from the stored snapshot SHALL produce an OrderbookState
    with equivalent bids, asks, and derived metrics (within floating-point
    tolerance).
    
    **Validates: Requirements 6.5**
    """
    
    @settings(max_examples=100)
    @given(
        symbol=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="/-")),
        exchange=st.sampled_from(["binance", "coinbase", "kraken", "okx"]),
        bids=orderbook_bids,
        asks=orderbook_asks,
        seq=st.integers(min_value=1, max_value=1000000),
        timestamp=st.floats(min_value=1600000000.0, max_value=2000000000.0),
    )
    def test_orderbook_state_round_trip(
        self,
        symbol: str,
        exchange: str,
        bids: List[tuple[float, float]],
        asks: List[tuple[float, float]],
        seq: int,
        timestamp: float,
    ) -> None:
        """Test that OrderbookState survives round-trip through snapshot.
        
        **Validates: Requirements 6.5**
        """
        # Create original state
        original_state = create_orderbook_state(symbol, bids, asks, seq)
        
        # Create snapshot from state (simulates storage)
        ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        snapshot = create_snapshot_from_state(original_state, exchange, ts)
        
        # Reconstruct state from snapshot (simulates replay)
        # We create a mock reader to test the reconstruct_state method
        reader = OrderbookSnapshotReader.__new__(OrderbookSnapshotReader)
        reader.pool = None  # Not needed for reconstruct_state
        reader.config = None
        
        reconstructed_state = reader.reconstruct_state(snapshot)
        
        # Verify equivalence
        assert states_are_equivalent(original_state, reconstructed_state), (
            f"States not equivalent after round-trip:\n"
            f"Original bids: {original_state.bids}\n"
            f"Reconstructed bids: {reconstructed_state.bids}\n"
            f"Original asks: {original_state.asks}\n"
            f"Reconstructed asks: {reconstructed_state.asks}"
        )
    
    @settings(max_examples=100)
    @given(
        symbol=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="/-")),
        exchange=st.sampled_from(["binance", "coinbase", "kraken", "okx"]),
        bids=orderbook_bids,
        asks=orderbook_asks,
        seq=st.integers(min_value=1, max_value=1000000),
        timestamp=st.floats(min_value=1600000000.0, max_value=2000000000.0),
    )
    def test_derived_metrics_preserved_after_round_trip(
        self,
        symbol: str,
        exchange: str,
        bids: List[tuple[float, float]],
        asks: List[tuple[float, float]],
        seq: int,
        timestamp: float,
    ) -> None:
        """Test that derived metrics are preserved after round-trip.
        
        **Validates: Requirements 6.5**
        """
        # Create original state
        original_state = create_orderbook_state(symbol, bids, asks, seq)
        
        # Create snapshot from state (simulates storage)
        ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        original_snapshot = create_snapshot_from_state(original_state, exchange, ts)
        
        # Reconstruct state from snapshot (simulates replay)
        reader = OrderbookSnapshotReader.__new__(OrderbookSnapshotReader)
        reader.pool = None
        reader.config = None
        
        reconstructed_state = reader.reconstruct_state(original_snapshot)
        
        # Create snapshot from reconstructed state
        reconstructed_snapshot = create_snapshot_from_state(reconstructed_state, exchange, ts)
        
        # Verify derived metrics are equivalent
        assert derived_metrics_are_equivalent(original_snapshot, reconstructed_snapshot), (
            f"Derived metrics not equivalent after round-trip:\n"
            f"Original spread_bps: {original_snapshot.spread_bps}\n"
            f"Reconstructed spread_bps: {reconstructed_snapshot.spread_bps}\n"
            f"Original bid_depth_usd: {original_snapshot.bid_depth_usd}\n"
            f"Reconstructed bid_depth_usd: {reconstructed_snapshot.bid_depth_usd}\n"
            f"Original ask_depth_usd: {original_snapshot.ask_depth_usd}\n"
            f"Reconstructed ask_depth_usd: {reconstructed_snapshot.ask_depth_usd}\n"
            f"Original imbalance: {original_snapshot.orderbook_imbalance}\n"
            f"Reconstructed imbalance: {reconstructed_snapshot.orderbook_imbalance}"
        )
    
    @settings(max_examples=100)
    @given(
        symbol=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="/-")),
        exchange=st.sampled_from(["binance", "coinbase", "kraken", "okx"]),
        bids=orderbook_bids,
        asks=orderbook_asks,
        seq=st.integers(min_value=1, max_value=1000000),
        timestamp=st.floats(min_value=1600000000.0, max_value=2000000000.0),
    )
    def test_as_levels_idempotent_after_round_trip(
        self,
        symbol: str,
        exchange: str,
        bids: List[tuple[float, float]],
        asks: List[tuple[float, float]],
        seq: int,
        timestamp: float,
    ) -> None:
        """Test that as_levels() produces same output after round-trip.
        
        **Validates: Requirements 6.5**
        """
        # Create original state
        original_state = create_orderbook_state(symbol, bids, asks, seq)
        original_bids, original_asks = original_state.as_levels(depth=20)
        
        # Create snapshot from state (simulates storage)
        ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        snapshot = create_snapshot_from_state(original_state, exchange, ts)
        
        # Reconstruct state from snapshot (simulates replay)
        reader = OrderbookSnapshotReader.__new__(OrderbookSnapshotReader)
        reader.pool = None
        reader.config = None
        
        reconstructed_state = reader.reconstruct_state(snapshot)
        reconstructed_bids, reconstructed_asks = reconstructed_state.as_levels(depth=20)
        
        # Verify as_levels output is equivalent
        assert len(original_bids) == len(reconstructed_bids), (
            f"Bid level count mismatch: {len(original_bids)} vs {len(reconstructed_bids)}"
        )
        assert len(original_asks) == len(reconstructed_asks), (
            f"Ask level count mismatch: {len(original_asks)} vs {len(reconstructed_asks)}"
        )
        
        for i, (orig, recon) in enumerate(zip(original_bids, reconstructed_bids)):
            assert math.isclose(orig[0], recon[0], rel_tol=1e-9), (
                f"Bid price mismatch at level {i}: {orig[0]} vs {recon[0]}"
            )
            assert math.isclose(orig[1], recon[1], rel_tol=1e-9), (
                f"Bid size mismatch at level {i}: {orig[1]} vs {recon[1]}"
            )
        
        for i, (orig, recon) in enumerate(zip(original_asks, reconstructed_asks)):
            assert math.isclose(orig[0], recon[0], rel_tol=1e-9), (
                f"Ask price mismatch at level {i}: {orig[0]} vs {recon[0]}"
            )
            assert math.isclose(orig[1], recon[1], rel_tol=1e-9), (
                f"Ask size mismatch at level {i}: {orig[1]} vs {recon[1]}"
            )
    
    @settings(max_examples=50)
    @given(
        symbol=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="/-")),
        exchange=st.sampled_from(["binance", "coinbase", "kraken", "okx"]),
        seq=st.integers(min_value=1, max_value=1000000),
        timestamp=st.floats(min_value=1600000000.0, max_value=2000000000.0),
    )
    def test_valid_flag_preserved_after_round_trip(
        self,
        symbol: str,
        exchange: str,
        seq: int,
        timestamp: float,
    ) -> None:
        """Test that valid flag is True after round-trip.
        
        **Validates: Requirements 6.5**
        """
        # Create original state with valid data
        bids = [[100.0, 1.0], [99.0, 2.0]]
        asks = [[101.0, 1.0], [102.0, 2.0]]
        
        original_state = OrderbookState(symbol=symbol)
        original_state.apply_snapshot(bids, asks, seq)
        
        assert original_state.valid, "Original state should be valid"
        
        # Create snapshot from state
        ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        snapshot = create_snapshot_from_state(original_state, exchange, ts)
        
        # Reconstruct state from snapshot
        reader = OrderbookSnapshotReader.__new__(OrderbookSnapshotReader)
        reader.pool = None
        reader.config = None
        
        reconstructed_state = reader.reconstruct_state(snapshot)
        
        assert reconstructed_state.valid, "Reconstructed state should be valid"
