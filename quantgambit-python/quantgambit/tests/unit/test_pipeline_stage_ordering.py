"""
Unit tests for pipeline stage ordering validation.

Tests for Requirement 8: Stage Ordering Fix with ProfileRouter
- 8.9: Pipeline config SHALL validate stage ordering at initialization
- 8.10: IF stage ordering is invalid THEN Pipeline SHALL raise ConfigurationError
- 8.11: Pipeline SHALL log stage execution order at startup
- 8.12: IF ProfileRouter is missing THEN Pipeline SHALL log warning and use default profile
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock

from quantgambit.signals.pipeline import (
    Stage,
    StageContext,
    StageResult,
    Orchestrator,
    ConfigurationError,
    CANONICAL_STAGE_ORDER,
    DEFAULT_PROFILE_ID,
    validate_stage_ordering,
    check_profile_router_present,
    log_stage_execution_order,
    get_canonical_stage_order,
)


# =============================================================================
# Test Fixtures - Mock Stages
# =============================================================================

class MockDataReadinessStage(Stage):
    name = "data_readiness"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


class MockGlobalGateStage(Stage):
    name = "global_gate"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


class MockProfileRoutingStage(Stage):
    name = "profile_routing"
    
    async def run(self, ctx: StageContext) -> StageResult:
        ctx.profile_id = "test_profile"
        return StageResult.CONTINUE


class MockAMTCalculatorStage(Stage):
    name = "amt_calculator"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


class MockSignalCheckStage(Stage):
    name = "signal_check"
    
    async def run(self, ctx: StageContext) -> StageResult:
        ctx.signal = {"signal": True, "side": "long"}
        return StageResult.CONTINUE


class MockArbitrationStage(Stage):
    name = "arbitration"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


class MockConfirmationStage(Stage):
    name = "confirmation"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


class MockEVGateStage(Stage):
    name = "ev_gate"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


class MockExecutionFeasibilityStage(Stage):
    name = "execution_feasibility"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


class MockExecutionStage(Stage):
    name = "execution"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.COMPLETE


class MockRiskCheckStage(Stage):
    name = "risk_check"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


class MockPositionEvaluationStage(Stage):
    name = "position_evaluation"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


# =============================================================================
# Test: Canonical Stage Order Constants
# =============================================================================

class TestCanonicalStageOrder:
    """Tests for canonical stage order constants."""
    
    def test_canonical_order_is_tuple(self):
        """Canonical order should be an immutable tuple."""
        assert isinstance(CANONICAL_STAGE_ORDER, tuple)
    
    def test_canonical_order_contains_required_stages(self):
        """Canonical order should contain all required stages."""
        required_stages = [
            "data_readiness",
            "global_gate",
            "profile_routing",
            "amt_calculator",
            "signal_check",
            "ev_gate",
            "execution",
        ]
        for stage in required_stages:
            assert stage in CANONICAL_STAGE_ORDER, f"Missing required stage: {stage}"
    
    def test_canonical_order_has_correct_sequence(self):
        """Canonical order should have correct relative positions."""
        order = list(CANONICAL_STAGE_ORDER)
        
        # data_readiness should come before global_gate
        assert order.index("data_readiness") < order.index("global_gate")
        
        # amt_calculator should come before profile_routing
        assert order.index("amt_calculator") < order.index("profile_routing")
        
        # signal_check (Strategy) should come before ev_gate
        assert order.index("signal_check") < order.index("ev_gate")
        
        # ev_gate should come before execution
        assert order.index("ev_gate") < order.index("execution")
    
    def test_get_canonical_stage_order_returns_same_tuple(self):
        """get_canonical_stage_order should return the canonical order."""
        assert get_canonical_stage_order() == CANONICAL_STAGE_ORDER


# =============================================================================
# Test: Stage Ordering Validation
# =============================================================================

class TestValidateStageOrdering:
    """Tests for validate_stage_ordering function."""
    
    def test_valid_ordering_passes(self):
        """Valid stage ordering should pass validation."""
        stages = [
            MockDataReadinessStage(),
            MockAMTCalculatorStage(),
            MockGlobalGateStage(),
            MockProfileRoutingStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            MockExecutionStage(),
        ]
        
        is_valid, errors = validate_stage_ordering(stages)
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_invalid_ordering_ev_gate_before_signal(self):
        """EVGate before SignalCheck should fail validation."""
        stages = [
            MockDataReadinessStage(),
            MockGlobalGateStage(),
            MockEVGateStage(),  # Wrong position - before signal_check
            MockSignalCheckStage(),
            MockExecutionStage(),
        ]
        
        is_valid, errors = validate_stage_ordering(stages)
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("ev_gate" in e.lower() and "signal" in e.lower() for e in errors)
    
    def test_invalid_ordering_execution_before_ev_gate(self):
        """Execution before EVGate should fail validation."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockExecutionStage(),  # Wrong position - before ev_gate
            MockEVGateStage(),
        ]
        
        is_valid, errors = validate_stage_ordering(stages)
        
        assert is_valid is False
        assert len(errors) > 0
    
    def test_flexible_stages_can_appear_anywhere(self):
        """Flexible stages (position_evaluation, risk_check) can appear anywhere."""
        stages = [
            MockPositionEvaluationStage(),  # Flexible - can be first
            MockDataReadinessStage(),
            MockRiskCheckStage(),  # Flexible - can be in middle
            MockSignalCheckStage(),
            MockEVGateStage(),
            MockExecutionStage(),
        ]
        
        is_valid, errors = validate_stage_ordering(stages)
        
        # Should pass because flexible stages don't affect ordering validation
        assert is_valid is True
    
    def test_optional_stages_can_be_omitted(self):
        """Optional stages (arbitration, confirmation) can be omitted."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            # arbitration and confirmation omitted
            MockEVGateStage(),
            MockExecutionStage(),
        ]
        
        is_valid, errors = validate_stage_ordering(stages)
        
        assert is_valid is True
    
    def test_empty_stages_list_passes(self):
        """Empty stages list should pass validation."""
        is_valid, errors = validate_stage_ordering([])
        
        assert is_valid is True
        assert len(errors) == 0


# =============================================================================
# Test: ProfileRouter Presence Check
# =============================================================================

class TestCheckProfileRouterPresent:
    """Tests for check_profile_router_present function."""
    
    def test_profile_router_present(self):
        """Should return True when ProfileRouter is present."""
        stages = [
            MockDataReadinessStage(),
            MockProfileRoutingStage(),
            MockSignalCheckStage(),
        ]
        
        is_present, warning = check_profile_router_present(stages)
        
        assert is_present is True
        assert warning is None
    
    def test_profile_router_missing(self):
        """Should return False with warning when ProfileRouter is missing."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
        ]
        
        is_present, warning = check_profile_router_present(stages)
        
        assert is_present is False
        assert warning is not None
        assert "ProfileRouter" in warning
        assert DEFAULT_PROFILE_ID in warning
    
    def test_empty_stages_list(self):
        """Empty stages list should indicate ProfileRouter is missing."""
        is_present, warning = check_profile_router_present([])
        
        assert is_present is False
        assert warning is not None


# =============================================================================
# Test: Orchestrator Stage Ordering Validation
# =============================================================================

class TestOrchestratorStageOrdering:
    """Tests for Orchestrator stage ordering validation at initialization."""
    
    def test_orchestrator_validates_ordering_by_default(self):
        """Orchestrator should validate stage ordering by default."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            MockExecutionStage(),
        ]
        
        with patch('quantgambit.signals.pipeline.log_info') as mock_log:
            orchestrator = Orchestrator(stages)
            
            # Should have logged stage order
            assert mock_log.called
    
    def test_orchestrator_strict_ordering_raises_on_invalid(self):
        """Orchestrator with strict_ordering=True should raise ConfigurationError."""
        stages = [
            MockDataReadinessStage(),
            MockEVGateStage(),  # Wrong position - before signal_check
            MockSignalCheckStage(),
            MockExecutionStage(),
        ]
        
        with pytest.raises(ConfigurationError) as exc_info:
            Orchestrator(stages, strict_ordering=True)
        
        assert "Invalid stage ordering" in str(exc_info.value)
    
    def test_orchestrator_non_strict_logs_warning_on_invalid(self):
        """Orchestrator with strict_ordering=False should log warning but not raise."""
        stages = [
            MockDataReadinessStage(),
            MockEVGateStage(),  # Wrong position
            MockSignalCheckStage(),
            MockExecutionStage(),
        ]
        
        with patch('quantgambit.signals.pipeline.log_warning') as mock_warning:
            # Should not raise
            orchestrator = Orchestrator(stages, strict_ordering=False)
            
            # Should have logged warning
            assert mock_warning.called
    
    def test_orchestrator_skip_validation(self):
        """Orchestrator with validate_ordering=False should skip validation."""
        stages = [
            MockDataReadinessStage(),
            MockEVGateStage(),  # Wrong position
            MockSignalCheckStage(),
        ]
        
        with patch('quantgambit.signals.pipeline.log_info') as mock_log:
            # Should not raise even with invalid ordering
            orchestrator = Orchestrator(stages, validate_ordering=False)
            
            # Should not have logged stage order
            assert not any(
                call.args[0] == "pipeline_stage_order" 
                for call in mock_log.call_args_list
            )
    
    def test_orchestrator_warns_on_missing_profile_router(self):
        """Orchestrator should warn when ProfileRouter is missing."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            MockExecutionStage(),
        ]
        
        with patch('quantgambit.signals.pipeline.log_warning') as mock_warning:
            orchestrator = Orchestrator(stages)
            
            # Should have logged warning about missing ProfileRouter
            warning_calls = [
                call for call in mock_warning.call_args_list
                if "profile_router" in str(call).lower()
            ]
            assert len(warning_calls) > 0


# =============================================================================
# Test: Orchestrator Default Profile Handling
# =============================================================================

class TestOrchestratorDefaultProfile:
    """Tests for Orchestrator default profile handling when ProfileRouter is missing."""
    
    def test_uses_default_profile_when_router_missing(self):
        """Should use default profile when ProfileRouter is missing."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockExecutionStage(),
        ]
        
        orchestrator = Orchestrator(stages)
        ctx = StageContext(symbol="BTCUSDT", data={})
        
        # Execute pipeline
        result = asyncio.run(orchestrator.execute(ctx))
        
        # Should have set default profile
        assert ctx.profile_id == DEFAULT_PROFILE_ID
    
    def test_preserves_existing_profile_when_router_missing(self):
        """Should preserve existing profile_id even when ProfileRouter is missing."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockExecutionStage(),
        ]
        
        orchestrator = Orchestrator(stages)
        ctx = StageContext(symbol="BTCUSDT", data={}, profile_id="custom_profile")
        
        # Execute pipeline
        result = asyncio.run(orchestrator.execute(ctx))
        
        # Should preserve existing profile
        assert ctx.profile_id == "custom_profile"
    
    def test_profile_router_sets_profile(self):
        """ProfileRouter should set profile_id when present."""
        stages = [
            MockDataReadinessStage(),
            MockProfileRoutingStage(),  # Sets profile_id to "test_profile"
            MockSignalCheckStage(),
            MockExecutionStage(),
        ]
        
        orchestrator = Orchestrator(stages)
        ctx = StageContext(symbol="BTCUSDT", data={})
        
        # Execute pipeline
        result = asyncio.run(orchestrator.execute(ctx))
        
        # Should have profile set by ProfileRouter
        assert ctx.profile_id == "test_profile"


# =============================================================================
# Test: Log Stage Execution Order
# =============================================================================

class TestLogStageExecutionOrder:
    """Tests for log_stage_execution_order function."""
    
    def test_logs_stage_order(self):
        """Should log stage execution order."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockExecutionStage(),
        ]
        
        with patch('quantgambit.signals.pipeline.log_info') as mock_log:
            log_stage_execution_order(stages)
            
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            
            # Check log message type
            assert call_args[0][0] == "pipeline_stage_order"
            
            # Check kwargs
            assert call_args[1]["stage_count"] == 3
            assert "data_readiness" in call_args[1]["stage_order"]
            assert "signal_check" in call_args[1]["stage_order"]
            assert "execution" in call_args[1]["stage_order"]
    
    def test_logs_empty_stages(self):
        """Should handle empty stages list."""
        with patch('quantgambit.signals.pipeline.log_info') as mock_log:
            log_stage_execution_order([])
            
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            assert call_args[1]["stage_count"] == 0


# =============================================================================
# Test: Integration - Full Pipeline Execution
# =============================================================================

class TestPipelineIntegration:
    """Integration tests for pipeline with stage ordering."""
    
    def test_full_pipeline_execution_correct_order(self):
        """Full pipeline should execute stages in correct order."""
        execution_order = []
        
        class TrackingStage(Stage):
            def __init__(self, name: str):
                self._name = name
            
            @property
            def name(self):
                return self._name
            
            async def run(self, ctx: StageContext) -> StageResult:
                execution_order.append(self._name)
                if self._name == "signal_check":
                    ctx.signal = {"signal": True}
                return StageResult.CONTINUE if self._name != "execution" else StageResult.COMPLETE
        
        stages = [
            TrackingStage("data_readiness"),
            TrackingStage("global_gate"),
            TrackingStage("profile_routing"),
            TrackingStage("signal_check"),
            TrackingStage("ev_gate"),
            TrackingStage("execution"),
        ]
        
        orchestrator = Orchestrator(stages)
        ctx = StageContext(symbol="BTCUSDT", data={})
        
        result = asyncio.run(orchestrator.execute(ctx))
        
        # Verify execution order
        assert execution_order == [
            "data_readiness",
            "global_gate",
            "profile_routing",
            "signal_check",
            "ev_gate",
            "execution",
        ]
        
        # Verify result
        assert result == StageResult.COMPLETE
    
    def test_pipeline_stops_on_rejection(self):
        """Pipeline should stop when a stage rejects."""
        execution_order = []
        
        class RejectingStage(Stage):
            name = "rejecting_stage"
            
            async def run(self, ctx: StageContext) -> StageResult:
                execution_order.append(self.name)
                ctx.rejection_reason = "test_rejection"
                return StageResult.REJECT
        
        stages = [
            MockDataReadinessStage(),
            RejectingStage(),
            MockSignalCheckStage(),  # Should not execute
        ]
        
        # Track execution
        original_run = MockDataReadinessStage.run
        async def tracking_run(self, ctx):
            execution_order.append(self.name)
            return await original_run(self, ctx)
        
        with patch.object(MockDataReadinessStage, 'run', tracking_run):
            orchestrator = Orchestrator(stages)
            ctx = StageContext(symbol="BTCUSDT", data={})
            
            result = asyncio.run(orchestrator.execute(ctx))
        
        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "test_rejection"
        # signal_check should not have executed
        assert "signal_check" not in execution_order
