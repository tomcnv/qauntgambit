"""Tests for AlertsClient and alert functions."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os

from quantgambit.observability.alerts import (
    AlertsClient,
    AlertConfig,
    send_kill_switch_alert,
    send_kill_switch_reset_alert,
    send_reconciliation_alert,
    send_latency_alert,
)


class TestAlertConfig:
    """Tests for AlertConfig."""
    
    def test_default_config(self):
        """Default config should have sensible defaults."""
        config = AlertConfig(webhook_url="https://example.com/webhook")
        assert config.provider == "generic"
        assert config.channel is None
        assert config.username == "QuantGambit Bot"
        assert config.icon_emoji == ":robot_face:"
    
    def test_slack_config(self):
        """Slack config should be configurable."""
        config = AlertConfig(
            webhook_url="https://hooks.slack.com/services/xxx",
            provider="slack",
            channel="#alerts",
            username="Trading Bot",
        )
        assert config.provider == "slack"
        assert config.channel == "#alerts"


class TestAlertsClient:
    """Tests for AlertsClient."""
    
    @pytest.fixture
    def slack_client(self):
        """Create Slack alerts client."""
        config = AlertConfig(
            webhook_url="https://hooks.slack.com/services/xxx",
            provider="slack",
        )
        return AlertsClient(config)
    
    @pytest.fixture
    def discord_client(self):
        """Create Discord alerts client."""
        config = AlertConfig(
            webhook_url="https://discord.com/api/webhooks/xxx",
            provider="discord",
        )
        return AlertsClient(config)
    
    @pytest.fixture
    def generic_client(self):
        """Create generic alerts client."""
        config = AlertConfig(
            webhook_url="https://example.com/webhook",
            provider="generic",
        )
        return AlertsClient(config)
    
    def test_build_slack_payload(self, slack_client):
        """Slack payload should use Block Kit format."""
        payload = slack_client._build_payload(
            alert_type="kill_switch",
            message="Test message",
            metadata={"tenant_id": "t1", "bot_id": "b1", "trigger": "STALE_BOOK"},
            severity="critical",
        )
        
        assert "blocks" in payload
        assert "attachments" in payload
        assert payload["attachments"][0]["color"] == "#ff0000"  # Critical = red
        
        # Check header block
        header = payload["blocks"][0]
        assert header["type"] == "header"
        assert "KILL SWITCH" in header["text"]["text"]
    
    def test_build_discord_payload(self, discord_client):
        """Discord payload should use embed format."""
        payload = discord_client._build_payload(
            alert_type="reconciliation",
            message="Found discrepancies",
            metadata={"count": 5},
            severity="warning",
        )
        
        assert "embeds" in payload
        embed = payload["embeds"][0]
        assert embed["title"] == "RECONCILIATION"
        assert embed["color"] == 0xffcc00  # Warning = yellow
        assert "timestamp" in embed
    
    def test_build_generic_payload(self, generic_client):
        """Generic payload should be simple JSON."""
        payload = generic_client._build_payload(
            alert_type="test",
            message="Test message",
            metadata={"key": "value"},
            severity="info",
        )
        
        assert payload["type"] == "test"
        assert payload["message"] == "Test message"
        assert payload["severity"] == "info"
        assert payload["metadata"]["key"] == "value"
    
    @pytest.mark.asyncio
    async def test_send_success(self, slack_client):
        """Send should return True on success."""
        mock_response = MagicMock()
        mock_response.status = 200
        
        # Create a proper async context manager mock
        mock_post_cm = AsyncMock()
        mock_post_cm.__aenter__.return_value = mock_response
        mock_post_cm.__aexit__.return_value = None
        
        mock_session = MagicMock()
        mock_session.post.return_value = mock_post_cm
        mock_session.closed = False
        
        slack_client._session = mock_session
        
        result = await slack_client.send(
            alert_type="test",
            message="Test",
            severity="info",
        )
        
        assert result is True
        mock_session.post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_failure(self, slack_client):
        """Send should return False on HTTP error."""
        mock_response = MagicMock()
        mock_response.status = 500
        
        # Create a proper async context manager mock
        mock_post_cm = AsyncMock()
        mock_post_cm.__aenter__.return_value = mock_response
        mock_post_cm.__aexit__.return_value = None
        
        mock_session = MagicMock()
        mock_session.post.return_value = mock_post_cm
        mock_session.closed = False
        
        slack_client._session = mock_session
        
        result = await slack_client.send(
            alert_type="test",
            message="Test",
            severity="info",
        )
        
        assert result is False


class TestAlertConvenienceFunctions:
    """Tests for convenience alert functions."""
    
    @pytest.fixture
    def mock_client(self):
        """Create mock alerts client."""
        client = MagicMock(spec=AlertsClient)
        client.send = AsyncMock(return_value=True)
        return client
    
    @pytest.mark.asyncio
    async def test_send_kill_switch_alert(self, mock_client):
        """Kill switch alert should have correct format."""
        result = await send_kill_switch_alert(
            client=mock_client,
            trigger="STALE_BOOK",
            message="Book data stale for 5s",
            tenant_id="t1",
            bot_id="b1",
            triggered_by={"STALE_BOOK": 1234567890.0},
        )
        
        assert result is True
        mock_client.send.assert_called_once()
        
        call_args = mock_client.send.call_args
        assert call_args.kwargs["alert_type"] == "kill_switch_triggered"
        assert call_args.kwargs["severity"] == "critical"
        assert "Kill switch" in call_args.kwargs["message"]
    
    @pytest.mark.asyncio
    async def test_send_kill_switch_reset_alert(self, mock_client):
        """Kill switch reset alert should have correct format."""
        result = await send_kill_switch_reset_alert(
            client=mock_client,
            operator_id="admin@example.com",
            tenant_id="t1",
            bot_id="b1",
        )
        
        assert result is True
        call_args = mock_client.send.call_args
        assert call_args.kwargs["alert_type"] == "kill_switch_reset"
        assert call_args.kwargs["severity"] == "info"
    
    @pytest.mark.asyncio
    async def test_send_reconciliation_alert(self, mock_client):
        """Reconciliation alert severity should scale with count."""
        # Low count = warning
        await send_reconciliation_alert(
            client=mock_client,
            discrepancy_count=2,
            healed_count=2,
            tenant_id="t1",
            bot_id="b1",
        )
        assert mock_client.send.call_args.kwargs["severity"] == "warning"
        
        mock_client.send.reset_mock()
        
        # High count = critical
        await send_reconciliation_alert(
            client=mock_client,
            discrepancy_count=10,
            healed_count=5,
            tenant_id="t1",
            bot_id="b1",
        )
        assert mock_client.send.call_args.kwargs["severity"] == "critical"
    
    @pytest.mark.asyncio
    async def test_send_latency_alert(self, mock_client):
        """Latency alert should include metric details."""
        result = await send_latency_alert(
            client=mock_client,
            metric_name="tick_to_decision",
            p99_ms=150.5,
            threshold_ms=100.0,
            tenant_id="t1",
            bot_id="b1",
        )
        
        assert result is True
        call_args = mock_client.send.call_args
        assert call_args.kwargs["alert_type"] == "latency_slo_breach"
        assert "150.5ms" in call_args.kwargs["message"]
        assert "100.0ms" in call_args.kwargs["message"]


class TestBuildAlertsClient:
    """Tests for _build_alerts_client factory function."""
    
    def test_no_webhook_returns_none(self):
        """Should return None if no webhook configured."""
        from quantgambit.runtime.app import _build_alerts_client
        
        with patch.dict(os.environ, {}, clear=True):
            # Clear all webhook env vars
            for key in ["SLACK_WEBHOOK_URL", "DISCORD_WEBHOOK_URL", "ALERT_WEBHOOK_URL"]:
                os.environ.pop(key, None)
            
            client = _build_alerts_client()
            assert client is None
    
    def test_slack_webhook_takes_precedence(self):
        """Slack webhook should take precedence over others."""
        from quantgambit.runtime.app import _build_alerts_client
        
        with patch.dict(os.environ, {
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/xxx",
            "DISCORD_WEBHOOK_URL": "https://discord.com/xxx",
            "ALERT_WEBHOOK_URL": "https://generic.com/xxx",
        }):
            client = _build_alerts_client()
            assert client is not None
            assert client.config.provider == "slack"
            assert client.config.webhook_url == "https://hooks.slack.com/xxx"
    
    def test_discord_webhook_second_priority(self):
        """Discord webhook should be used if no Slack."""
        from quantgambit.runtime.app import _build_alerts_client
        
        with patch.dict(os.environ, {
            "DISCORD_WEBHOOK_URL": "https://discord.com/xxx",
            "ALERT_WEBHOOK_URL": "https://generic.com/xxx",
        }, clear=True):
            # Ensure SLACK is not set
            os.environ.pop("SLACK_WEBHOOK_URL", None)
            
            client = _build_alerts_client()
            assert client is not None
            assert client.config.provider == "discord"
    
    def test_generic_webhook_fallback(self):
        """Generic webhook should be fallback."""
        from quantgambit.runtime.app import _build_alerts_client
        
        with patch.dict(os.environ, {
            "ALERT_WEBHOOK_URL": "https://generic.com/xxx",
        }, clear=True):
            os.environ.pop("SLACK_WEBHOOK_URL", None)
            os.environ.pop("DISCORD_WEBHOOK_URL", None)
            
            client = _build_alerts_client()
            assert client is not None
            assert client.config.provider == "generic"
    
    def test_custom_channel_and_username(self):
        """Should respect custom channel and username."""
        from quantgambit.runtime.app import _build_alerts_client
        
        with patch.dict(os.environ, {
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/xxx",
            "ALERT_CHANNEL": "#trading-alerts",
            "ALERT_USERNAME": "DeepTrader",
        }):
            client = _build_alerts_client()
            assert client.config.channel == "#trading-alerts"
            assert client.config.username == "DeepTrader"
