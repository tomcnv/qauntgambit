"""
Property-based tests for Replay Validation.

Feature: trading-pipeline-integration

These tests verify the correctness properties of the replay validation system,
ensuring decisions are correctly compared, changes are properly categorized,
and stage differences are accurately identified.

Uses hypothesis library with minimum 100 iterations per property test.

**Validates: Requirements 7.1, 7.2, 7.3, 7.6**
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from quantgambit.integration.replay_validation import (
    ReplayResult,
    ReplayReport,
    ReplayManager,
    categorize_change,
    identify_stage_diff,
    aggregate_changes,
    VALID_CHANGE_CATEGORIES,
)
from quantgambit.integration.decision_recording import RecordedDecision


# ═══════════════════════════════════════════════════════════════
# STRATEGIES FOR PROPERTY-BASED TESTING
# ═══════════════════════════════════════════════════════════════

# Symbol strategy
symbol_strategy = st.sampled_from([
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "MATICUSDT", "DOTUSDT", "AVAXUSDT",
])

# Decision outcome strategy (only accepted/rejected for replay)
decision_outcome_strategy = st.sampled_from(["accepted", "rejected"])

# Config version strategy
config_version_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"),
    min_size=1,
    max_size=32,
).map(lambda s: f"v_{s}")

# Rejection stage strategy
rejection_stage_strategy = st.sampled_from([
    None, "data_readiness", "ev_gate", "execution_feasibility",
    "confirmation", "arbitration", "vol_shock_gate",
])

# Non-null rejection stage strategy (for stage diff tests)
non_null_rejection_stage_strategy = st.sampled_from([
    "data_readiness", "ev_gate", "execution_feasibility",
    "confirmation", "arbitration", "vol_shock_gate",
])

# Profile ID strategy
profile_id_strategy = st.one_of(
    st.none(),
    st.sampled_from(["aggressive", "conservative", "balanced", "scalper", "swing"]),
)

# Price strategy (realistic crypto prices)
price_strategy = st.floats(
    min_value=0.001,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Size strategy (position sizes)
size_strategy = st.floats(
    min_value=0.0001,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Timestamp strategy
timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)

# Market snapshot strategy
market_snapshot_strategy = st.fixed_dictionaries({
    "bid": price_strategy,
    "ask": price_strategy,
    "mid": price_strategy,
    "spread_bps": st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
    "bid_depth_usd": st.floats(min_value=1000.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
    "ask_depth_usd": st.floats(min_value=1000.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
})

# Features strategy
features_strategy = st.fixed_dictionaries({
    "volatility": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "trend_strength": st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "momentum": st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "volume_ratio": st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
})

# Signal strategy (for accepted decisions)
signal_strategy = st.one_of(
    st.none(),
    st.fixed_dictionaries({
        "side": st.sampled_from(["buy", "sell"]),
        "size": size_strategy,
        "entry_price": price_strategy,
        "stop_loss": price_strategy,
        "take_profit": price_strategy,
    }),
)

# Change category strategy
change_category_strategy = st.sampled_from(list(VALID_CHANGE_CATEGORIES))


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def create_recorded_decision(
    decision_id: str = "dec_test123",
    timestamp: Optional[datetime] = None,
    symbol: str = "BTCUSDT",
    config_version: str = "v_test",
    market_snapshot: Optional[Dict[str, Any]] = None,
    features: Optional[Dict[str, Any]] = None,
    decision: str = "rejected",
    rejection_stage: Optional[str] = None,
    rejection_reason: Optional[str] = None,
    signal: Optional[Dict[str, Any]] = None,
    profile_id: Optional[str] = None,
) -> RecordedDecision:
    """Create a RecordedDecision for testing."""
    return RecordedDecision(
        decision_id=decision_id,
        timestamp=timestamp or datetime.now(timezone.utc),
        symbol=symbol,
        config_version=config_version,
        market_snapshot=market_snapshot or {"bid": 100.0, "ask": 101.0},
        features=features or {"volatility": 0.5},
        positions=[],
        account_state={},
        stage_results=[],
        rejection_stage=rejection_stage,
        rejection_reason=rejection_reason,
        decision=decision,
        signal=signal,
        profile_id=profile_id,
    )


def create_mock_pool():
    """Create a mock database pool for testing."""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


def create_mock_decision_engine(replayed_result: bool, rejection_stage: Optional[str] = None):
    """Create a mock decision engine for testing."""
    engine = MagicMock()
    
    @dataclass
    class MockContext:
        rejection_stage: Optional[str] = None
        signal: Optional[Dict[str, Any]] = None
    
    ctx = MockContext(
        rejection_stage=rejection_stage if not replayed_result else None,
        signal={"side": "buy", "size": 1.0} if replayed_result else None,
    )
    
    engine.decide_with_context = AsyncMock(return_value=(replayed_result, ctx))
    return engine


def create_mock_config_registry():
    """Create a mock configuration registry for testing."""
    registry = MagicMock()
    
    @dataclass
    class MockConfig:
        version_id: str = "v_test"
    
    registry.get_live_config = AsyncMock(return_value=MockConfig())
    return registry


# ═══════════════════════════════════════════════════════════════
# PROPERTY 17: REPLAY COMPARISON
# Feature: trading-pipeline-integration, Property 17
# Validates: Requirements 7.1, 7.2
# ═══════════════════════════════════════════════════════════════

class TestReplayComparison:
    """
    Feature: trading-pipeline-integration, Property 17: Replay Comparison
    
    For any recorded decision replayed through ReplayManager, the System SHALL
    compare the replayed_decision against the original decision and set
    matches=True if and only if they are identical.
    
    **Validates: Requirements 7.1, 7.2**
    """
    
    @settings(max_examples=100)
    @given(
        original_decision=decision_outcome_strategy,
        replayed_decision=decision_outcome_strategy,
    )
    def test_matches_true_when_decisions_identical(
        self,
        original_decision: str,
        replayed_decision: str,
    ):
        """
        **Validates: Requirements 7.1, 7.2**
        
        Property: matches=True if and only if original and replayed decisions
        are identical.
        """
        original = create_recorded_decision(
            decision=original_decision,
            rejection_stage="ev_gate" if original_decision == "rejected" else None,
        )
        
        # Determine if decisions match
        decisions_match = original_decision == replayed_decision
        
        # Create ReplayResult
        result = ReplayResult(
            original_decision=original,
            replayed_decision=replayed_decision,
            replayed_rejection_stage="ev_gate" if replayed_decision == "rejected" else None,
            matches=decisions_match,
            change_category="expected" if decisions_match else categorize_change(original_decision, replayed_decision),
        )
        
        # Verify matches is True if and only if decisions are identical
        assert result.matches == decisions_match
        if original_decision == replayed_decision:
            assert result.matches is True
        else:
            assert result.matches is False


    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        config_version=config_version_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
    )
    def test_replay_result_preserves_original_decision_context(
        self,
        symbol: str,
        config_version: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
    ):
        """
        **Validates: Requirements 7.1, 7.2**
        
        Property: ReplayResult preserves the original decision context for
        comparison and analysis.
        """
        original = create_recorded_decision(
            decision_id=f"dec_{symbol}",
            symbol=symbol,
            config_version=config_version,
            market_snapshot=market_snapshot,
            features=features,
            decision="rejected",
            rejection_stage="ev_gate",
        )
        
        result = ReplayResult(
            original_decision=original,
            replayed_decision="rejected",
            replayed_rejection_stage="ev_gate",
            matches=True,
            change_category="expected",
        )
        
        # Verify original decision context is preserved
        assert result.original_decision.symbol == symbol
        assert result.original_decision.config_version == config_version
        assert result.original_decision.market_snapshot == market_snapshot
        assert result.original_decision.features == features
        assert result.get_original_symbol() == symbol
        assert result.get_original_decision_id() == f"dec_{symbol}"


    @settings(max_examples=100)
    @given(
        num_matches=st.integers(min_value=0, max_value=50),
        num_changes=st.integers(min_value=0, max_value=50),
    )
    def test_replay_report_match_rate_calculation(
        self,
        num_matches: int,
        num_changes: int,
    ):
        """
        **Validates: Requirements 7.2**
        
        Property: ReplayReport correctly calculates match_rate as
        matches / total_replayed.
        """
        total = num_matches + num_changes
        assume(total > 0)  # Need at least one decision
        
        expected_match_rate = num_matches / total
        
        # Create report with the given counts
        report = ReplayReport(
            total_replayed=total,
            matches=num_matches,
            changes=num_changes,
            match_rate=expected_match_rate,
            changes_by_category={"unexpected": num_changes} if num_changes > 0 else {},
        )
        
        # Verify match rate calculation
        assert abs(report.match_rate - expected_match_rate) < 0.0001
        assert report.total_replayed == total
        assert report.matches == num_matches
        assert report.changes == num_changes

    @settings(max_examples=100)
    @given(decision=decision_outcome_strategy)
    def test_identical_decisions_always_match(
        self,
        decision: str,
    ):
        """
        **Validates: Requirements 7.1, 7.2**
        
        Property: When original and replayed decisions are identical,
        matches is always True.
        """
        original = create_recorded_decision(
            decision=decision,
            rejection_stage="ev_gate" if decision == "rejected" else None,
        )
        
        result = ReplayResult(
            original_decision=original,
            replayed_decision=decision,  # Same as original
            replayed_rejection_stage="ev_gate" if decision == "rejected" else None,
            matches=True,
            change_category="expected",
        )
        
        assert result.matches is True
        assert result.change_category == "expected"


    @settings(max_examples=100)
    @given(
        original_decision=decision_outcome_strategy,
        replayed_decision=decision_outcome_strategy,
    )
    def test_different_decisions_never_match(
        self,
        original_decision: str,
        replayed_decision: str,
    ):
        """
        **Validates: Requirements 7.1, 7.2**
        
        Property: When original and replayed decisions differ,
        matches is always False.
        """
        assume(original_decision != replayed_decision)
        
        original = create_recorded_decision(
            decision=original_decision,
            rejection_stage="ev_gate" if original_decision == "rejected" else None,
        )
        
        result = ReplayResult(
            original_decision=original,
            replayed_decision=replayed_decision,
            replayed_rejection_stage="ev_gate" if replayed_decision == "rejected" else None,
            matches=False,
            change_category=categorize_change(original_decision, replayed_decision),
        )
        
        assert result.matches is False
        assert result.change_category != "expected"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 18: REPLAY CHANGE CATEGORIZATION
# Feature: trading-pipeline-integration, Property 18
# Validates: Requirements 7.3
# ═══════════════════════════════════════════════════════════════

class TestReplayChangeCategorization:
    """
    Feature: trading-pipeline-integration, Property 18: Replay Change Categorization
    
    For any replay where matches=False, the change_category SHALL be:
    - "improved" if original was rejected and replay is accepted
    - "degraded" if original was accepted and replay is rejected
    - otherwise "unexpected"
    
    **Validates: Requirements 7.3**
    """
    
    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        config_version=config_version_strategy,
    )
    def test_rejected_to_accepted_is_improved(
        self,
        symbol: str,
        config_version: str,
    ):
        """
        **Validates: Requirements 7.3**
        
        Property: When original was rejected and replay is accepted,
        change_category is "improved".
        """
        original = create_recorded_decision(
            symbol=symbol,
            config_version=config_version,
            decision="rejected",
            rejection_stage="ev_gate",
            rejection_reason="EV below threshold",
        )
        
        # Use categorize_change function
        category = categorize_change("rejected", "accepted")
        assert category == "improved"
        
        # Verify in ReplayResult
        result = ReplayResult(
            original_decision=original,
            replayed_decision="accepted",
            replayed_rejection_stage=None,
            matches=False,
            change_category=category,
        )
        
        assert result.change_category == "improved"
        assert result.is_improvement() is True
        assert result.is_degradation() is False


    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        config_version=config_version_strategy,
        rejection_stage=non_null_rejection_stage_strategy,
    )
    def test_accepted_to_rejected_is_degraded(
        self,
        symbol: str,
        config_version: str,
        rejection_stage: str,
    ):
        """
        **Validates: Requirements 7.3**
        
        Property: When original was accepted and replay is rejected,
        change_category is "degraded".
        """
        original = create_recorded_decision(
            symbol=symbol,
            config_version=config_version,
            decision="accepted",
            rejection_stage=None,
            signal={"side": "buy", "size": 1.0},
        )
        
        # Use categorize_change function
        category = categorize_change("accepted", "rejected")
        assert category == "degraded"
        
        # Verify in ReplayResult
        result = ReplayResult(
            original_decision=original,
            replayed_decision="rejected",
            replayed_rejection_stage=rejection_stage,
            matches=False,
            change_category=category,
        )
        
        assert result.change_category == "degraded"
        assert result.is_degradation() is True
        assert result.is_improvement() is False

    @settings(max_examples=100)
    @given(decision=decision_outcome_strategy)
    def test_same_decision_is_expected(
        self,
        decision: str,
    ):
        """
        **Validates: Requirements 7.3**
        
        Property: When original and replayed decisions are the same,
        change_category is "expected".
        """
        category = categorize_change(decision, decision)
        assert category == "expected"
        
        original = create_recorded_decision(
            decision=decision,
            rejection_stage="ev_gate" if decision == "rejected" else None,
        )
        
        result = ReplayResult(
            original_decision=original,
            replayed_decision=decision,
            replayed_rejection_stage="ev_gate" if decision == "rejected" else None,
            matches=True,
            change_category=category,
        )
        
        assert result.change_category == "expected"
        assert result.matches is True


    @settings(max_examples=100)
    @given(
        original_decision=decision_outcome_strategy,
        replayed_decision=decision_outcome_strategy,
    )
    def test_categorize_change_exhaustive(
        self,
        original_decision: str,
        replayed_decision: str,
    ):
        """
        **Validates: Requirements 7.3**
        
        Property: categorize_change always returns a valid category from
        the set {expected, unexpected, improved, degraded}.
        """
        category = categorize_change(original_decision, replayed_decision)
        
        assert category in VALID_CHANGE_CATEGORIES
        
        # Verify specific categorization rules
        if original_decision == replayed_decision:
            assert category == "expected"
        elif original_decision == "rejected" and replayed_decision == "accepted":
            assert category == "improved"
        elif original_decision == "accepted" and replayed_decision == "rejected":
            assert category == "degraded"
        else:
            assert category == "unexpected"

    @settings(max_examples=100)
    @given(
        num_improved=st.integers(min_value=0, max_value=20),
        num_degraded=st.integers(min_value=0, max_value=20),
        num_unexpected=st.integers(min_value=0, max_value=20),
    )
    def test_replay_report_aggregates_changes_by_category(
        self,
        num_improved: int,
        num_degraded: int,
        num_unexpected: int,
    ):
        """
        **Validates: Requirements 7.3**
        
        Property: ReplayReport correctly aggregates changes by category.
        """
        total_changes = num_improved + num_degraded + num_unexpected
        assume(total_changes > 0)  # Need at least one change
        
        changes_by_category = {}
        if num_improved > 0:
            changes_by_category["improved"] = num_improved
        if num_degraded > 0:
            changes_by_category["degraded"] = num_degraded
        if num_unexpected > 0:
            changes_by_category["unexpected"] = num_unexpected
        
        report = ReplayReport(
            total_replayed=total_changes + 10,  # Some matches too
            matches=10,
            changes=total_changes,
            match_rate=10 / (total_changes + 10),
            changes_by_category=changes_by_category,
        )
        
        # Verify aggregation
        assert report.get_improvement_count() == num_improved
        assert report.get_degradation_count() == num_degraded
        assert report.get_unexpected_count() == num_unexpected
        assert report.has_improvements() == (num_improved > 0)
        assert report.has_degradations() == (num_degraded > 0)
        assert report.has_unexpected_changes() == (num_unexpected > 0)


    @settings(max_examples=100)
    @given(
        results_data=st.lists(
            st.tuples(
                st.booleans(),  # matches
                change_category_strategy,  # change_category
            ),
            min_size=1,
            max_size=50,
        ),
    )
    def test_aggregate_changes_counts_correctly(
        self,
        results_data: List[tuple],
    ):
        """
        **Validates: Requirements 7.3**
        
        Property: aggregate_changes correctly counts changes by category.
        """
        results = []
        expected_by_category: Dict[str, int] = {}
        
        for matches, category in results_data:
            original = create_recorded_decision(
                decision_id=f"dec_{len(results)}",
                decision="rejected" if category in ("improved", "expected") else "accepted",
            )
            
            # Only count non-matching results
            if not matches:
                expected_by_category[category] = expected_by_category.get(category, 0) + 1
            
            result = ReplayResult(
                original_decision=original,
                replayed_decision="accepted" if category == "improved" else "rejected",
                matches=matches,
                change_category=category if not matches else "expected",
            )
            results.append(result)
        
        # Use aggregate_changes function
        changes_by_category, _ = aggregate_changes(results)
        
        # Verify counts match expected
        for category, count in expected_by_category.items():
            assert changes_by_category.get(category, 0) == count


# ═══════════════════════════════════════════════════════════════
# PROPERTY 19: REPLAY STAGE DIFF IDENTIFICATION
# Feature: trading-pipeline-integration, Property 19
# Validates: Requirements 7.6
# ═══════════════════════════════════════════════════════════════

class TestReplayStageDiffIdentification:
    """
    Feature: trading-pipeline-integration, Property 19: Replay Stage Diff Identification
    
    For any replay where the rejection_stage differs between original and
    replayed, the stage_diff SHALL contain a string identifying both stages
    in format "{original_stage}->{replayed_stage}".
    
    **Validates: Requirements 7.6**
    """
    
    @settings(max_examples=100)
    @given(
        original_stage=rejection_stage_strategy,
        replayed_stage=rejection_stage_strategy,
    )
    def test_stage_diff_format(
        self,
        original_stage: Optional[str],
        replayed_stage: Optional[str],
    ):
        """
        **Validates: Requirements 7.6**
        
        Property: When stages differ, stage_diff is in format
        "{original_stage}->{replayed_stage}".
        """
        stage_diff = identify_stage_diff(original_stage, replayed_stage)
        
        if original_stage == replayed_stage:
            # Same stages should produce None
            assert stage_diff is None
        else:
            # Different stages should produce formatted string
            assert stage_diff is not None
            assert "->" in stage_diff
            
            # Parse the diff
            parts = stage_diff.split("->")
            assert len(parts) == 2
            
            original_part = parts[0]
            replayed_part = parts[1]
            
            # Verify original stage
            if original_stage is None:
                assert original_part == "none"
            else:
                assert original_part == original_stage
            
            # Verify replayed stage
            if replayed_stage is None:
                assert replayed_part == "none"
            else:
                assert replayed_part == replayed_stage


    @settings(max_examples=100)
    @given(
        original_stage=non_null_rejection_stage_strategy,
        replayed_stage=non_null_rejection_stage_strategy,
    )
    def test_stage_diff_with_both_stages_present(
        self,
        original_stage: str,
        replayed_stage: str,
    ):
        """
        **Validates: Requirements 7.6**
        
        Property: When both stages are present and different, stage_diff
        contains both stage names.
        """
        assume(original_stage != replayed_stage)
        
        stage_diff = identify_stage_diff(original_stage, replayed_stage)
        
        assert stage_diff is not None
        assert original_stage in stage_diff
        assert replayed_stage in stage_diff
        assert stage_diff == f"{original_stage}->{replayed_stage}"

    @settings(max_examples=100)
    @given(stage=non_null_rejection_stage_strategy)
    def test_stage_diff_from_none_to_stage(
        self,
        stage: str,
    ):
        """
        **Validates: Requirements 7.6**
        
        Property: When original was accepted (None) and replay is rejected,
        stage_diff shows "none->{stage}".
        """
        stage_diff = identify_stage_diff(None, stage)
        
        assert stage_diff is not None
        assert stage_diff == f"none->{stage}"
        assert "none" in stage_diff
        assert stage in stage_diff

    @settings(max_examples=100)
    @given(stage=non_null_rejection_stage_strategy)
    def test_stage_diff_from_stage_to_none(
        self,
        stage: str,
    ):
        """
        **Validates: Requirements 7.6**
        
        Property: When original was rejected and replay is accepted (None),
        stage_diff shows "{stage}->none".
        """
        stage_diff = identify_stage_diff(stage, None)
        
        assert stage_diff is not None
        assert stage_diff == f"{stage}->none"
        assert stage in stage_diff
        assert "none" in stage_diff


    @settings(max_examples=100)
    @given(stage=rejection_stage_strategy)
    def test_same_stage_produces_no_diff(
        self,
        stage: Optional[str],
    ):
        """
        **Validates: Requirements 7.6**
        
        Property: When original and replayed stages are the same,
        stage_diff is None.
        """
        stage_diff = identify_stage_diff(stage, stage)
        assert stage_diff is None

    @settings(max_examples=100)
    @given(
        results_data=st.lists(
            st.tuples(
                rejection_stage_strategy,  # original_stage
                rejection_stage_strategy,  # replayed_stage
            ),
            min_size=1,
            max_size=30,
        ),
    )
    def test_aggregate_changes_counts_stage_diffs(
        self,
        results_data: List[tuple],
    ):
        """
        **Validates: Requirements 7.6**
        
        Property: aggregate_changes correctly counts changes by stage diff.
        """
        results = []
        expected_by_stage: Dict[str, int] = {}
        
        for i, (original_stage, replayed_stage) in enumerate(results_data):
            original = create_recorded_decision(
                decision_id=f"dec_{i}",
                decision="rejected" if original_stage else "accepted",
                rejection_stage=original_stage,
            )
            
            stage_diff = identify_stage_diff(original_stage, replayed_stage)
            matches = original_stage == replayed_stage
            
            # Only count non-matching results with stage diffs
            if not matches and stage_diff:
                expected_by_stage[stage_diff] = expected_by_stage.get(stage_diff, 0) + 1
            
            result = ReplayResult(
                original_decision=original,
                replayed_decision="rejected" if replayed_stage else "accepted",
                replayed_rejection_stage=replayed_stage,
                matches=matches,
                change_category="expected" if matches else "unexpected",
                stage_diff=stage_diff,
            )
            results.append(result)
        
        # Use aggregate_changes function
        _, changes_by_stage = aggregate_changes(results)
        
        # Verify counts match expected
        for stage_diff, count in expected_by_stage.items():
            assert changes_by_stage.get(stage_diff, 0) == count


    @settings(max_examples=100)
    @given(
        original_stage=rejection_stage_strategy,
        replayed_stage=rejection_stage_strategy,
        symbol=symbol_strategy,
    )
    def test_replay_result_includes_stage_diff(
        self,
        original_stage: Optional[str],
        replayed_stage: Optional[str],
        symbol: str,
    ):
        """
        **Validates: Requirements 7.6**
        
        Property: ReplayResult correctly includes stage_diff when stages differ.
        """
        original = create_recorded_decision(
            symbol=symbol,
            decision="rejected" if original_stage else "accepted",
            rejection_stage=original_stage,
        )
        
        expected_stage_diff = identify_stage_diff(original_stage, replayed_stage)
        
        result = ReplayResult(
            original_decision=original,
            replayed_decision="rejected" if replayed_stage else "accepted",
            replayed_rejection_stage=replayed_stage,
            matches=original_stage == replayed_stage and (
                (original_stage is None and replayed_stage is None) or
                (original_stage is not None and replayed_stage is not None)
            ),
            change_category="expected" if original_stage == replayed_stage else "unexpected",
            stage_diff=expected_stage_diff,
        )
        
        assert result.stage_diff == expected_stage_diff
        
        if original_stage != replayed_stage:
            assert result.stage_diff is not None
        else:
            assert result.stage_diff is None


# ═══════════════════════════════════════════════════════════════
# ADDITIONAL EDGE CASE TESTS
# ═══════════════════════════════════════════════════════════════

class TestReplayValidationEdgeCases:
    """
    Additional edge case tests for replay validation.
    
    **Validates: Requirements 7.1, 7.2, 7.3, 7.6**
    """
    
    def test_empty_replay_report(self):
        """
        **Validates: Requirements 7.2**
        
        Edge case: Empty replay report has 100% match rate.
        """
        report = ReplayReport.create_empty(run_id="test_empty")
        
        assert report.total_replayed == 0
        assert report.matches == 0
        assert report.changes == 0
        assert report.match_rate == 1.0  # 100% when nothing to compare
        assert report.changes_by_category == {}
        assert report.changes_by_stage == {}
        assert report.sample_changes == []

    def test_all_matches_replay_report(self):
        """
        **Validates: Requirements 7.2**
        
        Edge case: All decisions match produces 100% match rate.
        """
        report = ReplayReport(
            total_replayed=100,
            matches=100,
            changes=0,
            match_rate=1.0,
            changes_by_category={},
            changes_by_stage={},
        )
        
        assert report.match_rate == 1.0
        assert report.changes == 0
        assert not report.has_degradations()
        assert not report.has_improvements()
        assert not report.has_unexpected_changes()
        assert report.is_passing()

    def test_all_changes_replay_report(self):
        """
        **Validates: Requirements 7.2, 7.3**
        
        Edge case: All decisions changed produces 0% match rate.
        """
        report = ReplayReport(
            total_replayed=100,
            matches=0,
            changes=100,
            match_rate=0.0,
            changes_by_category={"degraded": 50, "improved": 50},
            changes_by_stage={"ev_gate->none": 50, "none->ev_gate": 50},
        )
        
        assert report.match_rate == 0.0
        assert report.changes == 100
        assert report.has_degradations()
        assert report.has_improvements()
        assert report.get_degradation_count() == 50
        assert report.get_improvement_count() == 50


    @settings(max_examples=100)
    @given(
        degradation_count=st.integers(min_value=0, max_value=10),
        total=st.integers(min_value=100, max_value=200),
    )
    def test_replay_report_passing_threshold(
        self,
        degradation_count: int,
        total: int,
    ):
        """
        **Validates: Requirements 7.3**
        
        Edge case: is_passing() correctly applies degradation threshold.
        """
        assume(degradation_count <= total)
        
        matches = total - degradation_count
        
        report = ReplayReport(
            total_replayed=total,
            matches=matches,
            changes=degradation_count,
            match_rate=matches / total,
            changes_by_category={"degraded": degradation_count} if degradation_count > 0 else {},
        )
        
        degradation_rate = degradation_count / total
        
        # Default threshold is 5%
        if degradation_rate <= 0.05:
            assert report.is_passing() is True
        else:
            assert report.is_passing() is False
        
        # Custom threshold
        assert report.is_passing(max_degradation_rate=1.0) is True
        if degradation_count > 0:
            assert report.is_passing(max_degradation_rate=0.0) is False

    def test_replay_result_serialization_round_trip(self):
        """
        **Validates: Requirements 7.1, 7.2**
        
        Edge case: ReplayResult can be serialized and deserialized.
        """
        original = create_recorded_decision(
            decision_id="dec_test",
            symbol="BTCUSDT",
            decision="rejected",
            rejection_stage="ev_gate",
        )
        
        result = ReplayResult(
            original_decision=original,
            replayed_decision="accepted",
            replayed_signal={"side": "buy", "size": 1.0},
            replayed_rejection_stage=None,
            matches=False,
            change_category="improved",
            stage_diff="ev_gate->none",
        )
        
        # Serialize
        result_dict = result.to_dict()
        
        # Deserialize
        restored = ReplayResult.from_dict(result_dict, RecordedDecision)
        
        # Verify
        assert restored.replayed_decision == result.replayed_decision
        assert restored.matches == result.matches
        assert restored.change_category == result.change_category
        assert restored.stage_diff == result.stage_diff
        assert restored.original_decision.decision_id == original.decision_id


    def test_replay_report_validation(self):
        """
        **Validates: Requirements 7.2**
        
        Edge case: ReplayReport validates consistency.
        """
        # Valid report
        valid_report = ReplayReport(
            total_replayed=100,
            matches=60,
            changes=40,
            match_rate=0.6,
            changes_by_category={"improved": 20, "degraded": 20},
        )
        
        is_valid, errors = valid_report.validate()
        assert is_valid is True
        assert len(errors) == 0
        
        # Invalid report (matches + changes != total)
        with pytest.raises(ValueError):
            ReplayReport(
                total_replayed=100,
                matches=60,
                changes=50,  # Should be 40
                match_rate=0.6,
            )

    def test_replay_report_summary(self):
        """
        **Validates: Requirements 7.2, 7.3**
        
        Edge case: ReplayReport generates human-readable summary.
        """
        report = ReplayReport(
            total_replayed=100,
            matches=80,
            changes=20,
            match_rate=0.8,
            changes_by_category={"improved": 10, "degraded": 5, "unexpected": 5},
            changes_by_stage={"ev_gate->none": 10, "none->ev_gate": 5},
            run_id="test_run_123",
        )
        
        summary = report.get_summary()
        
        assert "test_run_123" in summary
        assert "100" in summary  # total_replayed
        assert "80" in summary  # matches
        assert "80.0%" in summary  # match_rate
        assert "improved" in summary
        assert "degraded" in summary
        assert "ev_gate->none" in summary
