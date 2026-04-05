"""
Unit tests for ExecutionFeasibilityGate.

Tests the execution feasibility gate that determines maker-first vs taker-only
execution policy based on market conditions.

Requirement 9.1: Run AFTER EVGate and BEFORE Execution
Requirement 9.3: When spread_percentile > 70% THEN recommend taker_only
Requirement 9.4: When spread_percentile <= 30% THEN recommend maker_first with full TTL
Requirement 9.5: When spread_percentile between 30-70% THEN recommend maker_first with reduced TTL
Requirement 9.7: Gate SHALL NOT reject signals - only sets execution policy
"""

import pytest
import os
from dataclasses import dataclass
from unittest.mock import patch

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.execution_feasibility_gate import (
    ExecutionFeasibilityGate,
    ExecutionFeasibilityConfig,
    ExecutionPolicy,
)


@pytest.fixture
def stage():
    """Create ExecutionFeasibilityGate with default config."""
    return ExecutionFeasibilityGate()


@pytest.fixture
def stage_with_config():
    """Create ExecutionFeasibilityGate with custom config."""
    config = ExecutionFeasibilityConfig(
        maker_spread_threshold=0.25,
        taker_spread_threshold=0.75,
        default_maker_ttl_ms=6000,
        reduced_maker_ttl_ms=3000,
        fallback_to_taker=False,
    )
    return ExecutionFeasibilityGate(config=config)


@pytest.fixture
def ctx():
    """Create a basic StageContext."""
    return StageContext(
        symbol="BTCUSDT",
        data={},
    )


@pytest.fixture
def ctx_with_signal():
    """Create StageContext with a signal."""
    return StageContext(
        symbol="BTCUSDT",
        data={},
        signal={"side": "long", "entry_price": 50000.0},
    )


class TestExecutionFeasibilityConfig:
    """Tests for ExecutionFeasibilityConfig."""
    
    def test_default_values(self):
        """Test default config values."""
        config = ExecutionFeasibilityConfig()
        
        assert config.maker_spread_threshold == 0.30
        assert config.taker_spread_threshold == 0.70
        assert config.default_maker_ttl_ms == 5000
        assert config.reduced_maker_ttl_ms == 2000
        assert config.fallback_to_taker is True
    
    def test_custom_values(self):
        """Test custom config values."""
        config = ExecutionFeasibilityConfig(
            maker_spread_threshold=0.20,
            taker_spread_threshold=0.80,
            default_maker_ttl_ms=10000,
            reduced_maker_ttl_ms=4000,
            fallback_to_taker=False,
        )
        
        assert config.maker_spread_threshold == 0.20
        assert config.taker_spread_threshold == 0.80
        assert config.default_maker_ttl_ms == 10000
        assert config.reduced_maker_ttl_ms == 4000
        assert config.fallback_to_taker is False
    
    def test_from_env(self):
        """Test config from environment variables."""
        env_vars = {
            "EXEC_FEASIBILITY_MAKER_SPREAD_THRESHOLD": "0.15",
            "EXEC_FEASIBILITY_TAKER_SPREAD_THRESHOLD": "0.85",
            "EXEC_FEASIBILITY_DEFAULT_MAKER_TTL_MS": "8000",
            "EXEC_FEASIBILITY_REDUCED_MAKER_TTL_MS": "3500",
            "EXEC_FEASIBILITY_FALLBACK_TO_TAKER": "false",
        }
        
        with patch.dict(os.environ, env_vars):
            config = ExecutionFeasibilityConfig.from_env()
        
        assert config.maker_spread_threshold == 0.15
        assert config.taker_spread_threshold == 0.85
        assert config.default_maker_ttl_ms == 8000
        assert config.reduced_maker_ttl_ms == 3500
        assert config.fallback_to_taker is False
    
    def test_from_env_defaults(self):
        """Test config from env uses defaults when vars not set."""
        # Clear any existing env vars
        env_vars = {}
        for key in [
            "EXEC_FEASIBILITY_MAKER_SPREAD_THRESHOLD",
            "EXEC_FEASIBILITY_TAKER_SPREAD_THRESHOLD",
            "EXEC_FEASIBILITY_DEFAULT_MAKER_TTL_MS",
            "EXEC_FEASIBILITY_REDUCED_MAKER_TTL_MS",
            "EXEC_FEASIBILITY_FALLBACK_TO_TAKER",
        ]:
            env_vars[key] = ""
        
        with patch.dict(os.environ, env_vars, clear=False):
            # Remove the keys entirely
            for key in env_vars:
                os.environ.pop(key, None)
            config = ExecutionFeasibilityConfig.from_env()
        
        assert config.maker_spread_threshold == 0.30
        assert config.taker_spread_threshold == 0.70


class TestExecutionPolicy:
    """Tests for ExecutionPolicy dataclass."""
    
    def test_maker_first_policy(self):
        """Test maker_first policy creation."""
        policy = ExecutionPolicy(
            mode="maker_first",
            ttl_ms=5000,
            fallback_to_taker=True,
            reason="tight_spread",
        )
        
        assert policy.mode == "maker_first"
        assert policy.ttl_ms == 5000
        assert policy.fallback_to_taker is True
        assert policy.reason == "tight_spread"
    
    def test_taker_only_policy(self):
        """Test taker_only policy creation."""
        policy = ExecutionPolicy(
            mode="taker_only",
            ttl_ms=0,
            fallback_to_taker=False,
            reason="wide_spread",
        )
        
        assert policy.mode == "taker_only"
        assert policy.ttl_ms == 0
        assert policy.fallback_to_taker is False
        assert policy.reason == "wide_spread"


class TestExecutionFeasibilityGate:
    """Tests for ExecutionFeasibilityGate stage."""
    
    @pytest.mark.asyncio
    async def test_no_signal_continues(self, stage, ctx):
        """Test stage continues when no signal present."""
        ctx.signal = None
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert "execution_policy" not in ctx.data
    
    @pytest.mark.asyncio
    async def test_never_rejects(self, stage, ctx_with_signal):
        """Test stage never rejects signals (Requirement 9.7)."""
        # Test with various spread percentiles
        for spread_pct in [0.0, 0.3, 0.5, 0.7, 0.9, 1.0]:
            ctx_with_signal.data["market_context"] = {"spread_percentile": spread_pct}
            
            result = await stage.run(ctx_with_signal)
            
            assert result == StageResult.CONTINUE
    
    @pytest.mark.asyncio
    async def test_wide_spread_taker_only(self, stage, ctx_with_signal):
        """Test taker_only when spread_percentile > 70% (Requirement 9.3)."""
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.75}
        
        result = await stage.run(ctx_with_signal)
        
        assert result == StageResult.CONTINUE
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.mode == "taker_only"
        assert policy.ttl_ms == 0
        assert policy.fallback_to_taker is False
        assert "0.75>0.7" in policy.reason
    
    @pytest.mark.asyncio
    async def test_tight_spread_maker_first_full_ttl(self, stage, ctx_with_signal):
        """Test maker_first with full TTL when spread_percentile <= 30% (Requirement 9.4)."""
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.25}
        
        result = await stage.run(ctx_with_signal)
        
        assert result == StageResult.CONTINUE
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.mode == "maker_first"
        assert policy.ttl_ms == 5000  # Default TTL
        assert policy.fallback_to_taker is True
        assert "0.25<=0.3" in policy.reason
    
    @pytest.mark.asyncio
    async def test_middle_spread_maker_first_reduced_ttl(self, stage, ctx_with_signal):
        """Test maker_first with reduced TTL when spread between 30-70% (Requirement 9.5)."""
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.50}
        
        result = await stage.run(ctx_with_signal)
        
        assert result == StageResult.CONTINUE
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.mode == "maker_first"
        assert policy.ttl_ms == 2000  # Reduced TTL
        assert policy.fallback_to_taker is True
        assert "middle_range" in policy.reason
    
    @pytest.mark.asyncio
    async def test_vol_shock_forced_taker(self, stage, ctx_with_signal):
        """Test taker_only when vol_shock forced taker upstream."""
        ctx_with_signal.data["force_taker"] = True
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.20}  # Tight spread
        
        result = await stage.run(ctx_with_signal)
        
        assert result == StageResult.CONTINUE
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.mode == "taker_only"
        assert policy.ttl_ms == 0
        assert policy.fallback_to_taker is False
        assert policy.reason == "vol_shock_forced_taker"
    
    @pytest.mark.asyncio
    async def test_boundary_at_maker_threshold(self, stage, ctx_with_signal):
        """Test exactly at maker threshold (30%)."""
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.30}
        
        result = await stage.run(ctx_with_signal)
        
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.mode == "maker_first"
        assert policy.ttl_ms == 5000  # Full TTL at boundary
    
    @pytest.mark.asyncio
    async def test_boundary_at_taker_threshold(self, stage, ctx_with_signal):
        """Test exactly at taker threshold (70%)."""
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.70}
        
        result = await stage.run(ctx_with_signal)
        
        policy = ctx_with_signal.data["execution_policy"]
        # At exactly 0.70, it's NOT > 0.70, so should be middle range
        assert policy.mode == "maker_first"
        assert policy.ttl_ms == 2000  # Reduced TTL
    
    @pytest.mark.asyncio
    async def test_just_above_taker_threshold(self, stage, ctx_with_signal):
        """Test just above taker threshold."""
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.71}
        
        result = await stage.run(ctx_with_signal)
        
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.mode == "taker_only"
    
    @pytest.mark.asyncio
    async def test_default_spread_percentile(self, stage, ctx_with_signal):
        """Test default spread_percentile when not in market_context."""
        ctx_with_signal.data["market_context"] = {}  # No spread_percentile
        
        result = await stage.run(ctx_with_signal)
        
        policy = ctx_with_signal.data["execution_policy"]
        # Default is 0.5, which is middle range
        assert policy.mode == "maker_first"
        assert policy.ttl_ms == 2000  # Reduced TTL
    
    @pytest.mark.asyncio
    async def test_no_market_context(self, stage, ctx_with_signal):
        """Test when market_context is missing entirely."""
        # No market_context in data
        
        result = await stage.run(ctx_with_signal)
        
        policy = ctx_with_signal.data["execution_policy"]
        # Default spread_percentile is 0.5
        assert policy.mode == "maker_first"
        assert policy.ttl_ms == 2000
    
    @pytest.mark.asyncio
    async def test_custom_config_thresholds(self, stage_with_config, ctx_with_signal):
        """Test custom config thresholds."""
        # Config has maker_threshold=0.25, taker_threshold=0.75
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.26}
        
        result = await stage_with_config.run(ctx_with_signal)
        
        policy = ctx_with_signal.data["execution_policy"]
        # 0.26 > 0.25 (maker threshold), so middle range
        assert policy.mode == "maker_first"
        assert policy.ttl_ms == 3000  # Custom reduced TTL
        assert policy.fallback_to_taker is False  # Custom config
    
    @pytest.mark.asyncio
    async def test_custom_config_ttl_values(self, stage_with_config, ctx_with_signal):
        """Test custom TTL values from config."""
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.20}
        
        result = await stage_with_config.run(ctx_with_signal)
        
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.ttl_ms == 6000  # Custom default TTL
    
    @pytest.mark.asyncio
    async def test_book_imbalance_in_context(self, stage, ctx_with_signal):
        """Test book_imbalance is read from context (for future use)."""
        ctx_with_signal.data["market_context"] = {
            "spread_percentile": 0.25,
            "book_imbalance": 0.3,
        }
        
        result = await stage.run(ctx_with_signal)
        
        # Currently book_imbalance is read but not used in decision
        # This test ensures it doesn't break anything
        assert result == StageResult.CONTINUE
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.mode == "maker_first"
    
    @pytest.mark.asyncio
    async def test_policy_stored_in_context(self, stage, ctx_with_signal):
        """Test execution policy is stored in ctx.data."""
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.50}
        
        result = await stage.run(ctx_with_signal)
        
        assert "execution_policy" in ctx_with_signal.data
        policy = ctx_with_signal.data["execution_policy"]
        assert isinstance(policy, ExecutionPolicy)
    
    def test_stage_name(self, stage):
        """Test stage has correct name."""
        assert stage.name == "execution_feasibility"


class TestExecutionFeasibilityGateEdgeCases:
    """Edge case tests for ExecutionFeasibilityGate."""
    
    @pytest.mark.asyncio
    async def test_spread_percentile_zero(self, stage, ctx_with_signal):
        """Test with spread_percentile = 0 (very tight spread)."""
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.0}
        
        result = await stage.run(ctx_with_signal)
        
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.mode == "maker_first"
        assert policy.ttl_ms == 5000
    
    @pytest.mark.asyncio
    async def test_spread_percentile_one(self, stage, ctx_with_signal):
        """Test with spread_percentile = 1 (very wide spread)."""
        ctx_with_signal.data["market_context"] = {"spread_percentile": 1.0}
        
        result = await stage.run(ctx_with_signal)
        
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.mode == "taker_only"
        assert policy.ttl_ms == 0
    
    @pytest.mark.asyncio
    async def test_force_taker_overrides_tight_spread(self, stage, ctx_with_signal):
        """Test force_taker overrides even very tight spread."""
        ctx_with_signal.data["force_taker"] = True
        ctx_with_signal.data["market_context"] = {"spread_percentile": 0.0}
        
        result = await stage.run(ctx_with_signal)
        
        policy = ctx_with_signal.data["execution_policy"]
        assert policy.mode == "taker_only"
        assert policy.reason == "vol_shock_forced_taker"
    
    @pytest.mark.asyncio
    async def test_signal_dict_format(self, stage, ctx):
        """Test with signal as dict."""
        ctx.signal = {"side": "long", "entry_price": 50000.0}
        ctx.data["market_context"] = {"spread_percentile": 0.50}
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert "execution_policy" in ctx.data
    
    @pytest.mark.asyncio
    async def test_signal_object_format(self, stage, ctx):
        """Test with signal as object."""
        @dataclass
        class MockSignal:
            side: str = "long"
            entry_price: float = 50000.0
        
        ctx.signal = MockSignal()
        ctx.data["market_context"] = {"spread_percentile": 0.50}
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert "execution_policy" in ctx.data
