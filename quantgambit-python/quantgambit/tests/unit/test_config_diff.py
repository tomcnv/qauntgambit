"""Unit tests for ConfigDiffEngine.

Feature: trading-pipeline-integration
Requirements: 1.3, 1.4
"""

from datetime import datetime, timezone

import pytest

from quantgambit.integration.config_diff import (
    ConfigDiff,
    ConfigDiffEngine,
    CRITICAL_PARAMS,
    WARNING_PARAMS,
)
from quantgambit.integration.config_version import ConfigVersion


class TestConfigDiff:
    """Tests for ConfigDiff dataclass."""
    
    def test_empty_diff_has_no_diffs(self):
        """Empty diff should report no differences."""
        diff = ConfigDiff(
            source_version="v1",
            target_version="v2",
            critical_diffs=[],
            warning_diffs=[],
            info_diffs=[],
        )
        
        assert not diff.has_critical_diffs
        assert not diff.has_any_diffs
        assert diff.total_diffs == 0
    
    def test_critical_diff_detection(self):
        """Diff with critical differences should be detected."""
        diff = ConfigDiff(
            source_version="v1",
            target_version="v2",
            critical_diffs=[("fee_rate", 0.001, 0.002)],
            warning_diffs=[],
            info_diffs=[],
        )
        
        assert diff.has_critical_diffs
        assert diff.has_any_diffs
        assert diff.total_diffs == 1
    
    def test_warning_diff_detection(self):
        """Diff with warning differences should be detected."""
        diff = ConfigDiff(
            source_version="v1",
            target_version="v2",
            critical_diffs=[],
            warning_diffs=[("cooldown_sec", 60, 120)],
            info_diffs=[],
        )
        
        assert not diff.has_critical_diffs
        assert diff.has_any_diffs
        assert diff.total_diffs == 1
    
    def test_info_diff_detection(self):
        """Diff with info differences should be detected."""
        diff = ConfigDiff(
            source_version="v1",
            target_version="v2",
            critical_diffs=[],
            warning_diffs=[],
            info_diffs=[("description", "old", "new")],
        )
        
        assert not diff.has_critical_diffs
        assert diff.has_any_diffs
        assert diff.total_diffs == 1
    
    def test_total_diffs_counts_all(self):
        """Total diffs should count all categories."""
        diff = ConfigDiff(
            source_version="v1",
            target_version="v2",
            critical_diffs=[("fee_rate", 0.001, 0.002)],
            warning_diffs=[("cooldown_sec", 60, 120)],
            info_diffs=[("description", "old", "new"), ("name", "a", "b")],
        )
        
        assert diff.total_diffs == 4
    
    def test_to_dict_serialization(self):
        """to_dict should serialize all fields correctly."""
        diff = ConfigDiff(
            source_version="v1",
            target_version="v2",
            critical_diffs=[("fee_rate", 0.001, 0.002)],
            warning_diffs=[("cooldown_sec", 60, 120)],
            info_diffs=[],
        )
        
        result = diff.to_dict()
        
        assert result["source_version"] == "v1"
        assert result["target_version"] == "v2"
        assert len(result["critical_diffs"]) == 1
        assert result["critical_diffs"][0] == {"key": "fee_rate", "old": 0.001, "new": 0.002}
        assert len(result["warning_diffs"]) == 1
        assert result["warning_diffs"][0] == {"key": "cooldown_sec", "old": 60, "new": 120}
        assert result["has_critical_diffs"] is True
        assert result["total_diffs"] == 2
    
    def test_format_report_with_diffs(self):
        """format_report should produce readable output."""
        diff = ConfigDiff(
            source_version="live_v1",
            target_version="backtest_v2",
            critical_diffs=[("fee_rate", 0.001, 0.002)],
            warning_diffs=[("cooldown_sec", 60, 120)],
            info_diffs=[("description", "old", "new")],
        )
        
        report = diff.format_report()
        
        assert "Configuration Diff Report" in report
        assert "live_v1" in report
        assert "backtest_v2" in report
        assert "CRITICAL DIFFERENCES" in report
        assert "fee_rate" in report
        assert "WARNING DIFFERENCES" in report
        assert "cooldown_sec" in report
        assert "INFO DIFFERENCES" in report
        assert "description" in report
    
    def test_format_report_no_diffs(self):
        """format_report should indicate no differences when empty."""
        diff = ConfigDiff(
            source_version="v1",
            target_version="v2",
            critical_diffs=[],
            warning_diffs=[],
            info_diffs=[],
        )
        
        report = diff.format_report()
        
        assert "No differences found" in report


class TestConfigDiffEngine:
    """Tests for ConfigDiffEngine."""
    
    @pytest.fixture
    def engine(self):
        """Create a ConfigDiffEngine instance."""
        return ConfigDiffEngine()
    
    @pytest.fixture
    def base_config(self):
        """Create a base ConfigVersion for testing."""
        return ConfigVersion.create(
            version_id="live_v1",
            created_by="live",
            parameters={
                "fee_rate": 0.001,
                "slippage_bps": 5.0,
                "position_size_pct": 0.1,
                "cooldown_sec": 60,
                "min_volume": 1000,
                "description": "Test config",
            },
        )
    
    def test_identical_configs_no_diffs(self, engine, base_config):
        """Identical configs should produce no differences."""
        target = ConfigVersion.create(
            version_id="backtest_v1",
            created_by="backtest",
            parameters=base_config.parameters.copy(),
        )
        
        diff = engine.compare(base_config, target)
        
        assert not diff.has_any_diffs
        assert diff.total_diffs == 0
    
    def test_critical_param_categorization(self, engine, base_config):
        """Critical parameters should be categorized correctly."""
        target = ConfigVersion.create(
            version_id="backtest_v1",
            created_by="backtest",
            parameters={
                **base_config.parameters,
                "fee_rate": 0.002,  # Changed critical param
            },
        )
        
        diff = engine.compare(base_config, target)
        
        assert diff.has_critical_diffs
        assert len(diff.critical_diffs) == 1
        assert diff.critical_diffs[0][0] == "fee_rate"
        assert diff.critical_diffs[0][1] == 0.001
        assert diff.critical_diffs[0][2] == 0.002
    
    def test_warning_param_categorization(self, engine, base_config):
        """Warning parameters should be categorized correctly."""
        target = ConfigVersion.create(
            version_id="backtest_v1",
            created_by="backtest",
            parameters={
                **base_config.parameters,
                "cooldown_sec": 120,  # Changed warning param
            },
        )
        
        diff = engine.compare(base_config, target)
        
        assert not diff.has_critical_diffs
        assert len(diff.warning_diffs) == 1
        assert diff.warning_diffs[0][0] == "cooldown_sec"
    
    def test_info_param_categorization(self, engine, base_config):
        """Non-critical/warning parameters should be info level."""
        target = ConfigVersion.create(
            version_id="backtest_v1",
            created_by="backtest",
            parameters={
                **base_config.parameters,
                "description": "Updated config",  # Changed info param
            },
        )
        
        diff = engine.compare(base_config, target)
        
        assert not diff.has_critical_diffs
        assert len(diff.warning_diffs) == 0
        assert len(diff.info_diffs) == 1
        assert diff.info_diffs[0][0] == "description"
    
    def test_multiple_diff_categories(self, engine, base_config):
        """Multiple changes should be categorized correctly."""
        target = ConfigVersion.create(
            version_id="backtest_v1",
            created_by="backtest",
            parameters={
                **base_config.parameters,
                "fee_rate": 0.002,  # Critical
                "slippage_bps": 10.0,  # Critical
                "cooldown_sec": 120,  # Warning
                "min_volume": 2000,  # Warning
                "description": "Updated",  # Info
            },
        )
        
        diff = engine.compare(base_config, target)
        
        assert len(diff.critical_diffs) == 2
        assert len(diff.warning_diffs) == 2
        assert len(diff.info_diffs) == 1
        assert diff.total_diffs == 5
    
    def test_missing_param_in_target(self, engine, base_config):
        """Missing parameter in target should be detected."""
        target_params = base_config.parameters.copy()
        del target_params["fee_rate"]
        
        target = ConfigVersion.create(
            version_id="backtest_v1",
            created_by="backtest",
            parameters=target_params,
        )
        
        diff = engine.compare(base_config, target)
        
        assert diff.has_critical_diffs
        assert len(diff.critical_diffs) == 1
        assert diff.critical_diffs[0] == ("fee_rate", 0.001, None)
    
    def test_new_param_in_target(self, engine, base_config):
        """New parameter in target should be detected."""
        target = ConfigVersion.create(
            version_id="backtest_v1",
            created_by="backtest",
            parameters={
                **base_config.parameters,
                "new_param": "value",
            },
        )
        
        diff = engine.compare(base_config, target)
        
        assert diff.has_any_diffs
        assert len(diff.info_diffs) == 1
        assert diff.info_diffs[0] == ("new_param", None, "value")
    
    def test_nested_param_categorization(self, engine):
        """Nested parameters should be categorized by their suffix."""
        source = ConfigVersion.create(
            version_id="v1",
            created_by="live",
            parameters={"strategy.fee_rate": 0.001},
        )
        target = ConfigVersion.create(
            version_id="v2",
            created_by="backtest",
            parameters={"strategy.fee_rate": 0.002},
        )
        
        diff = engine.compare(source, target)
        
        # Should be critical because suffix is "fee_rate"
        assert diff.has_critical_diffs
        assert diff.critical_diffs[0][0] == "strategy.fee_rate"
    
    def test_float_comparison_tolerance(self, engine):
        """Float values with tiny differences should be considered equal."""
        source = ConfigVersion.create(
            version_id="v1",
            created_by="live",
            parameters={"value": 0.1},
        )
        target = ConfigVersion.create(
            version_id="v2",
            created_by="backtest",
            parameters={"value": 0.1 + 1e-15},  # Tiny difference
        )
        
        diff = engine.compare(source, target)
        
        assert not diff.has_any_diffs
    
    def test_int_float_comparison(self, engine):
        """Int and float with same value should be considered equal."""
        source = ConfigVersion.create(
            version_id="v1",
            created_by="live",
            parameters={"value": 10},
        )
        target = ConfigVersion.create(
            version_id="v2",
            created_by="backtest",
            parameters={"value": 10.0},
        )
        
        diff = engine.compare(source, target)
        
        assert not diff.has_any_diffs
    
    def test_dict_comparison(self, engine):
        """Nested dict values should be compared correctly."""
        source = ConfigVersion.create(
            version_id="v1",
            created_by="live",
            parameters={"nested": {"a": 1, "b": 2}},
        )
        target = ConfigVersion.create(
            version_id="v2",
            created_by="backtest",
            parameters={"nested": {"a": 1, "b": 3}},  # b changed
        )
        
        diff = engine.compare(source, target)
        
        assert diff.has_any_diffs
        assert len(diff.info_diffs) == 1
    
    def test_list_comparison(self, engine):
        """List values should be compared correctly."""
        source = ConfigVersion.create(
            version_id="v1",
            created_by="live",
            parameters={"items": [1, 2, 3]},
        )
        target = ConfigVersion.create(
            version_id="v2",
            created_by="backtest",
            parameters={"items": [1, 2, 4]},  # Last item changed
        )
        
        diff = engine.compare(source, target)
        
        assert diff.has_any_diffs
    
    def test_compare_dicts_method(self, engine):
        """compare_dicts should work with raw dictionaries."""
        source_params = {"fee_rate": 0.001, "cooldown_sec": 60}
        target_params = {"fee_rate": 0.002, "cooldown_sec": 60}
        
        diff = engine.compare_dicts(
            source_params,
            target_params,
            source_version="live",
            target_version="backtest",
        )
        
        assert diff.source_version == "live"
        assert diff.target_version == "backtest"
        assert diff.has_critical_diffs
        assert len(diff.critical_diffs) == 1
    
    def test_custom_critical_params(self):
        """Custom critical params should be used."""
        engine = ConfigDiffEngine(
            critical_params=["custom_critical"],
            warning_params=["custom_warning"],
        )
        
        source = ConfigVersion.create(
            version_id="v1",
            created_by="live",
            parameters={"custom_critical": 1, "fee_rate": 0.001},
        )
        target = ConfigVersion.create(
            version_id="v2",
            created_by="backtest",
            parameters={"custom_critical": 2, "fee_rate": 0.002},
        )
        
        diff = engine.compare(source, target)
        
        # custom_critical should be critical, fee_rate should be info
        assert len(diff.critical_diffs) == 1
        assert diff.critical_diffs[0][0] == "custom_critical"
        assert len(diff.info_diffs) == 1
        assert diff.info_diffs[0][0] == "fee_rate"
    
    def test_add_critical_param(self, engine):
        """Adding a critical param should affect categorization."""
        engine.add_critical_param("my_custom_param")
        
        source = ConfigVersion.create(
            version_id="v1",
            created_by="live",
            parameters={"my_custom_param": 1},
        )
        target = ConfigVersion.create(
            version_id="v2",
            created_by="backtest",
            parameters={"my_custom_param": 2},
        )
        
        diff = engine.compare(source, target)
        
        assert diff.has_critical_diffs
    
    def test_add_warning_param(self, engine):
        """Adding a warning param should affect categorization."""
        engine.add_warning_param("my_custom_param")
        
        source = ConfigVersion.create(
            version_id="v1",
            created_by="live",
            parameters={"my_custom_param": 1},
        )
        target = ConfigVersion.create(
            version_id="v2",
            created_by="backtest",
            parameters={"my_custom_param": 2},
        )
        
        diff = engine.compare(source, target)
        
        assert len(diff.warning_diffs) == 1
    
    def test_remove_critical_param(self, engine):
        """Removing a critical param should affect categorization."""
        engine.remove_critical_param("fee_rate")
        
        source = ConfigVersion.create(
            version_id="v1",
            created_by="live",
            parameters={"fee_rate": 0.001},
        )
        target = ConfigVersion.create(
            version_id="v2",
            created_by="backtest",
            parameters={"fee_rate": 0.002},
        )
        
        diff = engine.compare(source, target)
        
        # fee_rate should now be info level
        assert not diff.has_critical_diffs
        assert len(diff.info_diffs) == 1


class TestCriticalAndWarningParams:
    """Tests for the default CRITICAL_PARAMS and WARNING_PARAMS lists."""
    
    def test_critical_params_contains_fee_params(self):
        """Critical params should include fee-related parameters."""
        assert "fee_rate" in CRITICAL_PARAMS
        assert "maker_fee_rate" in CRITICAL_PARAMS
        assert "taker_fee_rate" in CRITICAL_PARAMS
    
    def test_critical_params_contains_slippage_params(self):
        """Critical params should include slippage parameters."""
        assert "slippage_bps" in CRITICAL_PARAMS
        assert "slippage_pct" in CRITICAL_PARAMS
    
    def test_critical_params_contains_position_params(self):
        """Critical params should include position sizing parameters."""
        assert "position_size_pct" in CRITICAL_PARAMS
        assert "max_positions" in CRITICAL_PARAMS
        assert "leverage" in CRITICAL_PARAMS
    
    def test_critical_params_contains_threshold_params(self):
        """Critical params should include entry/exit thresholds."""
        assert "entry_threshold" in CRITICAL_PARAMS
        assert "exit_threshold" in CRITICAL_PARAMS
        assert "stop_loss_pct" in CRITICAL_PARAMS
        assert "take_profit_pct" in CRITICAL_PARAMS
    
    def test_warning_params_contains_timing_params(self):
        """Warning params should include timing parameters."""
        assert "cooldown_sec" in WARNING_PARAMS
        assert "min_hold_time_sec" in WARNING_PARAMS
    
    def test_warning_params_contains_volume_params(self):
        """Warning params should include volume parameters."""
        assert "min_volume" in WARNING_PARAMS
        assert "min_volume_usd" in WARNING_PARAMS
    
    def test_warning_params_contains_spread_params(self):
        """Warning params should include spread parameters."""
        assert "min_spread_bps" in WARNING_PARAMS
        assert "max_spread_bps" in WARNING_PARAMS
    
    def test_no_overlap_between_critical_and_warning(self):
        """Critical and warning params should not overlap."""
        critical_set = set(CRITICAL_PARAMS)
        warning_set = set(WARNING_PARAMS)
        
        overlap = critical_set & warning_set
        assert len(overlap) == 0, f"Overlapping params: {overlap}"
