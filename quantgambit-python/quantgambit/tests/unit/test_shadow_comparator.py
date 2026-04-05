"""Unit tests for ShadowComparator.

Tests the ShadowComparator class which compares live and shadow pipeline
decisions in real-time.

Feature: trading-pipeline-integration
Requirements: 4.1, 4.3, 4.4
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

from quantgambit.integration.shadow_comparison import (
    ComparisonResult,
    ComparisonMetrics,
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


class TestShadowComparatorInitialization:
    """Tests for ShadowComparator initialization."""
    
    def test_initialization_with_engines(self):
        """Test ShadowComparator can be initialized with live and shadow engines."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        assert comparator._live_engine is live_engine
        assert comparator._shadow_engine is shadow_engine
        assert comparator._telemetry is None
        assert comparator._alert_threshold == 0.20
        assert comparator._window_size == 100
        assert comparator._comparisons == []
    
    def test_initialization_with_custom_threshold(self):
        """Test ShadowComparator can be initialized with custom alert threshold."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            alert_threshold=0.10,
        )
        
        assert comparator._alert_threshold == 0.10
    
    def test_initialization_with_custom_window_size(self):
        """Test ShadowComparator can be initialized with custom window size."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            window_size=50,
        )
        
        assert comparator._window_size == 50
    
    def test_initialization_with_telemetry(self):
        """Test ShadowComparator can be initialized with telemetry."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        telemetry = MagicMock()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=telemetry,
        )
        
        assert comparator._telemetry is telemetry


class TestShadowComparatorCompare:
    """Tests for ShadowComparator.compare() method."""
    
    @pytest.mark.asyncio
    async def test_compare_both_accept(self):
        """Test compare() when both pipelines accept."""
        live_engine = MockDecisionEngine(
            result=True,
            profile_id="profile_a",
            signal={"side": "buy", "size": 0.1},
        )
        shadow_engine = MockDecisionEngine(
            result=True,
            profile_id="profile_a",
            signal={"side": "buy", "size": 0.1},
        )
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput(symbol="BTCUSDT")
        result = await comparator.compare(decision_input)
        
        assert result.symbol == "BTCUSDT"
        assert result.live_decision == "accepted"
        assert result.shadow_decision == "accepted"
        assert result.agrees is True
        assert result.divergence_reason is None
    
    @pytest.mark.asyncio
    async def test_compare_both_reject(self):
        """Test compare() when both pipelines reject."""
        live_engine = MockDecisionEngine(
            result=False,
            rejection_stage="global_gate",
        )
        shadow_engine = MockDecisionEngine(
            result=False,
            rejection_stage="global_gate",
        )
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput(symbol="ETHUSDT")
        result = await comparator.compare(decision_input)
        
        assert result.symbol == "ETHUSDT"
        assert result.live_decision == "rejected"
        assert result.shadow_decision == "rejected"
        assert result.agrees is True
        assert result.divergence_reason is None
    
    @pytest.mark.asyncio
    async def test_compare_live_accepts_shadow_rejects(self):
        """Test compare() when live accepts but shadow rejects."""
        live_engine = MockDecisionEngine(
            result=True,
            profile_id="profile_a",
            signal={"side": "buy"},
        )
        shadow_engine = MockDecisionEngine(
            result=False,
            rejection_stage="ev_gate",
        )
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput(symbol="BTCUSDT")
        result = await comparator.compare(decision_input)
        
        assert result.live_decision == "accepted"
        assert result.shadow_decision == "rejected"
        assert result.agrees is False
        assert result.divergence_reason is not None
    
    @pytest.mark.asyncio
    async def test_compare_live_rejects_shadow_accepts(self):
        """Test compare() when live rejects but shadow accepts."""
        live_engine = MockDecisionEngine(
            result=False,
            rejection_stage="cooldown",
        )
        shadow_engine = MockDecisionEngine(
            result=True,
            profile_id="profile_b",
            signal={"side": "sell"},
        )
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput(symbol="BTCUSDT")
        result = await comparator.compare(decision_input)
        
        assert result.live_decision == "rejected"
        assert result.shadow_decision == "accepted"
        assert result.agrees is False
        assert result.divergence_reason is not None
    
    @pytest.mark.asyncio
    async def test_compare_stores_result_in_window(self):
        """Test compare() stores result in comparison window."""
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        assert len(comparator._comparisons) == 0
        
        decision_input = MockDecisionInput()
        await comparator.compare(decision_input)
        
        assert len(comparator._comparisons) == 1
    
    @pytest.mark.asyncio
    async def test_compare_maintains_window_size(self):
        """Test compare() maintains window at window_size."""
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            window_size=5,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 7 comparisons
        for _ in range(7):
            await comparator.compare(decision_input)
        
        # Window should be capped at 5
        assert len(comparator._comparisons) == 5
    
    @pytest.mark.asyncio
    async def test_compare_returns_comparison_result(self):
        """Test compare() returns a ComparisonResult."""
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput()
        result = await comparator.compare(decision_input)
        
        assert isinstance(result, ComparisonResult)
        assert result.timestamp is not None
        assert result.timestamp.tzinfo is not None


class TestShadowComparatorIdentifyDivergence:
    """Tests for ShadowComparator._identify_divergence() method."""
    
    def test_identify_divergence_stage_difference(self):
        """Test _identify_divergence() correctly identifies stage differences."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        live_ctx = MockStageContext(rejection_stage="global_gate")
        shadow_ctx = MockStageContext(rejection_stage="ev_gate")
        
        reason = comparator._identify_divergence(live_ctx, shadow_ctx)
        
        assert reason == "stage_diff:global_gatevsev_gate"
    
    def test_identify_divergence_stage_none_vs_value(self):
        """Test _identify_divergence() when one stage is None."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        live_ctx = MockStageContext(rejection_stage=None)
        shadow_ctx = MockStageContext(rejection_stage="ev_gate")
        
        reason = comparator._identify_divergence(live_ctx, shadow_ctx)
        
        assert reason == "stage_diff:nonevsev_gate"
    
    def test_identify_divergence_profile_difference(self):
        """Test _identify_divergence() correctly identifies profile differences."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        live_ctx = MockStageContext(
            rejection_stage=None,
            profile_id="profile_a",
        )
        shadow_ctx = MockStageContext(
            rejection_stage=None,
            profile_id="profile_b",
        )
        
        reason = comparator._identify_divergence(live_ctx, shadow_ctx)
        
        assert reason == "profile_diff:profile_avsprofile_b"
    
    def test_identify_divergence_profile_none_vs_value(self):
        """Test _identify_divergence() when one profile is None."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        live_ctx = MockStageContext(
            rejection_stage=None,
            profile_id=None,
        )
        shadow_ctx = MockStageContext(
            rejection_stage=None,
            profile_id="profile_b",
        )
        
        reason = comparator._identify_divergence(live_ctx, shadow_ctx)
        
        assert reason == "profile_diff:nonevsprofile_b"
    
    def test_identify_divergence_unknown(self):
        """Test _identify_divergence() returns 'unknown' when no difference found."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        # Same rejection_stage and profile_id, but somehow decisions differ
        live_ctx = MockStageContext(
            rejection_stage="ev_gate",
            profile_id="profile_a",
        )
        shadow_ctx = MockStageContext(
            rejection_stage="ev_gate",
            profile_id="profile_a",
        )
        
        reason = comparator._identify_divergence(live_ctx, shadow_ctx)
        
        assert reason == "unknown"


class TestShadowComparatorGetMetrics:
    """Tests for ShadowComparator.get_metrics() method."""
    
    def test_get_metrics_empty(self):
        """Test get_metrics() returns correct metrics when no comparisons."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        metrics = comparator.get_metrics()
        
        assert metrics.total_comparisons == 0
        assert metrics.agreements == 0
        assert metrics.disagreements == 0
        assert metrics.agreement_rate == 1.0
        assert metrics.divergence_by_reason == {}
    
    @pytest.mark.asyncio
    async def test_get_metrics_all_agree(self):
        """Test get_metrics() returns correct metrics when all agree."""
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput()
        for _ in range(10):
            await comparator.compare(decision_input)
        
        metrics = comparator.get_metrics()
        
        assert metrics.total_comparisons == 10
        assert metrics.agreements == 10
        assert metrics.disagreements == 0
        assert metrics.agreement_rate == 1.0
        assert metrics.divergence_by_reason == {}
    
    @pytest.mark.asyncio
    async def test_get_metrics_all_disagree(self):
        """Test get_metrics() returns correct metrics when all disagree."""
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput()
        for _ in range(10):
            await comparator.compare(decision_input)
        
        metrics = comparator.get_metrics()
        
        assert metrics.total_comparisons == 10
        assert metrics.agreements == 0
        assert metrics.disagreements == 10
        assert metrics.agreement_rate == 0.0
    
    @pytest.mark.asyncio
    async def test_get_metrics_mixed(self):
        """Test get_metrics() returns correct metrics with mixed results."""
        # Create engines that alternate between agree and disagree
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput()
        
        # Add 6 agreements
        for _ in range(6):
            await comparator.compare(decision_input)
        
        # Change shadow to disagree
        comparator._shadow_engine = MockDecisionEngine(
            result=False,
            rejection_stage="ev_gate",
        )
        
        # Add 4 disagreements
        for _ in range(4):
            await comparator.compare(decision_input)
        
        metrics = comparator.get_metrics()
        
        assert metrics.total_comparisons == 10
        assert metrics.agreements == 6
        assert metrics.disagreements == 4
        assert metrics.agreement_rate == 0.6
    
    @pytest.mark.asyncio
    async def test_get_metrics_divergence_by_reason(self):
        """Test get_metrics() correctly aggregates divergence reasons."""
        live_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=MockDecisionEngine(result=False, rejection_stage="ev_gate"),
        )
        
        decision_input = MockDecisionInput()
        
        # Add 3 with ev_gate rejection
        for _ in range(3):
            await comparator.compare(decision_input)
        
        # Change to cooldown rejection
        comparator._shadow_engine = MockDecisionEngine(
            result=False,
            rejection_stage="cooldown",
        )
        
        # Add 2 with cooldown rejection
        for _ in range(2):
            await comparator.compare(decision_input)
        
        metrics = comparator.get_metrics()
        
        assert metrics.total_comparisons == 5
        assert metrics.disagreements == 5
        # Check divergence reasons are tracked
        assert len(metrics.divergence_by_reason) == 2


class TestShadowComparatorWindowMaintenance:
    """Tests for ShadowComparator comparison window maintenance."""
    
    @pytest.mark.asyncio
    async def test_window_fifo_order(self):
        """Test comparison window maintains FIFO order."""
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            window_size=3,
        )
        
        # Add comparisons with different symbols to track order
        for symbol in ["A", "B", "C", "D", "E"]:
            decision_input = MockDecisionInput(symbol=symbol)
            await comparator.compare(decision_input)
        
        # Window should contain C, D, E (oldest removed first)
        assert len(comparator._comparisons) == 3
        symbols = [c.symbol for c in comparator._comparisons]
        assert symbols == ["C", "D", "E"]
    
    def test_clear_comparisons(self):
        """Test clear_comparisons() empties the window."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        # Manually add some comparisons
        comparator._comparisons = [
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="accepted",
            )
        ]
        
        assert len(comparator._comparisons) == 1
        
        comparator.clear_comparisons()
        
        assert len(comparator._comparisons) == 0
    
    def test_comparison_count_property(self):
        """Test comparison_count property returns correct count."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        assert comparator.comparison_count == 0
        
        # Manually add comparisons
        comparator._comparisons = [
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="accepted",
            )
            for _ in range(5)
        ]
        
        assert comparator.comparison_count == 5
    
    def test_window_size_property(self):
        """Test window_size property returns correct value."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            window_size=50,
        )
        
        assert comparator.window_size == 50
    
    def test_alert_threshold_property(self):
        """Test alert_threshold property returns correct value."""
        live_engine = MockDecisionEngine()
        shadow_engine = MockDecisionEngine()
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            alert_threshold=0.15,
        )
        
        assert comparator.alert_threshold == 0.15
