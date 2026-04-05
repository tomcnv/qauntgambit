"""
Property-based tests for Configuration Management.

Feature: trading-pipeline-integration

These tests verify the correctness properties of the configuration management
system, ensuring parity between live and backtest configurations.

Uses hypothesis library with minimum 100 iterations per property test.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.integration.config_version import ConfigVersion, ConfigVersionStore
from quantgambit.integration.config_diff import (
    ConfigDiff,
    ConfigDiffEngine,
    CRITICAL_PARAMS,
    WARNING_PARAMS,
)
from quantgambit.integration.config_registry import (
    ConfigurationRegistry,
    ConfigurationError,
)


# ═══════════════════════════════════════════════════════════════
# STRATEGIES FOR PROPERTY-BASED TESTING
# ═══════════════════════════════════════════════════════════════

# Version ID strategy
version_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"),
    min_size=1,
    max_size=32,
)

# Created by strategy (valid sources)
created_by_strategy = st.sampled_from(["live", "backtest", "optimizer"])


# Parameter key strategy
param_key_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=32,
)

# Parameter value strategies for different types
param_value_float_strategy = st.floats(
    min_value=-1000.0,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Float strategy with more distinct values (avoiding very small differences)
distinct_float_strategy = st.one_of(
    st.floats(min_value=-1000.0, max_value=-0.01, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
    st.just(0.0),
)

param_value_int_strategy = st.integers(min_value=-1000, max_value=1000)

param_value_bool_strategy = st.booleans()

param_value_string_strategy = st.text(min_size=0, max_size=50)

# Combined parameter value strategy
param_value_strategy = st.one_of(
    param_value_float_strategy,
    param_value_int_strategy,
    param_value_bool_strategy,
    param_value_string_strategy,
)

# Configuration parameters dictionary strategy
config_params_strategy = st.dictionaries(
    keys=param_key_strategy,
    values=param_value_strategy,
    min_size=0,
    max_size=20,
)

# Critical parameter key strategy (from actual critical params list)
critical_param_key_strategy = st.sampled_from(CRITICAL_PARAMS[:10])  # Use first 10 critical params

# Warning parameter key strategy (from actual warning params list)
warning_param_key_strategy = st.sampled_from(WARNING_PARAMS[:10])  # Use first 10 warning params

# Timestamp strategy
timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def create_mock_pool():
    """Create a mock database pool for testing."""
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock())
    return pool


def create_mock_redis():
    """Create a mock Redis client for testing."""
    return MagicMock()


# ═══════════════════════════════════════════════════════════════
# PROPERTY 1: CONFIGURATION SINGLE SOURCE OF TRUTH
# Feature: trading-pipeline-integration, Property 1
# Validates: Requirements 1.1, 1.2
# ═══════════════════════════════════════════════════════════════

class TestConfigurationSingleSourceOfTruth:
    """
    Feature: trading-pipeline-integration, Property 1: Configuration Single Source of Truth
    
    For any configuration parameter accessed by both live and backtest systems,
    the value SHALL be retrieved from the same ConfigurationRegistry instance,
    ensuring identical values when no overrides are specified.
    
    **Validates: Requirements 1.1, 1.2**
    """
    
    @settings(max_examples=100)
    @given(params=config_params_strategy)
    def test_same_registry_returns_identical_config(self, params: Dict[str, Any]):
        """
        **Validates: Requirements 1.1**
        
        Property: For any configuration parameters, accessing the same registry
        multiple times returns identical configuration values.
        """
        # Create a ConfigVersion with the given parameters
        config = ConfigVersion.create(
            version_id="test_v1",
            created_by="live",
            parameters=params,
        )
        
        # Verify the config hash is deterministic
        hash1 = ConfigVersion.compute_hash(params)
        hash2 = ConfigVersion.compute_hash(params)
        
        assert hash1 == hash2, "Config hash should be deterministic"
        assert config.config_hash == hash1, "Config hash should match computed hash"
        
        # Verify parameters are preserved exactly
        assert config.parameters == params, "Parameters should be preserved exactly"
    
    @settings(max_examples=100)
    @given(params=config_params_strategy)
    def test_config_hash_deterministic(self, params: Dict[str, Any]):
        """
        **Validates: Requirements 1.1**
        
        Property: For any configuration parameters, the computed hash is
        deterministic and reproducible.
        """
        # Compute hash multiple times
        hashes = [ConfigVersion.compute_hash(params) for _ in range(5)]
        
        # All hashes should be identical
        assert len(set(hashes)) == 1, "All hashes should be identical"
        
        # Hash should be 16 characters (hex)
        assert len(hashes[0]) == 16, "Hash should be 16 characters"
        assert all(c in "0123456789abcdef" for c in hashes[0]), "Hash should be hex"

    @settings(max_examples=100)
    @given(
        params=config_params_strategy,
        created_by=created_by_strategy,
    )
    def test_config_version_preserves_all_fields(
        self,
        params: Dict[str, Any],
        created_by: str,
    ):
        """
        **Validates: Requirements 1.1, 1.2**
        
        Property: For any configuration created, all fields are preserved
        and accessible consistently.
        """
        version_id = f"test_{created_by}_v1"
        
        config = ConfigVersion.create(
            version_id=version_id,
            created_by=created_by,
            parameters=params,
        )
        
        # Verify all fields are preserved
        assert config.version_id == version_id
        assert config.created_by == created_by
        assert config.parameters == params
        assert config.config_hash == ConfigVersion.compute_hash(params)
        assert config.created_at is not None
        assert config.created_at.tzinfo is not None  # Should have timezone
    
    @settings(max_examples=100)
    @given(params=config_params_strategy)
    def test_config_serialization_round_trip(self, params: Dict[str, Any]):
        """
        **Validates: Requirements 1.1**
        
        Property: For any configuration, serialization to dict and back
        preserves all values exactly.
        """
        config = ConfigVersion.create(
            version_id="test_v1",
            created_by="live",
            parameters=params,
        )
        
        # Serialize to dict
        config_dict = config.to_dict()
        
        # Deserialize back
        restored = ConfigVersion.from_dict(config_dict)
        
        # Verify all fields match
        assert restored.version_id == config.version_id
        assert restored.created_by == config.created_by
        assert restored.config_hash == config.config_hash
        assert restored.parameters == config.parameters


# ═══════════════════════════════════════════════════════════════
# PROPERTY 2: CONFIGURATION DIFF COMPLETENESS
# Feature: trading-pipeline-integration, Property 2
# Validates: Requirements 1.3, 1.4
# ═══════════════════════════════════════════════════════════════

class TestConfigurationDiffCompleteness:
    """
    Feature: trading-pipeline-integration, Property 2: Configuration Diff Completeness
    
    For any two configuration versions with differing parameters, the
    ConfigDiffEngine SHALL identify all differences and categorize each
    as critical, warning, or info based on the parameter's impact on
    trading behavior.
    
    **Validates: Requirements 1.3, 1.4**
    """
    
    @settings(max_examples=100)
    @given(
        source_params=config_params_strategy,
        target_params=config_params_strategy,
    )
    def test_diff_identifies_all_differences(
        self,
        source_params: Dict[str, Any],
        target_params: Dict[str, Any],
    ):
        """
        **Validates: Requirements 1.3, 1.4**
        
        Property: For any two configurations, the diff engine identifies
        all parameter differences (using the engine's tolerance-based comparison).
        """
        source = ConfigVersion.create(
            version_id="source_v1",
            created_by="live",
            parameters=source_params,
        )
        target = ConfigVersion.create(
            version_id="target_v1",
            created_by="backtest",
            parameters=target_params,
        )
        
        engine = ConfigDiffEngine()
        diff = engine.compare(source, target)
        
        # Calculate expected differences using the same comparison logic as the engine
        # This accounts for floating point tolerance
        all_keys = set(source_params.keys()) | set(target_params.keys())
        expected_diff_count = 0
        for key in all_keys:
            source_val = source_params.get(key)
            target_val = target_params.get(key)
            # Use the engine's comparison logic
            if not engine._values_equal(source_val, target_val):
                expected_diff_count += 1
        
        # Verify total diff count matches
        actual_diff_count = diff.total_diffs
        assert actual_diff_count == expected_diff_count, (
            f"Expected {expected_diff_count} diffs, got {actual_diff_count}"
        )

    @settings(max_examples=100)
    @given(
        critical_key=critical_param_key_strategy,
        source_value=distinct_float_strategy,
        target_value=distinct_float_strategy,
    )
    def test_critical_params_categorized_correctly(
        self,
        critical_key: str,
        source_value: float,
        target_value: float,
    ):
        """
        **Validates: Requirements 1.3**
        
        Property: For any critical parameter that differs, the diff engine
        categorizes it as a critical difference.
        """
        # Ensure values are significantly different (not just floating point noise)
        assume(abs(source_value - target_value) > 0.001)
        
        source = ConfigVersion.create(
            version_id="source_v1",
            created_by="live",
            parameters={critical_key: source_value},
        )
        target = ConfigVersion.create(
            version_id="target_v1",
            created_by="backtest",
            parameters={critical_key: target_value},
        )
        
        engine = ConfigDiffEngine()
        diff = engine.compare(source, target)
        
        # Verify the critical param is in critical_diffs
        assert diff.has_critical_diffs, f"Critical param {critical_key} should be in critical_diffs"
        
        critical_keys = [k for k, _, _ in diff.critical_diffs]
        assert critical_key in critical_keys, (
            f"Critical param {critical_key} should be categorized as critical"
        )
    
    @settings(max_examples=100)
    @given(
        warning_key=warning_param_key_strategy,
        source_value=distinct_float_strategy,
        target_value=distinct_float_strategy,
    )
    def test_warning_params_categorized_correctly(
        self,
        warning_key: str,
        source_value: float,
        target_value: float,
    ):
        """
        **Validates: Requirements 1.3**
        
        Property: For any warning parameter that differs, the diff engine
        categorizes it as a warning difference.
        """
        # Ensure values are significantly different (not just floating point noise)
        assume(abs(source_value - target_value) > 0.001)
        
        source = ConfigVersion.create(
            version_id="source_v1",
            created_by="live",
            parameters={warning_key: source_value},
        )
        target = ConfigVersion.create(
            version_id="target_v1",
            created_by="backtest",
            parameters={warning_key: target_value},
        )
        
        engine = ConfigDiffEngine()
        diff = engine.compare(source, target)
        
        # Verify the warning param is in warning_diffs
        warning_keys = [k for k, _, _ in diff.warning_diffs]
        assert warning_key in warning_keys, (
            f"Warning param {warning_key} should be categorized as warning"
        )
    
    @settings(max_examples=100)
    @given(
        info_key=st.text(
            alphabet=st.characters(whitelist_categories=("Ll",)),
            min_size=5,
            max_size=20,
        ).filter(lambda k: k not in CRITICAL_PARAMS and k not in WARNING_PARAMS),
        source_value=distinct_float_strategy,
        target_value=distinct_float_strategy,
    )
    def test_info_params_categorized_correctly(
        self,
        info_key: str,
        source_value: float,
        target_value: float,
    ):
        """
        **Validates: Requirements 1.3**
        
        Property: For any non-critical, non-warning parameter that differs,
        the diff engine categorizes it as an info difference.
        """
        # Ensure values are significantly different (not just floating point noise)
        assume(abs(source_value - target_value) > 0.001)
        # Ensure key is not in critical or warning lists
        assume(info_key not in CRITICAL_PARAMS)
        assume(info_key not in WARNING_PARAMS)
        
        source = ConfigVersion.create(
            version_id="source_v1",
            created_by="live",
            parameters={info_key: source_value},
        )
        target = ConfigVersion.create(
            version_id="target_v1",
            created_by="backtest",
            parameters={info_key: target_value},
        )
        
        engine = ConfigDiffEngine()
        diff = engine.compare(source, target)
        
        # Verify the info param is in info_diffs
        info_keys = [k for k, _, _ in diff.info_diffs]
        assert info_key in info_keys, (
            f"Info param {info_key} should be categorized as info"
        )

    @settings(max_examples=100)
    @given(params=config_params_strategy)
    def test_identical_configs_have_no_diffs(self, params: Dict[str, Any]):
        """
        **Validates: Requirements 1.4**
        
        Property: For any two identical configurations, the diff engine
        reports no differences.
        """
        source = ConfigVersion.create(
            version_id="source_v1",
            created_by="live",
            parameters=params,
        )
        target = ConfigVersion.create(
            version_id="target_v1",
            created_by="backtest",
            parameters=params.copy(),  # Same params
        )
        
        engine = ConfigDiffEngine()
        diff = engine.compare(source, target)
        
        # Verify no differences
        assert not diff.has_any_diffs, "Identical configs should have no diffs"
        assert diff.total_diffs == 0, "Total diffs should be 0"
    
    @settings(max_examples=100)
    @given(
        source_params=config_params_strategy,
        target_params=config_params_strategy,
    )
    def test_diff_report_format(
        self,
        source_params: Dict[str, Any],
        target_params: Dict[str, Any],
    ):
        """
        **Validates: Requirements 1.4**
        
        Property: For any configuration diff, the format_report() method
        produces a valid human-readable report.
        """
        source = ConfigVersion.create(
            version_id="source_v1",
            created_by="live",
            parameters=source_params,
        )
        target = ConfigVersion.create(
            version_id="target_v1",
            created_by="backtest",
            parameters=target_params,
        )
        
        engine = ConfigDiffEngine()
        diff = engine.compare(source, target)
        
        # Generate report
        report = diff.format_report()
        
        # Verify report is a non-empty string
        assert isinstance(report, str)
        assert len(report) > 0
        
        # Verify report contains version IDs
        assert "source_v1" in report
        assert "target_v1" in report


# ═══════════════════════════════════════════════════════════════
# PROPERTY 3: CRITICAL CONFIGURATION BLOCKING
# Feature: trading-pipeline-integration, Property 3
# Validates: Requirements 1.5
# ═══════════════════════════════════════════════════════════════

class TestCriticalConfigurationBlocking:
    """
    Feature: trading-pipeline-integration, Property 3: Critical Configuration Blocking
    
    For any backtest initiation where critical configuration parameters differ
    from live and require_parity=True, the System SHALL raise ConfigurationError
    before execution begins.
    
    **Validates: Requirements 1.5**
    """
    
    @settings(max_examples=100)
    @given(
        critical_key=critical_param_key_strategy,
        live_value=distinct_float_strategy,
        override_value=distinct_float_strategy,
    )
    @pytest.mark.asyncio
    async def test_critical_diff_raises_error_when_parity_required(
        self,
        critical_key: str,
        live_value: float,
        override_value: float,
    ):
        """
        **Validates: Requirements 1.5**
        
        Property: When require_parity=True and a critical parameter differs,
        ConfigurationError is raised.
        """
        # Ensure values are significantly different (not just floating point noise)
        assume(abs(live_value - override_value) > 0.001)
        
        # Create mock pool and redis
        pool = create_mock_pool()
        redis = create_mock_redis()
        
        # Create registry
        registry = ConfigurationRegistry(pool, redis)
        
        # Mock the version store to return a live config
        live_config = ConfigVersion.create(
            version_id="live_v1",
            created_by="live",
            parameters={critical_key: live_value},
        )
        registry._version_store.get_active = AsyncMock(return_value=None)
        registry._version_store.get_latest = AsyncMock(return_value=live_config)
        
        # Attempt to get backtest config with critical override
        with pytest.raises(ConfigurationError) as exc_info:
            await registry.get_config_for_backtest(
                override_params={critical_key: override_value},
                require_parity=True,
            )
        
        # Verify error contains critical diff info
        error = exc_info.value
        assert len(error.critical_diffs) > 0, "Error should contain critical diffs"
        assert error.diff is not None, "Error should contain full diff"

    @settings(max_examples=100)
    @given(
        critical_key=critical_param_key_strategy,
        live_value=distinct_float_strategy,
        override_value=distinct_float_strategy,
    )
    @pytest.mark.asyncio
    async def test_critical_diff_allowed_when_parity_not_required(
        self,
        critical_key: str,
        live_value: float,
        override_value: float,
    ):
        """
        **Validates: Requirements 1.5**
        
        Property: When require_parity=False, critical parameter differences
        are allowed and the backtest config is returned with a diff.
        """
        # Ensure values are significantly different (not just floating point noise)
        assume(abs(live_value - override_value) > 0.001)
        
        # Create mock pool and redis
        pool = create_mock_pool()
        redis = create_mock_redis()
        
        # Create registry
        registry = ConfigurationRegistry(pool, redis)
        
        # Mock the version store to return a live config
        live_config = ConfigVersion.create(
            version_id="live_v1",
            created_by="live",
            parameters={critical_key: live_value},
        )
        registry._version_store.get_active = AsyncMock(return_value=None)
        registry._version_store.get_latest = AsyncMock(return_value=live_config)
        
        # Get backtest config with require_parity=False
        backtest_config, diff = await registry.get_config_for_backtest(
            override_params={critical_key: override_value},
            require_parity=False,
        )
        
        # Verify config is returned with the override
        assert backtest_config.parameters[critical_key] == override_value
        
        # Verify diff is returned
        assert diff is not None
        assert diff.has_critical_diffs
    
    @settings(max_examples=100)
    @given(
        warning_key=warning_param_key_strategy,
        live_value=distinct_float_strategy,
        override_value=distinct_float_strategy,
    )
    @pytest.mark.asyncio
    async def test_warning_diff_does_not_raise_error(
        self,
        warning_key: str,
        live_value: float,
        override_value: float,
    ):
        """
        **Validates: Requirements 1.5**
        
        Property: Warning parameter differences do not raise ConfigurationError
        even when require_parity=True.
        """
        # Ensure values are significantly different (not just floating point noise)
        assume(abs(live_value - override_value) > 0.001)
        
        # Create mock pool and redis
        pool = create_mock_pool()
        redis = create_mock_redis()
        
        # Create registry
        registry = ConfigurationRegistry(pool, redis)
        
        # Mock the version store to return a live config
        live_config = ConfigVersion.create(
            version_id="live_v1",
            created_by="live",
            parameters={warning_key: live_value},
        )
        registry._version_store.get_active = AsyncMock(return_value=None)
        registry._version_store.get_latest = AsyncMock(return_value=live_config)
        
        # Get backtest config - should not raise
        backtest_config, diff = await registry.get_config_for_backtest(
            override_params={warning_key: override_value},
            require_parity=True,
        )
        
        # Verify config is returned with the override
        assert backtest_config.parameters[warning_key] == override_value
        
        # Verify diff shows warning but no critical
        assert diff is not None
        assert not diff.has_critical_diffs
        assert len(diff.warning_diffs) > 0
    
    @settings(max_examples=100)
    @given(params=config_params_strategy)
    @pytest.mark.asyncio
    async def test_no_override_returns_live_config_directly(
        self,
        params: Dict[str, Any],
    ):
        """
        **Validates: Requirements 1.2**
        
        Property: When no overrides are specified, the exact live configuration
        is returned with no diff.
        """
        # Create mock pool and redis
        pool = create_mock_pool()
        redis = create_mock_redis()
        
        # Create registry
        registry = ConfigurationRegistry(pool, redis)
        
        # Mock the version store to return a live config
        live_config = ConfigVersion.create(
            version_id="live_v1",
            created_by="live",
            parameters=params,
        )
        registry._version_store.get_active = AsyncMock(return_value=None)
        registry._version_store.get_latest = AsyncMock(return_value=live_config)
        
        # Get backtest config without overrides
        backtest_config, diff = await registry.get_config_for_backtest(
            override_params=None,
            require_parity=True,
        )
        
        # Verify the exact live config is returned
        assert backtest_config.version_id == live_config.version_id
        assert backtest_config.parameters == live_config.parameters
        
        # Verify no diff
        assert diff is None


# ═══════════════════════════════════════════════════════════════
# PROPERTY 4: CONFIGURATION VERSION PERSISTENCE
# Feature: trading-pipeline-integration, Property 4
# Validates: Requirements 1.6
# ═══════════════════════════════════════════════════════════════

class TestConfigurationVersionPersistence:
    """
    Feature: trading-pipeline-integration, Property 4: Configuration Version Persistence
    
    For any configuration saved to the ConfigurationRegistry, the System SHALL
    create a versioned record with a unique version_id, timestamp, and
    deterministic config_hash that can be retrieved later.
    
    **Validates: Requirements 1.6**
    """
    
    @settings(max_examples=100)
    @given(
        params=config_params_strategy,
        created_by=created_by_strategy,
    )
    def test_config_version_has_unique_id(
        self,
        params: Dict[str, Any],
        created_by: str,
    ):
        """
        **Validates: Requirements 1.6**
        
        Property: Each configuration version has a unique version_id.
        """
        # Create multiple configs
        configs = [
            ConfigVersion.create(
                version_id=f"test_v{i}",
                created_by=created_by,
                parameters=params,
            )
            for i in range(5)
        ]
        
        # Verify all version_ids are unique
        version_ids = [c.version_id for c in configs]
        assert len(version_ids) == len(set(version_ids)), "All version_ids should be unique"
    
    @settings(max_examples=100)
    @given(
        params=config_params_strategy,
        created_by=created_by_strategy,
    )
    def test_config_version_has_timestamp(
        self,
        params: Dict[str, Any],
        created_by: str,
    ):
        """
        **Validates: Requirements 1.6**
        
        Property: Each configuration version has a valid timestamp with timezone.
        """
        config = ConfigVersion.create(
            version_id="test_v1",
            created_by=created_by,
            parameters=params,
        )
        
        # Verify timestamp exists and has timezone
        assert config.created_at is not None
        assert config.created_at.tzinfo is not None
        
        # Verify timestamp is recent (within last minute)
        now = datetime.now(timezone.utc)
        age = (now - config.created_at).total_seconds()
        assert age < 60, "Timestamp should be recent"
    
    @settings(max_examples=100)
    @given(params=config_params_strategy)
    def test_config_hash_is_deterministic(self, params: Dict[str, Any]):
        """
        **Validates: Requirements 1.6**
        
        Property: The config_hash is deterministic - same parameters always
        produce the same hash.
        """
        # Create multiple configs with same params
        configs = [
            ConfigVersion.create(
                version_id=f"test_v{i}",
                created_by="live",
                parameters=params,
            )
            for i in range(5)
        ]
        
        # Verify all hashes are identical
        hashes = [c.config_hash for c in configs]
        assert len(set(hashes)) == 1, "Same params should produce same hash"
    
    @settings(max_examples=100)
    @given(
        params1=config_params_strategy,
        params2=config_params_strategy,
    )
    def test_different_params_produce_different_hash(
        self,
        params1: Dict[str, Any],
        params2: Dict[str, Any],
    ):
        """
        **Validates: Requirements 1.6**
        
        Property: Different parameters produce different hashes (with high probability).
        """
        # Skip if params are identical
        assume(params1 != params2)
        
        hash1 = ConfigVersion.compute_hash(params1)
        hash2 = ConfigVersion.compute_hash(params2)
        
        # Different params should produce different hashes
        assert hash1 != hash2, "Different params should produce different hashes"
    
    @settings(max_examples=100)
    @given(
        params=config_params_strategy,
        created_by=created_by_strategy,
        timestamp=timestamp_strategy,
    )
    def test_config_version_preserves_custom_timestamp(
        self,
        params: Dict[str, Any],
        created_by: str,
        timestamp: datetime,
    ):
        """
        **Validates: Requirements 1.6**
        
        Property: When a custom timestamp is provided, it is preserved exactly.
        """
        config = ConfigVersion.create(
            version_id="test_v1",
            created_by=created_by,
            parameters=params,
            created_at=timestamp,
        )
        
        # Verify timestamp is preserved
        assert config.created_at == timestamp

    @settings(max_examples=100)
    @given(params=config_params_strategy)
    def test_config_hash_format(self, params: Dict[str, Any]):
        """
        **Validates: Requirements 1.6**
        
        Property: The config_hash is a 16-character hexadecimal string.
        """
        config = ConfigVersion.create(
            version_id="test_v1",
            created_by="live",
            parameters=params,
        )
        
        # Verify hash format
        assert len(config.config_hash) == 16, "Hash should be 16 characters"
        assert all(c in "0123456789abcdef" for c in config.config_hash), (
            "Hash should be hexadecimal"
        )
    
    @settings(max_examples=100)
    @given(
        params=config_params_strategy,
        created_by=created_by_strategy,
    )
    def test_config_to_dict_contains_all_fields(
        self,
        params: Dict[str, Any],
        created_by: str,
    ):
        """
        **Validates: Requirements 1.6**
        
        Property: The to_dict() method includes all required fields for persistence.
        """
        config = ConfigVersion.create(
            version_id="test_v1",
            created_by=created_by,
            parameters=params,
        )
        
        config_dict = config.to_dict()
        
        # Verify all required fields are present
        required_fields = ["version_id", "created_at", "created_by", "config_hash", "parameters"]
        for field in required_fields:
            assert field in config_dict, f"Missing required field: {field}"
        
        # Verify values match
        assert config_dict["version_id"] == config.version_id
        assert config_dict["created_by"] == config.created_by
        assert config_dict["config_hash"] == config.config_hash
        assert config_dict["parameters"] == config.parameters


# ═══════════════════════════════════════════════════════════════
# ADDITIONAL EDGE CASE TESTS
# ═══════════════════════════════════════════════════════════════

class TestConfigurationEdgeCases:
    """
    Additional edge case tests for configuration management.
    
    **Validates: Requirements 1.1, 1.3, 1.4, 1.6**
    """
    
    def test_empty_params_config(self):
        """
        **Validates: Requirements 1.1**
        
        Property: Empty parameters dictionary is valid and produces consistent hash.
        """
        config = ConfigVersion.create(
            version_id="test_v1",
            created_by="live",
            parameters={},
        )
        
        assert config.parameters == {}
        assert len(config.config_hash) == 16
        
        # Verify hash is deterministic for empty params
        hash1 = ConfigVersion.compute_hash({})
        hash2 = ConfigVersion.compute_hash({})
        assert hash1 == hash2
    
    def test_nested_params_config(self):
        """
        **Validates: Requirements 1.1**
        
        Property: Nested parameter dictionaries are handled correctly.
        """
        nested_params = {
            "strategy": {
                "entry_threshold": 0.5,
                "exit_threshold": 0.3,
            },
            "risk": {
                "max_position_size": 1000,
                "stop_loss_pct": 0.02,
            },
        }
        
        config = ConfigVersion.create(
            version_id="test_v1",
            created_by="live",
            parameters=nested_params,
        )
        
        assert config.parameters == nested_params
        
        # Verify serialization round-trip
        config_dict = config.to_dict()
        restored = ConfigVersion.from_dict(config_dict)
        assert restored.parameters == nested_params
    
    def test_diff_with_nested_params(self):
        """
        **Validates: Requirements 1.3**
        
        Property: Nested parameter differences are detected correctly.
        """
        source_params = {
            "strategy.fee_rate": 0.001,
            "risk.stop_loss_pct": 0.02,
        }
        target_params = {
            "strategy.fee_rate": 0.002,  # Different
            "risk.stop_loss_pct": 0.02,   # Same
        }
        
        source = ConfigVersion.create(
            version_id="source_v1",
            created_by="live",
            parameters=source_params,
        )
        target = ConfigVersion.create(
            version_id="target_v1",
            created_by="backtest",
            parameters=target_params,
        )
        
        engine = ConfigDiffEngine()
        diff = engine.compare(source, target)
        
        # fee_rate is critical, should be in critical_diffs
        assert diff.has_critical_diffs
        critical_keys = [k for k, _, _ in diff.critical_diffs]
        assert "strategy.fee_rate" in critical_keys
    
    def test_configuration_error_string_representation(self):
        """
        **Validates: Requirements 1.5**
        
        Property: ConfigurationError has informative string representation.
        """
        critical_diffs = [
            ("fee_rate", 0.001, 0.002),
            ("slippage_bps", 1.0, 2.0),
        ]
        
        error = ConfigurationError(
            message="Critical configuration differences detected",
            critical_diffs=critical_diffs,
        )
        
        error_str = str(error)
        
        # Verify error string contains useful info
        assert "Critical configuration differences" in error_str
        assert "fee_rate" in error_str
        assert "slippage_bps" in error_str
    
    @settings(max_examples=100)
    @given(
        float_val1=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        float_val2=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_float_comparison_tolerance(self, float_val1: float, float_val2: float):
        """
        **Validates: Requirements 1.3**
        
        Property: Float values are compared with appropriate tolerance.
        """
        engine = ConfigDiffEngine()
        
        # Very close floats should be considered equal
        if abs(float_val1 - float_val2) < 1e-9:
            assert engine._values_equal(float_val1, float_val2)
        
        # Significantly different floats should not be equal
        if abs(float_val1 - float_val2) > 0.01:
            assert not engine._values_equal(float_val1, float_val2)
    
    def test_invalid_created_by_raises_error(self):
        """
        **Validates: Requirements 1.6**
        
        Property: Invalid created_by value raises ValueError.
        """
        with pytest.raises(ValueError) as exc_info:
            ConfigVersion(
                version_id="test_v1",
                created_at=datetime.now(timezone.utc),
                created_by="invalid_source",
                config_hash="abc123",
                parameters={},
            )
        
        assert "created_by" in str(exc_info.value)
    
    def test_empty_version_id_raises_error(self):
        """
        **Validates: Requirements 1.6**
        
        Property: Empty version_id raises ValueError.
        """
        with pytest.raises(ValueError) as exc_info:
            ConfigVersion(
                version_id="",
                created_at=datetime.now(timezone.utc),
                created_by="live",
                config_hash="abc123",
                parameters={},
            )
        
        assert "version_id" in str(exc_info.value)
