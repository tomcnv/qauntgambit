"""
Property-based tests for Decision Recording.

Feature: trading-pipeline-integration

These tests verify the correctness properties of the decision recording system,
ensuring complete decision context is captured and queries return correct results.

Uses hypothesis library with minimum 100 iterations per property test.

**Validates: Requirements 2.1, 2.3, 2.4, 2.5**
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from quantgambit.integration.decision_recording import (
    RecordedDecision,
    DecisionRecorder,
)
from quantgambit.integration.config_version import ConfigVersion


# ═══════════════════════════════════════════════════════════════
# STRATEGIES FOR PROPERTY-BASED TESTING
# ═══════════════════════════════════════════════════════════════

# Symbol strategy
symbol_strategy = st.sampled_from([
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "MATICUSDT", "DOTUSDT", "AVAXUSDT",
])

# Decision outcome strategy
decision_outcome_strategy = st.sampled_from(["accepted", "rejected", "shadow"])

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

# Rejection reason strategy
rejection_reason_strategy = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=100),
)

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

# Position strategy
position_strategy = st.fixed_dictionaries({
    "symbol": symbol_strategy,
    "side": st.sampled_from(["long", "short"]),
    "size": size_strategy,
    "entry_price": price_strategy,
    "unrealized_pnl": st.floats(min_value=-10000.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
})

# Positions list strategy
positions_strategy = st.lists(position_strategy, min_size=0, max_size=5)

# Account state strategy
account_state_strategy = st.fixed_dictionaries({
    "equity": st.floats(min_value=1000.0, max_value=1000000.0, allow_nan=False, allow_infinity=False),
    "available_margin": st.floats(min_value=0.0, max_value=1000000.0, allow_nan=False, allow_infinity=False),
    "used_margin": st.floats(min_value=0.0, max_value=500000.0, allow_nan=False, allow_infinity=False),
})

# Stage result strategy
stage_result_strategy = st.fixed_dictionaries({
    "stage": st.sampled_from([
        "data_readiness", "ev_gate", "execution_feasibility",
        "confirmation", "arbitration", "vol_shock_gate",
    ]),
    "passed": st.booleans(),
    "score": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "reason": st.one_of(st.none(), st.text(min_size=1, max_size=50)),
})

# Stage results list strategy
stage_results_strategy = st.lists(stage_result_strategy, min_size=0, max_size=6)

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


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def create_mock_pool():
    """Create a mock database pool for testing."""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


def create_mock_config_registry(config_version: str = "test_v1"):
    """Create a mock ConfigurationRegistry for testing."""
    registry = MagicMock()
    config = ConfigVersion.create(
        version_id=config_version,
        created_by="live",
        parameters={"test_param": 1.0},
    )
    registry.get_live_config = AsyncMock(return_value=config)
    return registry


@dataclass
class MockStageContext:
    """Mock stage context for testing."""
    data: Dict[str, Any]
    rejection_stage: Optional[str] = None
    rejection_reason: Optional[str] = None
    signal: Optional[Dict[str, Any]] = None
    profile_id: Optional[str] = None
    stage_trace: Optional[List[Dict[str, Any]]] = None


# ═══════════════════════════════════════════════════════════════
# PROPERTY 5: DECISION RECORDING COMPLETENESS
# Feature: trading-pipeline-integration, Property 5
# Validates: Requirements 2.1, 2.3, 2.5
# ═══════════════════════════════════════════════════════════════

class TestDecisionRecordingCompleteness:
    """
    Feature: trading-pipeline-integration, Property 5: Decision Recording Completeness
    
    For any live trading decision recorded by DecisionRecorder, the record SHALL
    contain: market_snapshot, features, positions, account_state, stage_results,
    rejection_stage (if rejected), rejection_reason (if rejected), decision outcome,
    signal (if accepted), and config_version.
    
    **Validates: Requirements 2.1, 2.3, 2.5**
    """
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        symbol=symbol_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        positions=positions_strategy,
        account_state=account_state_strategy,
        stage_results=stage_results_strategy,
        decision=decision_outcome_strategy,
        signal=signal_strategy,
        profile_id=profile_id_strategy,
        config_version=config_version_strategy,
    )
    @pytest.mark.asyncio
    async def test_recorded_decision_contains_all_required_fields(
        self,
        symbol: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        stage_results: List[Dict[str, Any]],
        decision: str,
        signal: Optional[Dict[str, Any]],
        profile_id: Optional[str],
        config_version: str,
    ):
        """
        **Validates: Requirements 2.1, 2.3, 2.5**
        
        Property: For any decision recorded, all required fields are present
        in the RecordedDecision.
        """
        pool, conn = create_mock_pool()
        registry = create_mock_config_registry(config_version)
        
        # Create stage context
        ctx = MockStageContext(
            data={"positions": positions, "account": account_state},
            rejection_stage="ev_gate" if decision == "rejected" else None,
            rejection_reason="EV below threshold" if decision == "rejected" else None,
            signal=signal if decision == "accepted" else None,
            profile_id=profile_id,
            stage_trace=stage_results,
        )
        
        recorder = DecisionRecorder(pool, registry)
        
        # Record the decision
        decision_id = await recorder.record(
            symbol=symbol,
            snapshot=market_snapshot,
            features=features,
            ctx=ctx,
            decision=decision,
        )
        
        # Get the recorded decision from the batch
        assert len(recorder._batch) == 1
        recorded = recorder._batch[0]
        
        # Verify all required fields are present
        assert recorded.decision_id == decision_id
        assert recorded.symbol == symbol
        assert recorded.config_version == config_version
        assert recorded.market_snapshot == market_snapshot
        assert recorded.features == features
        assert recorded.positions == positions
        assert recorded.account_state == account_state
        assert recorded.stage_results == stage_results
        assert recorded.decision == decision
        
        # Verify rejection fields for rejected decisions
        if decision == "rejected":
            assert recorded.rejection_stage is not None
            assert recorded.rejection_reason is not None
        
        # Verify signal for accepted decisions
        if decision == "accepted" and signal is not None:
            assert recorded.signal == signal

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        symbol=symbol_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        config_version=config_version_strategy,
    )
    @pytest.mark.asyncio
    async def test_recorded_decision_has_config_version(
        self,
        symbol: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        config_version: str,
    ):
        """
        **Validates: Requirements 2.5**
        
        Property: Every recorded decision includes the config_version used
        for that decision.
        """
        pool, conn = create_mock_pool()
        registry = create_mock_config_registry(config_version)
        
        ctx = MockStageContext(
            data={"positions": [], "account": {}},
            stage_trace=[],
        )
        
        recorder = DecisionRecorder(pool, registry)
        
        await recorder.record(
            symbol=symbol,
            snapshot=market_snapshot,
            features=features,
            ctx=ctx,
            decision="rejected",
        )
        
        recorded = recorder._batch[0]
        assert recorded.config_version == config_version
        assert recorded.config_version is not None
        assert len(recorded.config_version) > 0

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        symbol=symbol_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        stage_results=stage_results_strategy,
    )
    @pytest.mark.asyncio
    async def test_recorded_decision_includes_all_stage_results(
        self,
        symbol: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        stage_results: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 2.3**
        
        Property: Every recorded decision includes all pipeline stage outputs.
        """
        pool, conn = create_mock_pool()
        registry = create_mock_config_registry()
        
        ctx = MockStageContext(
            data={"positions": [], "account": {}},
            stage_trace=stage_results,
        )
        
        recorder = DecisionRecorder(pool, registry)
        
        await recorder.record(
            symbol=symbol,
            snapshot=market_snapshot,
            features=features,
            ctx=ctx,
            decision="rejected",
        )
        
        recorded = recorder._batch[0]
        assert recorded.stage_results == stage_results
        assert len(recorded.stage_results) == len(stage_results)

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        symbol=symbol_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        rejection_stage=st.sampled_from([
            "data_readiness", "ev_gate", "execution_feasibility",
            "confirmation", "arbitration", "vol_shock_gate",
        ]),
        rejection_reason=st.text(min_size=1, max_size=100),
    )
    @pytest.mark.asyncio
    async def test_rejected_decision_includes_rejection_details(
        self,
        symbol: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        rejection_stage: str,
        rejection_reason: str,
    ):
        """
        **Validates: Requirements 2.3**
        
        Property: For rejected decisions, rejection_stage and rejection_reason
        are recorded.
        """
        pool, conn = create_mock_pool()
        registry = create_mock_config_registry()
        
        ctx = MockStageContext(
            data={"positions": [], "account": {}},
            rejection_stage=rejection_stage,
            rejection_reason=rejection_reason,
            stage_trace=[],
        )
        
        recorder = DecisionRecorder(pool, registry)
        
        await recorder.record(
            symbol=symbol,
            snapshot=market_snapshot,
            features=features,
            ctx=ctx,
            decision="rejected",
        )
        
        recorded = recorder._batch[0]
        assert recorded.rejection_stage == rejection_stage
        assert recorded.rejection_reason == rejection_reason

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        symbol=symbol_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        signal=st.fixed_dictionaries({
            "side": st.sampled_from(["buy", "sell"]),
            "size": size_strategy,
            "entry_price": price_strategy,
        }),
    )
    @pytest.mark.asyncio
    async def test_accepted_decision_includes_signal(
        self,
        symbol: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        signal: Dict[str, Any],
    ):
        """
        **Validates: Requirements 2.1**
        
        Property: For accepted decisions, the signal is recorded.
        """
        pool, conn = create_mock_pool()
        registry = create_mock_config_registry()
        
        ctx = MockStageContext(
            data={"positions": [], "account": {}},
            signal=signal,
            stage_trace=[],
        )
        
        recorder = DecisionRecorder(pool, registry)
        
        await recorder.record(
            symbol=symbol,
            snapshot=market_snapshot,
            features=features,
            ctx=ctx,
            decision="accepted",
        )
        
        recorded = recorder._batch[0]
        assert recorded.signal == signal
        assert recorded.decision == "accepted"

    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        positions=positions_strategy,
        account_state=account_state_strategy,
    )
    def test_recorded_decision_serialization_round_trip(
        self,
        symbol: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
    ):
        """
        **Validates: Requirements 2.1**
        
        Property: RecordedDecision can be serialized to dict and back
        without losing any data.
        """
        decision = RecordedDecision(
            decision_id="dec_test123",
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            config_version="v_test",
            market_snapshot=market_snapshot,
            features=features,
            positions=positions,
            account_state=account_state,
            stage_results=[{"stage": "ev_gate", "passed": True}],
            rejection_stage=None,
            rejection_reason=None,
            decision="accepted",
            signal={"side": "buy", "size": 1.0},
            profile_id="aggressive",
        )
        
        # Serialize to dict
        decision_dict = decision.to_dict()
        
        # Deserialize back
        restored = RecordedDecision.from_dict(decision_dict)
        
        # Verify all fields match
        assert restored.decision_id == decision.decision_id
        assert restored.symbol == decision.symbol
        assert restored.config_version == decision.config_version
        assert restored.market_snapshot == decision.market_snapshot
        assert restored.features == decision.features
        assert restored.positions == decision.positions
        assert restored.account_state == decision.account_state
        assert restored.stage_results == decision.stage_results
        assert restored.rejection_stage == decision.rejection_stage
        assert restored.rejection_reason == decision.rejection_reason
        assert restored.decision == decision.decision
        assert restored.signal == decision.signal
        assert restored.profile_id == decision.profile_id

    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        decision=decision_outcome_strategy,
    )
    def test_recorded_decision_has_complete_context_check(
        self,
        symbol: str,
        decision: str,
    ):
        """
        **Validates: Requirements 2.1**
        
        Property: has_complete_context() returns True only when market_snapshot,
        features, and config_version are all present.
        """
        # Decision with complete context
        complete_decision = RecordedDecision(
            decision_id="dec_test123",
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            config_version="v_test",
            market_snapshot={"bid": 100.0, "ask": 101.0},
            features={"volatility": 0.5},
            decision=decision,
        )
        assert complete_decision.has_complete_context() is True
        
        # Decision without market_snapshot
        no_snapshot = RecordedDecision(
            decision_id="dec_test124",
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            config_version="v_test",
            market_snapshot={},  # Empty
            features={"volatility": 0.5},
            decision=decision,
        )
        assert no_snapshot.has_complete_context() is False
        
        # Decision without features
        no_features = RecordedDecision(
            decision_id="dec_test125",
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            config_version="v_test",
            market_snapshot={"bid": 100.0},
            features={},  # Empty
            decision=decision,
        )
        assert no_features.has_complete_context() is False


# ═══════════════════════════════════════════════════════════════
# PROPERTY 6: DECISION QUERY FILTERING
# Feature: trading-pipeline-integration, Property 6
# Validates: Requirements 2.4
# ═══════════════════════════════════════════════════════════════

class TestDecisionQueryFiltering:
    """
    Feature: trading-pipeline-integration, Property 6: Decision Query Filtering
    
    For any query to recorded_decisions with filters (time_range, symbol,
    decision_outcome, rejection_stage), the returned results SHALL contain
    only records matching all specified filter criteria.
    
    **Validates: Requirements 2.4**
    """
    
    @settings(max_examples=100)
    @given(
        symbols=st.lists(symbol_strategy, min_size=2, max_size=5, unique=True),
        target_symbol=symbol_strategy,
    )
    @pytest.mark.asyncio
    async def test_query_filters_by_symbol(
        self,
        symbols: List[str],
        target_symbol: str,
    ):
        """
        **Validates: Requirements 2.4**
        
        Property: When querying with a symbol filter, only decisions for that
        symbol are returned.
        """
        # Create mock decisions with different symbols
        decisions = []
        base_time = datetime.now(timezone.utc)
        
        for i, symbol in enumerate(symbols):
            decisions.append(RecordedDecision(
                decision_id=f"dec_{i}",
                timestamp=base_time - timedelta(minutes=i),
                symbol=symbol,
                config_version="v_test",
                market_snapshot={"bid": 100.0},
                features={"vol": 0.5},
                decision="rejected",
            ))
        
        # Add some decisions for target symbol
        target_decisions = []
        for i in range(3):
            dec = RecordedDecision(
                decision_id=f"dec_target_{i}",
                timestamp=base_time - timedelta(minutes=len(symbols) + i),
                symbol=target_symbol,
                config_version="v_test",
                market_snapshot={"bid": 100.0},
                features={"vol": 0.5},
                decision="rejected",
            )
            decisions.append(dec)
            target_decisions.append(dec)
        
        # Create mock pool that returns filtered results
        pool, conn = create_mock_pool()
        
        # Mock the fetch to return only target symbol decisions
        async def mock_fetch(query, *params):
            # Simulate database filtering
            results = []
            for dec in decisions:
                # Check time range
                if dec.timestamp < params[0] or dec.timestamp > params[1]:
                    continue
                # Check symbol filter if present
                if len(params) > 2 and dec.symbol != params[2]:
                    continue
                results.append(self._decision_to_row(dec))
            return results
        
        conn.fetch = mock_fetch
        
        registry = create_mock_config_registry()
        recorder = DecisionRecorder(pool, registry)
        
        # Query with symbol filter
        start_time = base_time - timedelta(hours=1)
        end_time = base_time + timedelta(hours=1)
        
        results = await recorder.query_by_time_range(
            start_time=start_time,
            end_time=end_time,
            symbol=target_symbol,
        )
        
        # Verify all results match the target symbol
        for result in results:
            assert result.symbol == target_symbol
    
    def _decision_to_row(self, dec: RecordedDecision) -> dict:
        """Convert RecordedDecision to mock database row."""
        return {
            "decision_id": dec.decision_id,
            "timestamp": dec.timestamp,
            "symbol": dec.symbol,
            "config_version": dec.config_version,
            "market_snapshot": dec.market_snapshot,
            "features": dec.features,
            "positions": dec.positions,
            "account_state": dec.account_state,
            "stage_results": dec.stage_results,
            "rejection_stage": dec.rejection_stage,
            "rejection_reason": dec.rejection_reason,
            "decision": dec.decision,
            "signal": dec.signal,
            "profile_id": dec.profile_id,
        }

    @settings(max_examples=100)
    @given(
        decisions_data=st.lists(
            st.tuples(
                decision_outcome_strategy,
                st.integers(min_value=0, max_value=60),  # minutes offset
            ),
            min_size=5,
            max_size=20,
        ),
        target_decision=decision_outcome_strategy,
    )
    @pytest.mark.asyncio
    async def test_query_filters_by_decision_outcome(
        self,
        decisions_data: List[tuple],
        target_decision: str,
    ):
        """
        **Validates: Requirements 2.4**
        
        Property: When querying with a decision outcome filter, only decisions
        with that outcome are returned.
        """
        base_time = datetime.now(timezone.utc)
        decisions = []
        
        for i, (decision_outcome, minutes_offset) in enumerate(decisions_data):
            decisions.append(RecordedDecision(
                decision_id=f"dec_{i}",
                timestamp=base_time - timedelta(minutes=minutes_offset),
                symbol="BTCUSDT",
                config_version="v_test",
                market_snapshot={"bid": 100.0},
                features={"vol": 0.5},
                decision=decision_outcome,
            ))
        
        # Create mock pool
        pool, conn = create_mock_pool()
        
        async def mock_fetch(query, *params):
            results = []
            for dec in decisions:
                if dec.timestamp < params[0] or dec.timestamp > params[1]:
                    continue
                # Check decision filter
                if "decision" in query and len(params) > 2:
                    if dec.decision != params[2]:
                        continue
                results.append(self._decision_to_row(dec))
            return results
        
        conn.fetch = mock_fetch
        
        registry = create_mock_config_registry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = base_time - timedelta(hours=2)
        end_time = base_time + timedelta(hours=1)
        
        results = await recorder.query_by_time_range(
            start_time=start_time,
            end_time=end_time,
            decision=target_decision,
        )
        
        # Verify all results match the target decision outcome
        for result in results:
            assert result.decision == target_decision

    @settings(max_examples=100)
    @given(
        decisions_data=st.lists(
            st.tuples(
                rejection_stage_strategy,
                st.integers(min_value=0, max_value=60),
            ),
            min_size=5,
            max_size=20,
        ),
        target_stage=st.sampled_from([
            "data_readiness", "ev_gate", "execution_feasibility",
            "confirmation", "arbitration",
        ]),
    )
    @pytest.mark.asyncio
    async def test_query_filters_by_rejection_stage(
        self,
        decisions_data: List[tuple],
        target_stage: str,
    ):
        """
        **Validates: Requirements 2.4**
        
        Property: When querying with a rejection_stage filter, only decisions
        rejected at that stage are returned.
        """
        base_time = datetime.now(timezone.utc)
        decisions = []
        
        for i, (rejection_stage, minutes_offset) in enumerate(decisions_data):
            decisions.append(RecordedDecision(
                decision_id=f"dec_{i}",
                timestamp=base_time - timedelta(minutes=minutes_offset),
                symbol="BTCUSDT",
                config_version="v_test",
                market_snapshot={"bid": 100.0},
                features={"vol": 0.5},
                decision="rejected" if rejection_stage else "accepted",
                rejection_stage=rejection_stage,
            ))
        
        pool, conn = create_mock_pool()
        
        async def mock_fetch(query, *params):
            results = []
            for dec in decisions:
                if dec.timestamp < params[0] or dec.timestamp > params[1]:
                    continue
                # Check rejection_stage filter
                if "rejection_stage" in query:
                    stage_param_idx = query.count("$") - 1  # Last param before LIMIT
                    if len(params) > 2 and dec.rejection_stage != params[2]:
                        continue
                results.append(self._decision_to_row(dec))
            return results
        
        conn.fetch = mock_fetch
        
        registry = create_mock_config_registry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = base_time - timedelta(hours=2)
        end_time = base_time + timedelta(hours=1)
        
        results = await recorder.query_by_time_range(
            start_time=start_time,
            end_time=end_time,
            rejection_stage=target_stage,
        )
        
        # Verify all results match the target rejection stage
        for result in results:
            assert result.rejection_stage == target_stage

    @settings(max_examples=100)
    @given(
        num_decisions=st.integers(min_value=10, max_value=50),
        window_start_offset=st.integers(min_value=30, max_value=60),
        window_end_offset=st.integers(min_value=0, max_value=20),
    )
    @pytest.mark.asyncio
    async def test_query_filters_by_time_range(
        self,
        num_decisions: int,
        window_start_offset: int,
        window_end_offset: int,
    ):
        """
        **Validates: Requirements 2.4**
        
        Property: When querying with a time range, only decisions within that
        range are returned.
        """
        base_time = datetime.now(timezone.utc)
        decisions = []
        
        # Create decisions spread over time
        for i in range(num_decisions):
            decisions.append(RecordedDecision(
                decision_id=f"dec_{i}",
                timestamp=base_time - timedelta(minutes=i * 2),
                symbol="BTCUSDT",
                config_version="v_test",
                market_snapshot={"bid": 100.0},
                features={"vol": 0.5},
                decision="rejected",
            ))
        
        pool, conn = create_mock_pool()
        
        start_time = base_time - timedelta(minutes=window_start_offset)
        end_time = base_time - timedelta(minutes=window_end_offset)
        
        async def mock_fetch(query, *params):
            results = []
            query_start = params[0]
            query_end = params[1]
            for dec in decisions:
                if dec.timestamp >= query_start and dec.timestamp <= query_end:
                    results.append(self._decision_to_row(dec))
            return results
        
        conn.fetch = mock_fetch
        
        registry = create_mock_config_registry()
        recorder = DecisionRecorder(pool, registry)
        
        results = await recorder.query_by_time_range(
            start_time=start_time,
            end_time=end_time,
        )
        
        # Verify all results are within the time range
        for result in results:
            assert result.timestamp >= start_time
            assert result.timestamp <= end_time

    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        decision=decision_outcome_strategy,
        rejection_stage=st.sampled_from([
            "data_readiness", "ev_gate", "execution_feasibility",
        ]),
    )
    @pytest.mark.asyncio
    async def test_query_with_multiple_filters(
        self,
        symbol: str,
        decision: str,
        rejection_stage: str,
    ):
        """
        **Validates: Requirements 2.4**
        
        Property: When querying with multiple filters, only decisions matching
        ALL filter criteria are returned.
        """
        base_time = datetime.now(timezone.utc)
        
        # Create a mix of decisions
        decisions = [
            # Matches all filters
            RecordedDecision(
                decision_id="dec_match",
                timestamp=base_time - timedelta(minutes=5),
                symbol=symbol,
                config_version="v_test",
                market_snapshot={"bid": 100.0},
                features={"vol": 0.5},
                decision=decision,
                rejection_stage=rejection_stage if decision == "rejected" else None,
            ),
            # Wrong symbol
            RecordedDecision(
                decision_id="dec_wrong_symbol",
                timestamp=base_time - timedelta(minutes=10),
                symbol="DIFFERENT",
                config_version="v_test",
                market_snapshot={"bid": 100.0},
                features={"vol": 0.5},
                decision=decision,
                rejection_stage=rejection_stage if decision == "rejected" else None,
            ),
            # Wrong decision
            RecordedDecision(
                decision_id="dec_wrong_decision",
                timestamp=base_time - timedelta(minutes=15),
                symbol=symbol,
                config_version="v_test",
                market_snapshot={"bid": 100.0},
                features={"vol": 0.5},
                decision="shadow" if decision != "shadow" else "accepted",
            ),
        ]
        
        pool, conn = create_mock_pool()
        
        async def mock_fetch(query, *params):
            results = []
            for dec in decisions:
                # Check time range
                if dec.timestamp < params[0] or dec.timestamp > params[1]:
                    continue
                # Check all filters
                param_idx = 2
                if "symbol" in query:
                    if dec.symbol != params[param_idx]:
                        continue
                    param_idx += 1
                if "decision" in query and "decision =" in query:
                    if dec.decision != params[param_idx]:
                        continue
                    param_idx += 1
                if "rejection_stage" in query:
                    if dec.rejection_stage != params[param_idx]:
                        continue
                results.append(self._decision_to_row(dec))
            return results
        
        conn.fetch = mock_fetch
        
        registry = create_mock_config_registry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = base_time - timedelta(hours=1)
        end_time = base_time + timedelta(hours=1)
        
        # Query with all filters (only for rejected decisions with rejection_stage)
        if decision == "rejected":
            results = await recorder.query_by_time_range(
                start_time=start_time,
                end_time=end_time,
                symbol=symbol,
                decision=decision,
                rejection_stage=rejection_stage,
            )
            
            # Verify all results match ALL criteria
            for result in results:
                assert result.symbol == symbol
                assert result.decision == decision
                assert result.rejection_stage == rejection_stage
        else:
            # For non-rejected, just test symbol and decision filters
            results = await recorder.query_by_time_range(
                start_time=start_time,
                end_time=end_time,
                symbol=symbol,
                decision=decision,
            )
            
            for result in results:
                assert result.symbol == symbol
                assert result.decision == decision

    @settings(max_examples=100)
    @given(
        num_decisions=st.integers(min_value=5, max_value=30),
        limit=st.integers(min_value=1, max_value=20),
    )
    @pytest.mark.asyncio
    async def test_query_respects_limit(
        self,
        num_decisions: int,
        limit: int,
    ):
        """
        **Validates: Requirements 2.4**
        
        Property: Query results respect the limit parameter.
        """
        base_time = datetime.now(timezone.utc)
        decisions = []
        
        for i in range(num_decisions):
            decisions.append(RecordedDecision(
                decision_id=f"dec_{i}",
                timestamp=base_time - timedelta(minutes=i),
                symbol="BTCUSDT",
                config_version="v_test",
                market_snapshot={"bid": 100.0},
                features={"vol": 0.5},
                decision="rejected",
            ))
        
        pool, conn = create_mock_pool()
        
        async def mock_fetch(query, *params):
            # Get limit from last param
            query_limit = params[-1]
            results = []
            for dec in sorted(decisions, key=lambda d: d.timestamp, reverse=True):
                if dec.timestamp >= params[0] and dec.timestamp <= params[1]:
                    results.append(self._decision_to_row(dec))
                    if len(results) >= query_limit:
                        break
            return results
        
        conn.fetch = mock_fetch
        
        registry = create_mock_config_registry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = base_time - timedelta(hours=1)
        end_time = base_time + timedelta(hours=1)
        
        results = await recorder.query_by_time_range(
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        # Verify limit is respected
        assert len(results) <= limit

    @settings(max_examples=100)
    @given(decision=st.sampled_from(["invalid", "ACCEPTED", "Rejected", "test"]))
    @pytest.mark.asyncio
    async def test_query_rejects_invalid_decision_filter(
        self,
        decision: str,
    ):
        """
        **Validates: Requirements 2.4**
        
        Property: Query raises ValueError for invalid decision filter values.
        """
        pool, conn = create_mock_pool()
        registry = create_mock_config_registry()
        recorder = DecisionRecorder(pool, registry)
        
        base_time = datetime.now(timezone.utc)
        
        with pytest.raises(ValueError) as exc_info:
            await recorder.query_by_time_range(
                start_time=base_time - timedelta(hours=1),
                end_time=base_time,
                decision=decision,
            )
        
        assert "accepted" in str(exc_info.value).lower() or "rejected" in str(exc_info.value).lower()

    @settings(max_examples=100)
    @given(
        num_decisions=st.integers(min_value=0, max_value=20),
    )
    @pytest.mark.asyncio
    async def test_query_returns_empty_for_no_matches(
        self,
        num_decisions: int,
    ):
        """
        **Validates: Requirements 2.4**
        
        Property: Query returns empty list when no decisions match filters.
        """
        base_time = datetime.now(timezone.utc)
        decisions = []
        
        # Create decisions with one symbol
        for i in range(num_decisions):
            decisions.append(RecordedDecision(
                decision_id=f"dec_{i}",
                timestamp=base_time - timedelta(minutes=i),
                symbol="BTCUSDT",
                config_version="v_test",
                market_snapshot={"bid": 100.0},
                features={"vol": 0.5},
                decision="rejected",
            ))
        
        pool, conn = create_mock_pool()
        
        async def mock_fetch(query, *params):
            results = []
            for dec in decisions:
                if dec.timestamp < params[0] or dec.timestamp > params[1]:
                    continue
                # Check symbol filter
                if "symbol" in query and len(params) > 2:
                    if dec.symbol != params[2]:
                        continue
                results.append(self._decision_to_row(dec))
            return results
        
        conn.fetch = mock_fetch
        
        registry = create_mock_config_registry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = base_time - timedelta(hours=1)
        end_time = base_time + timedelta(hours=1)
        
        # Query for a symbol that doesn't exist
        results = await recorder.query_by_time_range(
            start_time=start_time,
            end_time=end_time,
            symbol="NONEXISTENT",
        )
        
        assert len(results) == 0
