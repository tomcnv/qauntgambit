"""
Property-based tests for Throttling and Entry Rate Limiting.

Feature: scalping-pipeline-audit

These tests verify correctness properties of the ExecutionWorker's
entry rate limiting logic (_allow_entry_attempt_rate).

**Validates: Requirements 8.4**
"""

from __future__ import annotations

import time
from typing import Optional
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.execution.execution_worker import (
    ExecutionWorker,
    ExecutionWorkerConfig,
)


# ═══════════════════════════════════════════════════════════════
# SHARED HYPOTHESIS STRATEGIES
# ═══════════════════════════════════════════════════════════════

symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

# Rate limit values (attempts per minute)
rate_limits = st.integers(min_value=1, max_value=20)

# Number of attempts to simulate
attempt_counts = st.integers(min_value=0, max_value=30)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _make_execution_worker(
    config: Optional[ExecutionWorkerConfig] = None,
) -> ExecutionWorker:
    """Build a minimal ExecutionWorker with mocked dependencies for unit testing."""
    redis_client = MagicMock()
    redis_client.redis = MagicMock()
    execution_manager = MagicMock()
    worker = ExecutionWorker(
        redis_client=redis_client,
        execution_manager=execution_manager,
        bot_id="test_bot",
        exchange="bybit",
        config=config or ExecutionWorkerConfig(),
    )
    return worker


# ═══════════════════════════════════════════════════════════════
# Property 27: Entry rate limiting
# ═══════════════════════════════════════════════════════════════


class TestEntryRateLimiting:
    """
    Feature: scalping-pipeline-audit, Property 27: Entry rate limiting

    Per symbol, at most ENTRY_MAX_ATTEMPTS_PER_SYMBOL_PER_MIN attempts per minute.

    **Validates: Requirements 8.4**
    """

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        rate_limit=rate_limits,
        num_attempts=attempt_counts,
    )
    def test_rate_limit_enforced_per_symbol(
        self, symbol: str, rate_limit: int, num_attempts: int,
    ):
        """Feature: scalping-pipeline-audit, Property 27: Entry rate limiting

        After recording `num_attempts` within the last minute for a symbol,
        _allow_entry_attempt_rate returns False once the count reaches the limit.
        """
        config = ExecutionWorkerConfig(
            entry_max_attempts_per_symbol_per_min=rate_limit,
        )
        worker = _make_execution_worker(config)

        now = time.time()
        # Pre-populate attempts within the last minute
        worker._entry_attempts[symbol] = [now - i for i in range(num_attempts)]

        result = worker._allow_entry_attempt_rate(symbol)

        if num_attempts < rate_limit:
            assert result is True, (
                f"Expected allowed: {num_attempts} attempts < limit {rate_limit}"
            )
        else:
            assert result is False, (
                f"Expected blocked: {num_attempts} attempts >= limit {rate_limit}"
            )

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        rate_limit=rate_limits,
    )
    def test_expired_attempts_not_counted(
        self, symbol: str, rate_limit: int,
    ):
        """Feature: scalping-pipeline-audit, Property 27: Entry rate limiting

        Attempts older than 60 seconds are pruned and not counted toward the limit.
        """
        config = ExecutionWorkerConfig(
            entry_max_attempts_per_symbol_per_min=rate_limit,
        )
        worker = _make_execution_worker(config)

        now = time.time()
        # All attempts are older than 60 seconds — should be pruned
        worker._entry_attempts[symbol] = [now - 120.0] * (rate_limit + 5)

        result = worker._allow_entry_attempt_rate(symbol)
        assert result is True, (
            "Expired attempts (>60s old) should be pruned; entry should be allowed"
        )

    @settings(max_examples=200)
    @given(symbol=symbols)
    def test_no_symbol_always_allowed(self, symbol: str):
        """Feature: scalping-pipeline-audit, Property 27: Entry rate limiting

        When symbol is None or empty, rate limiting is bypassed.
        """
        config = ExecutionWorkerConfig(
            entry_max_attempts_per_symbol_per_min=1,
        )
        worker = _make_execution_worker(config)

        assert worker._allow_entry_attempt_rate(None) is True
        assert worker._allow_entry_attempt_rate("") is True

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        num_attempts=attempt_counts,
    )
    def test_zero_limit_disables_rate_limiting(
        self, symbol: str, num_attempts: int,
    ):
        """Feature: scalping-pipeline-audit, Property 27: Entry rate limiting

        When entry_max_attempts_per_symbol_per_min <= 0, rate limiting is disabled.
        """
        config = ExecutionWorkerConfig(
            entry_max_attempts_per_symbol_per_min=0,
        )
        worker = _make_execution_worker(config)

        now = time.time()
        worker._entry_attempts[symbol] = [now] * num_attempts

        assert worker._allow_entry_attempt_rate(symbol) is True

    @settings(max_examples=200)
    @given(
        symbol_a=symbols,
        symbol_b=symbols,
        rate_limit=rate_limits,
    )
    def test_rate_limit_independent_per_symbol(
        self, symbol_a: str, symbol_b: str, rate_limit: int,
    ):
        """Feature: scalping-pipeline-audit, Property 27: Entry rate limiting

        Rate limiting is tracked independently per symbol. Exhausting the limit
        on one symbol does not affect another.
        """
        assume(symbol_a != symbol_b)

        config = ExecutionWorkerConfig(
            entry_max_attempts_per_symbol_per_min=rate_limit,
        )
        worker = _make_execution_worker(config)

        now = time.time()
        # Exhaust limit on symbol_a
        worker._entry_attempts[symbol_a] = [now] * rate_limit

        # symbol_a should be blocked
        assert worker._allow_entry_attempt_rate(symbol_a) is False

        # symbol_b should still be allowed (no attempts recorded)
        assert worker._allow_entry_attempt_rate(symbol_b) is True
