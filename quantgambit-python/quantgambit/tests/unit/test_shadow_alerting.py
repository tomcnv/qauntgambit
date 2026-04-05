"""Unit tests for shadow alerting functionality.

Tests the _check_alert_threshold() method of ShadowComparator which detects
systematic divergence and emits alerts via telemetry.

Feature: trading-pipeline-integration
Requirements: 4.6 - WHEN shadow mode detects systematic divergence (>20% disagreement
              over 100 decisions) THEN the System SHALL emit an alert

Tests verify:
1. Alert is emitted when divergence exceeds threshold (>20%) over 100+ decisions
2. Alert is NOT emitted when divergence is below threshold
3. Alert is NOT emitted when fewer than 100 decisions
4. Alert includes correct payload (divergence_rate, threshold, total_comparisons, divergence_by_reason, severity)
5. Alert is NOT emitted when telemetry is None
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

from quantgambit.integration.shadow_comparison import (
    ComparisonResult,
    ShadowComparator,
)


class MockStageContext:
    """Mock stage context for testing."""
    
    def __init__(
        self,
        rejection_stage: Optional[str] = None,
        profile_id: Optional[str] = None,
        signal: Optional[Dict[str, Any]] = None,
    ):
        self._rejection_stage = rejection_stage
        self._profile_id = profile_id
        self._signal = signal
    
    @property
    def rejection_stage(self) -> Optional[str]:
        return self._rejection_stage
    
    @property
    def profile_id(self) -> Optional[str]:
        return self._profile_id
    
    @property
    def signal(self) -> Optional[Dict[str, Any]]:
        return self._signal


class MockDecisionEngine:
    """Mock decision engine for testing."""
    
    def __init__(
        self,
        result: bool = True,
        rejection_stage: Optional[str] = None,
        profile_id: Optional[str] = None,
        signal: Optional[Dict[str, Any]] = None,
    ):
        self._result = result
        self._rejection_stage = rejection_stage
        self._profile_id = profile_id
        self._signal = signal
    
    async def decide_with_context(self, decision_input: Any) -> tuple[bool, MockStageContext]:
        ctx = MockStageContext(
            rejection_stage=self._rejection_stage,
            profile_id=self._profile_id,
            signal=self._signal,
        )
        return self._result, ctx


class MockDecisionInput:
    """Mock decision input for testing."""
    
    def __init__(self, symbol: str = "BTCUSDT"):
        self._symbol = symbol
    
    @property
    def symbol(self) -> str:
        return self._symbol


class TestShadowAlertingThreshold:
    """Tests for shadow alerting threshold detection."""
    
    @pytest.mark.asyncio
    async def test_alert_emitted_when_divergence_exceeds_threshold_over_100_decisions(self):
        """Test alert is emitted when divergence exceeds threshold (>20%) over 100+ decisions.
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        
        # Create mock telemetry with publish_event method
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 100 comparisons with 25% divergence (75 agree, 25 disagree)
        # First add 75 agreements
        comparator._shadow_engine = MockDecisionEngine(result=True)
        for _ in range(75):
            await comparator.compare(decision_input)
        
        # Then add 25 disagreements
        comparator._shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        for _ in range(25):
            await comparator.compare(decision_input)
        
        # Verify alert was emitted
        assert telemetry.publish_event.called
        
        # Get the last call arguments
        call_args = telemetry.publish_event.call_args
        assert call_args is not None
        
        # Verify event_type - check both kwargs and positional args
        event_type = call_args.kwargs.get("event_type")
        if event_type is None and call_args.args:
            event_type = call_args.args[0]
        assert event_type == "shadow_divergence_high"
    
    @pytest.mark.asyncio
    async def test_alert_not_emitted_when_divergence_below_threshold(self):
        """Test alert is NOT emitted when divergence is below threshold.
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        
        # Create mock telemetry with publish_event method
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=MockDecisionEngine(result=True),
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 100 comparisons with 15% divergence (85 agree, 15 disagree)
        # First add 85 agreements
        for _ in range(85):
            await comparator.compare(decision_input)
        
        # Then add 15 disagreements
        comparator._shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        for _ in range(15):
            await comparator.compare(decision_input)
        
        # Verify alert was NOT emitted (divergence is 15%, threshold is 20%)
        assert not telemetry.publish_event.called
    
    @pytest.mark.asyncio
    async def test_alert_not_emitted_when_fewer_than_100_decisions(self):
        """Test alert is NOT emitted when fewer than 100 decisions.
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        
        # Create mock telemetry with publish_event method
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add only 50 comparisons with 100% divergence
        for _ in range(50):
            await comparator.compare(decision_input)
        
        # Verify alert was NOT emitted (only 50 decisions, need 100)
        assert not telemetry.publish_event.called
    
    @pytest.mark.asyncio
    async def test_alert_not_emitted_when_telemetry_is_none(self):
        """Test alert is NOT emitted when telemetry is None.
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        
        # No telemetry provided
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=None,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 100 comparisons with 100% divergence
        for _ in range(100):
            await comparator.compare(decision_input)
        
        # Should not raise any exception even with high divergence
        # (no telemetry to emit to)
        metrics = comparator.get_metrics()
        assert metrics.total_comparisons == 100
        assert metrics.agreement_rate == 0.0


class TestShadowAlertingPayload:
    """Tests for shadow alerting payload content."""
    
    @pytest.mark.asyncio
    async def test_alert_includes_correct_payload(self):
        """Test alert includes correct payload (divergence_rate, threshold, total_comparisons, divergence_by_reason, severity).
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        
        # Create mock telemetry with publish_event method
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=MockDecisionEngine(result=True),
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 100 comparisons with 30% divergence (70 agree, 30 disagree)
        # First add 70 agreements
        for _ in range(70):
            await comparator.compare(decision_input)
        
        # Then add 30 disagreements with specific rejection stage
        comparator._shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        for _ in range(30):
            await comparator.compare(decision_input)
        
        # Verify alert was emitted
        assert telemetry.publish_event.called
        
        # Get the call arguments
        call_args = telemetry.publish_event.call_args
        assert call_args is not None
        
        # Extract payload from kwargs
        payload = call_args.kwargs.get("payload")
        assert payload is not None
        
        # Verify payload contents
        assert "divergence_rate" in payload
        assert payload["divergence_rate"] == pytest.approx(0.30, abs=0.01)
        
        assert "threshold" in payload
        assert payload["threshold"] == 0.20
        
        assert "total_comparisons" in payload
        assert payload["total_comparisons"] == 100
        
        assert "divergence_by_reason" in payload
        assert isinstance(payload["divergence_by_reason"], dict)
        
        assert "severity" in payload
        assert payload["severity"] == "warning"
    
    @pytest.mark.asyncio
    async def test_alert_payload_divergence_by_reason_is_accurate(self):
        """Test alert payload divergence_by_reason accurately reflects divergence reasons.
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        
        # Create mock telemetry with publish_event method
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=MockDecisionEngine(result=True),
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 70 agreements
        for _ in range(70):
            await comparator.compare(decision_input)
        
        # Add 20 disagreements with ev_gate rejection
        comparator._shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        for _ in range(20):
            await comparator.compare(decision_input)
        
        # Add 10 disagreements with cooldown rejection
        comparator._shadow_engine = MockDecisionEngine(result=False, rejection_stage="cooldown")
        for _ in range(10):
            await comparator.compare(decision_input)
        
        # Verify alert was emitted
        assert telemetry.publish_event.called
        
        # Get the call arguments
        call_args = telemetry.publish_event.call_args
        payload = call_args.kwargs.get("payload")
        
        # Verify divergence_by_reason contains both reasons
        divergence_by_reason = payload["divergence_by_reason"]
        assert len(divergence_by_reason) == 2
        
        # Check that both rejection stages are tracked
        # The reason format is "stage_diff:{live_stage}vs{shadow_stage}"
        # Since live accepts (no rejection_stage), it will be "stage_diff:nonevsev_gate"
        assert any("ev_gate" in reason for reason in divergence_by_reason.keys())
        assert any("cooldown" in reason for reason in divergence_by_reason.keys())


class TestShadowAlertingEdgeCases:
    """Tests for shadow alerting edge cases."""
    
    @pytest.mark.asyncio
    async def test_alert_at_exactly_100_decisions_with_exactly_20_percent_divergence(self):
        """Test alert is NOT emitted at exactly 20% divergence (threshold is >20%).
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        
        # Create mock telemetry with publish_event method
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=MockDecisionEngine(result=True),
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add exactly 100 comparisons with exactly 20% divergence (80 agree, 20 disagree)
        # First add 80 agreements
        for _ in range(80):
            await comparator.compare(decision_input)
        
        # Then add 20 disagreements
        comparator._shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        for _ in range(20):
            await comparator.compare(decision_input)
        
        # Verify alert was NOT emitted (divergence is exactly 20%, threshold is >20%)
        assert not telemetry.publish_event.called
    
    @pytest.mark.asyncio
    async def test_alert_at_exactly_21_percent_divergence(self):
        """Test alert IS emitted at 21% divergence (exceeds 20% threshold).
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        
        # Create mock telemetry with publish_event method
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=MockDecisionEngine(result=True),
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 100 comparisons with 21% divergence (79 agree, 21 disagree)
        # First add 79 agreements
        for _ in range(79):
            await comparator.compare(decision_input)
        
        # Then add 21 disagreements
        comparator._shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        for _ in range(21):
            await comparator.compare(decision_input)
        
        # Verify alert WAS emitted (divergence is 21%, threshold is 20%)
        assert telemetry.publish_event.called
    
    @pytest.mark.asyncio
    async def test_alert_with_custom_threshold(self):
        """Test alert respects custom threshold configuration.
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        
        # Create mock telemetry with publish_event method
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        # Use custom threshold of 10%
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=MockDecisionEngine(result=True),
            telemetry=telemetry,
            alert_threshold=0.10,  # Custom 10% threshold
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 100 comparisons with 15% divergence (85 agree, 15 disagree)
        # First add 85 agreements
        for _ in range(85):
            await comparator.compare(decision_input)
        
        # Then add 15 disagreements
        comparator._shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        for _ in range(15):
            await comparator.compare(decision_input)
        
        # Verify alert WAS emitted (divergence is 15%, custom threshold is 10%)
        assert telemetry.publish_event.called
        
        # Verify threshold in payload matches custom threshold
        call_args = telemetry.publish_event.call_args
        payload = call_args.kwargs.get("payload")
        assert payload["threshold"] == 0.10
    
    @pytest.mark.asyncio
    async def test_alert_handles_telemetry_without_publish_event(self):
        """Test alert gracefully handles telemetry without publish_event method.
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        
        # Create mock telemetry WITHOUT publish_event method
        telemetry = MagicMock(spec=[])  # Empty spec means no methods
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 100 comparisons with 100% divergence
        # This should not raise an exception even though telemetry lacks publish_event
        for _ in range(100):
            await comparator.compare(decision_input)
        
        # Should complete without error
        metrics = comparator.get_metrics()
        assert metrics.total_comparisons == 100
    
    @pytest.mark.asyncio
    async def test_alert_emitted_on_each_comparison_exceeding_threshold(self):
        """Test alert is checked on each comparison after threshold is exceeded.
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        
        # Create mock telemetry with publish_event method
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=MockDecisionEngine(result=True),
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 70 agreements
        for _ in range(70):
            await comparator.compare(decision_input)
        
        # Add 30 disagreements (30% divergence)
        comparator._shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        for _ in range(30):
            await comparator.compare(decision_input)
        
        # Count how many times alert was emitted
        # Alert should be emitted on each comparison after reaching 100 with >20% divergence
        call_count = telemetry.publish_event.call_count
        
        # The alert should have been called at least once
        assert call_count >= 1


class TestShadowAlertingIntegration:
    """Integration tests for shadow alerting with the full compare flow."""
    
    @pytest.mark.asyncio
    async def test_full_compare_flow_triggers_alert(self):
        """Test full compare() flow correctly triggers alert when conditions are met.
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(
            result=True,
            profile_id="profile_a",
            signal={"side": "buy", "size": 0.1},
        )
        shadow_engine = MockDecisionEngine(
            result=False,
            rejection_stage="ev_gate",
        )
        
        # Create mock telemetry
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput(symbol="BTCUSDT")
        
        # Run 100 comparisons with 100% divergence
        for _ in range(100):
            result = await comparator.compare(decision_input)
            assert result.agrees is False
        
        # Verify alert was emitted
        assert telemetry.publish_event.called
        
        # Verify the event type
        call_args = telemetry.publish_event.call_args
        event_type = call_args.kwargs.get("event_type")
        assert event_type == "shadow_divergence_high"
    
    @pytest.mark.asyncio
    async def test_metrics_reflect_divergence_state(self):
        """Test get_metrics() reflects the divergence state that triggers alerts.
        
        Validates: Requirements 4.6
        """
        live_engine = MockDecisionEngine(result=True)
        
        # Create mock telemetry
        telemetry = MagicMock()
        telemetry.publish_event = AsyncMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=MockDecisionEngine(result=True),
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=100,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 75 agreements
        for _ in range(75):
            await comparator.compare(decision_input)
        
        # Add 25 disagreements
        comparator._shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        for _ in range(25):
            await comparator.compare(decision_input)
        
        # Get metrics
        metrics = comparator.get_metrics()
        
        # Verify metrics match alert conditions
        assert metrics.total_comparisons == 100
        assert metrics.agreement_rate == 0.75
        assert metrics.divergence_rate() == 0.25
        assert metrics.exceeds_threshold(0.20) is True
