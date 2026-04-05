"""Tests for config hot-reload functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass

from quantgambit.config.watcher import ConfigWatcher, ConfigApplier
from quantgambit.config.safety import SafeConfigApplier
from quantgambit.config.models import BotConfig


@dataclass
class FakeRuntimeState:
    """Fake runtime state for testing."""
    trading_paused: bool = False


class FakePositionManager:
    """Fake position manager for testing."""
    
    def __init__(self, positions=None):
        self._positions = positions or []
    
    async def list_open_positions(self):
        return self._positions


class FakeRepository:
    """Fake config repository for testing."""
    
    def __init__(self):
        self.applied_configs = []
    
    def apply(self, config):
        self.applied_configs.append(config)


class FakeDelegate(ConfigApplier):
    """Fake delegate applier for testing."""
    
    def __init__(self):
        self.applied_configs = []
    
    async def apply(self, config):
        self.applied_configs.append(config)
        return True


class TestConfigWatcher:
    """Tests for ConfigWatcher."""
    
    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock()
        redis.create_group = AsyncMock()
        redis.read_group = AsyncMock(return_value=[])
        redis.ack = AsyncMock()
        return redis
    
    @pytest.fixture
    def mock_applier(self):
        """Create mock applier."""
        applier = MagicMock(spec=ConfigApplier)
        applier.apply = AsyncMock(return_value=True)
        return applier
    
    def _make_config_payload(self, tenant_id: str, bot_id: str, version: int) -> dict:
        """Create a valid config update payload."""
        import json
        ts_us = 1234567890 * 1_000_000
        event = {
            "event_id": "evt-1",
            "event_type": "config_update",
            "schema_version": "v1",
            "timestamp": "1234567890",
            "ts_recv_us": ts_us,
            "ts_canon_us": ts_us,
            "ts_exchange_s": None,
            "bot_id": bot_id,
            "payload": {
                "config": {
                    "tenant_id": tenant_id,
                    "bot_id": bot_id,
                    "version": version,
                    "active_exchange": "bybit",
                    "trading_mode": "paper",
                    "symbols": ["BTCUSDT"],  # Required field
                }
            }
        }
        return {"data": json.dumps(event)}
    
    @pytest.mark.asyncio
    async def test_handle_message_applies_config(self, mock_redis, mock_applier):
        """Should apply valid config from message."""
        watcher = ConfigWatcher(
            redis_client=mock_redis,
            applier=mock_applier,
        )
        
        payload = self._make_config_payload("t1", "b1", 1)
        
        await watcher._handle_message(payload)
        
        mock_applier.apply.assert_called_once()
        applied_config = mock_applier.apply.call_args[0][0]
        assert applied_config.tenant_id == "t1"
        assert applied_config.bot_id == "b1"
        assert applied_config.version == 1
    
    @pytest.mark.asyncio
    async def test_handle_message_ignores_old_version(self, mock_redis, mock_applier):
        """Should ignore config with older version."""
        watcher = ConfigWatcher(
            redis_client=mock_redis,
            applier=mock_applier,
        )
        
        # Apply version 2 first
        watcher._last_version[("t1", "b1")] = 2
        
        payload = self._make_config_payload("t1", "b1", 1)
        
        await watcher._handle_message(payload)
        
        # Should not apply older version
        mock_applier.apply.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_handle_message_updates_version_on_success(self, mock_redis, mock_applier):
        """Should update last version after successful apply."""
        watcher = ConfigWatcher(
            redis_client=mock_redis,
            applier=mock_applier,
        )
        
        payload = self._make_config_payload("t1", "b1", 5)
        
        await watcher._handle_message(payload)
        
        assert watcher._last_version[("t1", "b1")] == 5


class TestSafeConfigApplier:
    """Tests for SafeConfigApplier."""
    
    @pytest.fixture
    def runtime_state(self):
        """Create runtime state."""
        return FakeRuntimeState()
    
    @pytest.fixture
    def position_manager(self):
        """Create position manager."""
        return FakePositionManager()
    
    @pytest.fixture
    def repository(self):
        """Create repository."""
        return FakeRepository()
    
    @pytest.fixture
    def delegate(self):
        """Create delegate."""
        return FakeDelegate()
    
    @pytest.fixture
    def config(self):
        """Create test config."""
        return BotConfig(
            tenant_id="t1",
            bot_id="b1",
            version=1,
            active_exchange="bybit",
            trading_mode="paper",
            symbols=["BTCUSDT"],
        )
    
    @pytest.mark.asyncio
    async def test_apply_blocked_when_trading_active(
        self, runtime_state, position_manager, repository, delegate, config
    ):
        """Should block apply when trading is active."""
        runtime_state.trading_paused = False
        
        applier = SafeConfigApplier(
            runtime_state=runtime_state,
            position_manager=position_manager,
            repository=repository,
            delegate=delegate,
        )
        
        result = await applier.apply(config)
        
        assert result is False
        assert len(delegate.applied_configs) == 0
        assert len(applier._pending) == 1
    
    @pytest.mark.asyncio
    async def test_apply_blocked_when_positions_open(
        self, runtime_state, position_manager, repository, delegate, config
    ):
        """Should block apply when positions are open."""
        runtime_state.trading_paused = True
        position_manager._positions = [MagicMock()]  # One open position
        
        applier = SafeConfigApplier(
            runtime_state=runtime_state,
            position_manager=position_manager,
            repository=repository,
            delegate=delegate,
        )
        
        result = await applier.apply(config)
        
        assert result is False
        assert len(delegate.applied_configs) == 0
        assert len(applier._pending) == 1
    
    @pytest.mark.asyncio
    async def test_apply_allowed_when_safe(
        self, runtime_state, position_manager, repository, delegate, config
    ):
        """Should apply when trading paused and no positions."""
        runtime_state.trading_paused = True
        position_manager._positions = []
        
        applier = SafeConfigApplier(
            runtime_state=runtime_state,
            position_manager=position_manager,
            repository=repository,
            delegate=delegate,
        )
        
        result = await applier.apply(config)
        
        assert result is True
        assert len(delegate.applied_configs) == 1
        assert len(repository.applied_configs) == 1
    
    @pytest.mark.asyncio
    async def test_flush_if_safe_applies_pending(
        self, runtime_state, position_manager, repository, delegate, config
    ):
        """Should flush pending configs when safe."""
        runtime_state.trading_paused = False
        
        applier = SafeConfigApplier(
            runtime_state=runtime_state,
            position_manager=position_manager,
            repository=repository,
            delegate=delegate,
        )
        
        # Add pending config
        await applier.apply(config)
        assert len(applier._pending) == 1
        
        # Now make it safe
        runtime_state.trading_paused = True
        position_manager._positions = []
        
        await applier.flush_if_safe()
        
        assert len(applier._pending) == 0
        assert len(delegate.applied_configs) == 1
    
    @pytest.mark.asyncio
    async def test_flush_if_safe_does_nothing_when_unsafe(
        self, runtime_state, position_manager, repository, delegate, config
    ):
        """Should not flush when still unsafe."""
        runtime_state.trading_paused = False
        
        applier = SafeConfigApplier(
            runtime_state=runtime_state,
            position_manager=position_manager,
            repository=repository,
            delegate=delegate,
        )
        
        # Add pending config
        await applier.apply(config)
        
        # Still not safe
        await applier.flush_if_safe()
        
        assert len(applier._pending) == 1
        assert len(delegate.applied_configs) == 0
