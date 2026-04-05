"""Tests for position guard worker."""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass

from quantgambit.execution.position_guard_worker import (
    PositionGuardWorker,
    PositionGuardConfig,
    _should_close as _should_close_impl,
    _check_trailing_stop,
)
from quantgambit.execution.manager import PositionSnapshot
from quantgambit.risk.fee_model import FeeConfig, FeeModel


def _should_close(pos, price, config, trailing_peaks=None, fee_model=None, now_ts=None):
    if now_ts is None:
        now_ts = time.time()
    if trailing_peaks is None:
        trailing_peaks = {}
    return _should_close_impl(pos, price, now_ts, config, trailing_peaks, fee_model)


class TestShouldClose:
    """Tests for _should_close function."""
    
    def test_stop_loss_hit_long(self):
        """Long position should close when price hits stop loss."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            stop_loss=95.0,
        )
        config = PositionGuardConfig()
        
        # Price above stop loss - no close
        result = _should_close(pos, 96.0, config, {})
        assert result is None
        
        # Price at stop loss - close
        result = _should_close(pos, 95.0, config, {})
        assert result == "stop_loss_hit"
        
        # Price below stop loss - close
        result = _should_close(pos, 94.0, config, {})
        assert result == "stop_loss_hit"
    
    def test_stop_loss_hit_short(self):
        """Short position should close when price hits stop loss."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="short",
            size=1.0,
            entry_price=100.0,
            stop_loss=105.0,
        )
        config = PositionGuardConfig()
        
        # Price below stop loss - no close
        result = _should_close(pos, 104.0, config, {})
        assert result is None
        
        # Price at stop loss - close
        result = _should_close(pos, 105.0, config, {})
        assert result == "stop_loss_hit"
        
        # Price above stop loss - close
        result = _should_close(pos, 106.0, config, {})
        assert result == "stop_loss_hit"
    
    def test_take_profit_hit_long(self):
        """Long position should close when price hits take profit."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            take_profit=110.0,
        )
        config = PositionGuardConfig()
        
        # Price below take profit - no close
        result = _should_close(pos, 109.0, config, {})
        assert result is None
        
        # Price at take profit - close
        result = _should_close(pos, 110.0, config, {})
        assert result == "take_profit_hit"
        
        # Price above take profit - close
        result = _should_close(pos, 111.0, config, {})
        assert result == "take_profit_hit"
    
    def test_take_profit_hit_short(self):
        """Short position should close when price hits take profit."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="short",
            size=1.0,
            entry_price=100.0,
            take_profit=90.0,
        )
        config = PositionGuardConfig()
        
        # Price above take profit - no close
        result = _should_close(pos, 91.0, config, {})
        assert result is None
        
        # Price at take profit - close
        result = _should_close(pos, 90.0, config, {})
        assert result == "take_profit_hit"
        
        # Price below take profit - close
        result = _should_close(pos, 89.0, config, {})
        assert result == "take_profit_hit"
    
    def test_max_age_exceeded(self):
        """Position should close when max age exceeded."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            opened_at=now - 3600,  # Opened 1 hour ago
        )
        
        # Max age 2 hours - no close
        config = PositionGuardConfig(max_position_age_sec=7200)
        result = _should_close(pos, 100.0, config, {})
        assert result is None
        
        # Max age 30 minutes - close
        config = PositionGuardConfig(max_position_age_sec=1800)
        result = _should_close(pos, 100.0, config, {})
        assert result == "max_age_exceeded"
    
    def test_max_age_disabled(self):
        """Position should not close when max age is 0."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            opened_at=now - 86400,  # Opened 24 hours ago
        )
        config = PositionGuardConfig(max_position_age_sec=0.0)
        
        result = _should_close(pos, 100.0, config, {})
        assert result is None

    def test_breakeven_protection_triggers_after_mfe(self):
        """Breakeven protection should trigger after MFE threshold is reached."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            mfe_pct=0.20,  # 20 bps MFE
        )
        config = PositionGuardConfig(
            breakeven_activation_bps=10.0,
            breakeven_buffer_bps=2.0,
        )
        # Price retraces below breakeven + buffer
        result = _should_close(pos, 100.01, config, {}, None)
        assert result == "breakeven_stop_hit"

    def test_breakeven_protection_not_active_before_mfe(self):
        """Breakeven protection should not trigger before activation threshold."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            mfe_pct=0.05,  # 5 bps MFE
        )
        config = PositionGuardConfig(
            breakeven_activation_bps=10.0,
            breakeven_buffer_bps=2.0,
        )
        result = _should_close(pos, 100.01, config, {}, None)
        assert result is None

    def test_breakeven_respects_min_hold(self):
        """Breakeven protection should respect min hold time."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            mfe_pct=0.20,  # 20 bps MFE
            opened_at=now - 5,
        )
        config = PositionGuardConfig(
            breakeven_activation_bps=10.0,
            breakeven_buffer_bps=2.0,
            breakeven_min_hold_sec=10.0,
        )
        result = _should_close(pos, 100.01, config, {}, None)
        assert result is None
        # After min hold, breakeven can trigger
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            mfe_pct=0.20,
            opened_at=now - 20,
        )
        result = _should_close(pos, 100.01, config, {}, None)
        assert result == "breakeven_stop_hit"

    def test_trailing_respects_min_hold(self):
        """Trailing stop should respect min hold time."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            opened_at=now - 5,
        )
        config = PositionGuardConfig(
            trailing_stop_bps=100.0,
            trailing_activation_bps=0.0,
            trailing_min_hold_sec=10.0,
        )
        trailing_peaks = {"BTCUSDT:long": 110.0}
        # Would trigger trailing, but min hold blocks
        result = _should_close(pos, 108.0, config, trailing_peaks, None)
        assert result is None
        # After min hold, trailing can trigger
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            opened_at=now - 20,
        )
        result = _should_close(pos, 108.0, config, trailing_peaks, None)
        assert result == "trailing_stop_hit"


class TestTrailingStop:
    """Tests for trailing stop functionality."""
    
    def test_trailing_stop_long_position(self):
        """Trailing stop should track peak and close on pullback."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
        )
        # Initialize with a starting peak
        trailing_peaks = {"BTCUSDT:long": 100.0}
        trailing_bps = 100.0  # 1%
        
        # Price goes up - no close, peak updated
        result = _check_trailing_stop(pos, 105.0, trailing_bps, trailing_peaks)
        assert result is None
        assert trailing_peaks["BTCUSDT:long"] == 105.0
        
        # Price goes higher - no close, peak updated
        result = _check_trailing_stop(pos, 110.0, trailing_bps, trailing_peaks)
        assert result is None
        assert trailing_peaks["BTCUSDT:long"] == 110.0
        
        # Small pullback - no close
        result = _check_trailing_stop(pos, 109.5, trailing_bps, trailing_peaks)
        assert result is None
        
        # Large pullback (>1% from peak) - close
        result = _check_trailing_stop(pos, 108.0, trailing_bps, trailing_peaks)
        assert result == "trailing_stop_hit"
    
    def test_trailing_stop_short_position(self):
        """Trailing stop should track trough and close on rally."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="short",
            size=1.0,
            entry_price=100.0,
        )
        # Initialize with a starting trough
        trailing_peaks = {"BTCUSDT:short": 100.0}
        trailing_bps = 100.0  # 1%
        
        # Price goes down - no close, trough updated
        result = _check_trailing_stop(pos, 95.0, trailing_bps, trailing_peaks)
        assert result is None
        assert trailing_peaks["BTCUSDT:short"] == 95.0
        
        # Price goes lower - no close, trough updated
        result = _check_trailing_stop(pos, 90.0, trailing_bps, trailing_peaks)
        assert result is None
        assert trailing_peaks["BTCUSDT:short"] == 90.0
        
        # Small rally - no close
        result = _check_trailing_stop(pos, 90.5, trailing_bps, trailing_peaks)
        assert result is None
        
        # Large rally (>1% from trough) - close
        result = _check_trailing_stop(pos, 92.0, trailing_bps, trailing_peaks)
        assert result == "trailing_stop_hit"
    
    def test_trailing_stop_disabled(self):
        """Trailing stop should not trigger when disabled."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
        )
        trailing_peaks = {}
        
        result = _check_trailing_stop(pos, 50.0, 0.0, trailing_peaks)
        assert result is None

    def test_trailing_activation_blocks_until_mfe(self):
        """Trailing stop should not trigger before activation MFE threshold."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            mfe_pct=0.40,  # 40 bps MFE
        )
        config = PositionGuardConfig(
            trailing_stop_bps=100.0,
            trailing_activation_bps=50.0,
        )
        trailing_peaks = {"BTCUSDT:long": 110.0}
        result = _should_close(pos, 108.0, config, trailing_peaks, None)
        assert result is None

    def test_trailing_activation_allows_after_mfe(self):
        """Trailing stop should trigger once activation MFE threshold is reached."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            mfe_pct=0.60,  # 60 bps MFE
        )
        config = PositionGuardConfig(
            trailing_stop_bps=100.0,
            trailing_activation_bps=50.0,
        )
        trailing_peaks = {"BTCUSDT:long": 110.0}
        result = _should_close(pos, 108.0, config, trailing_peaks, None)
        assert result == "trailing_stop_hit"


class TestPositionGuardWorker:
    """Tests for PositionGuardWorker."""
    
    @pytest.fixture
    def exchange_client(self):
        """Create mock exchange client."""
        client = MagicMock()
        client.close_position = AsyncMock(return_value=MagicMock(
            status="filled",
            fill_price=100.0,
            fee_usd=0.1,
            order_id="o1",
            timestamp=time.time(),
        ))
        client.reference_prices = MagicMock()
        client.reference_prices.get_reference_price = MagicMock(return_value=100.0)
        return client
    
    @pytest.fixture
    def position_manager(self):
        """Create mock position manager."""
        manager = MagicMock()
        manager.list_open_positions = AsyncMock(return_value=[])
        manager.mark_closing = AsyncMock()
        manager.finalize_close = AsyncMock()
        return manager
    
    @pytest.mark.asyncio
    async def test_tick_closes_position_on_stop_loss(self, exchange_client, position_manager):
        """Should close position when stop loss hit."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            stop_loss=95.0,
            opened_at=time.time(),
        )
        position_manager.list_open_positions = AsyncMock(return_value=[pos])
        exchange_client.reference_prices.get_reference_price = MagicMock(return_value=94.0)
        
        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=position_manager,
            config=PositionGuardConfig(),
        )
        
        await worker._tick()
        
        position_manager.mark_closing.assert_called_once_with("BTCUSDT", reason="stop_loss_hit")
        exchange_client.close_position.assert_called_once()
        close_call = exchange_client.close_position.call_args
        assert close_call.args[:3] == ("BTCUSDT", "long", 1.0)
        assert close_call.kwargs.get("client_order_id")
    
    @pytest.mark.asyncio
    async def test_tick_closes_position_on_max_age(self, exchange_client, position_manager):
        """Should close position when max age exceeded."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            opened_at=time.time() - 3600,  # 1 hour ago
        )
        position_manager.list_open_positions = AsyncMock(return_value=[pos])
        
        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=position_manager,
            config=PositionGuardConfig(max_position_age_sec=1800),  # 30 min max
            fee_model=FeeModel(FeeConfig.bybit_regular()),
        )
        
        await worker._tick()
        
        position_manager.mark_closing.assert_called_once_with("BTCUSDT", reason="max_age_exceeded")
        exchange_client.close_position.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_tick_does_not_close_healthy_position(self, exchange_client, position_manager):
        """Should not close position that doesn't meet close criteria."""
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            stop_loss=90.0,
            take_profit=120.0,
            opened_at=time.time(),
        )
        position_manager.list_open_positions = AsyncMock(return_value=[pos])
        exchange_client.reference_prices.get_reference_price = MagicMock(return_value=105.0)
        
        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=position_manager,
            config=PositionGuardConfig(max_position_age_sec=3600),
        )
        
        await worker._tick()
        
        position_manager.mark_closing.assert_not_called()
        exchange_client.close_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_closes_when_exchange_protection_missing(self, exchange_client, position_manager):
        """If protection verification is enabled and exchange lacks SL/TP, close the position and trigger kill switch."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            opened_at=now - 10,
        )
        position_manager.list_open_positions = AsyncMock(return_value=[pos])
        exchange_client.reference_prices.get_reference_price = MagicMock(return_value=100.0)
        exchange_client.fetch_positions = AsyncMock(return_value=[{"symbol": "BTCUSDT"}])  # Missing SL/TP

        kill_switch = MagicMock()
        kill_switch.is_active = MagicMock(return_value=False)
        kill_switch.trigger = AsyncMock()

        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=position_manager,
            config=PositionGuardConfig(
                verify_exchange_protection=True,
                require_protection=True,
                require_stop_loss=True,
                protection_grace_sec=0.0,
                flatten_all_on_protection_failure=False,
            ),
            kill_switch=kill_switch,
        )

        await worker._tick()

        position_manager.mark_closing.assert_called_once_with("BTCUSDT", reason="protection_failure")
        exchange_client.close_position.assert_called_once()
        assert kill_switch.trigger.await_count == 1

    @pytest.mark.asyncio
    async def test_tick_does_not_close_within_protection_grace(self, exchange_client, position_manager):
        """Protection verification should allow a short grace period after entry."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            opened_at=now,  # fresh
        )
        position_manager.list_open_positions = AsyncMock(return_value=[pos])
        exchange_client.reference_prices.get_reference_price = MagicMock(return_value=100.0)
        exchange_client.fetch_positions = AsyncMock(return_value=[{"symbol": "BTCUSDT"}])  # Missing SL/TP

        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=position_manager,
            config=PositionGuardConfig(
                verify_exchange_protection=True,
                require_protection=True,
                require_stop_loss=True,
                protection_grace_sec=30.0,
                flatten_all_on_protection_failure=False,
            ),
        )

        await worker._tick()

        position_manager.mark_closing.assert_not_called()
        exchange_client.close_position.assert_not_called()
