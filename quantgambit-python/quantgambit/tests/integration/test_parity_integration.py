"""Integration tests for Backtest/Live Parity verification.

Feature: strategy-signal-architecture-fixes
Requirement 10: Backtest/Live Parity Guarantees

Tests for:
- 10.2.1: parity_mode: bool = True parameter
- 10.2.2: Raise ConfigurationError when parity_mode=True and configs differ
- 10.2.3: Log parity check summary at backtest start
- 10.2.4: parity_verified: bool in backtest results
- 10.3.1: Verify same stage implementations for backtest and live
- 10.3.2: Verify same fee model (not simplified)
- 10.3.3: Verify same slippage model (not zero slippage)
- 10.4: Integration tests for parity verification
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.backtesting.executor import (
    BacktestExecutor,
    ExecutorConfig,
    ExecutionResult,
    BacktestStatus,
)
from quantgambit.backtesting.parity_checker import (
    ParityChecker,
    ParityCheckResult,
)
from quantgambit.signals.pipeline import ConfigurationError


class TestExecutorConfigParityMode:
    """Tests for ExecutorConfig parity_mode parameter (Task 10.2.1)."""
    
    def test_parity_mode_default_is_true(self):
        """parity_mode should default to True."""
        config = ExecutorConfig()
        assert config.parity_mode is True
    
    def test_parity_mode_can_be_disabled(self):
        """parity_mode can be set to False."""
        config = ExecutorConfig(parity_mode=False)
        assert config.parity_mode is False
    
    def test_live_config_default_is_none(self):
        """live_config should default to None."""
        config = ExecutorConfig()
        assert config.live_config is None
    
    def test_live_config_can_be_set(self):
        """live_config can be set to a dictionary."""
        live_config = {"ev_gate": {"ev_min": 0.05}}
        config = ExecutorConfig(live_config=live_config)
        assert config.live_config == live_config


class TestExecutorParityCheck:
    """Tests for BacktestExecutor parity checking (Task 10.2.2, 10.2.3)."""
    
    def test_check_parity_skipped_when_disabled(self):
        """_check_parity should skip when parity_mode=False."""
        config = ExecutorConfig(parity_mode=False)
        executor = BacktestExecutor(
            db_pool=MagicMock(),
            redis_client=MagicMock(),
            config=config,
        )
        
        result = executor._check_parity({})
        
        assert result.parity_verified is True
    
    def test_check_parity_passes_with_matching_configs(self):
        """_check_parity should pass when configs match."""
        live_config = {
            "ev_gate": {"ev_min": 0.05, "ev_min_floor": 0.02},
            "threshold_calculator": {"k": 3.0, "b": 0.25, "floor_bps": 12.0},
            "fee_model": {"model_type": "flat", "maker_fee_bps": 1.0, "taker_fee_bps": 1.0},
            "slippage_model": {"model_type": "flat", "base_slippage_bps": 0.5},
            "pipeline_stages": [],
        }
        
        config = ExecutorConfig(
            parity_mode=True,
            live_config=live_config,
            fee_bps=1.0,
            fee_model="flat",
            slippage_bps=0.5,
            slippage_model="flat",
        )
        executor = BacktestExecutor(
            db_pool=MagicMock(),
            redis_client=MagicMock(),
            config=config,
        )
        
        backtest_config = {
            "ev_min": 0.05,
            "ev_min_floor": 0.02,
            "threshold_k": 3.0,
            "threshold_b": 0.25,
            "threshold_floor_bps": 12.0,
            "fee_bps": 1.0,
            "fee_model": "flat",
            "slippage_bps": 0.5,
            "slippage_model": "flat",
            "pipeline_stages": [],
        }
        
        result = executor._check_parity(backtest_config)
        
        assert result.parity_verified is True
    
    def test_check_parity_raises_on_mismatch(self):
        """_check_parity should raise ConfigurationError when configs differ."""
        live_config = {
            "ev_gate": {"ev_min": 0.10, "ev_min_floor": 0.02},  # Different ev_min
            "threshold_calculator": {"k": 3.0, "b": 0.25, "floor_bps": 12.0},
            "fee_model": {"model_type": "flat", "maker_fee_bps": 1.0, "taker_fee_bps": 1.0},
            "slippage_model": {"model_type": "flat", "base_slippage_bps": 0.5},
            "pipeline_stages": [],
        }
        
        config = ExecutorConfig(
            parity_mode=True,
            live_config=live_config,
            fee_bps=1.0,
            slippage_bps=0.5,
        )
        executor = BacktestExecutor(
            db_pool=MagicMock(),
            redis_client=MagicMock(),
            config=config,
        )
        
        backtest_config = {
            "ev_min": 0.05,  # Different from live
        }
        
        with pytest.raises(ConfigurationError) as exc_info:
            executor._check_parity(backtest_config)
        
        assert "parity" in str(exc_info.value).lower()
        assert "ev_gate.ev_min" in str(exc_info.value)
    
    def test_check_parity_raises_on_fee_model_mismatch(self):
        """_check_parity should raise when fee models differ."""
        live_config = {
            "ev_gate": {"ev_min": 0.05, "ev_min_floor": 0.02},
            "threshold_calculator": {"k": 3.0, "b": 0.25, "floor_bps": 12.0},
            "fee_model": {"model_type": "flat", "maker_fee_bps": 2.0, "taker_fee_bps": 2.0},
            "slippage_model": {"model_type": "flat", "base_slippage_bps": 0.5},
            "pipeline_stages": [],
        }
        
        config = ExecutorConfig(
            parity_mode=True,
            live_config=live_config,
            fee_bps=1.0,  # Different from live
            slippage_bps=0.5,
        )
        executor = BacktestExecutor(
            db_pool=MagicMock(),
            redis_client=MagicMock(),
            config=config,
        )
        
        backtest_config = {}
        
        with pytest.raises(ConfigurationError) as exc_info:
            executor._check_parity(backtest_config)
        
        assert "fee_model" in str(exc_info.value)
    
    def test_check_parity_raises_on_slippage_mismatch(self):
        """_check_parity should raise when slippage models differ."""
        live_config = {
            "ev_gate": {"ev_min": 0.05, "ev_min_floor": 0.02},
            "threshold_calculator": {"k": 3.0, "b": 0.25, "floor_bps": 12.0},
            "fee_model": {"model_type": "flat", "maker_fee_bps": 1.0, "taker_fee_bps": 1.0},
            "slippage_model": {"model_type": "flat", "base_slippage_bps": 2.0},
            "pipeline_stages": [],
        }
        
        config = ExecutorConfig(
            parity_mode=True,
            live_config=live_config,
            fee_bps=1.0,
            slippage_bps=0.5,  # Different from live
        )
        executor = BacktestExecutor(
            db_pool=MagicMock(),
            redis_client=MagicMock(),
            config=config,
        )
        
        backtest_config = {}
        
        with pytest.raises(ConfigurationError) as exc_info:
            executor._check_parity(backtest_config)
        
        assert "slippage" in str(exc_info.value).lower()


class TestExecutionResultParityVerified:
    """Tests for ExecutionResult parity_verified field (Task 10.2.4)."""
    
    def test_execution_result_has_parity_verified_field(self):
        """ExecutionResult should have parity_verified field."""
        result = ExecutionResult(
            run_id="test-run",
            status=BacktestStatus.FINISHED,
        )
        assert hasattr(result, "parity_verified")
    
    def test_execution_result_parity_verified_default_false(self):
        """ExecutionResult parity_verified should default to False."""
        result = ExecutionResult(
            run_id="test-run",
            status=BacktestStatus.FINISHED,
        )
        assert result.parity_verified is False
    
    def test_execution_result_parity_verified_can_be_true(self):
        """ExecutionResult parity_verified can be set to True."""
        result = ExecutionResult(
            run_id="test-run",
            status=BacktestStatus.FINISHED,
            parity_verified=True,
        )
        assert result.parity_verified is True


class TestParityCheckerStageVerification:
    """Tests for stage implementation verification (Task 10.3.1)."""
    
    def test_verify_identical_stages(self):
        """verify_stage_implementations should pass for identical stages."""
        checker = ParityChecker()
        
        stages = ["DataReadiness", "GlobalGate", "ProfileRouter", "EVGate"]
        
        result = checker.verify_stage_implementations(stages, stages)
        
        assert result.parity_verified is True
    
    def test_verify_different_stages_fails(self):
        """verify_stage_implementations should fail for different stages."""
        checker = ParityChecker()
        
        backtest_stages = ["DataReadiness", "EVGate"]
        live_stages = ["DataReadiness", "GlobalGate", "EVGate"]
        
        result = checker.verify_stage_implementations(backtest_stages, live_stages)
        
        assert result.parity_verified is False
    
    def test_verify_different_stage_order_fails(self):
        """verify_stage_implementations should fail for different stage order."""
        checker = ParityChecker()
        
        backtest_stages = ["DataReadiness", "EVGate", "GlobalGate"]
        live_stages = ["DataReadiness", "GlobalGate", "EVGate"]
        
        result = checker.verify_stage_implementations(backtest_stages, live_stages)
        
        assert result.parity_verified is False


class TestParityCheckerFeeModelVerification:
    """Tests for fee model verification (Task 10.3.2)."""
    
    def test_verify_identical_fee_model(self):
        """verify_fee_model should pass for identical fee models."""
        checker = ParityChecker()
        
        config = {"model_type": "flat", "maker_fee_bps": 1.0, "taker_fee_bps": 2.0}
        
        result = checker.verify_fee_model(config, config)
        
        assert result.parity_verified is True
    
    def test_verify_simplified_fee_model_fails(self):
        """verify_fee_model should fail for simplified fee model."""
        checker = ParityChecker()
        
        backtest_config = {"model_type": "simplified"}
        live_config = {"model_type": "flat"}
        
        result = checker.verify_fee_model(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("simplified" in d for d in result.differences)
    
    def test_verify_zero_fee_model_fails(self):
        """verify_fee_model should fail for zero fee model."""
        checker = ParityChecker()
        
        backtest_config = {"model_type": "zero"}
        live_config = {"model_type": "flat"}
        
        result = checker.verify_fee_model(backtest_config, live_config)
        
        assert result.parity_verified is False


class TestParityCheckerSlippageModelVerification:
    """Tests for slippage model verification (Task 10.3.3)."""
    
    def test_verify_identical_slippage_model(self):
        """verify_slippage_model should pass for identical slippage models."""
        checker = ParityChecker()
        
        config = {"model_type": "flat", "base_slippage_bps": 1.5}
        
        result = checker.verify_slippage_model(config, config)
        
        assert result.parity_verified is True
    
    def test_verify_zero_slippage_fails_when_live_nonzero(self):
        """verify_slippage_model should fail for zero slippage when live is non-zero."""
        checker = ParityChecker()
        
        backtest_config = {"base_slippage_bps": 0}
        live_config = {"base_slippage_bps": 1.5}
        
        result = checker.verify_slippage_model(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("zero slippage" in d.lower() for d in result.differences)
    
    def test_verify_different_slippage_fails(self):
        """verify_slippage_model should fail for different slippage values."""
        checker = ParityChecker()
        
        backtest_config = {"base_slippage_bps": 1.0}
        live_config = {"base_slippage_bps": 2.0}
        
        result = checker.verify_slippage_model(backtest_config, live_config)
        
        assert result.parity_verified is False


class TestBuildLiveConfig:
    """Tests for _build_live_config method."""
    
    def test_build_live_config_uses_executor_defaults(self):
        """_build_live_config should use executor config defaults."""
        config = ExecutorConfig(
            fee_bps=1.5,
            fee_model="tiered",
            slippage_bps=0.8,
            slippage_model="volume_based",
        )
        executor = BacktestExecutor(
            db_pool=MagicMock(),
            redis_client=MagicMock(),
            config=config,
        )
        
        live_config = executor._build_live_config()
        
        assert live_config["fee_model"]["model_type"] == "tiered"
        assert live_config["fee_model"]["maker_fee_bps"] == 1.5
        assert live_config["slippage_model"]["model_type"] == "volume_based"
        assert live_config["slippage_model"]["base_slippage_bps"] == 0.8


class TestBuildComparableConfig:
    """Tests for _build_comparable_config method."""
    
    def test_build_comparable_config_extracts_values(self):
        """_build_comparable_config should extract values from backtest config."""
        config = ExecutorConfig()
        executor = BacktestExecutor(
            db_pool=MagicMock(),
            redis_client=MagicMock(),
            config=config,
        )
        
        backtest_config = {
            "ev_min": 0.08,
            "ev_min_floor": 0.03,
            "threshold_k": 4.0,
            "threshold_b": 0.30,
            "threshold_floor_bps": 15.0,
            "fee_bps": 2.0,
            "fee_model": "tiered",
            "slippage_bps": 1.0,
            "slippage_model": "volume_based",
            "pipeline_stages": ["Stage1", "Stage2"],
        }
        
        comparable = executor._build_comparable_config(backtest_config)
        
        assert comparable["ev_gate"]["ev_min"] == 0.08
        assert comparable["ev_gate"]["ev_min_floor"] == 0.03
        assert comparable["threshold_calculator"]["k"] == 4.0
        assert comparable["threshold_calculator"]["b"] == 0.30
        assert comparable["threshold_calculator"]["floor_bps"] == 15.0
        assert comparable["fee_model"]["maker_fee_bps"] == 2.0
        assert comparable["fee_model"]["model_type"] == "tiered"
        assert comparable["slippage_model"]["base_slippage_bps"] == 1.0
        assert comparable["slippage_model"]["model_type"] == "volume_based"
        assert comparable["pipeline_stages"] == ["Stage1", "Stage2"]
    
    def test_build_comparable_config_uses_defaults(self):
        """_build_comparable_config should use defaults for missing values."""
        config = ExecutorConfig(
            fee_bps=1.0,
            fee_model="flat",
            slippage_bps=0.5,
            slippage_model="flat",
        )
        executor = BacktestExecutor(
            db_pool=MagicMock(),
            redis_client=MagicMock(),
            config=config,
        )
        
        backtest_config = {}  # Empty config
        
        comparable = executor._build_comparable_config(backtest_config)
        
        # Should use defaults
        assert comparable["ev_gate"]["ev_min"] == 0.05
        assert comparable["threshold_calculator"]["k"] == 3.0
        assert comparable["fee_model"]["maker_fee_bps"] == 1.0
        assert comparable["slippage_model"]["base_slippage_bps"] == 0.5


class TestParityIntegrationEndToEnd:
    """End-to-end integration tests for parity verification (Task 10.4)."""
    
    @pytest.mark.asyncio
    async def test_execute_with_parity_mode_disabled(self):
        """Execute should succeed with parity_mode=False even with mismatched configs."""
        # Create executor with parity mode disabled
        config = ExecutorConfig(
            parity_mode=False,
            fee_bps=1.0,
            slippage_bps=0.0,  # Zero slippage would fail parity check
        )
        
        # Mock dependencies
        db_pool = MagicMock()
        redis_client = MagicMock()
        
        executor = BacktestExecutor(
            db_pool=db_pool,
            redis_client=redis_client,
            config=config,
        )
        
        # Parity check should pass (skipped)
        result = executor._check_parity({})
        assert result.parity_verified is True
    
    def test_parity_check_with_all_critical_configs_matching(self):
        """Parity check should pass when all critical configs match."""
        checker = ParityChecker()
        
        # Create matching configs with all critical values
        config = {
            "ev_gate": {"ev_min": 0.05, "ev_min_floor": 0.02},
            "threshold_calculator": {"k": 3.0, "b": 0.25, "floor_bps": 12.0},
            "fee_model": {"maker_fee_bps": 1.0, "taker_fee_bps": 2.0},
            "slippage_model": {"base_slippage_bps": 1.5},
            "pipeline_stages": ["DataReadiness", "GlobalGate", "EVGate"],
        }
        
        result = checker.compare_configs(config, config)
        
        assert result.parity_verified is True
        assert len(result.differences) == 0
    
    def test_parity_check_detects_all_critical_config_differences(self):
        """Parity check should detect differences in all critical configs."""
        checker = ParityChecker()
        
        backtest_config = {
            "ev_gate": {"ev_min": 0.05, "ev_min_floor": 0.02},
            "threshold_calculator": {"k": 3.0, "b": 0.25, "floor_bps": 12.0},
            "fee_model": {"maker_fee_bps": 1.0, "taker_fee_bps": 2.0},
            "slippage_model": {"base_slippage_bps": 1.5},
        }
        
        live_config = {
            "ev_gate": {"ev_min": 0.10, "ev_min_floor": 0.03},  # Different
            "threshold_calculator": {"k": 4.0, "b": 0.30, "floor_bps": 15.0},  # Different
            "fee_model": {"maker_fee_bps": 2.0, "taker_fee_bps": 3.0},  # Different
            "slippage_model": {"base_slippage_bps": 2.0},  # Different
        }
        
        result = checker.compare_configs(backtest_config, live_config)
        
        assert result.parity_verified is False
        # Should have multiple differences
        assert len(result.differences) >= 4
