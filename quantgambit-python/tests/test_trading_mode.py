"""Tests for TradingMode configuration and TradingModeManager."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import json

from quantgambit.config.trading_mode import (
    TradingMode,
    TradingModeConfig,
    TradingModeManager,
    TRADING_MODE_PRESETS,
    get_preset,
    validate_config,
)


class TestTradingModeEnum:
    """Tests for TradingMode enum."""
    
    def test_trading_modes_exist(self):
        """All three trading modes should exist."""
        assert TradingMode.SCALPING == "scalping"
        assert TradingMode.SPOT == "spot"
        assert TradingMode.SWING == "swing"
        assert TradingMode.CONSERVATIVE == "conservative"
    
    def test_trading_mode_from_string(self):
        """Should create TradingMode from string."""
        assert TradingMode("scalping") == TradingMode.SCALPING
        assert TradingMode("spot") == TradingMode.SPOT
        assert TradingMode("swing") == TradingMode.SWING
        assert TradingMode("conservative") == TradingMode.CONSERVATIVE


class TestTradingModeConfig:
    """Tests for TradingModeConfig dataclass."""
    
    def test_scalping_preset_values(self):
        """Scalping preset should have aggressive parameters."""
        config = TRADING_MODE_PRESETS[TradingMode.SCALPING]
        
        assert config.min_order_interval_sec == 15.0
        assert config.same_direction_hysteresis_sec == 30.0
        assert config.max_entries_per_hour == 50
        assert config.min_hold_time_sec == 10.0
        assert config.min_confirmations_for_exit == 1
    
    def test_swing_preset_values(self):
        """Swing preset should have moderate parameters."""
        config = TRADING_MODE_PRESETS[TradingMode.SWING]
        
        assert config.min_order_interval_sec == 60.0
        assert config.same_direction_hysteresis_sec == 120.0
        assert config.max_entries_per_hour == 10
        assert config.min_hold_time_sec == 30.0
        assert config.min_confirmations_for_exit == 2
    
    def test_conservative_preset_values(self):
        """Conservative preset should have strict parameters."""
        config = TRADING_MODE_PRESETS[TradingMode.CONSERVATIVE]
        
        assert config.min_order_interval_sec == 120.0
        assert config.same_direction_hysteresis_sec == 300.0
        assert config.max_entries_per_hour == 6
        assert config.min_hold_time_sec == 60.0
        assert config.min_confirmations_for_exit == 2
    
    def test_config_to_dict(self):
        """Config should serialize to dict."""
        config = TRADING_MODE_PRESETS[TradingMode.SCALPING]
        data = config.to_dict()
        
        assert data["mode"] == "scalping"
        assert data["min_order_interval_sec"] == 15.0
        assert isinstance(data, dict)
    
    def test_config_from_dict(self):
        """Config should deserialize from dict."""
        data = {
            "mode": "scalping",
            "min_order_interval_sec": 15.0,
            "entry_cooldown_sec": 15.0,
            "exit_cooldown_sec": 10.0,
            "same_direction_hysteresis_sec": 30.0,
            "max_entries_per_hour": 50,
            "min_hold_time_sec": 10.0,
            "min_confirmations_for_exit": 1,
            "min_profit_buffer_bps": 3.0,
            "fee_check_grace_period_sec": 15.0,
            "urgency_bypass_threshold": 0.8,
            "confirmation_bypass_count": 3,
            "deterioration_force_exit_count": 3,
        }
        config = TradingModeConfig.from_dict(data)
        
        assert config.mode == TradingMode.SCALPING
        assert config.min_order_interval_sec == 15.0
    
    def test_all_presets_valid(self):
        """All preset configs should pass validation."""
        for mode, config in TRADING_MODE_PRESETS.items():
            assert validate_config(config), f"{mode} preset failed validation"
    
    def test_validate_config_rejects_invalid(self):
        """Validation should reject invalid configs."""
        config = TRADING_MODE_PRESETS[TradingMode.SCALPING]
        
        # Invalid min_order_interval_sec
        invalid = TradingModeConfig(
            mode=TradingMode.SCALPING,
            min_order_interval_sec=0,  # Invalid
            entry_cooldown_sec=15.0,
            exit_cooldown_sec=10.0,
            same_direction_hysteresis_sec=30.0,
            max_entries_per_hour=50,
            min_hold_time_sec=10.0,
            min_confirmations_for_exit=1,
            min_profit_buffer_bps=3.0,
            fee_check_grace_period_sec=15.0,
            urgency_bypass_threshold=0.8,
            confirmation_bypass_count=3,
            deterioration_force_exit_count=3,
        )
        assert not validate_config(invalid)
        
        # Invalid urgency_bypass_threshold
        invalid2 = TradingModeConfig(
            mode=TradingMode.SCALPING,
            min_order_interval_sec=15.0,
            entry_cooldown_sec=15.0,
            exit_cooldown_sec=10.0,
            same_direction_hysteresis_sec=30.0,
            max_entries_per_hour=50,
            min_hold_time_sec=10.0,
            min_confirmations_for_exit=1,
            min_profit_buffer_bps=3.0,
            fee_check_grace_period_sec=15.0,
            urgency_bypass_threshold=1.5,  # Invalid - must be <= 1.0
            confirmation_bypass_count=3,
            deterioration_force_exit_count=3,
        )
        assert not validate_config(invalid2)


class TestTradingModeManager:
    """Tests for TradingModeManager."""
    
    def test_default_mode(self):
        """Manager should use default mode when no override."""
        manager = TradingModeManager(default_mode=TradingMode.SWING)
        
        assert manager.default_mode == TradingMode.SWING
        assert manager.get_mode() == TradingMode.SWING
        assert manager.get_mode("BTCUSDT") == TradingMode.SWING
    
    def test_get_config_returns_preset(self):
        """get_config should return the preset for the mode."""
        manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        
        config = manager.get_config()
        assert config.mode == TradingMode.SCALPING
        assert config.min_order_interval_sec == 15.0
    
    @pytest.mark.asyncio
    async def test_set_mode_global(self):
        """set_mode without symbol should change default mode."""
        manager = TradingModeManager(default_mode=TradingMode.SWING)
        
        await manager.set_mode(TradingMode.SCALPING, persist=False)
        
        assert manager.default_mode == TradingMode.SCALPING
        assert manager.get_mode() == TradingMode.SCALPING
    
    @pytest.mark.asyncio
    async def test_set_mode_per_symbol(self):
        """set_mode with symbol should create override."""
        manager = TradingModeManager(default_mode=TradingMode.SWING)
        
        await manager.set_mode(TradingMode.SCALPING, symbol="BTCUSDT", persist=False)
        
        # Default unchanged
        assert manager.default_mode == TradingMode.SWING
        assert manager.get_mode() == TradingMode.SWING
        
        # Symbol has override
        assert manager.get_mode("BTCUSDT") == TradingMode.SCALPING
        assert manager.get_mode("ETHUSDT") == TradingMode.SWING  # No override
    
    @pytest.mark.asyncio
    async def test_clear_symbol_override(self):
        """clear_symbol_override should remove override."""
        manager = TradingModeManager(default_mode=TradingMode.SWING)
        
        await manager.set_mode(TradingMode.SCALPING, symbol="BTCUSDT", persist=False)
        assert manager.get_mode("BTCUSDT") == TradingMode.SCALPING
        
        await manager.clear_symbol_override("BTCUSDT", persist=False)
        assert manager.get_mode("BTCUSDT") == TradingMode.SWING
    
    @pytest.mark.asyncio
    async def test_redis_persistence(self):
        """Manager should persist to Redis."""
        mock_redis = AsyncMock()
        manager = TradingModeManager(
            redis_client=mock_redis,
            bot_id="test_bot",
            default_mode=TradingMode.SWING,
        )
        
        await manager.set_mode(TradingMode.SCALPING, persist=True)
        
        # Should have called redis.set
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        data = json.loads(call_args[0][1])
        
        assert key == "quantgambit:test_bot:config:trading_mode"
        assert data["default_mode"] == "scalping"
    
    @pytest.mark.asyncio
    async def test_redis_load(self):
        """Manager should load from Redis."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({
            "default_mode": "scalping",
            "symbol_overrides": {"BTCUSDT": "conservative"},
            "updated_at": 1234567890.0,
        })
        
        manager = TradingModeManager(
            redis_client=mock_redis,
            bot_id="test_bot",
            default_mode=TradingMode.SWING,
        )
        
        await manager.load()
        
        assert manager.default_mode == TradingMode.SCALPING
        assert manager.get_mode("BTCUSDT") == TradingMode.CONSERVATIVE
    
    @pytest.mark.asyncio
    async def test_telemetry_emission(self):
        """Manager should emit telemetry on mode change."""
        mock_telemetry = AsyncMock()
        mock_context = MagicMock()
        
        manager = TradingModeManager(
            bot_id="test_bot",
            default_mode=TradingMode.SWING,
            telemetry=mock_telemetry,
            telemetry_context=mock_context,
        )
        
        await manager.set_mode(TradingMode.SCALPING, persist=False)
        
        mock_telemetry.publish_event.assert_called_once()
        call_kwargs = mock_telemetry.publish_event.call_args[1]
        assert call_kwargs["event_type"] == "trading_mode_changed"
        assert call_kwargs["payload"]["old_mode"] == "swing"
        assert call_kwargs["payload"]["new_mode"] == "scalping"
    
    def test_symbol_overrides_property(self):
        """symbol_overrides should return copy of overrides."""
        manager = TradingModeManager(default_mode=TradingMode.SWING)
        manager._symbol_overrides = {"BTCUSDT": TradingMode.SCALPING}
        
        overrides = manager.symbol_overrides
        assert overrides == {"BTCUSDT": TradingMode.SCALPING}
        
        # Should be a copy
        overrides["ETHUSDT"] = TradingMode.CONSERVATIVE
        assert "ETHUSDT" not in manager._symbol_overrides


class TestGetPreset:
    """Tests for get_preset helper function."""
    
    def test_get_preset_scalping(self):
        """get_preset should return scalping config."""
        config = get_preset(TradingMode.SCALPING)
        assert config.mode == TradingMode.SCALPING
    
    def test_get_preset_swing(self):
        """get_preset should return swing config."""
        config = get_preset(TradingMode.SWING)
        assert config.mode == TradingMode.SWING
    
    def test_get_preset_conservative(self):
        """get_preset should return conservative config."""
        config = get_preset(TradingMode.CONSERVATIVE)
        assert config.mode == TradingMode.CONSERVATIVE



class TestCreateFromEnv:
    """Tests for create_trading_mode_manager_from_env factory function."""
    
    def test_create_with_default_mode(self, monkeypatch):
        """Should use THROTTLE_MODE env var."""
        from quantgambit.config.trading_mode import create_trading_mode_manager_from_env
        
        monkeypatch.setenv("THROTTLE_MODE", "scalping")
        monkeypatch.setenv("BOT_ID", "test_bot")
        
        manager = create_trading_mode_manager_from_env()
        
        assert manager.default_mode == TradingMode.SCALPING
    
    def test_create_with_invalid_mode_falls_back(self, monkeypatch):
        """Should fall back to swing for invalid mode."""
        from quantgambit.config.trading_mode import create_trading_mode_manager_from_env
        
        monkeypatch.setenv("THROTTLE_MODE", "invalid_mode")
        monkeypatch.setenv("BOT_ID", "test_bot")
        
        manager = create_trading_mode_manager_from_env()
        
        assert manager.default_mode == TradingMode.SWING
    
    def test_create_with_no_env_uses_swing_for_non_spot(self, monkeypatch):
        """Should default to swing when no env var set for non-spot markets."""
        from quantgambit.config.trading_mode import create_trading_mode_manager_from_env
        
        monkeypatch.delenv("THROTTLE_MODE", raising=False)
        monkeypatch.delenv("MARKET_TYPE", raising=False)
        monkeypatch.setenv("BOT_ID", "test_bot")
        
        manager = create_trading_mode_manager_from_env()
        
        assert manager.default_mode == TradingMode.SWING

    def test_create_with_no_env_uses_spot_for_spot_market(self, monkeypatch):
        """Spot runtimes should default to the explicit spot cadence preset."""
        from quantgambit.config.trading_mode import create_trading_mode_manager_from_env

        monkeypatch.delenv("THROTTLE_MODE", raising=False)
        monkeypatch.setenv("MARKET_TYPE", "spot")
        monkeypatch.setenv("BOT_ID", "test_bot")

        manager = create_trading_mode_manager_from_env()

        assert manager.default_mode == TradingMode.SPOT
    def test_spot_preset_values(self):
        """Spot preset should keep active entry cadence without scalp churn."""
        config = TRADING_MODE_PRESETS[TradingMode.SPOT]

        assert config.min_order_interval_sec == 15.0
        assert config.entry_cooldown_sec == 45.0
        assert config.same_direction_hysteresis_sec == 90.0
        assert config.max_entries_per_hour == 24
        assert config.min_hold_time_sec == 60.0
