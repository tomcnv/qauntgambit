"""Unit tests for ParityChecker.

Feature: strategy-signal-architecture-fixes
Requirement 10: Backtest/Live Parity Guarantees

Tests for:
- 10.1.1: CRITICAL_CONFIGS list definition
- 10.1.2: compare_configs(backtest_config, live_config) implementation
- 10.1.3: ParityCheckResult with differences and warnings
- 10.3.1: Verify same stage implementations for backtest and live
- 10.3.2: Verify same fee model (not simplified)
- 10.3.3: Verify same slippage model (not zero slippage)
"""

import pytest

from quantgambit.backtesting.parity_checker import (
    ParityChecker,
    ParityCheckResult,
)


class TestParityCheckResult:
    """Tests for ParityCheckResult dataclass."""
    
    def test_parity_verified_true_when_no_differences(self):
        """ParityCheckResult should have parity_verified=True when no differences."""
        result = ParityCheckResult(parity_verified=True, differences=[], warnings=[])
        assert result.parity_verified is True
        assert len(result.differences) == 0
    
    def test_parity_verified_false_when_differences_exist(self):
        """ParityCheckResult should have parity_verified=False when differences exist."""
        result = ParityCheckResult(
            parity_verified=False,
            differences=["ev_gate.ev_min: backtest=0.05, live=0.10"],
            warnings=[],
        )
        assert result.parity_verified is False
        assert len(result.differences) == 1
    
    def test_str_representation_verified(self):
        """String representation should indicate verified status."""
        result = ParityCheckResult(parity_verified=True)
        assert "verified" in str(result).lower()
    
    def test_str_representation_failed(self):
        """String representation should show differences when failed."""
        result = ParityCheckResult(
            parity_verified=False,
            differences=["ev_gate.ev_min: backtest=0.05, live=0.10"],
        )
        assert "failed" in str(result).lower()
        assert "ev_gate.ev_min" in str(result)
    
    def test_str_truncates_many_differences(self):
        """String representation should truncate when many differences."""
        result = ParityCheckResult(
            parity_verified=False,
            differences=[f"config_{i}: backtest={i}, live={i+1}" for i in range(10)],
        )
        result_str = str(result)
        assert "and" in result_str
        assert "more" in result_str


class TestParityCheckerCriticalConfigs:
    """Tests for CRITICAL_CONFIGS list definition (Task 10.1.1)."""
    
    def test_critical_configs_contains_ev_gate_ev_min(self):
        """CRITICAL_CONFIGS should contain ev_gate.ev_min."""
        assert "ev_gate.ev_min" in ParityChecker.CRITICAL_CONFIGS
    
    def test_critical_configs_contains_ev_gate_ev_min_floor(self):
        """CRITICAL_CONFIGS should contain ev_gate.ev_min_floor."""
        assert "ev_gate.ev_min_floor" in ParityChecker.CRITICAL_CONFIGS
    
    def test_critical_configs_contains_threshold_calculator_k(self):
        """CRITICAL_CONFIGS should contain threshold_calculator.k."""
        assert "threshold_calculator.k" in ParityChecker.CRITICAL_CONFIGS
    
    def test_critical_configs_contains_threshold_calculator_b(self):
        """CRITICAL_CONFIGS should contain threshold_calculator.b."""
        assert "threshold_calculator.b" in ParityChecker.CRITICAL_CONFIGS
    
    def test_critical_configs_contains_threshold_calculator_floor_bps(self):
        """CRITICAL_CONFIGS should contain threshold_calculator.floor_bps."""
        assert "threshold_calculator.floor_bps" in ParityChecker.CRITICAL_CONFIGS
    
    def test_critical_configs_contains_fee_model_maker_fee_bps(self):
        """CRITICAL_CONFIGS should contain fee_model.maker_fee_bps."""
        assert "fee_model.maker_fee_bps" in ParityChecker.CRITICAL_CONFIGS
    
    def test_critical_configs_contains_fee_model_taker_fee_bps(self):
        """CRITICAL_CONFIGS should contain fee_model.taker_fee_bps."""
        assert "fee_model.taker_fee_bps" in ParityChecker.CRITICAL_CONFIGS
    
    def test_critical_configs_contains_slippage_model_base_slippage_bps(self):
        """CRITICAL_CONFIGS should contain slippage_model.base_slippage_bps."""
        assert "slippage_model.base_slippage_bps" in ParityChecker.CRITICAL_CONFIGS
    
    def test_critical_configs_has_expected_count(self):
        """CRITICAL_CONFIGS should have exactly 8 entries."""
        assert len(ParityChecker.CRITICAL_CONFIGS) == 8


class TestParityCheckerCompareConfigs:
    """Tests for compare_configs method (Task 10.1.2)."""
    
    def test_identical_configs_return_parity_verified(self):
        """Identical configs should return parity_verified=True."""
        checker = ParityChecker()
        
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
    
    def test_different_ev_min_returns_difference(self):
        """Different ev_gate.ev_min should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"ev_gate": {"ev_min": 0.05}}
        live_config = {"ev_gate": {"ev_min": 0.10}}
        
        result = checker.compare_configs(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("ev_gate.ev_min" in d for d in result.differences)
    
    def test_different_threshold_k_returns_difference(self):
        """Different threshold_calculator.k should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"threshold_calculator": {"k": 3.0}}
        live_config = {"threshold_calculator": {"k": 4.0}}
        
        result = checker.compare_configs(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("threshold_calculator.k" in d for d in result.differences)
    
    def test_different_fee_model_returns_difference(self):
        """Different fee_model.maker_fee_bps should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"fee_model": {"maker_fee_bps": 1.0}}
        live_config = {"fee_model": {"maker_fee_bps": 2.0}}
        
        result = checker.compare_configs(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("fee_model.maker_fee_bps" in d for d in result.differences)
    
    def test_different_slippage_returns_difference(self):
        """Different slippage_model.base_slippage_bps should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"slippage_model": {"base_slippage_bps": 1.0}}
        live_config = {"slippage_model": {"base_slippage_bps": 2.0}}
        
        result = checker.compare_configs(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("slippage_model.base_slippage_bps" in d for d in result.differences)
    
    def test_different_pipeline_stages_returns_difference(self):
        """Different pipeline_stages should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"pipeline_stages": ["DataReadiness", "EVGate"]}
        live_config = {"pipeline_stages": ["DataReadiness", "GlobalGate", "EVGate"]}
        
        result = checker.compare_configs(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("pipeline_stages" in d for d in result.differences)
    
    def test_missing_config_key_treated_as_none(self):
        """Missing config key should be treated as None."""
        checker = ParityChecker()
        
        backtest_config = {"ev_gate": {"ev_min": 0.05}}
        live_config = {}  # Missing ev_gate entirely
        
        result = checker.compare_configs(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("ev_gate.ev_min" in d for d in result.differences)
    
    def test_simplified_fee_model_generates_warning(self):
        """Simplified fee model should generate a warning."""
        checker = ParityChecker()
        
        backtest_config = {"fee_model": {"model_type": "simplified"}}
        live_config = {"fee_model": {"model_type": "simplified"}}
        
        result = checker.compare_configs(backtest_config, live_config)
        
        assert any("simplified" in w for w in result.warnings)
    
    def test_zero_slippage_generates_warning(self):
        """Zero slippage should generate a warning."""
        checker = ParityChecker()
        
        backtest_config = {"slippage_model": {"base_slippage_bps": 0}}
        live_config = {"slippage_model": {"base_slippage_bps": 0}}
        
        result = checker.compare_configs(backtest_config, live_config)
        
        assert any("slippage" in w.lower() for w in result.warnings)
    
    def test_multiple_differences_all_captured(self):
        """Multiple differences should all be captured."""
        checker = ParityChecker()
        
        backtest_config = {
            "ev_gate": {"ev_min": 0.05, "ev_min_floor": 0.02},
            "threshold_calculator": {"k": 3.0},
        }
        live_config = {
            "ev_gate": {"ev_min": 0.10, "ev_min_floor": 0.03},
            "threshold_calculator": {"k": 4.0},
        }
        
        result = checker.compare_configs(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert len(result.differences) >= 3


class TestParityCheckerGetNested:
    """Tests for _get_nested helper method."""
    
    def test_get_nested_single_level(self):
        """_get_nested should work for single-level keys."""
        checker = ParityChecker()
        config = {"key": "value"}
        
        result = checker._get_nested(config, "key")
        
        assert result == "value"
    
    def test_get_nested_two_levels(self):
        """_get_nested should work for two-level keys."""
        checker = ParityChecker()
        config = {"outer": {"inner": "value"}}
        
        result = checker._get_nested(config, "outer.inner")
        
        assert result == "value"
    
    def test_get_nested_three_levels(self):
        """_get_nested should work for three-level keys."""
        checker = ParityChecker()
        config = {"a": {"b": {"c": "value"}}}
        
        result = checker._get_nested(config, "a.b.c")
        
        assert result == "value"
    
    def test_get_nested_missing_key_returns_none(self):
        """_get_nested should return None for missing keys."""
        checker = ParityChecker()
        config = {"outer": {"inner": "value"}}
        
        result = checker._get_nested(config, "outer.missing")
        
        assert result is None
    
    def test_get_nested_non_dict_intermediate_returns_none(self):
        """_get_nested should return None when intermediate is not a dict."""
        checker = ParityChecker()
        config = {"outer": "not_a_dict"}
        
        result = checker._get_nested(config, "outer.inner")
        
        assert result is None


class TestParityCheckerVerifyStageImplementations:
    """Tests for verify_stage_implementations method (Task 10.3.1)."""
    
    def test_identical_stages_return_parity_verified(self):
        """Identical stage lists should return parity_verified=True."""
        checker = ParityChecker()
        
        stages = ["DataReadiness", "GlobalGate", "EVGate", "Execution"]
        
        result = checker.verify_stage_implementations(stages, stages)
        
        assert result.parity_verified is True
        assert len(result.differences) == 0
    
    def test_different_stage_order_returns_difference(self):
        """Different stage order should return a difference."""
        checker = ParityChecker()
        
        backtest_stages = ["DataReadiness", "EVGate", "GlobalGate"]
        live_stages = ["DataReadiness", "GlobalGate", "EVGate"]
        
        result = checker.verify_stage_implementations(backtest_stages, live_stages)
        
        assert result.parity_verified is False
        assert len(result.differences) >= 1
    
    def test_different_stage_count_returns_difference(self):
        """Different stage count should return a difference."""
        checker = ParityChecker()
        
        backtest_stages = ["DataReadiness", "EVGate"]
        live_stages = ["DataReadiness", "GlobalGate", "EVGate"]
        
        result = checker.verify_stage_implementations(backtest_stages, live_stages)
        
        assert result.parity_verified is False
        assert any("stage_count" in d for d in result.differences)
    
    def test_extra_backtest_stages_captured(self):
        """Extra stages in backtest should be captured."""
        checker = ParityChecker()
        
        backtest_stages = ["DataReadiness", "GlobalGate", "EVGate", "Extra"]
        live_stages = ["DataReadiness", "GlobalGate", "EVGate"]
        
        result = checker.verify_stage_implementations(backtest_stages, live_stages)
        
        assert result.parity_verified is False
        assert any("extra_backtest_stages" in d for d in result.differences)
    
    def test_extra_live_stages_captured(self):
        """Extra stages in live should be captured."""
        checker = ParityChecker()
        
        backtest_stages = ["DataReadiness", "GlobalGate"]
        live_stages = ["DataReadiness", "GlobalGate", "EVGate"]
        
        result = checker.verify_stage_implementations(backtest_stages, live_stages)
        
        assert result.parity_verified is False
        assert any("extra_live_stages" in d for d in result.differences)


class TestParityCheckerVerifyFeeModel:
    """Tests for verify_fee_model method (Task 10.3.2)."""
    
    def test_identical_fee_model_returns_parity_verified(self):
        """Identical fee models should return parity_verified=True."""
        checker = ParityChecker()
        
        config = {"model_type": "flat", "maker_fee_bps": 1.0, "taker_fee_bps": 2.0}
        
        result = checker.verify_fee_model(config, config)
        
        assert result.parity_verified is True
    
    def test_different_model_type_returns_difference(self):
        """Different model types should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"model_type": "flat"}
        live_config = {"model_type": "tiered"}
        
        result = checker.verify_fee_model(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("model_type" in d for d in result.differences)
    
    def test_simplified_fee_model_returns_difference(self):
        """Simplified fee model should return a difference (not allowed in parity mode)."""
        checker = ParityChecker()
        
        backtest_config = {"model_type": "simplified"}
        live_config = {"model_type": "flat"}
        
        result = checker.verify_fee_model(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("simplified" in d for d in result.differences)
    
    def test_zero_fee_model_returns_difference(self):
        """Zero fee model should return a difference (not allowed in parity mode)."""
        checker = ParityChecker()
        
        backtest_config = {"model_type": "zero"}
        live_config = {"model_type": "flat"}
        
        result = checker.verify_fee_model(backtest_config, live_config)
        
        assert result.parity_verified is False
    
    def test_different_maker_fee_returns_difference(self):
        """Different maker_fee_bps should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"maker_fee_bps": 1.0}
        live_config = {"maker_fee_bps": 2.0}
        
        result = checker.verify_fee_model(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("maker_fee_bps" in d for d in result.differences)
    
    def test_different_taker_fee_returns_difference(self):
        """Different taker_fee_bps should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"taker_fee_bps": 2.0}
        live_config = {"taker_fee_bps": 3.0}
        
        result = checker.verify_fee_model(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("taker_fee_bps" in d for d in result.differences)


class TestParityCheckerVerifySlippageModel:
    """Tests for verify_slippage_model method (Task 10.3.3)."""
    
    def test_identical_slippage_model_returns_parity_verified(self):
        """Identical slippage models should return parity_verified=True."""
        checker = ParityChecker()
        
        config = {"model_type": "flat", "base_slippage_bps": 1.5}
        
        result = checker.verify_slippage_model(config, config)
        
        assert result.parity_verified is True
    
    def test_different_model_type_returns_difference(self):
        """Different model types should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"model_type": "flat"}
        live_config = {"model_type": "volume_based"}
        
        result = checker.verify_slippage_model(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("model_type" in d for d in result.differences)
    
    def test_zero_slippage_with_live_nonzero_returns_difference(self):
        """Zero slippage in backtest with non-zero live should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"base_slippage_bps": 0}
        live_config = {"base_slippage_bps": 1.5}
        
        result = checker.verify_slippage_model(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("zero slippage" in d.lower() for d in result.differences)
    
    def test_different_slippage_bps_returns_difference(self):
        """Different base_slippage_bps should return a difference."""
        checker = ParityChecker()
        
        backtest_config = {"base_slippage_bps": 1.0}
        live_config = {"base_slippage_bps": 2.0}
        
        result = checker.verify_slippage_model(backtest_config, live_config)
        
        assert result.parity_verified is False
        assert any("base_slippage_bps" in d for d in result.differences)
    
    def test_both_zero_slippage_returns_parity_verified(self):
        """Both zero slippage should return parity_verified=True (both match)."""
        checker = ParityChecker()
        
        config = {"base_slippage_bps": 0}
        
        result = checker.verify_slippage_model(config, config)
        
        # Both are zero, so they match (even though zero is not recommended)
        assert result.parity_verified is True


class TestParityCheckerLogParitySummary:
    """Tests for log_parity_summary method."""
    
    def test_log_parity_summary_verified(self, caplog):
        """log_parity_summary should log success for verified result."""
        checker = ParityChecker()
        result = ParityCheckResult(parity_verified=True)
        
        # This should not raise
        checker.log_parity_summary(result, run_id="test-run")
    
    def test_log_parity_summary_failed(self, caplog):
        """log_parity_summary should log failure for failed result."""
        checker = ParityChecker()
        result = ParityCheckResult(
            parity_verified=False,
            differences=["ev_gate.ev_min: backtest=0.05, live=0.10"],
        )
        
        # This should not raise
        checker.log_parity_summary(result, run_id="test-run")
    
    def test_log_parity_summary_with_warnings(self, caplog):
        """log_parity_summary should log warnings."""
        checker = ParityChecker()
        result = ParityCheckResult(
            parity_verified=True,
            warnings=["slippage_model.base_slippage_bps=0 may not match live behavior"],
        )
        
        # This should not raise
        checker.log_parity_summary(result, run_id="test-run")
