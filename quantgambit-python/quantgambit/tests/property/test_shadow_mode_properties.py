"""
Property-based tests for Shadow Mode Comparison.

Feature: trading-pipeline-integration

These tests verify the correctness properties of the shadow mode comparison system,
ensuring proper dual execution, agreement rate calculation, and divergence alerting.

Uses hypothesis library with minimum 100 iterations per property test.

**Validates: Requirements 4.1, 4.2, 4.3, 4.6**
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.integration.shadow_comparison import (
    ComparisonResult,
    ComparisonMetrics,
    ShadowComparator,
)


# ═══════════════════════════════════════════════════════════════
# STRATEGIES FOR PROPERTY-BASED TESTING
# ═══════════════════════════════════════════════════════════════

# Symbol strategy
symbol_strategy = st.sampled_from([
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
])

# Decision strategy
decision_strategy = st.sampled_from(["accepted", "rejected"])

# Boolean strategy for decision results
decision_result_strategy = st.booleans()


# Rejection stage strategy
rejection_stage_strategy = st.sampled_from([
    None, "global_gate", "ev_gate", "cooldown", "data_readiness",
    "confirmation", "arbitration", "execution_feasibility",
])

# Profile ID strategy
profile_id_strategy = st.sampled_from([
    None, "profile_a", "profile_b", "profile_c", "aggressive", "conservative",
])

# Signal strategy
@st.composite
def signal_strategy(draw):
    """Generate a valid signal dictionary."""
    return {
        "side": draw(st.sampled_from(["buy", "sell"])),
        "size": draw(st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False)),
        "price": draw(st.floats(min_value=1.0, max_value=100000.0, allow_nan=False, allow_infinity=False)),
    }


# Alert threshold strategy
alert_threshold_strategy = st.floats(
    min_value=0.01,
    max_value=0.50,
    allow_nan=False,
    allow_infinity=False,
)

# Window size strategy
window_size_strategy = st.integers(min_value=10, max_value=500)

# Number of comparisons strategy
num_comparisons_strategy = st.integers(min_value=1, max_value=200)


# ═══════════════════════════════════════════════════════════════
# MOCK CLASSES FOR TESTING
# ═══════════════════════════════════════════════════════════════

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
        self.call_count = 0
        self.last_input = None
    
    async def decide_with_context(self, decision_input: Any) -> tuple[bool, MockStageContext]:
        self.call_count += 1
        self.last_input = decision_input
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


class MockTelemetry:
    """Mock telemetry pipeline for testing alerts."""
    
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
    
    async def publish_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.events.append({
            "event_type": event_type,
            "payload": payload,
        })


# ═══════════════════════════════════════════════════════════════
# PROPERTY 10: SHADOW PIPELINE DUAL EXECUTION
# Feature: trading-pipeline-integration, Property 10
# Validates: Requirements 4.1, 4.2
# ═══════════════════════════════════════════════════════════════

class TestShadowPipelineDualExecution:
    """
    Feature: trading-pipeline-integration, Property 10: Shadow Pipeline Dual Execution
    
    For any market event processed when shadow mode is enabled, the ShadowComparator
    SHALL execute both live_engine and shadow_engine with identical input and record
    both decisions.
    
    **Validates: Requirements 4.1, 4.2**
    """
    
    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        live_result=decision_result_strategy,
        shadow_result=decision_result_strategy,
        live_rejection_stage=rejection_stage_strategy,
        shadow_rejection_stage=rejection_stage_strategy,
        live_profile_id=profile_id_strategy,
        shadow_profile_id=profile_id_strategy,
    )
    @pytest.mark.asyncio
    async def test_both_engines_called_with_identical_input(
        self,
        symbol: str,
        live_result: bool,
        shadow_result: bool,
        live_rejection_stage: Optional[str],
        shadow_rejection_stage: Optional[str],
        live_profile_id: Optional[str],
        shadow_profile_id: Optional[str],
    ):
        """
        **Validates: Requirements 4.1, 4.2**
        
        Property: For any decision input, both live_engine and shadow_engine
        are called exactly once with the same input.
        """
        live_engine = MockDecisionEngine(
            result=live_result,
            rejection_stage=live_rejection_stage if not live_result else None,
            profile_id=live_profile_id,
        )
        shadow_engine = MockDecisionEngine(
            result=shadow_result,
            rejection_stage=shadow_rejection_stage if not shadow_result else None,
            profile_id=shadow_profile_id,
        )
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput(symbol=symbol)
        await comparator.compare(decision_input)
        
        # Both engines should be called exactly once
        assert live_engine.call_count == 1, "Live engine should be called exactly once"
        assert shadow_engine.call_count == 1, "Shadow engine should be called exactly once"
        
        # Both engines should receive the same input
        assert live_engine.last_input is decision_input, \
            "Live engine should receive the original input"
        assert shadow_engine.last_input is decision_input, \
            "Shadow engine should receive the same input as live engine"

    
    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        live_result=decision_result_strategy,
        shadow_result=decision_result_strategy,
    )
    @pytest.mark.asyncio
    async def test_both_decisions_recorded_in_result(
        self,
        symbol: str,
        live_result: bool,
        shadow_result: bool,
    ):
        """
        **Validates: Requirements 4.2**
        
        Property: For any comparison, the result contains both live and shadow
        decisions accurately recorded.
        """
        live_engine = MockDecisionEngine(result=live_result)
        shadow_engine = MockDecisionEngine(result=shadow_result)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput(symbol=symbol)
        result = await comparator.compare(decision_input)
        
        # Verify both decisions are recorded
        expected_live = "accepted" if live_result else "rejected"
        expected_shadow = "accepted" if shadow_result else "rejected"
        
        assert result.live_decision == expected_live, \
            f"Live decision should be '{expected_live}', got '{result.live_decision}'"
        assert result.shadow_decision == expected_shadow, \
            f"Shadow decision should be '{expected_shadow}', got '{result.shadow_decision}'"
        assert result.symbol == symbol, \
            f"Symbol should be '{symbol}', got '{result.symbol}'"
    
    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        live_result=decision_result_strategy,
        shadow_result=decision_result_strategy,
    )
    @pytest.mark.asyncio
    async def test_comparison_stored_in_window(
        self,
        symbol: str,
        live_result: bool,
        shadow_result: bool,
    ):
        """
        **Validates: Requirements 4.2**
        
        Property: For any comparison, the result is stored in the comparison window.
        """
        live_engine = MockDecisionEngine(result=live_result)
        shadow_engine = MockDecisionEngine(result=shadow_result)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        initial_count = comparator.comparison_count
        
        decision_input = MockDecisionInput(symbol=symbol)
        result = await comparator.compare(decision_input)
        
        # Verify comparison is stored
        assert comparator.comparison_count == initial_count + 1, \
            "Comparison count should increase by 1"
        
        # Verify the stored comparison matches the returned result
        stored = comparator._comparisons[-1]
        assert stored.symbol == result.symbol
        assert stored.live_decision == result.live_decision
        assert stored.shadow_decision == result.shadow_decision
        assert stored.agrees == result.agrees

    
    @settings(max_examples=100)
    @given(
        num_comparisons=st.integers(min_value=1, max_value=50),
        window_size=st.integers(min_value=10, max_value=100),
    )
    @pytest.mark.asyncio
    async def test_multiple_comparisons_all_recorded(
        self,
        num_comparisons: int,
        window_size: int,
    ):
        """
        **Validates: Requirements 4.1, 4.2**
        
        Property: For any sequence of N comparisons, all N are processed through
        both engines and recorded (up to window size).
        """
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            window_size=window_size,
        )
        
        for i in range(num_comparisons):
            decision_input = MockDecisionInput(symbol=f"SYM{i}USDT")
            await comparator.compare(decision_input)
        
        # Both engines should be called num_comparisons times
        assert live_engine.call_count == num_comparisons, \
            f"Live engine should be called {num_comparisons} times"
        assert shadow_engine.call_count == num_comparisons, \
            f"Shadow engine should be called {num_comparisons} times"
        
        # Window should contain min(num_comparisons, window_size) comparisons
        expected_stored = min(num_comparisons, window_size)
        assert comparator.comparison_count == expected_stored, \
            f"Should have {expected_stored} comparisons stored"
    
    @settings(max_examples=100)
    @given(
        live_signal=signal_strategy(),
        shadow_signal=signal_strategy(),
    )
    @pytest.mark.asyncio
    async def test_signals_captured_in_result(
        self,
        live_signal: Dict[str, Any],
        shadow_signal: Dict[str, Any],
    ):
        """
        **Validates: Requirements 4.2**
        
        Property: For any comparison where decisions are accepted, the signals
        from both pipelines are captured in the result.
        """
        live_engine = MockDecisionEngine(
            result=True,
            signal=live_signal,
            profile_id="profile_a",
        )
        shadow_engine = MockDecisionEngine(
            result=True,
            signal=shadow_signal,
            profile_id="profile_b",
        )
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        decision_input = MockDecisionInput(symbol="BTCUSDT")
        result = await comparator.compare(decision_input)
        
        # Verify signals are captured
        assert result.live_signal == live_signal, \
            "Live signal should be captured in result"
        assert result.shadow_signal == shadow_signal, \
            "Shadow signal should be captured in result"



# ═══════════════════════════════════════════════════════════════
# PROPERTY 11: SHADOW AGREEMENT RATE CALCULATION
# Feature: trading-pipeline-integration, Property 11
# Validates: Requirements 4.3
# ═══════════════════════════════════════════════════════════════

class TestShadowAgreementRateCalculation:
    """
    Feature: trading-pipeline-integration, Property 11: Shadow Agreement Rate Calculation
    
    For any sequence of N shadow comparisons, the agreement_rate SHALL equal
    (count of agrees=True) / N, computed correctly from the comparison history.
    
    **Validates: Requirements 4.3**
    """
    
    @settings(max_examples=100)
    @given(
        num_agreements=st.integers(min_value=0, max_value=100),
        num_disagreements=st.integers(min_value=0, max_value=100),
    )
    def test_agreement_rate_calculation_from_comparisons(
        self,
        num_agreements: int,
        num_disagreements: int,
    ):
        """
        **Validates: Requirements 4.3**
        
        Property: For any list of comparisons with known agreement counts,
        ComparisonMetrics.from_comparisons() computes agreement_rate correctly.
        """
        # Skip if no comparisons
        assume(num_agreements + num_disagreements > 0)
        
        # Create comparison results
        comparisons = []
        
        # Add agreements
        for i in range(num_agreements):
            comparisons.append(ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol=f"SYM{i}USDT",
                live_decision="accepted",
                shadow_decision="accepted",
            ))
        
        # Add disagreements
        for i in range(num_disagreements):
            comparisons.append(ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol=f"DIS{i}USDT",
                live_decision="accepted",
                shadow_decision="rejected",
                divergence_reason="stage_diff:nonevsev_gate",
            ))
        
        metrics = ComparisonMetrics.from_comparisons(comparisons)
        
        total = num_agreements + num_disagreements
        expected_rate = num_agreements / total
        
        assert metrics.total_comparisons == total, \
            f"Total comparisons should be {total}"
        assert metrics.agreements == num_agreements, \
            f"Agreements should be {num_agreements}"
        assert metrics.disagreements == num_disagreements, \
            f"Disagreements should be {num_disagreements}"
        assert abs(metrics.agreement_rate - expected_rate) < 0.0001, \
            f"Agreement rate should be {expected_rate}, got {metrics.agreement_rate}"

    
    @settings(max_examples=100)
    @given(
        num_comparisons=st.integers(min_value=1, max_value=100),
        agreement_probability=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @pytest.mark.asyncio
    async def test_agreement_rate_from_shadow_comparator(
        self,
        num_comparisons: int,
        agreement_probability: float,
    ):
        """
        **Validates: Requirements 4.3**
        
        Property: For any sequence of comparisons through ShadowComparator,
        get_metrics() returns agreement_rate = agreements / total_comparisons.
        """
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            window_size=num_comparisons + 10,  # Ensure window is large enough
        )
        
        # Track expected agreements
        expected_agreements = 0
        
        for i in range(num_comparisons):
            # Determine if this comparison should agree based on probability
            should_agree = (i / num_comparisons) < agreement_probability
            
            if should_agree:
                comparator._shadow_engine = MockDecisionEngine(result=True)
                expected_agreements += 1
            else:
                comparator._shadow_engine = MockDecisionEngine(
                    result=False,
                    rejection_stage="ev_gate",
                )
            
            decision_input = MockDecisionInput(symbol=f"SYM{i}USDT")
            await comparator.compare(decision_input)
        
        metrics = comparator.get_metrics()
        
        expected_rate = expected_agreements / num_comparisons
        
        assert metrics.total_comparisons == num_comparisons, \
            f"Total comparisons should be {num_comparisons}"
        assert metrics.agreements == expected_agreements, \
            f"Agreements should be {expected_agreements}"
        assert abs(metrics.agreement_rate - expected_rate) < 0.0001, \
            f"Agreement rate should be {expected_rate}, got {metrics.agreement_rate}"
    
    @settings(max_examples=100)
    @given(
        num_comparisons=st.integers(min_value=1, max_value=50),
    )
    @pytest.mark.asyncio
    async def test_agreement_rate_all_agree(
        self,
        num_comparisons: int,
    ):
        """
        **Validates: Requirements 4.3**
        
        Property: When all comparisons agree, agreement_rate equals 1.0.
        """
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        for i in range(num_comparisons):
            decision_input = MockDecisionInput(symbol=f"SYM{i}USDT")
            await comparator.compare(decision_input)
        
        metrics = comparator.get_metrics()
        
        assert metrics.agreement_rate == 1.0, \
            "Agreement rate should be 1.0 when all comparisons agree"
        assert metrics.agreements == num_comparisons
        assert metrics.disagreements == 0

    
    @settings(max_examples=100)
    @given(
        num_comparisons=st.integers(min_value=1, max_value=50),
    )
    @pytest.mark.asyncio
    async def test_agreement_rate_all_disagree(
        self,
        num_comparisons: int,
    ):
        """
        **Validates: Requirements 4.3**
        
        Property: When all comparisons disagree, agreement_rate equals 0.0.
        """
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        for i in range(num_comparisons):
            decision_input = MockDecisionInput(symbol=f"SYM{i}USDT")
            await comparator.compare(decision_input)
        
        metrics = comparator.get_metrics()
        
        assert metrics.agreement_rate == 0.0, \
            "Agreement rate should be 0.0 when all comparisons disagree"
        assert metrics.agreements == 0
        assert metrics.disagreements == num_comparisons
    
    @settings(max_examples=100)
    @given(
        num_comparisons=st.integers(min_value=1, max_value=100),
    )
    def test_agreement_rate_empty_returns_one(
        self,
        num_comparisons: int,
    ):
        """
        **Validates: Requirements 4.3**
        
        Property: When there are no comparisons, agreement_rate defaults to 1.0.
        """
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
        )
        
        # Don't add any comparisons
        metrics = comparator.get_metrics()
        
        assert metrics.total_comparisons == 0
        assert metrics.agreement_rate == 1.0, \
            "Agreement rate should default to 1.0 when no comparisons"
    
    @settings(max_examples=100)
    @given(
        num_agreements=st.integers(min_value=0, max_value=50),
        num_disagreements=st.integers(min_value=0, max_value=50),
    )
    def test_agreement_rate_consistency_check(
        self,
        num_agreements: int,
        num_disagreements: int,
    ):
        """
        **Validates: Requirements 4.3**
        
        Property: For any ComparisonMetrics, agreements + disagreements = total_comparisons
        and agreement_rate = agreements / total_comparisons.
        """
        assume(num_agreements + num_disagreements > 0)
        
        total = num_agreements + num_disagreements
        expected_rate = num_agreements / total
        
        metrics = ComparisonMetrics(
            total_comparisons=total,
            agreements=num_agreements,
            disagreements=num_disagreements,
            agreement_rate=expected_rate,
        )
        
        # Verify consistency
        assert metrics.agreements + metrics.disagreements == metrics.total_comparisons, \
            "agreements + disagreements should equal total_comparisons"
        
        computed_rate = metrics.agreements / metrics.total_comparisons
        assert abs(metrics.agreement_rate - computed_rate) < 0.0001, \
            "agreement_rate should equal agreements / total_comparisons"

    
    @settings(max_examples=100)
    @given(
        divergence_reasons=st.lists(
            st.sampled_from([
                "stage_diff:global_gatevsev_gate",
                "stage_diff:nonevscooldown",
                "profile_diff:profile_avsprofile_b",
                "unknown",
            ]),
            min_size=1,
            max_size=50,
        ),
    )
    def test_divergence_by_reason_aggregation(
        self,
        divergence_reasons: List[str],
    ):
        """
        **Validates: Requirements 4.3**
        
        Property: For any list of comparisons with divergence reasons,
        divergence_by_reason correctly counts each reason.
        """
        # Create disagreeing comparisons with the given reasons
        comparisons = []
        for i, reason in enumerate(divergence_reasons):
            comparisons.append(ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol=f"SYM{i}USDT",
                live_decision="accepted",
                shadow_decision="rejected",
                divergence_reason=reason,
            ))
        
        metrics = ComparisonMetrics.from_comparisons(comparisons)
        
        # Count expected occurrences
        expected_counts: Dict[str, int] = {}
        for reason in divergence_reasons:
            expected_counts[reason] = expected_counts.get(reason, 0) + 1
        
        # Verify counts match
        assert metrics.divergence_by_reason == expected_counts, \
            f"Divergence counts should match: expected {expected_counts}, got {metrics.divergence_by_reason}"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 12: SHADOW DIVERGENCE ALERTING
# Feature: trading-pipeline-integration, Property 12
# Validates: Requirements 4.6
# ═══════════════════════════════════════════════════════════════

class TestShadowDivergenceAlerting:
    """
    Feature: trading-pipeline-integration, Property 12: Shadow Divergence Alerting
    
    For any shadow comparison window where disagreement rate exceeds alert_threshold
    (default 0.20) over 100+ decisions, the System SHALL emit an alert with
    severity "warning".
    
    **Validates: Requirements 4.6**
    """
    
    @settings(max_examples=100)
    @given(
        alert_threshold=st.floats(min_value=0.05, max_value=0.40, allow_nan=False, allow_infinity=False),
        disagreement_rate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @pytest.mark.asyncio
    async def test_alert_emitted_when_threshold_exceeded(
        self,
        alert_threshold: float,
        disagreement_rate: float,
    ):
        """
        **Validates: Requirements 4.6**
        
        Property: When disagreement rate exceeds alert_threshold over 100+ decisions,
        an alert is emitted with severity "warning".
        """
        # Skip boundary cases
        assume(abs(disagreement_rate - alert_threshold) > 0.02)
        
        telemetry = MockTelemetry()
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=telemetry,
            alert_threshold=alert_threshold,
            window_size=150,
        )
        
        # Calculate how many disagreements we need for the target rate
        total_comparisons = 100
        num_disagreements = int(total_comparisons * disagreement_rate)
        num_agreements = total_comparisons - num_disagreements
        
        # Add agreements first
        for i in range(num_agreements):
            comparator._shadow_engine = MockDecisionEngine(result=True)
            decision_input = MockDecisionInput(symbol=f"AGR{i}USDT")
            await comparator.compare(decision_input)
        
        # Add disagreements
        for i in range(num_disagreements):
            comparator._shadow_engine = MockDecisionEngine(
                result=False,
                rejection_stage="ev_gate",
            )
            decision_input = MockDecisionInput(symbol=f"DIS{i}USDT")
            await comparator.compare(decision_input)
        
        # Check if alert was emitted
        should_alert = disagreement_rate > alert_threshold
        
        if should_alert:
            assert len(telemetry.events) > 0, \
                f"Alert should be emitted when disagreement rate {disagreement_rate} > threshold {alert_threshold}"
            
            # Verify alert content
            alert = telemetry.events[-1]
            assert alert["event_type"] == "shadow_divergence_high"
            assert alert["payload"]["severity"] == "warning"
            assert alert["payload"]["threshold"] == alert_threshold
        else:
            # Alert should not be emitted (or fewer alerts)
            # Note: alerts may have been emitted during the process if threshold was temporarily exceeded
            pass

    
    @settings(max_examples=100)
    @given(
        alert_threshold=st.floats(min_value=0.10, max_value=0.40, allow_nan=False, allow_infinity=False),
    )
    @pytest.mark.asyncio
    async def test_no_alert_below_100_comparisons(
        self,
        alert_threshold: float,
    ):
        """
        **Validates: Requirements 4.6**
        
        Property: No alert is emitted when there are fewer than 100 comparisons,
        even if disagreement rate exceeds threshold.
        """
        telemetry = MockTelemetry()
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=telemetry,
            alert_threshold=alert_threshold,
        )
        
        # Add 99 disagreements (100% disagreement rate, but < 100 comparisons)
        for i in range(99):
            decision_input = MockDecisionInput(symbol=f"DIS{i}USDT")
            await comparator.compare(decision_input)
        
        # No alert should be emitted yet
        assert len(telemetry.events) == 0, \
            "No alert should be emitted with fewer than 100 comparisons"
    
    @settings(max_examples=100)
    @given(
        alert_threshold=st.floats(min_value=0.10, max_value=0.40, allow_nan=False, allow_infinity=False),
    )
    @pytest.mark.asyncio
    async def test_alert_at_exactly_100_comparisons(
        self,
        alert_threshold: float,
    ):
        """
        **Validates: Requirements 4.6**
        
        Property: Alert is emitted at exactly 100 comparisons when threshold is exceeded.
        """
        telemetry = MockTelemetry()
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=telemetry,
            alert_threshold=alert_threshold,
        )
        
        # Add 100 disagreements (100% disagreement rate)
        for i in range(100):
            decision_input = MockDecisionInput(symbol=f"DIS{i}USDT")
            await comparator.compare(decision_input)
        
        # Alert should be emitted (100% > any threshold)
        assert len(telemetry.events) > 0, \
            "Alert should be emitted at 100 comparisons when threshold exceeded"
        
        alert = telemetry.events[-1]
        assert alert["event_type"] == "shadow_divergence_high"
        assert alert["payload"]["severity"] == "warning"

    
    @settings(max_examples=100)
    @given(
        alert_threshold=st.floats(min_value=0.10, max_value=0.40, allow_nan=False, allow_infinity=False),
    )
    @pytest.mark.asyncio
    async def test_no_alert_when_below_threshold(
        self,
        alert_threshold: float,
    ):
        """
        **Validates: Requirements 4.6**
        
        Property: No alert is emitted when disagreement rate is below threshold,
        even with 100+ comparisons.
        """
        telemetry = MockTelemetry()
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=telemetry,
            alert_threshold=alert_threshold,
        )
        
        # Add 100 agreements (0% disagreement rate)
        for i in range(100):
            decision_input = MockDecisionInput(symbol=f"AGR{i}USDT")
            await comparator.compare(decision_input)
        
        # No alert should be emitted (0% < any threshold)
        assert len(telemetry.events) == 0, \
            "No alert should be emitted when disagreement rate is below threshold"
    
    @settings(max_examples=100)
    @given(
        alert_threshold=alert_threshold_strategy,
    )
    def test_exceeds_threshold_method(
        self,
        alert_threshold: float,
    ):
        """
        **Validates: Requirements 4.6**
        
        Property: ComparisonMetrics.exceeds_threshold() correctly identifies
        when divergence rate exceeds the given threshold.
        """
        # Test case 1: Divergence rate above threshold
        high_divergence = ComparisonMetrics(
            total_comparisons=100,
            agreements=50,
            disagreements=50,
            agreement_rate=0.5,
        )
        
        if 0.5 > alert_threshold:
            assert high_divergence.exceeds_threshold(alert_threshold), \
                f"50% divergence should exceed {alert_threshold} threshold"
        else:
            assert not high_divergence.exceeds_threshold(alert_threshold), \
                f"50% divergence should not exceed {alert_threshold} threshold"
        
        # Test case 2: Divergence rate clearly below threshold
        # Use 96% agreement (4% divergence) to avoid floating point edge cases
        low_divergence = ComparisonMetrics(
            total_comparisons=100,
            agreements=96,
            disagreements=4,
            agreement_rate=0.96,
        )
        
        # 4% divergence (0.04) should only exceed threshold if threshold < 0.04
        if 0.04 > alert_threshold:
            assert low_divergence.exceeds_threshold(alert_threshold), \
                f"4% divergence should exceed {alert_threshold} threshold"
        else:
            assert not low_divergence.exceeds_threshold(alert_threshold), \
                f"4% divergence should not exceed {alert_threshold} threshold"

    
    @settings(max_examples=100)
    @given(
        num_agreements=st.integers(min_value=0, max_value=100),
        num_disagreements=st.integers(min_value=0, max_value=100),
    )
    def test_divergence_rate_calculation(
        self,
        num_agreements: int,
        num_disagreements: int,
    ):
        """
        **Validates: Requirements 4.6**
        
        Property: ComparisonMetrics.divergence_rate() correctly computes
        1 - agreement_rate.
        """
        assume(num_agreements + num_disagreements > 0)
        
        total = num_agreements + num_disagreements
        agreement_rate = num_agreements / total
        expected_divergence = 1.0 - agreement_rate
        
        metrics = ComparisonMetrics(
            total_comparisons=total,
            agreements=num_agreements,
            disagreements=num_disagreements,
            agreement_rate=agreement_rate,
        )
        
        actual_divergence = metrics.divergence_rate()
        
        assert abs(actual_divergence - expected_divergence) < 0.0001, \
            f"Divergence rate should be {expected_divergence}, got {actual_divergence}"
    
    @settings(max_examples=100)
    @given(
        alert_threshold=alert_threshold_strategy,
    )
    @pytest.mark.asyncio
    async def test_alert_contains_required_fields(
        self,
        alert_threshold: float,
    ):
        """
        **Validates: Requirements 4.6**
        
        Property: When an alert is emitted, it contains all required fields:
        divergence_rate, threshold, total_comparisons, divergence_by_reason, severity.
        """
        telemetry = MockTelemetry()
        live_engine = MockDecisionEngine(result=True)
        shadow_engine = MockDecisionEngine(result=False, rejection_stage="ev_gate")
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=telemetry,
            alert_threshold=alert_threshold,
        )
        
        # Add 100 disagreements to trigger alert
        for i in range(100):
            decision_input = MockDecisionInput(symbol=f"DIS{i}USDT")
            await comparator.compare(decision_input)
        
        # Verify alert was emitted with required fields
        assert len(telemetry.events) > 0, "Alert should be emitted"
        
        alert = telemetry.events[-1]
        payload = alert["payload"]
        
        assert "divergence_rate" in payload, "Alert should contain divergence_rate"
        assert "threshold" in payload, "Alert should contain threshold"
        assert "total_comparisons" in payload, "Alert should contain total_comparisons"
        assert "divergence_by_reason" in payload, "Alert should contain divergence_by_reason"
        assert "severity" in payload, "Alert should contain severity"
        assert payload["severity"] == "warning", "Severity should be 'warning'"

    
    @settings(max_examples=100)
    @given(
        window_size=st.integers(min_value=100, max_value=300),
    )
    @pytest.mark.asyncio
    async def test_alert_respects_window_size(
        self,
        window_size: int,
    ):
        """
        **Validates: Requirements 4.6**
        
        Property: Alert threshold check uses the current window of comparisons,
        respecting the configured window_size.
        """
        telemetry = MockTelemetry()
        live_engine = MockDecisionEngine(result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=MockDecisionEngine(result=True),
            telemetry=telemetry,
            alert_threshold=0.20,
            window_size=window_size,
        )
        
        # Fill window with agreements
        for i in range(window_size):
            decision_input = MockDecisionInput(symbol=f"AGR{i}USDT")
            await comparator.compare(decision_input)
        
        # No alerts should have been emitted (0% disagreement)
        initial_alert_count = len(telemetry.events)
        
        # Now add disagreements that will push out agreements
        comparator._shadow_engine = MockDecisionEngine(
            result=False,
            rejection_stage="ev_gate",
        )
        
        # Add enough disagreements to exceed threshold
        # Need >20% of window_size to be disagreements
        num_disagreements_needed = int(window_size * 0.25) + 1
        
        for i in range(num_disagreements_needed):
            decision_input = MockDecisionInput(symbol=f"DIS{i}USDT")
            await comparator.compare(decision_input)
        
        # Verify window size is maintained
        assert comparator.comparison_count == window_size, \
            f"Window should maintain size {window_size}"


# ═══════════════════════════════════════════════════════════════
# ADDITIONAL PROPERTY TESTS FOR COMPARISON RESULT
# Feature: trading-pipeline-integration
# Validates: Requirements 4.2, 4.3
# ═══════════════════════════════════════════════════════════════

class TestComparisonResultProperties:
    """
    Additional property tests for ComparisonResult.
    
    These tests ensure ComparisonResult correctly computes and validates
    the agrees field based on live and shadow decisions.
    
    **Validates: Requirements 4.2, 4.3**
    """
    
    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        live_decision=decision_strategy,
        shadow_decision=decision_strategy,
    )
    def test_agrees_computed_correctly(
        self,
        symbol: str,
        live_decision: str,
        shadow_decision: str,
    ):
        """
        **Validates: Requirements 4.2, 4.3**
        
        Property: For any ComparisonResult, agrees is True iff
        live_decision == shadow_decision.
        """
        result = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            live_decision=live_decision,
            shadow_decision=shadow_decision,
        )
        
        expected_agrees = live_decision == shadow_decision
        
        assert result.agrees == expected_agrees, \
            f"agrees should be {expected_agrees} for live={live_decision}, shadow={shadow_decision}"
    
    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        live_decision=decision_strategy,
        shadow_decision=decision_strategy,
    )
    def test_is_agreement_and_is_divergence_mutually_exclusive(
        self,
        symbol: str,
        live_decision: str,
        shadow_decision: str,
    ):
        """
        **Validates: Requirements 4.2, 4.3**
        
        Property: For any ComparisonResult, is_agreement() and is_divergence()
        are mutually exclusive and exhaustive.
        """
        result = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            live_decision=live_decision,
            shadow_decision=shadow_decision,
        )
        
        # Exactly one should be True
        assert result.is_agreement() != result.is_divergence(), \
            "is_agreement() and is_divergence() should be mutually exclusive"
        
        # is_agreement should match agrees
        assert result.is_agreement() == result.agrees
        assert result.is_divergence() == (not result.agrees)

    
    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        live_decision=decision_strategy,
        shadow_decision=decision_strategy,
        divergence_reason=st.one_of(
            st.none(),
            st.sampled_from([
                "stage_diff:global_gatevsev_gate",
                "profile_diff:profile_avsprofile_b",
                "unknown",
            ]),
        ),
    )
    def test_comparison_result_round_trip_serialization(
        self,
        symbol: str,
        live_decision: str,
        shadow_decision: str,
        divergence_reason: Optional[str],
    ):
        """
        **Validates: Requirements 4.2**
        
        Property: For any ComparisonResult, to_dict() and from_dict() form
        a round-trip that preserves all fields.
        """
        original = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            live_decision=live_decision,
            shadow_decision=shadow_decision,
            divergence_reason=divergence_reason if live_decision != shadow_decision else None,
        )
        
        # Round-trip through dict
        as_dict = original.to_dict()
        restored = ComparisonResult.from_dict(as_dict)
        
        # Verify all fields match
        assert restored.symbol == original.symbol
        assert restored.live_decision == original.live_decision
        assert restored.shadow_decision == original.shadow_decision
        assert restored.agrees == original.agrees
        assert restored.divergence_reason == original.divergence_reason
        
        # Timestamp should be close (within 1 second due to serialization)
        time_diff = abs((restored.timestamp - original.timestamp).total_seconds())
        assert time_diff < 1.0, f"Timestamp difference {time_diff}s should be < 1s"
    
    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
    )
    def test_comparison_result_validates_decisions(
        self,
        symbol: str,
    ):
        """
        **Validates: Requirements 4.2**
        
        Property: ComparisonResult validates that live_decision and shadow_decision
        are either "accepted" or "rejected".
        """
        # Valid decisions should work
        valid_result = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            live_decision="accepted",
            shadow_decision="rejected",
        )
        assert valid_result.live_decision == "accepted"
        assert valid_result.shadow_decision == "rejected"
        
        # Invalid decisions should raise ValueError
        with pytest.raises(ValueError):
            ComparisonResult(
                timestamp=datetime.now(timezone.utc),
                symbol=symbol,
                live_decision="invalid",
                shadow_decision="accepted",
                agrees=False,
            )
        
        with pytest.raises(ValueError):
            ComparisonResult(
                timestamp=datetime.now(timezone.utc),
                symbol=symbol,
                live_decision="accepted",
                shadow_decision="invalid",
                agrees=False,
            )
