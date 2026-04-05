"""
Property-based tests for Decision Recording Completeness.

Feature: bot-integration-fixes
Tests correctness properties for:
- Property 1: Decision Recording Completeness

**Validates: Requirements 2.1, 2.2**

For any decision made by DecisionEngine when a DecisionRecorder is available,
the decision SHALL be recorded with complete context including symbol, market
snapshot, features, stage context, and decision outcome.
"""

import pytest
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, call

from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput
from quantgambit.signals.pipeline import StageContext, StageResult, Stage, Orchestrator


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Symbols - common trading pairs
symbol_strategy = st.sampled_from([
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "BNBUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT"
])

# Price values - realistic price ranges
price_strategy = st.floats(min_value=0.001, max_value=100000.0, allow_nan=False, allow_infinity=False)

# Volume values
volume_strategy = st.floats(min_value=0.0, max_value=1000000.0, allow_nan=False, allow_infinity=False)

# Confidence values in 0-1 range
confidence_strategy = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Direction
direction_strategy = st.sampled_from(["long", "short", "neutral"])

# Feature values - floats for various indicators
feature_value_strategy = st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)


@st.composite
def market_context_strategy(draw):
    """Generate random market context dictionaries."""
    return {
        "bid": draw(price_strategy),
        "ask": draw(price_strategy),
        "mid_price": draw(price_strategy),
        "spread_bps": draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)),
        "volume_24h": draw(volume_strategy),
        "timestamp": draw(st.integers(min_value=1600000000, max_value=2000000000)),
        "orderbook_depth": draw(st.integers(min_value=1, max_value=100)),
    }


@st.composite
def features_strategy(draw):
    """Generate random features dictionaries."""
    return {
        "rsi": draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)),
        "macd": draw(feature_value_strategy),
        "macd_signal": draw(feature_value_strategy),
        "bollinger_upper": draw(price_strategy),
        "bollinger_lower": draw(price_strategy),
        "atr": draw(st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False)),
        "volume_ratio": draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
    }


@st.composite
def prediction_strategy(draw):
    """Generate random prediction dictionaries."""
    return {
        "confidence": draw(confidence_strategy),
        "direction": draw(direction_strategy),
        "expected_return": draw(st.floats(min_value=-0.1, max_value=0.1, allow_nan=False, allow_infinity=False)),
    }


@st.composite
def account_state_strategy(draw):
    """Generate random account state dictionaries."""
    return {
        "equity": draw(st.floats(min_value=100.0, max_value=1000000.0, allow_nan=False, allow_infinity=False)),
        "available_margin": draw(st.floats(min_value=0.0, max_value=1000000.0, allow_nan=False, allow_infinity=False)),
        "used_margin": draw(st.floats(min_value=0.0, max_value=500000.0, allow_nan=False, allow_infinity=False)),
    }


@st.composite
def positions_strategy(draw):
    """Generate random positions list."""
    num_positions = draw(st.integers(min_value=0, max_value=3))
    positions = []
    for _ in range(num_positions):
        positions.append({
            "symbol": draw(symbol_strategy),
            "side": draw(st.sampled_from(["long", "short"])),
            "size": draw(st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False)),
            "entry_price": draw(price_strategy),
            "unrealized_pnl": draw(st.floats(min_value=-10000.0, max_value=10000.0, allow_nan=False, allow_infinity=False)),
        })
    return positions


@st.composite
def decision_input_strategy(draw):
    """Generate random DecisionInput objects."""
    return DecisionInput(
        symbol=draw(symbol_strategy),
        market_context=draw(market_context_strategy()),
        features=draw(features_strategy()),
        account_state=draw(account_state_strategy()),
        positions=draw(positions_strategy()),
        risk_limits={"max_position_size": 10.0, "max_drawdown_pct": 0.1},
        profile_settings={"profile_id": "default"},
        prediction=draw(prediction_strategy()),
        risk_ok=draw(st.booleans()),
    )


# =============================================================================
# Mock Stage for Testing
# =============================================================================

class PassThroughStage(Stage):
    """A stage that always continues, used for testing."""
    name = "pass_through"
    
    def __init__(self, result: StageResult = StageResult.CONTINUE, set_signal: bool = False):
        self._result = result
        self._set_signal = set_signal
    
    async def run(self, ctx: StageContext) -> StageResult:
        # The Orchestrator requires ctx.signal to be set for COMPLETE result
        # final_result = COMPLETE if result in (COMPLETE, CONTINUE) and ctx.signal else REJECT
        if self._set_signal:
            ctx.signal = {"action": "test_signal", "side": "long", "size": 1.0}
        return self._result


class AcceptingStage(Stage):
    """A stage that completes with a signal, used for testing accepted decisions."""
    name = "accepting"
    
    async def run(self, ctx: StageContext) -> StageResult:
        # Set a signal so the Orchestrator returns COMPLETE
        ctx.signal = {"action": "test_signal", "side": "long", "size": 1.0}
        return StageResult.COMPLETE


class RejectingStage(Stage):
    """A stage that always rejects, used for testing."""
    name = "rejecting"
    
    async def run(self, ctx: StageContext) -> StageResult:
        ctx.rejection_reason = "test_rejection"
        ctx.rejection_stage = "rejecting"
        return StageResult.REJECT


# =============================================================================
# Mock DecisionRecorder
# =============================================================================

class MockDecisionRecorder:
    """Mock DecisionRecorder for testing."""
    
    def __init__(self):
        self.record_calls: List[Dict[str, Any]] = []
        self.record_mock = AsyncMock(return_value="dec_test123")
    
    async def record(
        self,
        symbol: str,
        snapshot: Any,
        features: Any,
        ctx: Any,
        decision: str,
    ) -> str:
        """Record a decision and track the call."""
        self.record_calls.append({
            "symbol": symbol,
            "snapshot": snapshot,
            "features": features,
            "ctx": ctx,
            "decision": decision,
        })
        return await self.record_mock(
            symbol=symbol,
            snapshot=snapshot,
            features=features,
            ctx=ctx,
            decision=decision,
        )


# =============================================================================
# Property 1: Decision Recording Completeness
# Feature: bot-integration-fixes, Property 1: Decision Recording Completeness
# Validates: Requirements 2.1, 2.2
# =============================================================================

@settings(max_examples=100)
@given(decision_input=decision_input_strategy())
def test_property_1_decision_recording_completeness_accepted(
    decision_input: DecisionInput,
):
    """
    Property 1: Decision Recording Completeness (Accepted Decisions)
    
    *For any* decision made by DecisionEngine when a DecisionRecorder is available,
    the decision SHALL be recorded with complete context including symbol, market
    snapshot, features, stage context, and decision outcome.
    
    This test verifies that accepted decisions (COMPLETE result) are recorded
    with all required fields.
    
    **Validates: Requirements 2.1, 2.2**
    """
    # Create mock recorder
    mock_recorder = MockDecisionRecorder()
    
    # Create engine with an accepting stage that sets a signal and completes
    engine = DecisionEngine(
        stages=[AcceptingStage()],
        decision_recorder=mock_recorder,
        use_gating_system=False,
    )
    
    # Run the decision
    result = asyncio.run(engine.decide(decision_input))
    
    # Property: record() was called exactly once
    assert len(mock_recorder.record_calls) == 1, \
        f"record() should be called exactly once, was called {len(mock_recorder.record_calls)} times"
    
    # Get the recorded call
    recorded = mock_recorder.record_calls[0]
    
    # Property: symbol is present and matches input
    assert recorded["symbol"] is not None, "symbol should not be None"
    assert recorded["symbol"] == decision_input.symbol, \
        f"symbol should match input: expected {decision_input.symbol}, got {recorded['symbol']}"
    
    # Property: snapshot is present (market context)
    assert recorded["snapshot"] is not None, "snapshot should not be None"
    assert isinstance(recorded["snapshot"], dict), "snapshot should be a dict"
    
    # Property: features is present
    assert recorded["features"] is not None, "features should not be None"
    assert isinstance(recorded["features"], dict), "features should be a dict"
    
    # Property: ctx (stage context) is present
    assert recorded["ctx"] is not None, "ctx should not be None"
    assert isinstance(recorded["ctx"], StageContext), "ctx should be a StageContext"
    
    # Property: decision outcome is present and correct for accepted
    assert recorded["decision"] is not None, "decision should not be None"
    assert recorded["decision"] == "accepted", \
        f"decision should be 'accepted' for COMPLETE result, got {recorded['decision']}"


@settings(max_examples=100)
@given(decision_input=decision_input_strategy())
def test_property_1_decision_recording_completeness_rejected(
    decision_input: DecisionInput,
):
    """
    Property 1: Decision Recording Completeness (Rejected Decisions)
    
    *For any* decision made by DecisionEngine when a DecisionRecorder is available,
    the decision SHALL be recorded with complete context including symbol, market
    snapshot, features, stage context, and decision outcome.
    
    This test verifies that rejected decisions are recorded with all required fields.
    
    **Validates: Requirements 2.1, 2.2**
    """
    # Create mock recorder
    mock_recorder = MockDecisionRecorder()
    
    # Create engine with a rejecting stage
    engine = DecisionEngine(
        stages=[RejectingStage()],
        decision_recorder=mock_recorder,
        use_gating_system=False,
    )
    
    # Run the decision
    result = asyncio.run(engine.decide(decision_input))
    
    # Property: record() was called exactly once
    assert len(mock_recorder.record_calls) == 1, \
        f"record() should be called exactly once, was called {len(mock_recorder.record_calls)} times"
    
    # Get the recorded call
    recorded = mock_recorder.record_calls[0]
    
    # Property: symbol is present and matches input
    assert recorded["symbol"] is not None, "symbol should not be None"
    assert recorded["symbol"] == decision_input.symbol, \
        f"symbol should match input: expected {decision_input.symbol}, got {recorded['symbol']}"
    
    # Property: snapshot is present (market context)
    assert recorded["snapshot"] is not None, "snapshot should not be None"
    assert isinstance(recorded["snapshot"], dict), "snapshot should be a dict"
    
    # Property: features is present
    assert recorded["features"] is not None, "features should not be None"
    assert isinstance(recorded["features"], dict), "features should be a dict"
    
    # Property: ctx (stage context) is present
    assert recorded["ctx"] is not None, "ctx should not be None"
    assert isinstance(recorded["ctx"], StageContext), "ctx should be a StageContext"
    
    # Property: decision outcome is present and correct for rejected
    assert recorded["decision"] is not None, "decision should not be None"
    assert recorded["decision"] == "rejected", \
        f"decision should be 'rejected' for REJECT result, got {recorded['decision']}"


@settings(max_examples=100)
@given(decision_input=decision_input_strategy())
def test_property_1_decide_with_context_recording_completeness(
    decision_input: DecisionInput,
):
    """
    Property 1: Decision Recording Completeness (decide_with_context)
    
    *For any* decision made via decide_with_context() when a DecisionRecorder is
    available, the decision SHALL be recorded with complete context.
    
    **Validates: Requirements 2.1, 2.2**
    """
    # Create mock recorder
    mock_recorder = MockDecisionRecorder()
    
    # Create engine with an accepting stage
    engine = DecisionEngine(
        stages=[AcceptingStage()],
        decision_recorder=mock_recorder,
        use_gating_system=False,
    )
    
    # Run the decision with context
    result, ctx = asyncio.run(engine.decide_with_context(decision_input))
    
    # Property: record() was called exactly once
    assert len(mock_recorder.record_calls) == 1, \
        f"record() should be called exactly once, was called {len(mock_recorder.record_calls)} times"
    
    # Get the recorded call
    recorded = mock_recorder.record_calls[0]
    
    # Property: all required fields are present
    assert recorded["symbol"] == decision_input.symbol, "symbol should match input"
    assert recorded["snapshot"] is not None, "snapshot should not be None"
    assert recorded["features"] is not None, "features should not be None"
    assert recorded["ctx"] is not None, "ctx should not be None"
    assert recorded["decision"] in ("accepted", "rejected"), \
        f"decision should be 'accepted' or 'rejected', got {recorded['decision']}"


@settings(max_examples=50)
@given(decision_input=decision_input_strategy())
def test_property_1_no_recording_when_recorder_is_none(
    decision_input: DecisionInput,
):
    """
    Property 1 (Edge Case): No recording when DecisionRecorder is None
    
    *For any* decision made by DecisionEngine when DecisionRecorder is None,
    the decision SHALL proceed without recording (graceful handling).
    
    **Validates: Requirements 2.3**
    """
    # Create engine WITHOUT a recorder
    engine = DecisionEngine(
        stages=[AcceptingStage()],
        decision_recorder=None,  # No recorder
        use_gating_system=False,
    )
    
    # Run the decision - should not raise any errors
    result = asyncio.run(engine.decide(decision_input))
    
    # Property: decision completes successfully without recorder
    assert result is True, "Decision should complete successfully without recorder"


@settings(max_examples=50)
@given(decision_input=decision_input_strategy())
def test_property_1_recording_error_does_not_fail_decision(
    decision_input: DecisionInput,
):
    """
    Property 1 (Error Handling): Recording errors don't fail the decision
    
    *For any* decision where the DecisionRecorder.record() raises an exception,
    the decision SHALL still complete (error is logged but not propagated).
    
    **Validates: Requirements 2.1, 2.2**
    """
    # Create mock recorder that raises an error
    mock_recorder = MockDecisionRecorder()
    mock_recorder.record_mock.side_effect = Exception("Database connection failed")
    
    # Create engine with the failing recorder
    engine = DecisionEngine(
        stages=[AcceptingStage()],
        decision_recorder=mock_recorder,
        use_gating_system=False,
    )
    
    # Run the decision - should not raise any errors
    result = asyncio.run(engine.decide(decision_input))
    
    # Property: decision completes successfully despite recording error
    assert result is True, "Decision should complete successfully despite recording error"
    
    # Property: record() was still attempted
    assert len(mock_recorder.record_calls) == 1, \
        "record() should have been attempted once"


@settings(max_examples=100)
@given(decision_input=decision_input_strategy())
def test_property_1_decision_outcome_accepted_vs_rejected(
    decision_input: DecisionInput,
):
    """
    Property 1: Decision outcome correctly reflects accepted vs rejected
    
    *For any* decision, the recorded decision outcome SHALL correctly reflect
    the final result: accepted decisions record "accepted", rejected decisions
    record "rejected".
    
    **Validates: Requirements 2.1, 2.2**
    """
    # Test accepted decision
    mock_recorder_accepted = MockDecisionRecorder()
    engine_accepted = DecisionEngine(
        stages=[AcceptingStage()],
        decision_recorder=mock_recorder_accepted,
        use_gating_system=False,
    )
    result_accepted = asyncio.run(engine_accepted.decide(decision_input))
    
    assert len(mock_recorder_accepted.record_calls) == 1
    assert mock_recorder_accepted.record_calls[0]["decision"] == "accepted", \
        "Accepted decision should record 'accepted'"
    
    # Test rejected decision
    mock_recorder_rejected = MockDecisionRecorder()
    engine_rejected = DecisionEngine(
        stages=[RejectingStage()],
        decision_recorder=mock_recorder_rejected,
        use_gating_system=False,
    )
    result_rejected = asyncio.run(engine_rejected.decide(decision_input))
    
    assert len(mock_recorder_rejected.record_calls) == 1
    assert mock_recorder_rejected.record_calls[0]["decision"] == "rejected", \
        "Rejected decision should record 'rejected'"
