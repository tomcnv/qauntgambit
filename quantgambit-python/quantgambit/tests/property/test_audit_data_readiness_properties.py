"""
Property-based tests for Data Readiness and Order Book Pipeline Integrity.

Feature: scalping-pipeline-audit

These tests verify correctness properties of the DataReadinessStage and EVGateStage
related to order book data freshness and depth validation.

**Validates: Requirements 1.1, 1.2, 1.3**
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.signals.stages.data_readiness import (
    DataReadinessConfig,
    DataReadinessStage,
)
from quantgambit.signals.stages.ev_gate import (
    EVGateConfig,
    EVGateStage,
    EVGateRejectCode,
)
from quantgambit.signals.pipeline import StageContext, StageResult


# ═══════════════════════════════════════════════════════════════
# SHARED HYPOTHESIS STRATEGIES
# ═══════════════════════════════════════════════════════════════

# Market context generator
market_contexts = st.fixed_dictionaries({
    "book_age_ms": st.floats(min_value=0, max_value=30000, allow_nan=False, allow_infinity=False),
    "bid_depth_usd": st.floats(min_value=0, max_value=100000, allow_nan=False, allow_infinity=False),
    "ask_depth_usd": st.floats(min_value=0, max_value=100000, allow_nan=False, allow_infinity=False),
    "spread_bps": st.floats(min_value=0, max_value=50, allow_nan=False, allow_infinity=False),
    "volatility_regime": st.sampled_from(["low", "normal", "high", "extreme"]),
})

# Prediction output generator
predictions = st.fixed_dictionaries({
    "p_hat": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "direction": st.sampled_from(["up", "down", "flat"]),
    "margin": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "confidence": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
})

# Position state generator
positions = st.fixed_dictionaries({
    "entry_price": st.floats(min_value=100, max_value=100000, allow_nan=False, allow_infinity=False),
    "current_price": st.floats(min_value=100, max_value=100000, allow_nan=False, allow_infinity=False),
    "side": st.sampled_from(["long", "short"]),
    "hold_time_sec": st.floats(min_value=0, max_value=600, allow_nan=False, allow_infinity=False),
    "size_usd": st.floats(min_value=50, max_value=2000, allow_nan=False, allow_infinity=False),
})

# Symbol generator
symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _run_async(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _build_valid_features(
    bid_depth_usd: float = 5000.0,
    ask_depth_usd: float = 5000.0,
) -> dict:
    """Build a minimal valid features dict that passes basic checks."""
    now = time.time()
    return {
        "price": 50000.0,
        "bid": 49999.0,
        "ask": 50001.0,
        "bid_depth_usd": bid_depth_usd,
        "ask_depth_usd": ask_depth_usd,
        "timestamp": now,  # fresh trade data
    }


def _build_data_readiness_ctx(
    symbol: str = "BTCUSDT",
    features: Optional[dict] = None,
    market_context: Optional[dict] = None,
) -> StageContext:
    """Build a StageContext for DataReadinessStage testing."""
    return StageContext(
        symbol=symbol,
        data={
            "features": features or _build_valid_features(),
            "market_context": market_context or {},
        },
    )


# ═══════════════════════════════════════════════════════════════
# Property 1: Data Readiness rejects stale order books
# ═══════════════════════════════════════════════════════════════


class TestDataReadinessRejectsStaleBooks:
    """
    Feature: scalping-pipeline-audit, Property 1: Data Readiness rejects stale order books

    For any StageContext where the order book exchange lag exceeds the hard safety cap
    (max_orderbook_exchange_lag_ms), the DataReadinessStage should return a rejected
    StageResult.

    The DataReadinessStage uses a tiered latency gate system:
    - book_lag_green_ms (150ms): full speed
    - book_lag_yellow_ms (300ms): degraded
    - book_lag_red_ms (800ms): exits only (REJECT)
    - max_orderbook_exchange_lag_ms (3000ms): hard block (REJECT)

    Additionally, receive-time gaps (book_gap) trigger rejection at RED/EMERGENCY levels.

    **Validates: Requirements 1.1**
    """

    @settings(max_examples=200)
    @given(
        book_lag_ms=st.integers(min_value=801, max_value=30000),
        symbol=symbols,
    )
    def test_rejects_when_book_lag_exceeds_red_threshold(
        self, book_lag_ms: int, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 1: Data Readiness rejects stale order books

        When book_lag_ms exceeds book_lag_red_ms (800ms), the stage should reject
        because readiness drops to EMERGENCY level.

        **Validates: Requirements 1.1**
        """
        config = DataReadinessConfig()
        stage = DataReadinessStage(config=config)

        now_ms = time.time() * 1000
        cts_ms = now_ms - book_lag_ms

        features = _build_valid_features()
        features["cts_ms"] = cts_ms

        ctx = _build_data_readiness_ctx(
            symbol=symbol,
            features=features,
            market_context={
                "book_recv_ms": now_ms,  # fresh receive time
                "trade_recv_ms": now_ms,
            },
        )

        result = _run_async(stage.run(ctx))
        assert result == StageResult.REJECT, (
            f"Expected REJECT for book_lag_ms={book_lag_ms} > red={config.book_lag_red_ms}, "
            f"got {result}"
        )

    @settings(max_examples=200)
    @given(
        exchange_lag_ms=st.integers(min_value=3001, max_value=30000),
        symbol=symbols,
    )
    def test_rejects_when_exchange_lag_exceeds_hard_cap(
        self, exchange_lag_ms: int, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 1: Data Readiness rejects stale order books

        When orderbook exchange lag exceeds max_orderbook_exchange_lag_ms (3000ms),
        the stage should hard-block regardless of other conditions.

        **Validates: Requirements 1.1**
        """
        config = DataReadinessConfig()
        stage = DataReadinessStage(config=config)

        now_ms = time.time() * 1000
        cts_ms = now_ms - exchange_lag_ms

        features = _build_valid_features()
        features["cts_ms"] = cts_ms

        ctx = _build_data_readiness_ctx(
            symbol=symbol,
            features=features,
            market_context={
                "book_recv_ms": now_ms,
                "trade_recv_ms": now_ms,
            },
        )

        result = _run_async(stage.run(ctx))
        assert result == StageResult.REJECT, (
            f"Expected REJECT for exchange_lag_ms={exchange_lag_ms} > "
            f"hard_cap={config.max_orderbook_exchange_lag_ms}, got {result}"
        )

    @settings(max_examples=200)
    @given(
        book_gap_ms=st.integers(min_value=10001, max_value=60000),
        symbol=symbols,
    )
    def test_rejects_when_book_gap_exceeds_red_threshold(
        self, book_gap_ms: int, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 1: Data Readiness rejects stale order books

        When the receive-time book gap exceeds book_gap_red_ms (10000ms),
        readiness drops to EMERGENCY and the stage rejects.

        **Validates: Requirements 1.1**
        """
        config = DataReadinessConfig()
        stage = DataReadinessStage(config=config)

        now_ms = time.time() * 1000
        stale_recv_ms = now_ms - book_gap_ms

        features = _build_valid_features()
        # No cts_ms so exchange-lag gate won't fire; rely on receive-gap gate
        ctx = _build_data_readiness_ctx(
            symbol=symbol,
            features=features,
            market_context={
                "book_recv_ms": stale_recv_ms,
                "trade_recv_ms": now_ms,  # trade feed is fresh
            },
        )

        result = _run_async(stage.run(ctx))
        assert result == StageResult.REJECT, (
            f"Expected REJECT for book_gap_ms={book_gap_ms} > "
            f"red={config.book_gap_red_ms}, got {result}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 2: EV Gate rejects stale book data
# ═══════════════════════════════════════════════════════════════


class TestEVGateRejectsStaleBookData:
    """
    Feature: scalping-pipeline-audit, Property 2: EV Gate rejects stale book data

    For any StageContext where the order book age exceeds EV_GATE_MAX_BOOK_AGE_MS,
    the EVGateStage should reject the decision with STALE_BOOK reject code.

    The EVGateStage checks book age via _get_book_age_ms() and rejects when
    book_age_ms > config.max_book_age_ms.

    **Validates: Requirements 1.2**
    """

    @settings(max_examples=200)
    @given(
        max_book_age_ms=st.integers(min_value=100, max_value=10000),
        overshoot_ms=st.integers(min_value=1, max_value=20000),
        symbol=symbols,
    )
    def test_rejects_when_book_age_exceeds_max(
        self, max_book_age_ms: int, overshoot_ms: int, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 2: EV Gate rejects stale book data

        For any max_book_age_ms config and any book age that exceeds it,
        the EVGateStage should reject with STALE_BOOK.

        **Validates: Requirements 1.2**
        """
        config = EVGateConfig(
            max_book_age_ms=max_book_age_ms,
            max_spread_age_ms=max_book_age_ms,  # keep spread age aligned
        )
        stage = EVGateStage(config=config)

        book_age_ms = max_book_age_ms + overshoot_ms

        # Build a context with a signal so the EV gate actually evaluates
        # (it skips if no signal present)
        now_ms = time.time() * 1000
        book_lag_ms = book_age_ms

        ctx = StageContext(
            symbol=symbol,
            data={
                "features": {
                    "price": 50000.0,
                    "bid": 49999.0,
                    "ask": 50001.0,
                },
                "market_context": {
                    "book_lag_ms": book_lag_ms,
                    "price": 50000.0,
                },
                "prediction": {
                    "p_hat": 0.6,
                    "direction": "up",
                },
            },
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49900.0,
                "take_profit": 50200.0,
                "strategy_id": "mean_reversion_fade",
            },
        )

        result = _run_async(stage.run(ctx))
        assert result == StageResult.REJECT, (
            f"Expected REJECT for book_age_ms={book_age_ms} > "
            f"max_book_age_ms={max_book_age_ms}, got {result}"
        )
        assert ctx.rejection_stage == "ev_gate"
        # The EVGateStage has two book-age check paths:
        # 1. _check_connectivity() → ORDERBOOK_SYNC (checks book_lag_ms in market_context)
        # 2. _evaluate() → STALE_BOOK (checks _get_book_age_ms())
        # Both enforce the same max_book_age_ms threshold; either rejection is valid.
        stale_reject_codes = {EVGateRejectCode.STALE_BOOK.value, EVGateRejectCode.ORDERBOOK_SYNC.value}
        assert ctx.rejection_reason in stale_reject_codes, (
            f"Expected rejection reason in {stale_reject_codes}, got {ctx.rejection_reason}"
        )


def test_ev_gate_prefers_feed_staleness_over_stale_book_recv_timestamp():
    stage = EVGateStage(config=EVGateConfig(max_book_age_ms=10_000, max_spread_age_ms=10_000))
    ctx = StageContext(
        symbol="BTCUSDT",
        data={
            "features": _build_valid_features(),
            "market_context": {
                "book_recv_ms": (time.time() * 1000) - 120_000,
                "feed_staleness": {"orderbook": 0.0},
            },
        },
    )

    assert stage._get_book_age_ms(ctx) == 0.0

    @settings(max_examples=200)
    @given(
        max_book_age_ms=st.integers(min_value=100, max_value=10000),
        symbol=symbols,
    )
    def test_rejects_when_book_timestamp_missing(
        self, max_book_age_ms: int, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 2: EV Gate rejects stale book data

        When no book timestamp is available, the EVGateStage should reject
        because it cannot verify data freshness.

        **Validates: Requirements 1.2**
        """
        config = EVGateConfig(max_book_age_ms=max_book_age_ms)
        stage = EVGateStage(config=config)

        # Build context with NO book timestamp sources
        ctx = StageContext(
            symbol=symbol,
            data={
                "features": {
                    "price": 50000.0,
                    "bid": 49999.0,
                    "ask": 50001.0,
                },
                "market_context": {
                    "price": 50000.0,
                    # No book_lag_ms, book_recv_ms, book_timestamp_ms, etc.
                },
                "prediction": {
                    "p_hat": 0.6,
                },
            },
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49900.0,
                "take_profit": 50200.0,
                "strategy_id": "mean_reversion_fade",
            },
        )

        result = _run_async(stage.run(ctx))
        assert result == StageResult.REJECT, (
            f"Expected REJECT when book timestamp is missing, got {result}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 3: Data Readiness rejects insufficient depth
# ═══════════════════════════════════════════════════════════════


class TestDataReadinessRejectsInsufficientDepth:
    """
    Feature: scalping-pipeline-audit, Property 3: Data Readiness rejects insufficient depth

    For any StageContext where bid_depth_usd < DATA_READINESS_MIN_BID_DEPTH_USD or
    ask_depth_usd < DATA_READINESS_MIN_ASK_DEPTH_USD, the DataReadinessStage should
    return a rejected StageResult.

    **Validates: Requirements 1.3**
    """

    @settings(max_examples=200)
    @given(
        min_bid_depth=st.floats(min_value=100, max_value=5000, allow_nan=False, allow_infinity=False),
        bid_fraction=st.floats(min_value=0.0, max_value=0.999, allow_nan=False, allow_infinity=False),
        symbol=symbols,
    )
    def test_rejects_when_bid_depth_below_minimum(
        self, min_bid_depth: float, bid_fraction: float, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 3: Data Readiness rejects insufficient depth

        When bid_depth_usd is below the configured minimum, the stage should reject.

        **Validates: Requirements 1.3**
        """
        config = DataReadinessConfig(
            min_bid_depth_usd=min_bid_depth,
            use_cts_latency_gates=False,  # disable latency gates to isolate depth check
        )
        stage = DataReadinessStage(config=config)

        # bid_depth is strictly below the minimum
        bid_depth = min_bid_depth * bid_fraction

        features = _build_valid_features(
            bid_depth_usd=bid_depth,
            ask_depth_usd=min_bid_depth + 1000,  # ask depth is fine
        )

        ctx = _build_data_readiness_ctx(
            symbol=symbol,
            features=features,
        )

        result = _run_async(stage.run(ctx))
        assert result == StageResult.REJECT, (
            f"Expected REJECT for bid_depth={bid_depth:.2f} < "
            f"min_bid_depth={min_bid_depth:.2f}, got {result}"
        )

    @settings(max_examples=200)
    @given(
        min_ask_depth=st.floats(min_value=100, max_value=5000, allow_nan=False, allow_infinity=False),
        ask_fraction=st.floats(min_value=0.0, max_value=0.999, allow_nan=False, allow_infinity=False),
        symbol=symbols,
    )
    def test_rejects_when_ask_depth_below_minimum(
        self, min_ask_depth: float, ask_fraction: float, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 3: Data Readiness rejects insufficient depth

        When ask_depth_usd is below the configured minimum, the stage should reject.

        **Validates: Requirements 1.3**
        """
        config = DataReadinessConfig(
            min_ask_depth_usd=min_ask_depth,
            use_cts_latency_gates=False,  # disable latency gates to isolate depth check
        )
        stage = DataReadinessStage(config=config)

        # ask_depth is strictly below the minimum
        ask_depth = min_ask_depth * ask_fraction

        features = _build_valid_features(
            bid_depth_usd=min_ask_depth + 1000,  # bid depth is fine
            ask_depth_usd=ask_depth,
        )

        ctx = _build_data_readiness_ctx(
            symbol=symbol,
            features=features,
        )

        result = _run_async(stage.run(ctx))
        assert result == StageResult.REJECT, (
            f"Expected REJECT for ask_depth={ask_depth:.2f} < "
            f"min_ask_depth={min_ask_depth:.2f}, got {result}"
        )

    @settings(max_examples=200)
    @given(
        min_depth=st.floats(min_value=100, max_value=5000, allow_nan=False, allow_infinity=False),
        bid_fraction=st.floats(min_value=0.0, max_value=0.999, allow_nan=False, allow_infinity=False),
        ask_fraction=st.floats(min_value=0.0, max_value=0.999, allow_nan=False, allow_infinity=False),
        symbol=symbols,
    )
    def test_rejects_when_both_depths_below_minimum(
        self, min_depth: float, bid_fraction: float, ask_fraction: float, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 3: Data Readiness rejects insufficient depth

        When both bid and ask depth are below their minimums, the stage should reject.

        **Validates: Requirements 1.3**
        """
        config = DataReadinessConfig(
            min_bid_depth_usd=min_depth,
            min_ask_depth_usd=min_depth,
            use_cts_latency_gates=False,
        )
        stage = DataReadinessStage(config=config)

        features = _build_valid_features(
            bid_depth_usd=min_depth * bid_fraction,
            ask_depth_usd=min_depth * ask_fraction,
        )

        ctx = _build_data_readiness_ctx(
            symbol=symbol,
            features=features,
        )

        result = _run_async(stage.run(ctx))
        assert result == StageResult.REJECT, (
            f"Expected REJECT when both depths below minimum, got {result}"
        )
