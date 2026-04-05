"""Unit tests for ConfigurationRegistry.

Feature: trading-pipeline-integration
Requirements: 1.1, 1.2, 1.5
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantgambit.integration.config_registry import (
    ConfigurationRegistry,
    ConfigurationError,
)
from quantgambit.integration.config_version import ConfigVersion
from quantgambit.integration.config_diff import ConfigDiff


class TestConfigurationError:
    """Tests for ConfigurationError exception."""
    
    def test_basic_error_message(self):
        """Error should have basic message."""
        error = ConfigurationError("Test error")
        
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.critical_diffs == []
        assert error.diff is None
    
    def test_error_with_critical_diffs(self):
        """Error should format critical diffs in string representation."""
        error = ConfigurationError(
            "Critical differences detected",
            critical_diffs=[
                ("fee_rate", 0.001, 0.002),
                ("slippage_bps", 5.0, 10.0),
            ],
        )
        
        error_str = str(error)
        assert "Critical differences detected" in error_str
        assert "fee_rate" in error_str
        assert "0.001" in error_str
        assert "0.002" in error_str
        assert "slippage_bps" in error_str
    
    def test_error_with_diff_object(self):
        """Error should store the full diff object."""
        diff = ConfigDiff(
            source_version="v1",
            target_version="v2",
            critical_diffs=[("fee_rate", 0.001, 0.002)],
            warning_diffs=[],
            info_diffs=[],
        )
        error = ConfigurationError(
            "Critical differences detected",
            critical_diffs=diff.critical_diffs,
            diff=diff,
        )
        
        assert error.diff is diff
        assert error.diff.source_version == "v1"


class TestConfigurationRegistry:
    """Tests for ConfigurationRegistry."""
    
    @pytest.fixture
    def mock_pool(self):
        """Create a mock database pool."""
        pool = MagicMock()
        return pool
    
    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return MagicMock()
    
    @pytest.fixture
    def registry(self, mock_pool, mock_redis):
        """Create a ConfigurationRegistry instance with mocks."""
        return ConfigurationRegistry(mock_pool, mock_redis)
    
    @pytest.fixture
    def sample_live_config(self):
        """Create a sample live configuration."""
        return ConfigVersion.create(
            version_id="live_abc123",
            created_by="live",
            parameters={
                "fee_rate": 0.001,
                "slippage_bps": 5.0,
                "position_size_pct": 0.1,
                "cooldown_sec": 60,
                "description": "Live trading config",
            },
        )
    
    @pytest.mark.asyncio
    async def test_get_live_config_returns_active(self, registry, sample_live_config):
        """get_live_config should return active config if available."""
        registry._version_store.get_active = AsyncMock(return_value=sample_live_config)
        
        result = await registry.get_live_config()
        
        assert result == sample_live_config
        registry._version_store.get_active.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_live_config_falls_back_to_latest(self, registry, sample_live_config):
        """get_live_config should fall back to latest live config."""
        registry._version_store.get_active = AsyncMock(return_value=None)
        registry._version_store.get_latest = AsyncMock(return_value=sample_live_config)
        
        result = await registry.get_live_config()
        
        assert result == sample_live_config
        registry._version_store.get_latest.assert_called_once_with("live")
    
    @pytest.mark.asyncio
    async def test_get_live_config_returns_default_when_none(self, registry):
        """get_live_config should return default config when none exists."""
        registry._version_store.get_active = AsyncMock(return_value=None)
        registry._version_store.get_latest = AsyncMock(return_value=None)
        
        result = await registry.get_live_config()
        
        assert result is not None
        assert result.created_by == "live"
        assert result.parameters == {}
        assert result.version_id.startswith("default_")
    
    @pytest.mark.asyncio
    async def test_get_config_for_backtest_no_overrides(self, registry, sample_live_config):
        """get_config_for_backtest without overrides returns live config."""
        registry._version_store.get_active = AsyncMock(return_value=sample_live_config)
        
        config, diff = await registry.get_config_for_backtest()
        
        assert config == sample_live_config
        assert diff is None
    
    @pytest.mark.asyncio
    async def test_get_config_for_backtest_with_overrides(self, registry, sample_live_config):
        """get_config_for_backtest with overrides creates new config."""
        registry._version_store.get_active = AsyncMock(return_value=sample_live_config)
        
        config, diff = await registry.get_config_for_backtest(
            override_params={"description": "Backtest config"},
            require_parity=False,
        )
        
        assert config.version_id.startswith("backtest_")
        assert config.created_by == "backtest"
        assert config.parameters["description"] == "Backtest config"
        # Other params should be inherited from live
        assert config.parameters["fee_rate"] == 0.001
        assert diff is not None
        assert diff.has_any_diffs
    
    @pytest.mark.asyncio
    async def test_get_config_for_backtest_critical_diff_raises(self, registry, sample_live_config):
        """get_config_for_backtest raises on critical diff with require_parity=True."""
        registry._version_store.get_active = AsyncMock(return_value=sample_live_config)
        
        with pytest.raises(ConfigurationError) as exc_info:
            await registry.get_config_for_backtest(
                override_params={"fee_rate": 0.002},  # Critical param
                require_parity=True,
            )
        
        error = exc_info.value
        assert "Critical configuration differences" in error.message
        assert len(error.critical_diffs) == 1
        assert error.critical_diffs[0][0] == "fee_rate"
        assert error.diff is not None
    
    @pytest.mark.asyncio
    async def test_get_config_for_backtest_critical_diff_allowed(self, registry, sample_live_config):
        """get_config_for_backtest allows critical diff with require_parity=False."""
        registry._version_store.get_active = AsyncMock(return_value=sample_live_config)
        
        config, diff = await registry.get_config_for_backtest(
            override_params={"fee_rate": 0.002},  # Critical param
            require_parity=False,
        )
        
        assert config.parameters["fee_rate"] == 0.002
        assert diff.has_critical_diffs
    
    @pytest.mark.asyncio
    async def test_get_config_for_backtest_warning_diff_allowed(self, registry, sample_live_config):
        """get_config_for_backtest allows warning diff with require_parity=True."""
        registry._version_store.get_active = AsyncMock(return_value=sample_live_config)
        
        config, diff = await registry.get_config_for_backtest(
            override_params={"cooldown_sec": 120},  # Warning param
            require_parity=True,
        )
        
        assert config.parameters["cooldown_sec"] == 120
        assert not diff.has_critical_diffs
        assert len(diff.warning_diffs) == 1
    
    @pytest.mark.asyncio
    async def test_save_version(self, registry, sample_live_config):
        """save_version should delegate to version store."""
        registry._version_store.save = AsyncMock()
        
        await registry.save_version(sample_live_config)
        
        registry._version_store.save.assert_called_once_with(sample_live_config)
    
    @pytest.mark.asyncio
    async def test_get_version(self, registry, sample_live_config):
        """get_version should delegate to version store."""
        registry._version_store.get_by_id = AsyncMock(return_value=sample_live_config)
        
        result = await registry.get_version("live_abc123")
        
        assert result == sample_live_config
        registry._version_store.get_by_id.assert_called_once_with("live_abc123")
    
    @pytest.mark.asyncio
    async def test_set_active_config(self, registry):
        """set_active_config should delegate to version store."""
        registry._version_store.set_active = AsyncMock(return_value=True)
        
        result = await registry.set_active_config("live_abc123")
        
        assert result is True
        registry._version_store.set_active.assert_called_once_with("live_abc123")
    
    @pytest.mark.asyncio
    async def test_create_and_save_config(self, registry):
        """create_and_save_config should create, save, and optionally activate."""
        registry._version_store.save = AsyncMock()
        registry._version_store.set_active = AsyncMock(return_value=True)
        
        config = await registry.create_and_save_config(
            parameters={"fee_rate": 0.001},
            created_by="live",
            set_active=True,
        )
        
        assert config.created_by == "live"
        assert config.parameters["fee_rate"] == 0.001
        assert config.version_id.startswith("live_")
        registry._version_store.save.assert_called_once()
        registry._version_store.set_active.assert_called_once_with(config.version_id)
    
    @pytest.mark.asyncio
    async def test_create_and_save_config_no_activate(self, registry):
        """create_and_save_config should not activate when set_active=False."""
        registry._version_store.save = AsyncMock()
        registry._version_store.set_active = AsyncMock()
        
        await registry.create_and_save_config(
            parameters={"fee_rate": 0.001},
            created_by="backtest",
            set_active=False,
        )
        
        registry._version_store.save.assert_called_once()
        registry._version_store.set_active.assert_not_called()
    
    def test_compare_configs(self, registry, sample_live_config):
        """compare_configs should use diff engine."""
        target = ConfigVersion.create(
            version_id="backtest_v1",
            created_by="backtest",
            parameters={
                **sample_live_config.parameters,
                "fee_rate": 0.002,
            },
        )
        
        diff = registry.compare_configs(sample_live_config, target)
        
        assert diff.has_critical_diffs
        assert diff.critical_diffs[0][0] == "fee_rate"
    
    def test_hash_params_deterministic(self, registry):
        """_hash_params should produce deterministic hashes."""
        params = {"a": 1, "b": 2, "c": 3}
        
        hash1 = registry._hash_params(params)
        hash2 = registry._hash_params(params)
        
        assert hash1 == hash2
        assert len(hash1) == 16
    
    def test_hash_params_order_independent(self, registry):
        """_hash_params should be independent of key order."""
        params1 = {"a": 1, "b": 2, "c": 3}
        params2 = {"c": 3, "a": 1, "b": 2}
        
        hash1 = registry._hash_params(params1)
        hash2 = registry._hash_params(params2)
        
        assert hash1 == hash2
    
    def test_hash_params_different_values(self, registry):
        """_hash_params should produce different hashes for different values."""
        params1 = {"a": 1}
        params2 = {"a": 2}
        
        hash1 = registry._hash_params(params1)
        hash2 = registry._hash_params(params2)
        
        assert hash1 != hash2
    
    def test_hash_params_handles_datetime(self, registry):
        """_hash_params should handle datetime values."""
        params = {"timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)}
        
        # Should not raise
        hash_result = registry._hash_params(params)
        
        assert len(hash_result) == 16
    
    def test_hash_params_handles_nested(self, registry):
        """_hash_params should handle nested structures."""
        params = {
            "nested": {"a": 1, "b": [1, 2, 3]},
            "list": [{"x": 1}, {"y": 2}],
        }
        
        # Should not raise
        hash_result = registry._hash_params(params)
        
        assert len(hash_result) == 16


class TestConfigurationRegistryIntegration:
    """Integration-style tests for ConfigurationRegistry."""
    
    @pytest.fixture
    def mock_pool(self):
        """Create a mock database pool."""
        return MagicMock()
    
    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return MagicMock()
    
    @pytest.mark.asyncio
    async def test_backtest_workflow_with_parity(self, mock_pool, mock_redis):
        """Test typical backtest workflow with parity enforcement."""
        registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Set up live config
        live_config = ConfigVersion.create(
            version_id="live_v1",
            created_by="live",
            parameters={
                "fee_rate": 0.001,
                "slippage_bps": 5.0,
                "cooldown_sec": 60,
            },
        )
        registry._version_store.get_active = AsyncMock(return_value=live_config)
        
        # Get backtest config with non-critical override
        config, diff = await registry.get_config_for_backtest(
            override_params={"cooldown_sec": 120},
            require_parity=True,
        )
        
        # Should succeed - cooldown_sec is warning level
        assert config.parameters["cooldown_sec"] == 120
        assert config.parameters["fee_rate"] == 0.001  # Inherited
        assert not diff.has_critical_diffs
    
    @pytest.mark.asyncio
    async def test_backtest_workflow_critical_override_blocked(self, mock_pool, mock_redis):
        """Test that critical overrides are blocked with parity enforcement."""
        registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Set up live config
        live_config = ConfigVersion.create(
            version_id="live_v1",
            created_by="live",
            parameters={
                "fee_rate": 0.001,
                "slippage_bps": 5.0,
            },
        )
        registry._version_store.get_active = AsyncMock(return_value=live_config)
        
        # Try to override critical param with parity enforcement
        with pytest.raises(ConfigurationError) as exc_info:
            await registry.get_config_for_backtest(
                override_params={"fee_rate": 0.002},
                require_parity=True,
            )
        
        # Should fail with informative error
        assert "fee_rate" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_backtest_workflow_critical_override_acknowledged(self, mock_pool, mock_redis):
        """Test that critical overrides work when parity not required."""
        registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Set up live config
        live_config = ConfigVersion.create(
            version_id="live_v1",
            created_by="live",
            parameters={
                "fee_rate": 0.001,
                "slippage_bps": 5.0,
            },
        )
        registry._version_store.get_active = AsyncMock(return_value=live_config)
        
        # Override critical param with explicit acknowledgment
        config, diff = await registry.get_config_for_backtest(
            override_params={"fee_rate": 0.002},
            require_parity=False,  # Explicit acknowledgment
        )
        
        # Should succeed
        assert config.parameters["fee_rate"] == 0.002
        assert diff.has_critical_diffs
        # Diff should document the change
        assert diff.critical_diffs[0] == ("fee_rate", 0.001, 0.002)
