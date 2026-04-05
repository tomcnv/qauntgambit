"""Alerting hooks for critical runtime events."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertConfig:
    webhook_url: str
    provider: str = "generic"  # generic | slack | discord
    channel: Optional[str] = None
    username: str = "QuantGambit Bot"
    icon_emoji: str = ":robot_face:"


class AlertsClient:
    """Webhook-based alert dispatcher with Slack/Discord support."""

    def __init__(self, config: AlertConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def send(
        self,
        alert_type: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
        severity: str = "warning",
    ) -> bool:
        """
        Send an alert to the configured webhook.
        
        Args:
            alert_type: Type of alert (e.g., "kill_switch", "reconciliation")
            message: Human-readable message
            metadata: Additional context
            severity: One of "info", "warning", "critical"
            
        Returns:
            True if sent successfully
        """
        try:
            payload = self._build_payload(alert_type, message, metadata, severity)
            session = await self._get_session()
            
            async with session.post(
                self.config.webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status >= 400:
                    logger.error(f"Alert send failed: {response.status}")
                    return False
                return True
        except Exception as e:
            logger.error(f"Alert send error: {e}")
            return False

    def _build_payload(
        self,
        alert_type: str,
        message: str,
        metadata: Optional[Dict[str, Any]],
        severity: str,
    ) -> Dict[str, Any]:
        """Build provider-specific payload."""
        if self.config.provider == "slack":
            return self._build_slack_payload(alert_type, message, metadata, severity)
        elif self.config.provider == "discord":
            return self._build_discord_payload(alert_type, message, metadata, severity)
        else:
            return self._build_generic_payload(alert_type, message, metadata, severity)

    def _build_slack_payload(
        self,
        alert_type: str,
        message: str,
        metadata: Optional[Dict[str, Any]],
        severity: str,
    ) -> Dict[str, Any]:
        """Build Slack Block Kit payload."""
        color_map = {
            "info": "#36a64f",
            "warning": "#ffcc00",
            "critical": "#ff0000",
        }
        emoji_map = {
            "info": ":information_source:",
            "warning": ":warning:",
            "critical": ":rotating_light:",
        }
        
        color = color_map.get(severity, "#808080")
        emoji = emoji_map.get(severity, ":bell:")
        
        # Build fields from metadata
        fields = []
        if metadata:
            for key, value in metadata.items():
                if key not in ("tenant_id", "bot_id"):  # These go in header
                    fields.append({
                        "type": "mrkdwn",
                        "text": f"*{key}:* {value}"
                    })
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {alert_type.upper().replace('_', ' ')}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message
                }
            },
        ]
        
        # Add context with tenant/bot info
        if metadata and ("tenant_id" in metadata or "bot_id" in metadata):
            context_elements = []
            if "tenant_id" in metadata:
                context_elements.append({
                    "type": "mrkdwn",
                    "text": f"*Tenant:* {metadata['tenant_id']}"
                })
            if "bot_id" in metadata:
                context_elements.append({
                    "type": "mrkdwn",
                    "text": f"*Bot:* {metadata['bot_id']}"
                })
            context_elements.append({
                "type": "mrkdwn",
                "text": f"*Time:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            })
            blocks.append({
                "type": "context",
                "elements": context_elements
            })
        
        # Add fields section if we have metadata
        if fields:
            blocks.append({
                "type": "section",
                "fields": fields[:10]  # Slack limits to 10 fields
            })
        
        payload = {
            "username": self.config.username,
            "icon_emoji": self.config.icon_emoji,
            "blocks": blocks,
            "attachments": [{
                "color": color,
                "fallback": f"[{alert_type}] {message}",
            }]
        }
        
        if self.config.channel:
            payload["channel"] = self.config.channel
            
        return payload

    def _build_discord_payload(
        self,
        alert_type: str,
        message: str,
        metadata: Optional[Dict[str, Any]],
        severity: str,
    ) -> Dict[str, Any]:
        """Build Discord embed payload."""
        color_map = {
            "info": 0x36a64f,
            "warning": 0xffcc00,
            "critical": 0xff0000,
        }
        
        color = color_map.get(severity, 0x808080)
        
        fields = []
        if metadata:
            for key, value in metadata.items():
                fields.append({
                    "name": key,
                    "value": str(value),
                    "inline": True
                })
        
        return {
            "username": self.config.username,
            "embeds": [{
                "title": alert_type.upper().replace("_", " "),
                "description": message,
                "color": color,
                "fields": fields[:25],  # Discord limits to 25 fields
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }

    def _build_generic_payload(
        self,
        alert_type: str,
        message: str,
        metadata: Optional[Dict[str, Any]],
        severity: str,
    ) -> Dict[str, Any]:
        """Build generic webhook payload."""
        return {
            "type": alert_type,
            "message": message,
            "severity": severity,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow().isoformat(),
        }


# Convenience functions for common alerts

async def send_kill_switch_alert(
    client: AlertsClient,
    trigger: str,
    message: str,
    tenant_id: str,
    bot_id: str,
    triggered_by: Optional[Dict[str, float]] = None,
) -> bool:
    """Send kill switch trigger alert."""
    return await client.send(
        alert_type="kill_switch_triggered",
        message=f"🛑 *Kill switch activated!*\n\n{message}",
        metadata={
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "trigger": trigger,
            "triggered_by": triggered_by or {},
        },
        severity="critical",
    )


async def send_kill_switch_reset_alert(
    client: AlertsClient,
    operator_id: str,
    tenant_id: str,
    bot_id: str,
) -> bool:
    """Send kill switch reset alert."""
    return await client.send(
        alert_type="kill_switch_reset",
        message=f"✅ *Kill switch has been reset*\n\nOperator: {operator_id}",
        metadata={
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "operator_id": operator_id,
        },
        severity="info",
    )


async def send_reconciliation_alert(
    client: AlertsClient,
    discrepancy_count: int,
    healed_count: int,
    tenant_id: str,
    bot_id: str,
    discrepancies: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Send reconciliation discrepancy alert."""
    severity = "critical" if discrepancy_count > 5 else "warning"
    
    return await client.send(
        alert_type="reconciliation_discrepancy",
        message=f"⚠️ *Reconciliation found {discrepancy_count} discrepancies*\n\nHealed: {healed_count}",
        metadata={
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "discrepancy_count": discrepancy_count,
            "healed_count": healed_count,
            "sample_discrepancies": (discrepancies or [])[:3],
        },
        severity=severity,
    )


async def send_latency_alert(
    client: AlertsClient,
    metric_name: str,
    p99_ms: float,
    threshold_ms: float,
    tenant_id: str,
    bot_id: str,
) -> bool:
    """Send latency SLO breach alert."""
    return await client.send(
        alert_type="latency_slo_breach",
        message=f"⏱️ *Latency SLO breached for {metric_name}*\n\np99: {p99_ms:.1f}ms (threshold: {threshold_ms}ms)",
        metadata={
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "metric": metric_name,
            "p99_ms": p99_ms,
            "threshold_ms": threshold_ms,
        },
        severity="warning",
    )


async def send_guard_trigger_alert(
    client: AlertsClient,
    symbol: str,
    reason: str,
    side: str,
    entry_price: Optional[float],
    exit_price: Optional[float],
    realized_pnl: Optional[float],
    realized_pnl_pct: Optional[float],
    hold_time_sec: Optional[float],
    tenant_id: str,
    bot_id: str,
) -> bool:
    """Send position guard trigger alert."""
    # Map reason to emoji and severity
    reason_config = {
        "trailing_stop_hit": ("📉", "warning", "Trailing Stop"),
        "stop_loss_hit": ("🛑", "warning", "Stop Loss"),
        "take_profit_hit": ("🎯", "info", "Take Profit"),
        "max_age_exceeded": ("⏰", "warning", "Max Age"),
    }
    
    emoji, severity, label = reason_config.get(reason, ("⚠️", "warning", reason))
    
    pnl_emoji = "🟢" if (realized_pnl or 0) > 0 else "🔴"
    pnl_str = f"${realized_pnl:.2f}" if realized_pnl is not None else "N/A"
    pnl_pct_str = f"{realized_pnl_pct:.2f}%" if realized_pnl_pct is not None else "N/A"
    
    entry_str = f"${entry_price:.2f}" if entry_price else "N/A"
    exit_str = f"${exit_price:.2f}" if exit_price else "N/A"
    hold_str = f"{hold_time_sec:.0f}s" if hold_time_sec else "N/A"
    
    message = f"""{emoji} *{label} Triggered*

• Symbol: `{symbol}`
• Side: {side}
• Entry: {entry_str}
• Exit: {exit_str}
• P&L: {pnl_emoji} {pnl_str} ({pnl_pct_str})
• Hold Time: {hold_str}"""
    
    return await client.send(
        alert_type="guard_trigger",
        message=message,
        metadata={
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "symbol": symbol,
            "reason": reason,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "hold_time_sec": hold_time_sec,
        },
        severity=severity,
    )


async def send_correlation_block_alert(
    client: AlertsClient,
    blocked_symbol: str,
    existing_symbol: str,
    correlation: float,
    tenant_id: str,
    bot_id: str,
) -> bool:
    """Send correlation guard block alert."""
    return await client.send(
        alert_type="correlation_block",
        message=f"⚠️ *Position Blocked by Correlation Guard*\n\n`{blocked_symbol}` blocked due to {correlation:.0%} correlation with existing `{existing_symbol}` position",
        metadata={
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "blocked_symbol": blocked_symbol,
            "existing_symbol": existing_symbol,
            "correlation": correlation,
        },
        severity="info",
    )
