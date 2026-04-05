"""
Integration tests for Vol Shock Conditional Gate in the pipeline.

Tests the integration of conditional vol shock handling with other pipeline stages.

Requirement 6: Vol Shock Conditional Gate
- 6.1: NEVER hard reject on vol_shock
- 6.2: Apply conditional logic based on strategy type
- 6.3: Force taker-only when spread_percentile > 80%
- 6.4: Allow maker-first with reduced TTL otherwise
- 6.5: Set ctx.data["vol_shock_active"] = True for downstream stages
"""

import asyncio
import time
import pytest
from dataclasses import dataclass
from typing import Optional, List

from quantgambit.signals.pipeline import (
    Stage,
    StageContext,
    StageResult,
    Orchestrator,
)
from quantgambit.signals.stages.global_gate import (
    GlobalGateStage,
    GlobalGateConfig,
    VolShockConfig,
)
from quantgambit.signals.stages.execution_feasibility_gate import (
    ExecutionFeasibilityGate,
    ExecutionPolicy,
)
from quantgambit.deeptrader_core.types import MarketSnapshot


# =============================================================================
# Mock Stages for Integration Testing
# =============================================================================

class MockDataReadinessStage(Stage):
    name = "data_readiness"
    
    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


class MockSnapshotBuilderStage(Stage):
    """Mock snapshot builder that creates a snapshot from ctx.data."""
    name = "snapshot_builder"
    
    async def run(self, ctx: StageContext) -> StageResult:
        # Snapshot should already be in ctx.data for these tests
        return StageResult.CONTINUE


class MockProfileRouterStage(Stage):
    """Mock profile router that sets strategy type."""
    name = "profile_router"
    
    def __init__(self, strategy_type: str = "mean_reversion"):
        self.strategy_type = strategy_type
    
    async def run(self, ctx: StageContext) -> StageResult:
        ctx.data["strategy_type"] = self.strategy_type
        ctx.data["profile_params"] = {"strategy_type": self.strategy_type}
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
    """Mock EVGate that checks vol_shock_ev_multiplier."""
    name = "ev_gate"
    
    def __init__(self):
        self.received_ev_multiplier: Optional[float] = None
    
    async def run(self, ctx: StageContext) -> StageResult:
        # Record the EV multiplier for verification
        self.received_ev_multiplier = ctx.data.get("vol_shock_ev_multiplier")
        return StageResult.CONTINUE


class MockExecutionStage(Stage):
    """Mock execution stage that records execution policy and vol shock data."""
    name = "execution"
    
    def __init__(self):
        self.received_policy: Optional[ExecutionPolicy] = None
        self.vol_shock_active: Optional[bool] = None
        self.force_taker: Optional[bool] = None
        self.maker_ttl_ms: Optional[int] = None
        self.size_factor: Optional[float] = None
    
    async def run(self, ctx: StageContext) -> StageResult:
        # Record all vol shock related data
        self.received_policy = ctx.data.get("execution_policy")
        self.vol_shock_active = ctx.data.get("vol_shock_active")
        self.force_taker = ctx.data.get("force_taker")
        self.maker_ttl_ms = ctx.data.get("maker_ttl_ms")
        self.size_factor = ctx.data.get("size_factor")
        return StageResult.COMPLETE


class ExecutionOrderTracker:
    """Tracks the order of stage execution."""
    
    def __init__(self):
        self.execution_order: List[str] = []
    
    def record(self, stage_name: str):
        self.execution_order.append(stage_name)


def make_snapshot(**overrides) -> MarketSnapshot:
    """Create test snapshot with overrides."""
    defaults = {
        "symbol": "BTCUSDT",
        "exchange": "bybit",
        "timestamp_ns": int(time.time() * 1e9),
        "snapshot_age_ms": 50.0,
        "mid_price": 50000.0,
        "bid": 49999.0,
        "ask": 50001.0,
        "spread_bps": 4.0,
        "bid_depth_usd": 100000.0,
        "ask_depth_usd": 100000.0,
        "depth_imbalance": 0.0,
        "imb_1s": 0.0,
        "imb_5s": 0.0,
        "imb_30s": 0.0,
        "orderflow_persistence_sec": 0.0,
        "rv_1s": 0.01,
        "rv_10s": 0.005,
        "rv_1m": 0.003,
        "vol_shock": False,
        "vol_regime": "normal",
        "vol_regime_score": 0.5,
        "trend_direction": "neutral",
        "trend_strength": 0.0,
        "poc_price": 49950.0,
        "vah_price": 50100.0,
        "val_price": 49800.0,
        "position_in_value": "inside",
        "expected_fill_slippage_bps": 2.0,
        "typical_spread_bps": 3.5,
        "data_quality_score": 0.95,
        "ws_connected": True,
    }
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


# =============================================================================
# Integration Tests
# =============================================================================

class TestVolShockPipelineIntegration:
    """Integration tests for vol shock handling in pipeline."""
    
    @pytest.mark.asyncio
    async def test_vol_shock_propagates_to_downstream_stages(self):
        """Test that vol shock data propagates through the pipeline."""
        execution_stage = MockExecutionStage()
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(),  # Vol shock handling here
            MockProfileRouterStage(strategy_type="mean_reversion"),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.50},
            },
        )
        
        result = await orchestrator.execute(ctx)
        
        assert result == StageResult.COMPLETE
        # Vol shock data should propagate to execution
        assert execution_stage.vol_shock_active is True
        assert execution_stage.size_factor == 0.50  # mean_reversion multiplier
    
    @pytest.mark.asyncio
    async def test_vol_shock_ev_multiplier_reaches_ev_gate(self):
        """Test that EV multiplier is available to EVGate."""
        ev_gate = MockEVGateStage()
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(),
            MockProfileRouterStage(strategy_type="breakout"),
            MockSignalCheckStage(),
            ev_gate,
            MockExecutionStage(),
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.50},
                # Strategy type must be set before GlobalGate runs
                "strategy_type": "breakout",
            },
        )
        
        await orchestrator.execute(ctx)
        
        # EVGate should receive the EV multiplier
        assert ev_gate.received_ev_multiplier == 1.25  # breakout multiplier
    
    @pytest.mark.asyncio
    async def test_vol_shock_force_taker_propagates_to_execution_feasibility(self):
        """Test that force_taker from vol shock is respected by ExecutionFeasibilityGate."""
        execution_stage = MockExecutionStage()
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(),
            MockProfileRouterStage(strategy_type="mean_reversion"),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.85},  # Wide spread
            },
        )
        
        await orchestrator.execute(ctx)
        
        # ExecutionFeasibilityGate should see force_taker and set taker_only policy
        assert execution_stage.received_policy is not None
        assert execution_stage.received_policy.mode == "taker_only"
        assert execution_stage.received_policy.reason == "vol_shock_forced_taker"
    
    @pytest.mark.asyncio
    async def test_vol_shock_maker_ttl_propagates(self):
        """Test that reduced maker TTL propagates when spread is acceptable."""
        execution_stage = MockExecutionStage()
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(),
            MockProfileRouterStage(strategy_type="mean_reversion"),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.50},  # Acceptable spread
            },
        )
        
        await orchestrator.execute(ctx)
        
        # maker_ttl_ms should be set to reduced value
        assert execution_stage.maker_ttl_ms == 2000
        assert execution_stage.force_taker is None
    
    @pytest.mark.asyncio
    async def test_no_vol_shock_normal_flow(self):
        """Test that normal flow works without vol shock."""
        execution_stage = MockExecutionStage()
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(),
            MockProfileRouterStage(strategy_type="mean_reversion"),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=False),
                "market_context": {"spread_percentile": 0.50},
            },
        )
        
        await orchestrator.execute(ctx)
        
        # No vol shock data should be set
        assert execution_stage.vol_shock_active is None
        assert execution_stage.size_factor == 1.0  # No reduction


class TestVolShockStrategyTypeIntegration:
    """Integration tests for strategy-specific vol shock handling."""
    
    @pytest.mark.asyncio
    async def test_mean_reversion_strategy_multipliers(self):
        """Test mean_reversion strategy gets correct multipliers."""
        execution_stage = MockExecutionStage()
        ev_gate = MockEVGateStage()
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(),
            MockProfileRouterStage(strategy_type="mean_reversion"),
            MockSignalCheckStage(),
            ev_gate,
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.50},
            },
        )
        
        await orchestrator.execute(ctx)
        
        assert execution_stage.size_factor == 0.50
        assert ev_gate.received_ev_multiplier == 1.50
    
    @pytest.mark.asyncio
    async def test_breakout_strategy_multipliers(self):
        """Test breakout strategy gets correct multipliers (less conservative)."""
        execution_stage = MockExecutionStage()
        ev_gate = MockEVGateStage()
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(),
            MockProfileRouterStage(strategy_type="breakout"),
            MockSignalCheckStage(),
            ev_gate,
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.50},
                # Strategy type must be set before GlobalGate runs
                "strategy_type": "breakout",
            },
        )
        
        await orchestrator.execute(ctx)
        
        # Breakout should have less conservative multipliers
        assert execution_stage.size_factor == 0.75
        assert ev_gate.received_ev_multiplier == 1.25
    
    @pytest.mark.asyncio
    async def test_trend_pullback_strategy_multipliers(self):
        """Test trend_pullback strategy gets correct multipliers."""
        execution_stage = MockExecutionStage()
        ev_gate = MockEVGateStage()
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(),
            MockProfileRouterStage(strategy_type="trend_pullback"),
            MockSignalCheckStage(),
            ev_gate,
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.50},
                # Strategy type must be set before GlobalGate runs
                "strategy_type": "trend_pullback",
            },
        )
        
        await orchestrator.execute(ctx)
        
        assert execution_stage.size_factor == 0.70
        assert ev_gate.received_ev_multiplier == 1.30


class TestVolShockNeverRejects:
    """Tests verifying vol shock NEVER causes hard rejection (Requirement 6.1)."""
    
    @pytest.mark.asyncio
    async def test_vol_shock_never_rejects_default_config(self):
        """Test that vol shock never rejects with default config."""
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(),  # Default config has block_on_vol_shock=False
            MockProfileRouterStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            MockExecutionStage(),
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.99},  # Very wide spread
            },
        )
        
        result = await orchestrator.execute(ctx)
        
        # Should complete, not reject
        assert result == StageResult.COMPLETE
        assert ctx.rejection_reason is None
    
    @pytest.mark.asyncio
    async def test_vol_shock_with_all_adverse_conditions(self):
        """Test that vol shock doesn't reject even with all adverse conditions."""
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(),
            MockProfileRouterStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            MockExecutionStage(),
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(
                    vol_shock=True,
                    spread_bps=8.0,  # Wide but not over max
                ),
                "market_context": {
                    "spread_percentile": 0.95,
                    "data_quality_score": 0.6,
                },
            },
        )
        
        result = await orchestrator.execute(ctx)
        
        # Should complete, not reject
        assert result == StageResult.COMPLETE
        assert ctx.rejection_reason is None


class TestVolShockCustomConfig:
    """Tests for custom vol shock configuration in pipeline."""
    
    @pytest.mark.asyncio
    async def test_custom_multipliers_in_pipeline(self):
        """Test custom multipliers work in pipeline context."""
        execution_stage = MockExecutionStage()
        ev_gate = MockEVGateStage()
        
        custom_vol_shock_config = VolShockConfig(
            size_multiplier_by_strategy={"mean_reversion": 0.30, "default": 0.40},
            ev_multiplier_by_strategy={"mean_reversion": 2.00, "default": 1.80},
            spread_threshold_for_taker=0.70,
            reduced_maker_ttl_ms=1500,
        )
        global_gate_config = GlobalGateConfig(vol_shock_config=custom_vol_shock_config)
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(config=global_gate_config),
            MockProfileRouterStage(strategy_type="mean_reversion"),
            MockSignalCheckStage(),
            ev_gate,
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.60},  # Below custom threshold
                # Strategy type must be set before GlobalGate runs
                "strategy_type": "mean_reversion",
            },
        )
        
        await orchestrator.execute(ctx)
        
        # Custom multipliers should be applied
        assert execution_stage.size_factor == 0.30
        assert ev_gate.received_ev_multiplier == 2.00
        assert execution_stage.maker_ttl_ms == 1500
    
    @pytest.mark.asyncio
    async def test_custom_spread_threshold_forces_taker(self):
        """Test custom spread threshold for forcing taker."""
        execution_stage = MockExecutionStage()
        
        custom_vol_shock_config = VolShockConfig(
            spread_threshold_for_taker=0.60,  # Lower threshold
        )
        global_gate_config = GlobalGateConfig(vol_shock_config=custom_vol_shock_config)
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(config=global_gate_config),
            MockProfileRouterStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            ExecutionFeasibilityGate(),
            execution_stage,
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.65},  # Above custom threshold
            },
        )
        
        await orchestrator.execute(ctx)
        
        # Should force taker due to custom threshold
        assert execution_stage.force_taker is True
        assert execution_stage.received_policy.mode == "taker_only"


class TestVolShockLegacyBehavior:
    """Tests for legacy vol shock behavior when explicitly enabled."""
    
    @pytest.mark.asyncio
    async def test_legacy_hard_reject_when_enabled(self):
        """Test that legacy hard reject works when block_on_vol_shock=True."""
        config = GlobalGateConfig(block_on_vol_shock=True)
        
        stages = [
            MockDataReadinessStage(),
            GlobalGateStage(config=config),
            MockProfileRouterStage(),
            MockSignalCheckStage(),
            MockEVGateStage(),
            MockExecutionStage(),
        ]
        
        orchestrator = Orchestrator(stages, validate_ordering=False)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.50},
            },
        )
        
        result = await orchestrator.execute(ctx)
        
        # Should reject with legacy behavior
        assert result == StageResult.REJECT
        assert "vol_shock" in ctx.rejection_reason
