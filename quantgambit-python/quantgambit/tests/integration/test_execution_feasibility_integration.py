"""
Integration tests for ExecutionFeasibilityGate in the pipeline.

Tests the integration of ExecutionFeasibilityGate with other pipeline stages.

Requirement 9.1: Execution_Feasibility_Gate SHALL run AFTER EVGate and BEFORE Execution
"""

import asyncio
import pytest
from dataclasses import dataclass
from typing import Optional, List

from quantgambit.signals.pipeline import (
    Stage,
    StageContext,
    StageResult,
    Orchestrator,
    validate_stage_ordering,
)
from quantgambit.signals.stages.execution_feasibility_gate import (
    ExecutionFeasibilityGate,
    ExecutionFeasibilityConfig,
    ExecutionPolicy,
)


# =============================================================================
# Mock Stages for Integration Testing
# =============================================================================

class MockDataReadinessStage(Stage):
    name = "data_readiness"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


class MockSignalCheckStage(Stage):
    """Mock strategy stage that produces a signal."""
    name = "signal_check"
    
    async def run(self, ctx: StageContext) -> StageResult:
        ctx.signal = {
            "side": "long",
            "entry_price": 50000.0,
            "stop_loss": 49500.0,
            "take_profit": 51000.0,
        }
        return StageResult.CONTINUE


class MockEVGateStage(Stage):
    """Mock EVGate that passes signals through."""
    name = "ev_gate"
    
    async def run(self, ctx: StageContext) -> StageResult:
        # EVGate passes the signal through
        return StageResult.CONTINUE


class MockExecutionStage(Stage):
    """Mock execution stage that records execution policy."""
    name = "execution"
    
    def __init__(self):
        self.received_policy: Optional[ExecutionPolicy] = None
    
    async def run(self, ctx: StageContext) -> StageResult:
        # Record the execution policy for verification
        self.received_policy = ctx.data.get("execution_policy")
        return StageResult.COMPLETE


class ExecutionOrderTracker:
    """Tracks the order of stage execution."""
    
    def __init__(self):
        self.execution_order: List[str] = []
    
    def record(self, stage_name: str):
        self.execution_order.append(stage_name)


# =============================================================================
# Integration Tests
# =============================================================================

class TestExecutionFeasibilityIntegration:
    """Integration tests for ExecutionFeasibilityGate in pipeline."""
    
    @pytest.mark.asyncio
    async def test_stage_ordering_validation(self):
        """Test that ExecutionFeasibilityGate is valid in canonical position."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            MockExecutionStage(),
        ]
        
        is_valid, errors = validate_stage_ordering(stages)
        
        assert is_valid is True
        assert len(errors) == 0
    
    @pytest.mark.asyncio
    async def test_execution_receives_policy(self):
        """Test that execution stage receives the execution policy."""
        execution_stage = MockExecutionStage()
        
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {"spread_percentile": 0.25},
            },
        )
        
        result = await orchestrator.execute(ctx)
        
        assert result == StageResult.COMPLETE
        assert execution_stage.received_policy is not None
        assert execution_stage.received_policy.mode == "maker_first"
        assert execution_stage.received_policy.ttl_ms == 5000
    
    @pytest.mark.asyncio
    async def test_taker_only_policy_propagates(self):
        """Test that taker_only policy propagates to execution."""
        execution_stage = MockExecutionStage()
        
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {"spread_percentile": 0.80},  # Wide spread
            },
        )
        
        result = await orchestrator.execute(ctx)
        
        assert result == StageResult.COMPLETE
        assert execution_stage.received_policy is not None
        assert execution_stage.received_policy.mode == "taker_only"
        assert execution_stage.received_policy.ttl_ms == 0
    
    @pytest.mark.asyncio
    async def test_vol_shock_forced_taker_propagates(self):
        """Test that vol_shock forced taker propagates correctly."""
        execution_stage = MockExecutionStage()
        
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "force_taker": True,  # Vol shock forced taker
                "market_context": {"spread_percentile": 0.10},  # Tight spread
            },
        )
        
        result = await orchestrator.execute(ctx)
        
        assert result == StageResult.COMPLETE
        assert execution_stage.received_policy is not None
        assert execution_stage.received_policy.mode == "taker_only"
        assert execution_stage.received_policy.reason == "vol_shock_forced_taker"
    
    @pytest.mark.asyncio
    async def test_stage_execution_order(self):
        """Test that stages execute in correct order."""
        tracker = ExecutionOrderTracker()
        
        class TrackingDataReadiness(Stage):
            name = "data_readiness"
            async def run(self, ctx: StageContext) -> StageResult:
                tracker.record(self.name)
                return StageResult.CONTINUE
        
        class TrackingSignalCheck(Stage):
            name = "signal_check"
            async def run(self, ctx: StageContext) -> StageResult:
                tracker.record(self.name)
                ctx.signal = {"side": "long"}
                return StageResult.CONTINUE
        
        class TrackingEVGate(Stage):
            name = "ev_gate"
            async def run(self, ctx: StageContext) -> StageResult:
                tracker.record(self.name)
                return StageResult.CONTINUE
        
        class TrackingExecutionFeasibility(ExecutionFeasibilityGate):
            async def run(self, ctx: StageContext) -> StageResult:
                tracker.record(self.name)
                return await super().run(ctx)
        
        class TrackingExecution(Stage):
            name = "execution"
            async def run(self, ctx: StageContext) -> StageResult:
                tracker.record(self.name)
                return StageResult.COMPLETE
        
        stages = [
            TrackingDataReadiness(),
            TrackingSignalCheck(),
            TrackingEVGate(),
            TrackingExecutionFeasibility(),
            TrackingExecution(),
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"market_context": {"spread_percentile": 0.50}},
        )
        
        await orchestrator.execute(ctx)
        
        # Verify execution order
        assert tracker.execution_order == [
            "data_readiness",
            "signal_check",
            "ev_gate",
            "execution_feasibility",
            "execution",
        ]
    
    @pytest.mark.asyncio
    async def test_no_signal_skips_policy_setting(self):
        """Test that no policy is set when there's no signal."""
        class NoSignalStage(Stage):
            name = "signal_check"
            async def run(self, ctx: StageContext) -> StageResult:
                # Don't set a signal
                return StageResult.CONTINUE
        
        execution_stage = MockExecutionStage()
        
        stages = [
            MockDataReadinessStage(),
            NoSignalStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"market_context": {"spread_percentile": 0.50}},
        )
        
        await orchestrator.execute(ctx)
        
        # No policy should be set
        assert execution_stage.received_policy is None
    
    @pytest.mark.asyncio
    async def test_custom_config_in_pipeline(self):
        """Test custom config works in pipeline context."""
        execution_stage = MockExecutionStage()
        
        custom_config = ExecutionFeasibilityConfig(
            maker_spread_threshold=0.20,
            taker_spread_threshold=0.80,
            default_maker_ttl_ms=10000,
            reduced_maker_ttl_ms=4000,
        )
        
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(config=custom_config),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {"spread_percentile": 0.15},  # Below custom threshold
            },
        )
        
        await orchestrator.execute(ctx)
        
        assert execution_stage.received_policy is not None
        assert execution_stage.received_policy.mode == "maker_first"
        assert execution_stage.received_policy.ttl_ms == 10000  # Custom TTL


class TestExecutionFeasibilityPipelineRejection:
    """Tests verifying ExecutionFeasibilityGate never rejects."""
    
    @pytest.mark.asyncio
    async def test_never_rejects_wide_spread(self):
        """Test that wide spread doesn't cause rejection."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            MockExecutionStage(),
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {"spread_percentile": 0.99},  # Very wide
            },
        )
        
        result = await orchestrator.execute(ctx)
        
        # Should complete, not reject
        assert result == StageResult.COMPLETE
        assert ctx.rejection_reason is None
    
    @pytest.mark.asyncio
    async def test_never_rejects_missing_market_context(self):
        """Test that missing market context doesn't cause rejection."""
        stages = [
            MockDataReadinessStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            MockExecutionStage(),
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={},  # No market_context
        )
        
        result = await orchestrator.execute(ctx)
        
        # Should complete, not reject
        assert result == StageResult.COMPLETE
        assert ctx.rejection_reason is None
