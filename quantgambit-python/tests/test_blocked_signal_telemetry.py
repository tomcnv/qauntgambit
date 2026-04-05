"""
Unit tests for BlockedSignalTelemetry class.

Tests for:
- Recording blocked signals by gate (Requirements 9.1, 9.2, 9.3)
- Aggregating counts per gate per hour (Requirement 9.4)
- Hourly counter reset
- Per-symbol tracking
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.observability.blocked_signal_telemetry import (
    BlockedSignalTelemetry,
    BlockedSignalEvent,
    VALID_GATES,
)


class TestBlockedSignalEvent:
    """Tests for BlockedSignalEvent dataclass."""
    
    def test_create_event(self):
        """Should create event with all fields."""
        event = BlockedSignalEvent(
            timestamp=1234567890.0,
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled: 30s < 60s",
            metrics={"time_since_last": 30.0, "min_interval": 60.0},
        )
        
        assert event.timestamp == 1234567890.0
        assert event.symbol == "BTCUSDT"
        assert event.gate_name == "execution_throttle"
        assert event.reason == "throttled: 30s < 60s"
        assert event.metrics["time_since_last"] == 30.0
    
    def test_to_dict(self):
        """Should convert event to dictionary."""
        event = BlockedSignalEvent(
            timestamp=1234567890.0,
            symbol="BTCUSDT",
            gate_name="cooldown",
            reason="entry_cooldown:30s_remaining",
            metrics={"remaining": 30.0},
        )
        
        result = event.to_dict()
        
        assert isinstance(result, dict)
        assert result["timestamp"] == 1234567890.0
        assert result["symbol"] == "BTCUSDT"
        assert result["gate_name"] == "cooldown"
        assert result["reason"] == "entry_cooldown:30s_remaining"
        assert result["metrics"]["remaining"] == 30.0
    
    def test_default_metrics(self):
        """Should default metrics to empty dict."""
        event = BlockedSignalEvent(
            timestamp=1234567890.0,
            symbol="BTCUSDT",
            gate_name="fee_check",
            reason="fee_check_blocked",
        )
        
        assert event.metrics == {}


class TestBlockedSignalTelemetryRecording:
    """Tests for recording blocked signals (Requirements 9.1, 9.2, 9.3)."""
    
    def test_record_execution_throttle_blocked(self):
        """Should record execution throttle blocked signal (Requirement 9.1)."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled: 30s < 60s",
            metrics={"time_since_last": 30.0},
        ))
        
        summary = telemetry.get_hourly_summary()
        assert "execution_throttle" in summary
        assert summary["execution_throttle"]["BTCUSDT"] == 1
    
    def test_record_cooldown_blocked(self):
        """Should record cooldown blocked signal (Requirement 9.2)."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="ETHUSDT",
            gate_name="cooldown",
            reason="entry_cooldown:30s_remaining",
        ))
        
        summary = telemetry.get_hourly_summary()
        assert "cooldown" in summary
        assert summary["cooldown"]["ETHUSDT"] == 1
    
    def test_record_hysteresis_blocked(self):
        """Should record hysteresis blocked signal (Requirement 9.2)."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="hysteresis",
            reason="same_direction_hysteresis:60s_remaining",
        ))
        
        summary = telemetry.get_hourly_summary()
        assert "hysteresis" in summary
        assert summary["hysteresis"]["BTCUSDT"] == 1
    
    def test_record_fee_check_blocked(self):
        """Should record fee check blocked signal (Requirement 9.3)."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="fee_check",
            reason="fee_check_blocked: below_breakeven",
            metrics={
                "gross_pnl_bps": 3.0,
                "net_pnl_bps": -2.0,
                "shortfall_bps": 5.0,
            },
        ))
        
        summary = telemetry.get_hourly_summary()
        assert "fee_check" in summary
        assert summary["fee_check"]["BTCUSDT"] == 1
    
    def test_record_hourly_limit_blocked(self):
        """Should record hourly limit blocked signal."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="hourly_limit",
            reason="hourly_limit_reached:10>=10",
        ))
        
        summary = telemetry.get_hourly_summary()
        assert "hourly_limit" in summary
        assert summary["hourly_limit"]["BTCUSDT"] == 1
    
    def test_reject_invalid_gate_name(self):
        """Should reject invalid gate names."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="invalid_gate",
            reason="some reason",
        ))
        
        # Should not record anything
        summary = telemetry.get_hourly_summary()
        assert "invalid_gate" not in summary


class TestBlockedSignalTelemetryAggregation:
    """Tests for hourly aggregation (Requirement 9.4)."""
    
    def test_aggregate_multiple_blocks_same_gate_same_symbol(self):
        """Should aggregate multiple blocks for same gate and symbol."""
        telemetry = BlockedSignalTelemetry()
        
        for _ in range(5):
            asyncio.run(telemetry.record_blocked(
                symbol="BTCUSDT",
                gate_name="execution_throttle",
                reason="throttled",
            ))
        
        summary = telemetry.get_hourly_summary()
        assert summary["execution_throttle"]["BTCUSDT"] == 5
    
    def test_aggregate_multiple_gates(self):
        """Should aggregate across multiple gates."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="cooldown",
            reason="cooldown_active",
        ))
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="fee_check",
            reason="fee_check_blocked",
        ))
        
        summary = telemetry.get_hourly_summary()
        assert summary["execution_throttle"]["BTCUSDT"] == 1
        assert summary["cooldown"]["BTCUSDT"] == 1
        assert summary["fee_check"]["BTCUSDT"] == 1
    
    def test_aggregate_multiple_symbols(self):
        """Should aggregate across multiple symbols."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        asyncio.run(telemetry.record_blocked(
            symbol="ETHUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        
        summary = telemetry.get_hourly_summary()
        assert summary["execution_throttle"]["BTCUSDT"] == 2
        assert summary["execution_throttle"]["ETHUSDT"] == 1
    
    def test_get_total_counts(self):
        """Should return total counts per gate."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        asyncio.run(telemetry.record_blocked(
            symbol="ETHUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="cooldown",
            reason="cooldown_active",
        ))
        
        totals = telemetry.get_total_counts()
        assert totals["execution_throttle"] == 2
        assert totals["cooldown"] == 1
    
    def test_get_count_for_gate(self):
        """Should return count for specific gate."""
        telemetry = BlockedSignalTelemetry()
        
        for _ in range(3):
            asyncio.run(telemetry.record_blocked(
                symbol="BTCUSDT",
                gate_name="fee_check",
                reason="fee_check_blocked",
            ))
        
        assert telemetry.get_count_for_gate("fee_check") == 3
        assert telemetry.get_count_for_gate("cooldown") == 0
    
    def test_get_count_for_symbol(self):
        """Should return count for specific symbol."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="cooldown",
            reason="cooldown_active",
        ))
        asyncio.run(telemetry.record_blocked(
            symbol="ETHUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        
        assert telemetry.get_count_for_symbol("BTCUSDT") == 2
        assert telemetry.get_count_for_symbol("ETHUSDT") == 1
        assert telemetry.get_count_for_symbol("SOLUSDT") == 0
    
    def test_get_count_for_symbol_with_gate_filter(self):
        """Should return count for specific symbol and gate."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="cooldown",
            reason="cooldown_active",
        ))
        
        assert telemetry.get_count_for_symbol("BTCUSDT", gate_name="execution_throttle") == 1
        assert telemetry.get_count_for_symbol("BTCUSDT", gate_name="cooldown") == 1
        assert telemetry.get_count_for_symbol("BTCUSDT", gate_name="fee_check") == 0


class TestBlockedSignalTelemetryHourlyReset:
    """Tests for hourly counter reset."""
    
    def test_manual_reset(self):
        """Should reset counters on manual reset."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        
        assert telemetry.get_count_for_gate("execution_throttle") == 1
        
        telemetry.reset_hourly_counts()
        
        assert telemetry.get_count_for_gate("execution_throttle") == 0
        assert telemetry.get_hourly_summary() == {}
    
    def test_auto_reset_on_hour_boundary(self):
        """Should auto-reset counters when hour changes."""
        telemetry = BlockedSignalTelemetry()
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        
        assert telemetry.get_count_for_gate("execution_throttle") == 1
        
        # Simulate hour change by modifying internal state
        telemetry._current_hour = telemetry._current_hour - 1
        
        # Next access should trigger reset
        summary = telemetry.get_hourly_summary()
        assert summary == {}


class TestBlockedSignalTelemetryWithPipeline:
    """Tests for integration with TelemetryPipeline."""
    
    def test_publishes_to_telemetry_pipeline(self):
        """Should publish events to telemetry pipeline when available."""
        mock_telemetry = MagicMock()
        mock_telemetry.publish_guardrail = AsyncMock()
        
        mock_context = MagicMock()
        mock_context.tenant_id = "test_tenant"
        mock_context.bot_id = "test_bot"
        
        telemetry = BlockedSignalTelemetry(
            telemetry=mock_telemetry,
            telemetry_context=mock_context,
        )
        
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled: 30s < 60s",
            metrics={"time_since_last": 30.0},
        ))
        
        # Verify publish_guardrail was called
        mock_telemetry.publish_guardrail.assert_called_once()
        
        # Verify payload structure
        call_args = mock_telemetry.publish_guardrail.call_args
        payload = call_args[1]["payload"]
        
        assert payload["type"] == "signal_blocked"
        assert payload["symbol"] == "BTCUSDT"
        assert payload["gate_name"] == "execution_throttle"
        assert payload["reason"] == "throttled: 30s < 60s"
        assert payload["metrics"]["time_since_last"] == 30.0
        assert payload["hourly_count"] == 1
        assert payload["total_gate_count"] == 1
    
    def test_works_without_telemetry_pipeline(self):
        """Should work without telemetry pipeline (no errors)."""
        telemetry = BlockedSignalTelemetry()  # No pipeline
        
        # Should not raise
        asyncio.run(telemetry.record_blocked(
            symbol="BTCUSDT",
            gate_name="execution_throttle",
            reason="throttled",
        ))
        
        assert telemetry.get_count_for_gate("execution_throttle") == 1


class TestValidGates:
    """Tests for VALID_GATES constant."""
    
    def test_valid_gates_contains_expected_gates(self):
        """Should contain all expected gate names."""
        expected_gates = {
            "execution_throttle",
            "cooldown",
            "hysteresis",
            "fee_check",
            "hourly_limit",
            # Trading loss prevention gates (Requirements 1.1, 2.1, 4.1, 5.1)
            "confidence_gate",
            "strategy_trend_mismatch",
            "fee_trap",
            "session_mismatch",
            # EV-based entry gate (replaces confidence_gate)
            "ev_gate",
        }
        
        assert VALID_GATES == expected_gates
    
    def test_valid_gates_is_frozenset(self):
        """Should be a frozenset (immutable)."""
        assert isinstance(VALID_GATES, frozenset)
