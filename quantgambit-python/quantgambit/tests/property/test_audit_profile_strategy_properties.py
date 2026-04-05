"""
Property-based tests for Profile Routing and Strategy Signal Generation.

Feature: scalping-pipeline-audit

These tests verify correctness properties of the ProfileRouter, StrategyRegistry,
and CandidateVetoStage related to profile selection, strategy disabling, mean
reversion veto, and forced profile override.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.6**
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from unittest.mock import patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.profiles.router import (
    _build_context_vector,
    DeepTraderProfileRouter,
    _get_attr,
    _safe_float,
)
from quantgambit.strategies.disable_rules import (
    disabled_strategies_from_env,
    is_strategy_disabled_for_symbol,
    MEAN_REVERSION_STRATEGIES,
)
from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.candidate_veto import (
    CandidateVetoConfig,
    CandidateVetoStage,
)
from quantgambit.deeptrader_core.types import (
    MarketSnapshot,
    TradeCandidate,
    GateDecision,
)


# ═══════════════════════════════════════════════════════════════
# SHARED HYPOTHESIS STRATEGIES
# ═══════════════════════════════════════════════════════════════

symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

volatility_regimes = st.sampled_from(["low", "normal", "high", "extreme"])

trend_directions = st.sampled_from(["up", "down", "flat"])

sessions = st.sampled_from(["asia", "europe", "us", "overnight"])


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


def _make_market_snapshot(
    symbol: str = "BTCUSDT",
    spread_bps: float = 2.0,
    bid_depth_usd: float = 5000.0,
    ask_depth_usd: float = 5000.0,
    vol_regime: str = "normal",
    trend_direction: str = "flat",
    trend_strength: float = 0.1,
    imb_5s: float = 0.0,
    data_quality_score: float = 0.9,
    poc_price: float = 50000.0,
    mid_price: float = 50000.0,
) -> MarketSnapshot:
    """Build a minimal valid MarketSnapshot for testing."""
    return MarketSnapshot(
        symbol=symbol,
        exchange="bybit",
        timestamp_ns=int(time.time() * 1e9),
        snapshot_age_ms=100.0,
        mid_price=mid_price,
        bid=mid_price - 0.5,
        ask=mid_price + 0.5,
        spread_bps=spread_bps,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        depth_imbalance=0.0,
        imb_1s=0.0,
        imb_5s=imb_5s,
        imb_30s=0.0,
        orderflow_persistence_sec=0.0,
        rv_1s=0.001,
        rv_10s=0.001,
        rv_1m=0.001,
        vol_shock=False,
        vol_regime=vol_regime,
        vol_regime_score=0.5,
        trend_direction=trend_direction,
        trend_strength=trend_strength,
        poc_price=poc_price,
        vah_price=poc_price + 100,
        val_price=poc_price - 100,
        position_in_value="inside",
        expected_fill_slippage_bps=1.0,
        typical_spread_bps=2.0,
        data_quality_score=data_quality_score,
        ws_connected=True,
    )


def _make_trade_candidate(
    symbol: str = "BTCUSDT",
    side: str = "long",
    strategy_id: str = "mean_reversion_fade",
    profile_id: str = "test_profile",
    expected_edge_bps: float = 30.0,
    entry_price: float = 50000.0,
) -> TradeCandidate:
    """Build a minimal valid TradeCandidate for testing."""
    sl = entry_price * 0.998 if side == "long" else entry_price * 1.002
    tp = entry_price * 1.004 if side == "long" else entry_price * 0.996
    return TradeCandidate(
        symbol=symbol,
        side=side,
        strategy_id=strategy_id,
        profile_id=profile_id,
        expected_edge_bps=expected_edge_bps,
        confidence=0.8,
        entry_price=entry_price,
        stop_loss=sl,
        take_profit=tp,
        max_position_usd=400.0,
        generation_reason="test",
        snapshot_timestamp_ns=int(time.time() * 1e9),
    )


# ═══════════════════════════════════════════════════════════════
# Property 10: Profile router context vector completeness
# ═══════════════════════════════════════════════════════════════


class TestProfileRouterContextVectorCompleteness:
    """
    Feature: scalping-pipeline-audit, Property 10: Profile router context vector completeness

    For any market context and features input, the _build_context_vector() function
    should produce a vector containing all required components: spread, depth,
    volatility regime, trend, POC price, session, and data quality score.

    **Validates: Requirements 4.1**
    """

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        spread_bps=st.floats(min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False),
        bid_depth_usd=st.floats(min_value=100, max_value=100000, allow_nan=False, allow_infinity=False),
        ask_depth_usd=st.floats(min_value=100, max_value=100000, allow_nan=False, allow_infinity=False),
        vol_regime=volatility_regimes,
        trend_direction=trend_directions,
        trend_strength=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        poc_price=st.floats(min_value=100, max_value=100000, allow_nan=False, allow_infinity=False),
        session=sessions,
        data_quality_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_context_vector_contains_all_required_fields(
        self,
        symbol: str,
        spread_bps: float,
        bid_depth_usd: float,
        ask_depth_usd: float,
        vol_regime: str,
        trend_direction: str,
        trend_strength: float,
        poc_price: float,
        session: str,
        data_quality_score: float,
    ):
        """
        Feature: scalping-pipeline-audit, Property 10: Profile router context vector completeness

        When all required fields are provided in market_context/features,
        the resulting ContextVector should contain spread, depth, volatility regime,
        trend, POC price, session, and data quality score.

        **Validates: Requirements 4.1**
        """
        price = poc_price
        market_context = {
            "price": price,
            "bid": price - (spread_bps / 10000 * price / 2),
            "ask": price + (spread_bps / 10000 * price / 2),
            "spread_bps": spread_bps,
            "bid_depth_usd": bid_depth_usd,
            "ask_depth_usd": ask_depth_usd,
            "vol_regime": vol_regime,
            "trend_direction": trend_direction,
            "trend_strength": trend_strength,
            "poc_price": poc_price,
            "session": session,
            "data_quality_score": data_quality_score,
            "timestamp": time.time(),
        }
        features = {}

        cv = _build_context_vector(symbol, market_context, features)

        # _build_context_vector may return None if the deeptrader_core import fails
        if cv is None:
            pytest.skip("deeptrader_core.profiles.context_vector not available")

        # Verify all required components are present in the context vector
        # 1. Spread
        assert hasattr(cv, "spread_bps"), "Context vector missing spread_bps"
        assert cv.spread_bps is not None, "spread_bps should not be None"

        # 2. Depth
        assert hasattr(cv, "bid_depth_usd"), "Context vector missing bid_depth_usd"
        assert hasattr(cv, "ask_depth_usd"), "Context vector missing ask_depth_usd"

        # 3. Volatility regime
        assert hasattr(cv, "volatility_regime"), "Context vector missing volatility_regime"

        # 4. Trend
        assert hasattr(cv, "trend_direction"), "Context vector missing trend_direction"
        assert hasattr(cv, "trend_strength"), "Context vector missing trend_strength"

        # 5. POC price
        assert hasattr(cv, "point_of_control"), "Context vector missing point_of_control"

        # 6. Session
        assert hasattr(cv, "session"), "Context vector missing session"

        # 7. Data quality score
        assert hasattr(cv, "data_completeness") or hasattr(cv, "data_quality_state"), (
            "Context vector missing data quality indicator"
        )


# ═══════════════════════════════════════════════════════════════
# Property 11: Profile router selects highest adjusted score
# ═══════════════════════════════════════════════════════════════


class TestProfileRouterSelectsHighestAdjustedScore:
    """
    Feature: scalping-pipeline-audit, Property 11: Profile router selects highest adjusted score

    When multiple profiles score above the minimum threshold, the
    DeepTraderProfileRouter.route_with_context() should return the profile
    with the highest adjusted_score = score × confidence × data_quality × risk_bias_multiplier.

    We test the _filter_scores method directly since it implements the scoring
    and selection logic. The route_with_context method delegates to the
    deeptrader_core router for scoring, then calls _filter_scores.

    **Validates: Requirements 4.2**
    """

    @settings(max_examples=200)
    @given(
        num_profiles=st.integers(min_value=2, max_value=6),
        scores_data=st.lists(
            st.fixed_dictionaries({
                "score": st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
                "confidence": st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
            }),
            min_size=2,
            max_size=6,
        ),
        data_quality_score=st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_selects_profile_with_highest_adjusted_score(
        self,
        num_profiles: int,
        scores_data: list,
        data_quality_score: float,
    ):
        """
        Feature: scalping-pipeline-audit, Property 11: Profile router selects highest adjusted score

        Given multiple profile scores, _filter_scores returns eligible profiles
        and the caller (route_with_context) picks the one with the highest
        adjusted_score.

        **Validates: Requirements 4.2**
        """
        # Build mock ProfileScore objects
        @dataclass
        class MockProfileScore:
            profile_id: str
            score: float
            confidence: float
            reasons: list = field(default_factory=list)

        mock_scores = []
        for i, sd in enumerate(scores_data):
            mock_scores.append(MockProfileScore(
                profile_id=f"profile_{i}",
                score=sd["score"],
                confidence=sd["confidence"],
                reasons=[],
            ))

        # Create router (it may not have the deeptrader_core router, but
        # _filter_scores is pure logic that doesn't need it)
        router = DeepTraderProfileRouter.__new__(DeepTraderProfileRouter)
        router._router = None
        router.last_scores = []
        router._policy = {}
        router._profile_first_seen = {}
        router._profile_seen_counts = {}
        router._profile_versions = {}

        market_context = {"data_quality_score": data_quality_score}
        features = {}

        eligible = router._filter_scores(mock_scores, None, market_context, features)

        # All profiles should be eligible (no policy filters set)
        assert len(eligible) == len(mock_scores), (
            f"Expected {len(mock_scores)} eligible profiles, got {len(eligible)}"
        )

        # Compute expected adjusted scores
        risk_bias_multiplier = 1.0  # No exposure data → default 1.0
        expected_best_id = None
        expected_best_adjusted = -1.0
        for i, sd in enumerate(scores_data):
            adj = sd["score"] * sd["confidence"] * data_quality_score * risk_bias_multiplier
            if adj > expected_best_adjusted:
                expected_best_adjusted = adj
                expected_best_id = f"profile_{i}"

        # Verify the eligible list contains correct adjusted scores
        for entry in eligible:
            idx = int(entry["profile_id"].split("_")[1])
            sd = scores_data[idx]
            expected_adj = sd["score"] * sd["confidence"] * data_quality_score * risk_bias_multiplier
            assert abs(entry["adjusted_score"] - expected_adj) < 1e-9, (
                f"Profile {entry['profile_id']}: expected adjusted_score={expected_adj}, "
                f"got {entry['adjusted_score']}"
            )

        # Verify that selecting max adjusted_score gives the expected profile
        best = max(eligible, key=lambda e: e.get("adjusted_score", 0.0))
        assert best["profile_id"] == expected_best_id, (
            f"Expected best profile={expected_best_id}, got {best['profile_id']}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 12: Disabled strategies produce no signals
# ═══════════════════════════════════════════════════════════════


class TestDisabledStrategiesProduceNoSignals:
    """
    Feature: scalping-pipeline-audit, Property 12: Disabled strategies produce no signals

    Any strategy ID that appears in DISABLE_STRATEGIES should be blocked by
    is_strategy_disabled_for_symbol() and by the CandidateVetoStage.

    **Validates: Requirements 4.3**
    """

    @settings(max_examples=200)
    @given(
        strategy_id=st.sampled_from([
            "mean_reversion_fade",
            "breakout_scalp",
            "poc_magnet_scalp",
            "low_vol_grind",
            "trend_pullback",
            "vwap_reversion",
            "spread_compression_scalp",
        ]),
        symbol=symbols,
    )
    def test_disabled_strategy_blocked_by_disable_rules(
        self, strategy_id: str, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 12: Disabled strategies produce no signals

        When a strategy is in the DISABLE_STRATEGIES set, is_strategy_disabled_for_symbol
        returns True.

        **Validates: Requirements 4.3**
        """
        disabled_set = {strategy_id}  # The strategy under test is disabled

        result = is_strategy_disabled_for_symbol(
            strategy_id,
            symbol,
            disabled_strategies=disabled_set,
        )
        assert result is True, (
            f"Expected strategy '{strategy_id}' to be disabled when in DISABLE_STRATEGIES"
        )

    @settings(max_examples=200)
    @given(
        strategy_id=st.sampled_from([
            "mean_reversion_fade",
            "breakout_scalp",
            "poc_magnet_scalp",
            "low_vol_grind",
            "trend_pullback",
        ]),
        symbol=symbols,
    )
    def test_disabled_strategy_vetoed_by_candidate_veto_stage(
        self, strategy_id: str, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 12: Disabled strategies produce no signals

        When a strategy is in DISABLE_STRATEGIES, the CandidateVetoStage rejects
        the candidate with 'strategy_disabled' reason.

        **Validates: Requirements 4.3**
        """
        # Set up env with the strategy disabled
        env_patch = {
            "DISABLE_STRATEGIES": strategy_id,
            "PREDICTION_ALLOWED_DIRECTIONS": "up,down,flat",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            config = CandidateVetoConfig(
                min_net_edge_bps=0.0,  # Don't veto on edge
            )
            stage = CandidateVetoStage(config=config)

            snapshot = _make_market_snapshot(symbol=symbol)
            candidate = _make_trade_candidate(
                symbol=symbol,
                strategy_id=strategy_id,
                expected_edge_bps=50.0,
            )

            ctx = StageContext(
                symbol=symbol,
                data={
                    "candidate": candidate,
                    "snapshot": snapshot,
                    "market_context": {"session": "us"},
                },
            )

            result = _run_async(stage.run(ctx))
            assert result == StageResult.REJECT, (
                f"Expected REJECT for disabled strategy '{strategy_id}', got {result}"
            )
            assert "strategy_disabled" in (ctx.rejection_reason or ""), (
                f"Expected 'strategy_disabled' in rejection reason, "
                f"got '{ctx.rejection_reason}'"
            )


# ═══════════════════════════════════════════════════════════════
# Property 13: Mean reversion veto on strong trends
# ═══════════════════════════════════════════════════════════════


class TestMeanReversionVetoOnStrongTrends:
    """
    Feature: scalping-pipeline-audit, Property 13: Mean reversion veto on strong trends

    When trend strength exceeds CANDIDATE_VETO_TREND_BLOCK_MEAN_REVERSION,
    the CandidateVetoStage should reject mean reversion signals via the
    _check_regime_compatibility check.

    **Validates: Requirements 4.4**
    """

    @settings(max_examples=200)
    @given(
        strategy_id=st.sampled_from(sorted(MEAN_REVERSION_STRATEGIES)),
        trend_threshold=st.floats(min_value=0.05, max_value=0.9, allow_nan=False, allow_infinity=False),
        overshoot=st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False),
        symbol=symbols,
        side=st.sampled_from(["long", "short"]),
    )
    def test_mean_reversion_rejected_when_trend_exceeds_threshold(
        self,
        strategy_id: str,
        trend_threshold: float,
        overshoot: float,
        symbol: str,
        side: str,
    ):
        """
        Feature: scalping-pipeline-audit, Property 13: Mean reversion veto on strong trends

        For any mean reversion strategy, when trend_strength exceeds the configured
        threshold, the CandidateVetoStage rejects with regime_veto.

        **Validates: Requirements 4.4**
        """
        trend_strength = min(trend_threshold + overshoot, 1.0)
        assume(trend_strength > trend_threshold)

        # Use a clean env to avoid interference from other env vars
        env_patch = {
            "DISABLE_STRATEGIES": "",
            "DISABLE_MEAN_REVERSION_SYMBOLS": "",
            "PREDICTION_ALLOWED_DIRECTIONS": "up,down,flat",
            "CANDIDATE_VETO_TREND_BLOCK_MEAN_REVERSION": str(trend_threshold),
        }
        with patch.dict(os.environ, env_patch, clear=False):
            config = CandidateVetoConfig(
                trend_strength_block_mean_reversion=trend_threshold,
                min_net_edge_bps=0.0,
                orderflow_veto_base=100.0,  # Very high to avoid orderflow veto
            )
            stage = CandidateVetoStage(config=config)

            snapshot = _make_market_snapshot(
                symbol=symbol,
                trend_strength=trend_strength,
                trend_direction="up",
            )
            candidate = _make_trade_candidate(
                symbol=symbol,
                side=side,
                strategy_id=strategy_id,
                expected_edge_bps=100.0,  # High edge to avoid tradeability veto
            )

            ctx = StageContext(
                symbol=symbol,
                data={
                    "candidate": candidate,
                    "snapshot": snapshot,
                    "market_context": {"session": "us"},
                },
            )

            result = _run_async(stage.run(ctx))
            assert result == StageResult.REJECT, (
                f"Expected REJECT for mean reversion strategy '{strategy_id}' "
                f"with trend_strength={trend_strength:.3f} > threshold={trend_threshold:.3f}, "
                f"got {result}"
            )
            assert "regime_veto" in (ctx.rejection_reason or ""), (
                f"Expected 'regime_veto' in rejection reason, "
                f"got '{ctx.rejection_reason}'"
            )

    @settings(max_examples=200)
    @given(
        strategy_id=st.sampled_from(sorted(MEAN_REVERSION_STRATEGIES)),
        trend_threshold=st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False),
        fraction=st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False),
        symbol=symbols,
    )
    def test_mean_reversion_allowed_when_trend_below_threshold(
        self,
        strategy_id: str,
        trend_threshold: float,
        fraction: float,
        symbol: str,
    ):
        """
        Feature: scalping-pipeline-audit, Property 13: Mean reversion veto on strong trends

        When trend_strength is below the threshold, mean reversion strategies
        should NOT be rejected by the regime compatibility check.

        **Validates: Requirements 4.4**
        """
        trend_strength = trend_threshold * fraction

        env_patch = {
            "DISABLE_STRATEGIES": "",
            "DISABLE_MEAN_REVERSION_SYMBOLS": "",
            "PREDICTION_ALLOWED_DIRECTIONS": "up,down,flat",
            "CANDIDATE_VETO_TREND_BLOCK_MEAN_REVERSION": str(trend_threshold),
        }
        with patch.dict(os.environ, env_patch, clear=False):
            config = CandidateVetoConfig(
                trend_strength_block_mean_reversion=trend_threshold,
                min_net_edge_bps=0.0,
                orderflow_veto_base=100.0,  # Very high to avoid orderflow veto
            )
            stage = CandidateVetoStage(config=config)

            snapshot = _make_market_snapshot(
                symbol=symbol,
                trend_strength=trend_strength,
                trend_direction="flat",
            )
            candidate = _make_trade_candidate(
                symbol=symbol,
                side="long",
                strategy_id=strategy_id,
                expected_edge_bps=100.0,
            )

            ctx = StageContext(
                symbol=symbol,
                data={
                    "candidate": candidate,
                    "snapshot": snapshot,
                    "market_context": {"session": "us"},
                },
            )

            result = _run_async(stage.run(ctx))
            # Should NOT be rejected by regime veto (may still be rejected by other checks)
            if result == StageResult.REJECT:
                assert "regime_veto:mean_reversion_in_trend" not in (ctx.rejection_reason or ""), (
                    f"Mean reversion should NOT be regime-vetoed when "
                    f"trend_strength={trend_strength:.3f} < threshold={trend_threshold:.3f}"
                )


# ═══════════════════════════════════════════════════════════════
# Property 14: Forced profile bypasses scoring
# ═══════════════════════════════════════════════════════════════


class TestForcedProfileBypassesScoring:
    """
    Feature: scalping-pipeline-audit, Property 14: Forced profile bypasses scoring

    When FORCE_PROFILE_ID is set (non-empty), the ProfileRouter should return
    that profile ID regardless of market context or scoring results.

    The mechanism works via feature_worker.py injecting profile_id into
    market_context when FORCE_PROFILE_ID is set. The DeepTraderProfileRouter.
    route_with_context() then detects the explicit profile_id and returns it
    directly, bypassing the scoring engine.

    **Validates: Requirements 4.6**
    """

    @settings(max_examples=200)
    @given(
        forced_profile=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
            min_size=3,
            max_size=30,
        ),
        symbol=symbols,
    )
    def test_explicit_profile_id_bypasses_scoring(
        self,
        forced_profile: str,
        symbol: str,
    ):
        """
        Feature: scalping-pipeline-audit, Property 14: Forced profile bypasses scoring

        When market_context contains an explicit profile_id (as injected by
        FORCE_PROFILE_ID), route_with_context returns that profile directly
        without running the scoring engine.

        **Validates: Requirements 4.6**
        """
        assume(forced_profile.strip())  # Must be non-empty after strip

        router = DeepTraderProfileRouter.__new__(DeepTraderProfileRouter)
        router._router = None  # No deeptrader_core router needed
        router.last_scores = []
        router._policy = {}
        router._profile_first_seen = {}
        router._profile_seen_counts = {}
        router._profile_versions = {}

        # Simulate what feature_worker does: inject profile_id into market_context
        market_context = {
            "profile_id": forced_profile,
            "price": 50000.0,
        }
        features = {}

        result = router.route_with_context(symbol, market_context, features)

        # The base ProfileRouter.route_with_context calls route() which
        # extracts profile_id from market_context
        assert result == forced_profile, (
            f"Expected forced profile '{forced_profile}', got '{result}'"
        )

    @settings(max_examples=200)
    @given(
        forced_profile=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
            min_size=3,
            max_size=30,
        ),
        symbol=symbols,
        spread_bps=st.floats(min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False),
        vol_regime=volatility_regimes,
        trend_direction=trend_directions,
    )
    def test_forced_profile_ignores_market_conditions(
        self,
        forced_profile: str,
        symbol: str,
        spread_bps: float,
        vol_regime: str,
        trend_direction: str,
    ):
        """
        Feature: scalping-pipeline-audit, Property 14: Forced profile bypasses scoring

        Regardless of market conditions (spread, volatility, trend), the forced
        profile is always returned when profile_id is set in market_context.

        **Validates: Requirements 4.6**
        """
        assume(forced_profile.strip())

        router = DeepTraderProfileRouter.__new__(DeepTraderProfileRouter)
        router._router = None
        router.last_scores = []
        router._policy = {}
        router._profile_first_seen = {}
        router._profile_seen_counts = {}
        router._profile_versions = {}

        market_context = {
            "profile_id": forced_profile,
            "price": 50000.0,
            "spread_bps": spread_bps,
            "vol_regime": vol_regime,
            "trend_direction": trend_direction,
        }
        features = {}

        result = router.route_with_context(symbol, market_context, features)
        assert result == forced_profile, (
            f"Expected forced profile '{forced_profile}' regardless of market conditions "
            f"(spread={spread_bps}, vol={vol_regime}, trend={trend_direction}), "
            f"got '{result}'"
        )

    @settings(max_examples=200)
    @given(
        forced_profile=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
            min_size=3,
            max_size=30,
        ),
        symbol=symbols,
    )
    def test_forced_profile_records_explicit_override_in_scores(
        self,
        forced_profile: str,
        symbol: str,
    ):
        """
        Feature: scalping-pipeline-audit, Property 14: Forced profile bypasses scoring

        When an explicit profile is used, the router records it in last_scores
        with 'explicit_profile_override' reason for observability.

        **Validates: Requirements 4.6**
        """
        assume(forced_profile.strip())

        router = DeepTraderProfileRouter.__new__(DeepTraderProfileRouter)
        # Need _router to be truthy so route_with_context takes the explicit path
        # instead of falling through to super()
        router._router = True  # Truthy sentinel
        router.last_scores = []
        router._policy = {}
        router._profile_first_seen = {}
        router._profile_seen_counts = {}
        router._profile_versions = {}

        market_context = {
            "profile_id": forced_profile,
            "price": 50000.0,
        }
        features = {}

        result = router.route_with_context(symbol, market_context, features)
        assert result == forced_profile

        # Verify the last_scores records the override
        assert len(router.last_scores) == 1, (
            f"Expected 1 score entry for forced profile, got {len(router.last_scores)}"
        )
        score_entry = router.last_scores[0]
        assert score_entry["profile_id"] == forced_profile
        assert "explicit_profile_override" in score_entry.get("reasons", []), (
            f"Expected 'explicit_profile_override' in reasons, got {score_entry.get('reasons')}"
        )
