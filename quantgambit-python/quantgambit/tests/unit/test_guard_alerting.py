"""
Unit tests for Position Guard alerting functionality.

Tests cover:
1. Alert sent on trailing stop trigger
2. Alert sent on stop loss trigger  
3. Alert sent on take profit trigger
4. Alert sent on max age trigger
5. Alert contains correct P&L information
6. Alert failure doesn't crash guard worker
7. No alert sent when alerts_client is None
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import Optional

from quantgambit.execution.position_guard_worker import (
    PositionGuardWorker,
    PositionGuardConfig,
    GUARD_ALERT_CONFIG,
)


# Mock PositionSnapshot for testing
@dataclass
class MockPositionSnapshot:
    symbol: str
    side: str
    size: float
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: Optional[float] = None
    reference_price: Optional[float] = None
    strategy_id: Optional[str] = None
    profile_id: Optional[str] = None


# Mock CloseStatus for testing
@dataclass
class MockCloseStatus:
    status: str = "filled"
    fill_price: Optional[float] = None
    fee_usd: Optional[float] = None
    order_id: Optional[str] = None
    timestamp: Optional[float] = None


@pytest.fixture
def mock_exchange_client():
    """Create mock exchange client."""
    client = MagicMock()
    client.close_position = AsyncMock(return_value=MockCloseStatus(
        status="filled",
        fill_price=51000.0,
        fee_usd=5.0,
        order_id="order_123",
        timestamp=1704067300.0,
    ))
    return client


@pytest.fixture
def mock_position_manager():
    """Create mock position manager."""
    manager = MagicMock()
    manager.list_open_positions = AsyncMock(return_value=[])
    manager.mark_closing = AsyncMock()
    manager.finalize_close = AsyncMock()
    return manager


@pytest.fixture
def mock_alerts_client():
    """Create mock alerts client."""
    client = AsyncMock()
    client.send = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_telemetry():
    """Create mock telemetry."""
    telemetry = MagicMock()
    telemetry.publish_order = AsyncMock()
    telemetry.publish_position_lifecycle = AsyncMock()
    telemetry.publish_guardrail = AsyncMock()
    telemetry.publish_health_snapshot = AsyncMock()
    return telemetry


@pytest.fixture
def guard_worker(mock_exchange_client, mock_position_manager, mock_alerts_client, mock_telemetry):
    """Create guard worker with all mocks."""
    return PositionGuardWorker(
        exchange_client=mock_exchange_client,
        position_manager=mock_position_manager,
        config=PositionGuardConfig(interval_sec=1.0, trailing_stop_bps=50),
        telemetry=mock_telemetry,
        telemetry_context=MagicMock(),
        alerts_client=mock_alerts_client,
        tenant_id="test_tenant",
        bot_id="test_bot",
    )


class TestGuardAlerting:
    """Tests for guard alerting functionality."""
    
    @pytest.mark.asyncio
    async def test_trailing_stop_sends_alert(self, guard_worker, mock_alerts_client):
        """Trailing stop trigger should send Slack/Discord alert."""
        pos = MockPositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50000.0,
            opened_at=1704067200.0,
        )
        
        await guard_worker._send_guard_alert(
            pos=pos,
            reason="trailing_stop_hit",
            exit_price=51000.0,
            realized_pnl=95.0,
            realized_pnl_pct=1.9,
            hold_time_sec=100.0,
        )
        
        mock_alerts_client.send.assert_called_once()
        call_args = mock_alerts_client.send.call_args
        
        assert call_args.kwargs["alert_type"] == "guard_trigger"
        assert "Trailing Stop" in call_args.kwargs["message"]
        assert call_args.kwargs["severity"] == "warning"
        assert call_args.kwargs["metadata"]["symbol"] == "BTCUSDT"
        assert call_args.kwargs["metadata"]["reason"] == "trailing_stop_hit"
    
    @pytest.mark.asyncio
    async def test_stop_loss_sends_alert(self, guard_worker, mock_alerts_client):
        """Stop loss trigger should send alert."""
        pos = MockPositionSnapshot(
            symbol="ETHUSDT",
            side="long",
            size=1.0,
            entry_price=3000.0,
            stop_loss=2900.0,
        )
        
        await guard_worker._send_guard_alert(
            pos=pos,
            reason="stop_loss_hit",
            exit_price=2895.0,
            realized_pnl=-105.0,
            realized_pnl_pct=-3.5,
            hold_time_sec=300.0,
        )
        
        mock_alerts_client.send.assert_called_once()
        call_args = mock_alerts_client.send.call_args
        
        assert "Stop Loss" in call_args.kwargs["message"]
        assert call_args.kwargs["severity"] == "warning"
        assert "🛑" in call_args.kwargs["message"]
    
    @pytest.mark.asyncio
    async def test_take_profit_sends_info_alert(self, guard_worker, mock_alerts_client):
        """Take profit trigger should send info-level alert."""
        pos = MockPositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50000.0,
            take_profit=52000.0,
        )
        
        await guard_worker._send_guard_alert(
            pos=pos,
            reason="take_profit_hit",
            exit_price=52100.0,
            realized_pnl=205.0,
            realized_pnl_pct=4.2,
            hold_time_sec=600.0,
        )
        
        mock_alerts_client.send.assert_called_once()
        call_args = mock_alerts_client.send.call_args
        
        assert "Take Profit" in call_args.kwargs["message"]
        assert call_args.kwargs["severity"] == "info"  # Not warning
        assert "🎯" in call_args.kwargs["message"]
    
    @pytest.mark.asyncio
    async def test_max_age_sends_alert(self, guard_worker, mock_alerts_client):
        """Max age trigger should send alert."""
        pos = MockPositionSnapshot(
            symbol="SOLUSDT",
            side="short",
            size=5.0,
            entry_price=100.0,
            opened_at=1704060000.0,
        )
        
        await guard_worker._send_guard_alert(
            pos=pos,
            reason="max_age_exceeded",
            exit_price=98.0,
            realized_pnl=10.0,
            realized_pnl_pct=2.0,
            hold_time_sec=7200.0,
        )
        
        mock_alerts_client.send.assert_called_once()
        call_args = mock_alerts_client.send.call_args
        
        assert "Max Age" in call_args.kwargs["message"]
        assert "⏰" in call_args.kwargs["message"]
    
    @pytest.mark.asyncio
    async def test_alert_contains_pnl(self, guard_worker, mock_alerts_client):
        """Alert should include P&L information with correct emoji."""
        pos = MockPositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50000.0,
        )
        
        # Positive P&L
        await guard_worker._send_guard_alert(
            pos=pos,
            reason="take_profit_hit",
            exit_price=55000.0,
            realized_pnl=500.0,
            realized_pnl_pct=10.0,
            hold_time_sec=3600.0,
        )
        
        call_args = mock_alerts_client.send.call_args
        message = call_args.kwargs["message"]
        
        assert "🟢" in message  # Positive P&L emoji
        assert "$500.00" in message
        assert "10.00%" in message
    
    @pytest.mark.asyncio
    async def test_alert_negative_pnl_emoji(self, guard_worker, mock_alerts_client):
        """Alert should show red emoji for negative P&L."""
        pos = MockPositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50000.0,
        )
        
        await guard_worker._send_guard_alert(
            pos=pos,
            reason="stop_loss_hit",
            exit_price=48000.0,
            realized_pnl=-200.0,
            realized_pnl_pct=-4.0,
            hold_time_sec=1800.0,
        )
        
        call_args = mock_alerts_client.send.call_args
        message = call_args.kwargs["message"]
        
        assert "🔴" in message  # Negative P&L emoji
    
    @pytest.mark.asyncio
    async def test_alert_failure_does_not_crash(self, guard_worker, mock_alerts_client):
        """Alert failure should not crash the guard worker."""
        mock_alerts_client.send.side_effect = Exception("Webhook error")
        
        pos = MockPositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50000.0,
        )
        
        # Should not raise
        await guard_worker._send_guard_alert(
            pos=pos,
            reason="trailing_stop_hit",
            exit_price=51000.0,
            realized_pnl=100.0,
            realized_pnl_pct=2.0,
            hold_time_sec=60.0,
        )
        
        # Test passed if we get here without exception
    
    @pytest.mark.asyncio
    async def test_no_alert_when_client_none(self, mock_exchange_client, mock_position_manager, mock_telemetry):
        """No alert should be sent when alerts_client is None."""
        worker = PositionGuardWorker(
            exchange_client=mock_exchange_client,
            position_manager=mock_position_manager,
            config=PositionGuardConfig(),
            telemetry=mock_telemetry,
            telemetry_context=MagicMock(),
            alerts_client=None,  # No alerts client
            tenant_id="test",
            bot_id="test",
        )
        
        pos = MockPositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50000.0,
        )
        
        # Should not raise
        await worker._send_guard_alert(
            pos=pos,
            reason="trailing_stop_hit",
            exit_price=51000.0,
            realized_pnl=100.0,
            realized_pnl_pct=2.0,
            hold_time_sec=60.0,
        )
    
    @pytest.mark.asyncio
    async def test_alert_metadata_includes_tenant_bot(self, guard_worker, mock_alerts_client):
        """Alert metadata should include tenant_id and bot_id."""
        pos = MockPositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50000.0,
        )
        
        await guard_worker._send_guard_alert(
            pos=pos,
            reason="trailing_stop_hit",
            exit_price=51000.0,
            realized_pnl=100.0,
            realized_pnl_pct=2.0,
            hold_time_sec=60.0,
        )
        
        call_args = mock_alerts_client.send.call_args
        metadata = call_args.kwargs["metadata"]
        
        assert metadata["tenant_id"] == "test_tenant"
        assert metadata["bot_id"] == "test_bot"


class TestGuardAlertConfig:
    """Tests for guard alert configuration mapping."""
    
    def test_all_reasons_have_config(self):
        """All guard reasons should have alert config."""
        reasons = [
            "trailing_stop_hit",
            "stop_loss_hit",
            "take_profit_hit",
            "max_age_exceeded",
        ]
        
        for reason in reasons:
            assert reason in GUARD_ALERT_CONFIG
            config = GUARD_ALERT_CONFIG[reason]
            assert "emoji" in config
            assert "severity" in config
            assert "label" in config
    
    def test_take_profit_is_info_severity(self):
        """Take profit should be info severity (not warning)."""
        assert GUARD_ALERT_CONFIG["take_profit_hit"]["severity"] == "info"
    
    def test_other_guards_are_warning_severity(self):
        """Other guards should be warning severity."""
        for reason in ["trailing_stop_hit", "stop_loss_hit", "max_age_exceeded"]:
            assert GUARD_ALERT_CONFIG[reason]["severity"] == "warning"
