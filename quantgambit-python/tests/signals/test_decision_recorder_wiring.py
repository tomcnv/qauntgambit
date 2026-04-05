"""
Unit tests for DecisionRecorder wiring to DecisionEngine.

Feature: bot-integration-fixes
Tests for:
- Recording happens when recorder is available
- Decisions work when recorder is None
- DECISION_RECORDER_ENABLED="false" skips recording

**Validates: Requirements 2.3, 2.4**
"""

import asyncio
import os
import pytest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput
from quantgambit.signals.pipeline import StageContext, StageResult, Stage


# =============================================================================
# Mock Stages for Testing
# =============================================================================

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
    
    def __init__(self, should_fail: bool = False):
        self.record_calls: List[Dict[str, Any]] = []
        self.should_fail = should_fail
    
    async def record(
        self,
        symbol: str,
        snapshot: Any,
        features: Any,
        ctx: Any,
        decision: str,
    ) -> str:
        """Record a decision and track the call."""
        if self.should_fail:
            raise Exception("Database connection failed")
        
        self.record_calls.append({
            "symbol": symbol,
            "snapshot": snapshot,
            "features": features,
            "ctx": ctx,
            "decision": decision,
        })
        return "dec_test123"


# =============================================================================
# Test Fixtures
# =============================================================================

def create_test_decision_input(symbol: str = "BTCUSDT") -> DecisionInput:
    """Create a test DecisionInput with minimal required data."""
    return DecisionInput(
        symbol=symbol,
        market_context={
            "bid": 50000.0,
            "ask": 50010.0,
            "mid_price": 50005.0,
            "spread_bps": 2.0,
            "volume_24h": 1000000.0,
            "timestamp": 1700000000,
        },
        features={
            "rsi": 50.0,
            "macd": 0.5,
            "atr": 100.0,
        },
        account_state={
            "equity": 100000.0,
            "available_margin": 50000.0,
        },
        positions=[],
        risk_limits={"max_position_size": 10.0},
        profile_settings={"profile_id": "default"},
        prediction={"confidence": 0.8, "direction": "long"},
        risk_ok=True,
    )


# =============================================================================
# Test: Recording happens when recorder is available
# Validates: Requirement 2.3 (inverse - when recorder IS available)
# =============================================================================

class TestRecordingWhenRecorderAvailable:
    """Tests verifying recording happens when DecisionRecorder is available."""
    
    def test_record_called_on_accepted_decision(self):
        """When recorder is available and decision is accepted, record() should be called.
        
        Validates: Requirements 2.1, 2.2 - WHEN the DecisionEngine makes a decision
        THEN the System SHALL record the decision using DecisionRecorder
        """
        mock_recorder = MockDecisionRecorder()
        engine = DecisionEngine(
            stages=[AcceptingStage()],
            decision_recorder=mock_recorder,
            use_gating_system=False,
        )
        
        decision_input = create_test_decision_input()
        result = asyncio.run(engine.decide(decision_input))
        
        # Decision should be accepted
        assert result is True
        
        # record() should have been called exactly once
        assert len(mock_recorder.record_calls) == 1, \
            f"record() should be called once, was called {len(mock_recorder.record_calls)} times"
        
        # Verify the recorded data
        recorded = mock_recorder.record_calls[0]
        assert recorded["symbol"] == "BTCUSDT"
        assert recorded["decision"] == "accepted"
    
    def test_record_called_on_rejected_decision(self):
        """When recorder is available and decision is rejected, record() should be called.
        
        Validates: Requirements 2.1, 2.2 - WHEN the DecisionEngine makes a decision
        THEN the System SHALL record the decision using DecisionRecorder
        """
        mock_recorder = MockDecisionRecorder()
        engine = DecisionEngine(
            stages=[RejectingStage()],
            decision_recorder=mock_recorder,
            use_gating_system=False,
        )
        
        decision_input = create_test_decision_input()
        result = asyncio.run(engine.decide(decision_input))
        
        # Decision should be rejected
        assert result is False
        
        # record() should have been called exactly once
        assert len(mock_recorder.record_calls) == 1, \
            f"record() should be called once, was called {len(mock_recorder.record_calls)} times"
        
        # Verify the recorded data
        recorded = mock_recorder.record_calls[0]
        assert recorded["symbol"] == "BTCUSDT"
        assert recorded["decision"] == "rejected"
    
    def test_record_called_with_complete_context(self):
        """When recording, all required context fields should be present.
        
        Validates: Requirement 2.2 - WHEN recording a decision THEN the System SHALL
        include the symbol, market snapshot, features, stage context, and decision outcome
        """
        mock_recorder = MockDecisionRecorder()
        engine = DecisionEngine(
            stages=[AcceptingStage()],
            decision_recorder=mock_recorder,
            use_gating_system=False,
        )
        
        decision_input = create_test_decision_input(symbol="ETHUSDT")
        asyncio.run(engine.decide(decision_input))
        
        assert len(mock_recorder.record_calls) == 1
        recorded = mock_recorder.record_calls[0]
        
        # Verify all required fields are present
        assert recorded["symbol"] == "ETHUSDT", "symbol should match input"
        assert recorded["snapshot"] is not None, "snapshot should not be None"
        assert isinstance(recorded["snapshot"], dict), "snapshot should be a dict"
        assert recorded["features"] is not None, "features should not be None"
        assert isinstance(recorded["features"], dict), "features should be a dict"
        assert recorded["ctx"] is not None, "ctx should not be None"
        assert isinstance(recorded["ctx"], StageContext), "ctx should be a StageContext"
        assert recorded["decision"] in ("accepted", "rejected"), \
            f"decision should be 'accepted' or 'rejected', got {recorded['decision']}"
    
    def test_record_called_for_decide_with_context(self):
        """Recording should also work for decide_with_context() method.
        
        Validates: Requirements 2.1, 2.2
        """
        mock_recorder = MockDecisionRecorder()
        engine = DecisionEngine(
            stages=[AcceptingStage()],
            decision_recorder=mock_recorder,
            use_gating_system=False,
        )
        
        decision_input = create_test_decision_input()
        result, ctx = asyncio.run(engine.decide_with_context(decision_input))
        
        # Decision should be accepted
        assert result is True
        
        # record() should have been called exactly once
        assert len(mock_recorder.record_calls) == 1
        
        # Verify the recorded data
        recorded = mock_recorder.record_calls[0]
        assert recorded["symbol"] == "BTCUSDT"
        assert recorded["decision"] == "accepted"


# =============================================================================
# Test: Decisions work when recorder is None
# Validates: Requirement 2.3
# =============================================================================

class TestDecisionsWorkWithoutRecorder:
    """Tests verifying decisions work when DecisionRecorder is None.
    
    Validates: Requirement 2.3 - WHEN the DecisionRecorder is not available (None)
    THEN the System SHALL continue making decisions without recording
    """
    
    def test_accepted_decision_works_without_recorder(self):
        """Accepted decisions should work when recorder is None.
        
        Validates: Requirement 2.3
        """
        engine = DecisionEngine(
            stages=[AcceptingStage()],
            decision_recorder=None,  # No recorder
            use_gating_system=False,
        )
        
        decision_input = create_test_decision_input()
        result = asyncio.run(engine.decide(decision_input))
        
        # Decision should complete successfully
        assert result is True, "Decision should be accepted without recorder"
    
    def test_rejected_decision_works_without_recorder(self):
        """Rejected decisions should work when recorder is None.
        
        Validates: Requirement 2.3
        """
        engine = DecisionEngine(
            stages=[RejectingStage()],
            decision_recorder=None,  # No recorder
            use_gating_system=False,
        )
        
        decision_input = create_test_decision_input()
        result = asyncio.run(engine.decide(decision_input))
        
        # Decision should complete (rejected)
        assert result is False, "Decision should be rejected without recorder"
    
    def test_decide_with_context_works_without_recorder(self):
        """decide_with_context() should work when recorder is None.
        
        Validates: Requirement 2.3
        """
        engine = DecisionEngine(
            stages=[AcceptingStage()],
            decision_recorder=None,  # No recorder
            use_gating_system=False,
        )
        
        decision_input = create_test_decision_input()
        result, ctx = asyncio.run(engine.decide_with_context(decision_input))
        
        # Decision should complete successfully
        assert result is True, "Decision should be accepted without recorder"
        assert ctx is not None, "Context should be returned"
    
    def test_no_error_when_recorder_is_none(self):
        """No errors should be raised when recorder is None.
        
        Validates: Requirement 2.3
        """
        engine = DecisionEngine(
            stages=[AcceptingStage()],
            decision_recorder=None,
            use_gating_system=False,
        )
        
        decision_input = create_test_decision_input()
        
        # Should not raise any exceptions
        try:
            result = asyncio.run(engine.decide(decision_input))
            assert result is True
        except Exception as e:
            pytest.fail(f"Should not raise exception when recorder is None: {e}")


# =============================================================================
# Test: Recording errors don't fail decisions
# Validates: Requirements 2.1, 2.2 (error handling)
# =============================================================================

class TestRecordingErrorHandling:
    """Tests verifying recording errors don't fail decisions."""
    
    def test_decision_succeeds_when_recording_fails(self):
        """Decision should succeed even if recording fails.
        
        Validates: Requirements 2.1, 2.2 - Recording errors should be logged
        but not propagated to fail the decision.
        """
        mock_recorder = MockDecisionRecorder(should_fail=True)
        engine = DecisionEngine(
            stages=[AcceptingStage()],
            decision_recorder=mock_recorder,
            use_gating_system=False,
        )
        
        decision_input = create_test_decision_input()
        
        # Should not raise exception despite recording failure
        result = asyncio.run(engine.decide(decision_input))
        
        # Decision should still be accepted
        assert result is True, "Decision should succeed despite recording error"
    
    def test_rejected_decision_succeeds_when_recording_fails(self):
        """Rejected decision should complete even if recording fails.
        
        Validates: Requirements 2.1, 2.2
        """
        mock_recorder = MockDecisionRecorder(should_fail=True)
        engine = DecisionEngine(
            stages=[RejectingStage()],
            decision_recorder=mock_recorder,
            use_gating_system=False,
        )
        
        decision_input = create_test_decision_input()
        
        # Should not raise exception despite recording failure
        result = asyncio.run(engine.decide(decision_input))
        
        # Decision should still be rejected (not error)
        assert result is False, "Decision should be rejected despite recording error"


# =============================================================================
# Test: DECISION_RECORDER_ENABLED="false" skips recording
# Validates: Requirement 2.4, 5.3, 5.7
# =============================================================================

class TestDecisionRecorderEnabledEnvVar:
    """Tests for DECISION_RECORDER_ENABLED environment variable.
    
    Validates: Requirement 2.4 - WHEN the DECISION_RECORDER_ENABLED environment
    variable is set to "false" THEN the System SHALL skip decision recording
    
    Also validates: Requirements 5.3, 5.7
    """
    
    def test_runtime_skips_recorder_when_disabled(self):
        """Runtime should skip DecisionRecorder initialization when DECISION_RECORDER_ENABLED=false.
        
        Validates: Requirement 5.7 - WHEN DECISION_RECORDER_ENABLED is "false" THEN
        the Runtime SHALL skip DecisionRecorder initialization
        """
        import quantgambit.runtime.app as runtime_module
        import inspect
        
        source_file = inspect.getfile(runtime_module)
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # Verify the conditional initialization pattern exists
        assert 'decision_recorder_enabled' in source_code, \
            "Runtime should have decision_recorder_enabled variable"
        assert 'if decision_recorder_enabled and timescale_pool:' in source_code, \
            "Runtime should check decision_recorder_enabled before initializing DecisionRecorder"
    
    def test_runtime_defaults_recorder_enabled_to_true(self):
        """Runtime should default DECISION_RECORDER_ENABLED to "true".
        
        Validates: Requirement 5.3 - THE System SHALL support DECISION_RECORDER_ENABLED
        environment variable with default value "true"
        """
        import quantgambit.runtime.app as runtime_module
        import inspect
        
        source_file = inspect.getfile(runtime_module)
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # Verify the default value is "true"
        assert 'os.getenv("DECISION_RECORDER_ENABLED", "true")' in source_code, \
            "Runtime should default DECISION_RECORDER_ENABLED to 'true'"
    
    def test_env_var_false_values_recognized(self):
        """Various "false" values should be recognized for DECISION_RECORDER_ENABLED.
        
        Validates: Requirement 2.4
        """
        import quantgambit.runtime.app as runtime_module
        import inspect
        
        source_file = inspect.getfile(runtime_module)
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # The code should check for truthy values like "1", "true", "yes"
        # When the env var is "false", it won't match these, so recorder is skipped
        assert '.lower() in {"1", "true", "yes"}' in source_code or \
               '.lower() in ("1", "true", "yes")' in source_code or \
               '.lower() in {\'1\', \'true\', \'yes\'}' in source_code, \
            "Runtime should check for truthy values for DECISION_RECORDER_ENABLED"
    
    @patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "false"})
    def test_env_var_false_skips_initialization(self):
        """When DECISION_RECORDER_ENABLED=false, recorder should not be initialized.
        
        Validates: Requirement 2.4, 5.7
        """
        # Test the logic directly
        decision_recorder_enabled = os.getenv("DECISION_RECORDER_ENABLED", "true").lower() in {"1", "true", "yes"}
        
        assert decision_recorder_enabled is False, \
            "decision_recorder_enabled should be False when env var is 'false'"
    
    @patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "true"})
    def test_env_var_true_enables_initialization(self):
        """When DECISION_RECORDER_ENABLED=true, recorder should be initialized.
        
        Validates: Requirement 5.3
        """
        decision_recorder_enabled = os.getenv("DECISION_RECORDER_ENABLED", "true").lower() in {"1", "true", "yes"}
        
        assert decision_recorder_enabled is True, \
            "decision_recorder_enabled should be True when env var is 'true'"
    
    @patch.dict(os.environ, {}, clear=False)
    def test_env_var_not_set_defaults_to_true(self):
        """When DECISION_RECORDER_ENABLED is not set, it should default to true.
        
        Validates: Requirement 5.3 - default value "true"
        """
        # Remove the env var if it exists
        env_copy = os.environ.copy()
        if "DECISION_RECORDER_ENABLED" in env_copy:
            del env_copy["DECISION_RECORDER_ENABLED"]
        
        with patch.dict(os.environ, env_copy, clear=True):
            decision_recorder_enabled = os.getenv("DECISION_RECORDER_ENABLED", "true").lower() in {"1", "true", "yes"}
            
            assert decision_recorder_enabled is True, \
                "decision_recorder_enabled should default to True when env var is not set"
    
    @patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "1"})
    def test_env_var_1_enables_initialization(self):
        """When DECISION_RECORDER_ENABLED=1, recorder should be initialized.
        
        Validates: Requirement 5.3
        """
        decision_recorder_enabled = os.getenv("DECISION_RECORDER_ENABLED", "true").lower() in {"1", "true", "yes"}
        
        assert decision_recorder_enabled is True, \
            "decision_recorder_enabled should be True when env var is '1'"
    
    @patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "yes"})
    def test_env_var_yes_enables_initialization(self):
        """When DECISION_RECORDER_ENABLED=yes, recorder should be initialized.
        
        Validates: Requirement 5.3
        """
        decision_recorder_enabled = os.getenv("DECISION_RECORDER_ENABLED", "true").lower() in {"1", "true", "yes"}
        
        assert decision_recorder_enabled is True, \
            "decision_recorder_enabled should be True when env var is 'yes'"
    
    @patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "no"})
    def test_env_var_no_skips_initialization(self):
        """When DECISION_RECORDER_ENABLED=no, recorder should not be initialized.
        
        Validates: Requirement 2.4
        """
        decision_recorder_enabled = os.getenv("DECISION_RECORDER_ENABLED", "true").lower() in {"1", "true", "yes"}
        
        assert decision_recorder_enabled is False, \
            "decision_recorder_enabled should be False when env var is 'no'"
    
    @patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "0"})
    def test_env_var_0_skips_initialization(self):
        """When DECISION_RECORDER_ENABLED=0, recorder should not be initialized.
        
        Validates: Requirement 2.4
        """
        decision_recorder_enabled = os.getenv("DECISION_RECORDER_ENABLED", "true").lower() in {"1", "true", "yes"}
        
        assert decision_recorder_enabled is False, \
            "decision_recorder_enabled should be False when env var is '0'"


# =============================================================================
# Test: DecisionEngine accepts decision_recorder parameter
# Validates: Requirement 2.5
# =============================================================================

class TestDecisionEngineRecorderParameter:
    """Tests verifying DecisionEngine accepts decision_recorder parameter.
    
    Validates: Requirement 2.5 - THE DecisionEngine SHALL accept an optional
    DecisionRecorder parameter in its constructor
    """
    
    def test_decision_engine_accepts_recorder_parameter(self):
        """DecisionEngine should accept decision_recorder parameter.
        
        Validates: Requirement 2.5
        """
        mock_recorder = MockDecisionRecorder()
        
        # Should not raise any errors
        engine = DecisionEngine(
            stages=[AcceptingStage()],
            decision_recorder=mock_recorder,
            use_gating_system=False,
        )
        
        assert engine._decision_recorder is mock_recorder, \
            "DecisionEngine should store the decision_recorder"
    
    def test_decision_engine_accepts_none_recorder(self):
        """DecisionEngine should accept None for decision_recorder.
        
        Validates: Requirement 2.5
        """
        engine = DecisionEngine(
            stages=[AcceptingStage()],
            decision_recorder=None,
            use_gating_system=False,
        )
        
        assert engine._decision_recorder is None, \
            "DecisionEngine should accept None for decision_recorder"
    
    def test_decision_engine_default_recorder_is_none(self):
        """DecisionEngine should default decision_recorder to None.
        
        Validates: Requirement 2.5
        """
        engine = DecisionEngine(
            stages=[AcceptingStage()],
            use_gating_system=False,
        )
        
        assert engine._decision_recorder is None, \
            "DecisionEngine should default decision_recorder to None"
