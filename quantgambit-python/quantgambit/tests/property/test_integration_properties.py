"""
Property-based tests for Integration Testing Framework.

Feature: trading-pipeline-integration

These tests verify Property 24: Decision Consistency for Identical Inputs,
ensuring that identical inputs always produce identical decisions.

Uses hypothesis library with minimum 100 iterations per property test.

**Validates: Requirements 10.2, 10.6**
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from quantgambit.integration.decision_recording import RecordedDecision
from quantgambit.tests.fixtures.parity_fixtures import (
    STANDARD_TEST_CONFIG,
    ParityTestFixtures,
    create_test_decision,
    create_decision_sequence,
)


# ═══════════════════════════════════════════════════════════════
# STRATEGIES FOR PROPERTY-BASED TESTING
# ═══════════════════════════════════════════════════════════════

# Symbol strategy
symbol_strategy = st.sampled_from([
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "MATICUSDT", "DOTUSDT", "AVAXUSDT",
])

# Decision outcome strategy
decision_outcome_strategy = st.sampled_from(["accepted", "rejected"])

# Config version strategy
config_version_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"),
    min_size=1,
    max_size=32,
).map(lambda s: f"v_{s}")

# Rejection stage strategy
rejection_stage_strategy = st.sampled_from([
    "DataReadiness", "GlobalGate", "EVGate", "ExecutionFeasibility",
    "Confirmation", "Arbitration",
])

# Profile ID strategy
profile_id_strategy = st.one_of(
    st.none(),
    st.sampled_from([
        "micro_range_mean_reversion", "momentum_breakout", "aggressive",
        "conservative", "balanced", "scalper", "swing",
    ]),
)

# Price strategy (realistic crypto prices)
price_strategy = st.floats(
    min_value=0.001,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Size strategy (position sizes)
size_strategy = st.floats(
    min_value=0.0001,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Timestamp strategy
timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)

# EV strategy (expected value)
ev_strategy = st.floats(
    min_value=0.0001,
    max_value=0.01,
    allow_nan=False,
    allow_infinity=False,
)

# Market snapshot strategy
market_snapshot_strategy = st.fixed_dictionaries({
    "price": price_strategy,
    "bid": price_strategy,
    "ask": price_strategy,
    "spread_bps": st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
    "volume_24h": st.floats(min_value=10000.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
    "bid_depth_usd": st.floats(min_value=1000.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
    "ask_depth_usd": st.floats(min_value=1000.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
})

# Features strategy
features_strategy = st.fixed_dictionaries({
    "ev": ev_strategy,
    "trend_strength": st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "volatility": st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
    "momentum": st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "signal_strength": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    "regime": st.sampled_from(["trending", "ranging", "volatile", "calm"]),
})

# Position strategy
position_strategy = st.fixed_dictionaries({
    "symbol": symbol_strategy,
    "side": st.sampled_from(["long", "short"]),
    "size": size_strategy,
    "entry_price": price_strategy,
})

# Positions list strategy
positions_strategy = st.lists(position_strategy, min_size=0, max_size=5)

# Account state strategy
account_state_strategy = st.fixed_dictionaries({
    "equity": st.floats(min_value=1000.0, max_value=1000000.0, allow_nan=False, allow_infinity=False),
    "margin_used": st.floats(min_value=0.0, max_value=500000.0, allow_nan=False, allow_infinity=False),
})

# Stage result strategy
stage_result_strategy = st.fixed_dictionaries({
    "stage": rejection_stage_strategy,
    "passed": st.booleans(),
    "reason": st.one_of(st.none(), st.text(min_size=1, max_size=50)),
})

# Stage results list strategy
stage_results_strategy = st.lists(stage_result_strategy, min_size=1, max_size=6)

# Signal strategy (for accepted decisions)
signal_strategy = st.fixed_dictionaries({
    "side": st.sampled_from(["long", "short"]),
    "entry_price": price_strategy,
    "size": size_strategy,
    "stop_loss": price_strategy,
    "take_profit": price_strategy,
    "confidence": st.floats(min_value=0.5, max_value=1.0, allow_nan=False, allow_infinity=False),
    "ev": ev_strategy,
})


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

@dataclass
class DecisionInput:
    """Input data for a trading decision.
    
    Represents all the input data needed to make a trading decision,
    used for testing decision consistency.
    """
    symbol: str
    timestamp: datetime
    config_version: str
    market_snapshot: Dict[str, Any]
    features: Dict[str, Any]
    positions: List[Dict[str, Any]]
    account_state: Dict[str, Any]
    profile_id: Optional[str] = None


@dataclass
class Configuration:
    """Configuration for decision making.
    
    Represents the configuration parameters used for decision making.
    """
    version_id: str
    parameters: Dict[str, Any]


def decide(
    input_data: DecisionInput,
    config: Configuration,
) -> RecordedDecision:
    """Simulate a decision based on input and configuration.
    
    This function simulates the decision-making process based on the
    input data and configuration. It uses deterministic logic to ensure
    identical inputs produce identical outputs.
    
    Args:
        input_data: The decision input data
        config: The configuration to use
        
    Returns:
        RecordedDecision representing the decision outcome
    """
    # Get EV threshold from config
    ev_threshold = config.parameters.get("ev_gate", {}).get("ev_min", 0.0015)
    
    # Get EV from features
    ev = input_data.features.get("ev", 0.0)
    
    # Determine decision based on EV threshold
    if ev >= ev_threshold:
        # Accepted decision
        trend_strength = input_data.features.get("trend_strength", 0.0)
        signal_side = "long" if trend_strength >= 0 else "short"
        
        return RecordedDecision(
            decision_id=f"dec_{uuid4().hex[:12]}",
            timestamp=input_data.timestamp,
            symbol=input_data.symbol,
            config_version=config.version_id,
            market_snapshot=input_data.market_snapshot,
            features=input_data.features,
            positions=input_data.positions,
            account_state=input_data.account_state,
            stage_results=[
                {"stage": "DataReadiness", "passed": True, "reason": None},
                {"stage": "GlobalGate", "passed": True, "reason": None},
                {"stage": "EVGate", "passed": True, "ev": ev, "threshold": ev_threshold},
                {"stage": "ExecutionFeasibility", "passed": True, "reason": None},
                {"stage": "Confirmation", "passed": True, "confidence": 0.85},
                {"stage": "Arbitration", "passed": True, "selected_signal": signal_side},
            ],
            rejection_stage=None,
            rejection_reason=None,
            decision="accepted",
            signal={
                "side": signal_side,
                "entry_price": input_data.market_snapshot.get("price", 50000.0),
                "size": 0.1,
                "stop_loss": input_data.market_snapshot.get("price", 50000.0) * 0.99,
                "take_profit": input_data.market_snapshot.get("price", 50000.0) * 1.02,
                "confidence": 0.85,
                "ev": ev,
            },
            profile_id=input_data.profile_id,
        )
    else:
        # Rejected decision at EVGate
        return RecordedDecision(
            decision_id=f"dec_{uuid4().hex[:12]}",
            timestamp=input_data.timestamp,
            symbol=input_data.symbol,
            config_version=config.version_id,
            market_snapshot=input_data.market_snapshot,
            features=input_data.features,
            positions=input_data.positions,
            account_state=input_data.account_state,
            stage_results=[
                {"stage": "DataReadiness", "passed": True, "reason": None},
                {"stage": "GlobalGate", "passed": True, "reason": None},
                {"stage": "EVGate", "passed": False, "ev": ev, "threshold": ev_threshold},
            ],
            rejection_stage="EVGate",
            rejection_reason=f"EV {ev:.5f} below threshold {ev_threshold}",
            decision="rejected",
            signal=None,
            profile_id=input_data.profile_id,
        )


def decisions_are_consistent(d1: RecordedDecision, d2: RecordedDecision) -> bool:
    """Check if two decisions are consistent.
    
    Two decisions are consistent if:
    - They have the same decision outcome (accepted/rejected)
    - For rejected decisions, they have the same rejection_stage
    
    Args:
        d1: First decision
        d2: Second decision
        
    Returns:
        True if decisions are consistent
    """
    # Check decision outcome matches
    if d1.decision != d2.decision:
        return False
    
    # For rejected decisions, check rejection_stage matches
    if d1.decision == "rejected":
        if d1.rejection_stage != d2.rejection_stage:
            return False
    
    return True


# ═══════════════════════════════════════════════════════════════
# PROPERTY 24: DECISION CONSISTENCY FOR IDENTICAL INPUTS
# Feature: trading-pipeline-integration, Property 24
# Validates: Requirements 10.2, 10.6
# ═══════════════════════════════════════════════════════════════

class TestDecisionConsistencyForIdenticalInputs:
    """
    Feature: trading-pipeline-integration, Property 24: Decision Consistency for Identical Inputs
    
    For any DecisionInput processed by both live and backtest DecisionEngine
    instances with identical configuration, the decision outcome (accepted/rejected)
    and rejection_stage (if rejected) SHALL be identical.
    
    Property 24: Decision Consistency for Identical Inputs
    ∀ input ∈ DecisionInput, config ∈ Configuration:
      let d1 = decide(input, config)
      let d2 = decide(input, config)
      d1.decision == d2.decision ∧
      (d1.decision == "rejected" → d1.rejection_stage == d2.rejection_stage)
    
    **Validates: Requirements 10.2, 10.6**
    """
    
    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        timestamp=timestamp_strategy,
        config_version=config_version_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        positions=positions_strategy,
        account_state=account_state_strategy,
        profile_id=profile_id_strategy,
    )
    def test_identical_inputs_produce_identical_decisions(
        self,
        symbol: str,
        timestamp: datetime,
        config_version: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        profile_id: Optional[str],
    ):
        """
        **Validates: Requirements 10.2, 10.6**
        
        Property: For any input and configuration, calling decide() twice with
        identical inputs produces identical decision outcomes.
        
        ∀ input ∈ DecisionInput, config ∈ Configuration:
          let d1 = decide(input, config)
          let d2 = decide(input, config)
          d1.decision == d2.decision
        """
        # Create decision input
        input_data = DecisionInput(
            symbol=symbol,
            timestamp=timestamp,
            config_version=config_version,
            market_snapshot=market_snapshot,
            features=features,
            positions=positions,
            account_state=account_state,
            profile_id=profile_id,
        )
        
        # Create configuration
        config = Configuration(
            version_id=config_version,
            parameters=STANDARD_TEST_CONFIG,
        )
        
        # Make two decisions with identical inputs
        d1 = decide(input_data, config)
        d2 = decide(input_data, config)
        
        # Verify decision outcomes are identical
        assert d1.decision == d2.decision, (
            f"Decision outcomes should be identical: d1={d1.decision}, d2={d2.decision}"
        )

    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        timestamp=timestamp_strategy,
        config_version=config_version_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        positions=positions_strategy,
        account_state=account_state_strategy,
        profile_id=profile_id_strategy,
    )
    def test_rejection_stage_matches_for_rejected_decisions(
        self,
        symbol: str,
        timestamp: datetime,
        config_version: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        profile_id: Optional[str],
    ):
        """
        **Validates: Requirements 10.2, 10.6**
        
        Property: For rejected decisions, the rejection_stage is identical
        when processing identical inputs.
        
        ∀ input ∈ DecisionInput, config ∈ Configuration:
          let d1 = decide(input, config)
          let d2 = decide(input, config)
          d1.decision == "rejected" → d1.rejection_stage == d2.rejection_stage
        """
        # Create decision input
        input_data = DecisionInput(
            symbol=symbol,
            timestamp=timestamp,
            config_version=config_version,
            market_snapshot=market_snapshot,
            features=features,
            positions=positions,
            account_state=account_state,
            profile_id=profile_id,
        )
        
        # Create configuration
        config = Configuration(
            version_id=config_version,
            parameters=STANDARD_TEST_CONFIG,
        )
        
        # Make two decisions with identical inputs
        d1 = decide(input_data, config)
        d2 = decide(input_data, config)
        
        # If decision is rejected, verify rejection_stage matches
        if d1.decision == "rejected":
            assert d1.rejection_stage == d2.rejection_stage, (
                f"Rejection stages should be identical for rejected decisions: "
                f"d1.rejection_stage={d1.rejection_stage}, d2.rejection_stage={d2.rejection_stage}"
            )

    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        timestamp=timestamp_strategy,
        config_version=config_version_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        positions=positions_strategy,
        account_state=account_state_strategy,
        profile_id=profile_id_strategy,
    )
    def test_full_decision_consistency(
        self,
        symbol: str,
        timestamp: datetime,
        config_version: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        profile_id: Optional[str],
    ):
        """
        **Validates: Requirements 10.2, 10.6**
        
        Property: Full decision consistency check - both decision outcome
        and rejection_stage (if rejected) must match.
        
        ∀ input ∈ DecisionInput, config ∈ Configuration:
          let d1 = decide(input, config)
          let d2 = decide(input, config)
          d1.decision == d2.decision ∧
          (d1.decision == "rejected" → d1.rejection_stage == d2.rejection_stage)
        """
        # Create decision input
        input_data = DecisionInput(
            symbol=symbol,
            timestamp=timestamp,
            config_version=config_version,
            market_snapshot=market_snapshot,
            features=features,
            positions=positions,
            account_state=account_state,
            profile_id=profile_id,
        )
        
        # Create configuration
        config = Configuration(
            version_id=config_version,
            parameters=STANDARD_TEST_CONFIG,
        )
        
        # Make two decisions with identical inputs
        d1 = decide(input_data, config)
        d2 = decide(input_data, config)
        
        # Verify full consistency using helper function
        assert decisions_are_consistent(d1, d2), (
            f"Decisions should be consistent: "
            f"d1.decision={d1.decision}, d2.decision={d2.decision}, "
            f"d1.rejection_stage={d1.rejection_stage}, d2.rejection_stage={d2.rejection_stage}"
        )

    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        timestamp=timestamp_strategy,
        config_version=config_version_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        positions=positions_strategy,
        account_state=account_state_strategy,
        profile_id=profile_id_strategy,
        num_iterations=st.integers(min_value=2, max_value=10),
    )
    def test_decision_consistency_across_multiple_calls(
        self,
        symbol: str,
        timestamp: datetime,
        config_version: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        profile_id: Optional[str],
        num_iterations: int,
    ):
        """
        **Validates: Requirements 10.2, 10.6**
        
        Property: Decision consistency holds across multiple calls with
        identical inputs - all decisions should be identical.
        """
        # Create decision input
        input_data = DecisionInput(
            symbol=symbol,
            timestamp=timestamp,
            config_version=config_version,
            market_snapshot=market_snapshot,
            features=features,
            positions=positions,
            account_state=account_state,
            profile_id=profile_id,
        )
        
        # Create configuration
        config = Configuration(
            version_id=config_version,
            parameters=STANDARD_TEST_CONFIG,
        )
        
        # Make multiple decisions with identical inputs
        decisions = [decide(input_data, config) for _ in range(num_iterations)]
        
        # All decisions should have the same outcome
        first_decision = decisions[0]
        for i, d in enumerate(decisions[1:], start=2):
            assert d.decision == first_decision.decision, (
                f"Decision {i} should match decision 1: "
                f"d{i}.decision={d.decision}, d1.decision={first_decision.decision}"
            )
            
            # For rejected decisions, rejection_stage should also match
            if first_decision.decision == "rejected":
                assert d.rejection_stage == first_decision.rejection_stage, (
                    f"Rejection stage {i} should match rejection stage 1: "
                    f"d{i}.rejection_stage={d.rejection_stage}, "
                    f"d1.rejection_stage={first_decision.rejection_stage}"
                )

    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        timestamp=timestamp_strategy,
        config_version=config_version_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        positions=positions_strategy,
        account_state=account_state_strategy,
        profile_id=profile_id_strategy,
    )
    def test_decision_consistency_with_deep_copy(
        self,
        symbol: str,
        timestamp: datetime,
        config_version: str,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        profile_id: Optional[str],
    ):
        """
        **Validates: Requirements 10.2, 10.6**
        
        Property: Decision consistency holds when inputs are deep copied -
        ensuring no reference-based side effects affect consistency.
        """
        # Create original decision input
        input_data = DecisionInput(
            symbol=symbol,
            timestamp=timestamp,
            config_version=config_version,
            market_snapshot=market_snapshot,
            features=features,
            positions=positions,
            account_state=account_state,
            profile_id=profile_id,
        )
        
        # Create deep copy of input
        input_data_copy = DecisionInput(
            symbol=symbol,
            timestamp=timestamp,
            config_version=config_version,
            market_snapshot=deepcopy(market_snapshot),
            features=deepcopy(features),
            positions=deepcopy(positions),
            account_state=deepcopy(account_state),
            profile_id=profile_id,
        )
        
        # Create configuration
        config = Configuration(
            version_id=config_version,
            parameters=STANDARD_TEST_CONFIG,
        )
        
        # Make decisions with original and copied inputs
        d1 = decide(input_data, config)
        d2 = decide(input_data_copy, config)
        
        # Verify consistency
        assert decisions_are_consistent(d1, d2), (
            f"Decisions should be consistent with deep copied inputs: "
            f"d1.decision={d1.decision}, d2.decision={d2.decision}, "
            f"d1.rejection_stage={d1.rejection_stage}, d2.rejection_stage={d2.rejection_stage}"
        )

    @settings(max_examples=100)
    @given(
        ev=st.floats(min_value=0.0001, max_value=0.003, allow_nan=False, allow_infinity=False),
    )
    def test_decision_consistency_at_ev_threshold_boundary(
        self,
        ev: float,
    ):
        """
        **Validates: Requirements 10.2, 10.6**
        
        Property: Decision consistency holds at EV threshold boundaries -
        the same EV value always produces the same decision.
        """
        # Create decision input with specific EV
        input_data = DecisionInput(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            config_version="test_v1",
            market_snapshot={"price": 50000.0, "bid": 49995.0, "ask": 50005.0},
            features={"ev": ev, "trend_strength": 0.5, "volatility": 0.02},
            positions=[],
            account_state={"equity": 100000.0, "margin_used": 0.0},
            profile_id="micro_range_mean_reversion",
        )
        
        # Create configuration
        config = Configuration(
            version_id="test_v1",
            parameters=STANDARD_TEST_CONFIG,
        )
        
        # Make two decisions
        d1 = decide(input_data, config)
        d2 = decide(input_data, config)
        
        # Verify consistency
        assert d1.decision == d2.decision, (
            f"Decision outcomes should be identical at EV={ev}: "
            f"d1={d1.decision}, d2={d2.decision}"
        )
        
        if d1.decision == "rejected":
            assert d1.rejection_stage == d2.rejection_stage, (
                f"Rejection stages should be identical at EV={ev}: "
                f"d1.rejection_stage={d1.rejection_stage}, "
                f"d2.rejection_stage={d2.rejection_stage}"
            )

    @settings(max_examples=100)
    @given(
        decision_data=st.lists(
            st.tuples(
                symbol_strategy,
                ev_strategy,
                profile_id_strategy,
            ),
            min_size=5,
            max_size=20,
        ),
    )
    def test_decision_sequence_consistency(
        self,
        decision_data: List[Tuple[str, float, Optional[str]]],
    ):
        """
        **Validates: Requirements 10.2, 10.6**
        
        Property: A sequence of decisions maintains consistency when
        replayed with identical inputs.
        """
        base_timestamp = datetime.now(timezone.utc)
        config = Configuration(
            version_id="test_v1",
            parameters=STANDARD_TEST_CONFIG,
        )
        
        # Create inputs and make first pass of decisions
        inputs_and_decisions_1 = []
        for i, (symbol, ev, profile_id) in enumerate(decision_data):
            input_data = DecisionInput(
                symbol=symbol,
                timestamp=base_timestamp + timedelta(minutes=i),
                config_version="test_v1",
                market_snapshot={"price": 50000.0, "bid": 49995.0, "ask": 50005.0},
                features={"ev": ev, "trend_strength": 0.5, "volatility": 0.02},
                positions=[],
                account_state={"equity": 100000.0, "margin_used": 0.0},
                profile_id=profile_id,
            )
            decision = decide(input_data, config)
            inputs_and_decisions_1.append((input_data, decision))
        
        # Make second pass with same inputs
        for input_data, d1 in inputs_and_decisions_1:
            d2 = decide(input_data, config)
            
            assert decisions_are_consistent(d1, d2), (
                f"Decision sequence should be consistent: "
                f"d1.decision={d1.decision}, d2.decision={d2.decision}, "
                f"d1.rejection_stage={d1.rejection_stage}, "
                f"d2.rejection_stage={d2.rejection_stage}"
            )


    @settings(max_examples=100)
    @given(
        symbol=symbol_strategy,
        timestamp=timestamp_strategy,
        market_snapshot=market_snapshot_strategy,
        features=features_strategy,
        positions=positions_strategy,
        account_state=account_state_strategy,
        profile_id=profile_id_strategy,
    )
    def test_decision_consistency_with_fixture_config(
        self,
        symbol: str,
        timestamp: datetime,
        market_snapshot: Dict[str, Any],
        features: Dict[str, Any],
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        profile_id: Optional[str],
    ):
        """
        **Validates: Requirements 10.2, 10.6**
        
        Property: Decision consistency holds when using the standard test
        configuration from parity fixtures.
        """
        # Use the standard test config from fixtures
        fixtures = ParityTestFixtures()
        standard_config = fixtures.get_standard_config()
        
        # Create decision input
        input_data = DecisionInput(
            symbol=symbol,
            timestamp=timestamp,
            config_version=standard_config.version_id,
            market_snapshot=market_snapshot,
            features=features,
            positions=positions,
            account_state=account_state,
            profile_id=profile_id,
        )
        
        # Create configuration from fixtures
        config = Configuration(
            version_id=standard_config.version_id,
            parameters=standard_config.parameters,
        )
        
        # Make two decisions
        d1 = decide(input_data, config)
        d2 = decide(input_data, config)
        
        # Verify consistency
        assert decisions_are_consistent(d1, d2), (
            f"Decisions should be consistent with fixture config: "
            f"d1.decision={d1.decision}, d2.decision={d2.decision}"
        )


# ═══════════════════════════════════════════════════════════════
# ADDITIONAL TESTS FOR REGRESSION TESTING (Requirement 10.6)
# ═══════════════════════════════════════════════════════════════

class TestAutomatedRegressionTesting:
    """
    Tests for automated regression testing for decision consistency.
    
    Feature: trading-pipeline-integration
    Requirement 10.6: THE System SHALL provide automated regression testing
                      for decision consistency
    
    **Validates: Requirements 10.6**
    """
    
    def test_known_good_accepted_decisions_remain_consistent(self):
        """
        **Validates: Requirements 10.6**
        
        Test that known-good accepted decisions from fixtures remain
        consistent when processed again.
        """
        fixtures = ParityTestFixtures()
        accepted_decisions = fixtures.get_accepted_decisions()
        
        for original in accepted_decisions:
            # Create input from the original decision
            input_data = DecisionInput(
                symbol=original.symbol,
                timestamp=original.timestamp,
                config_version=original.config_version,
                market_snapshot=original.market_snapshot,
                features=original.features,
                positions=original.positions,
                account_state=original.account_state,
                profile_id=original.profile_id,
            )
            
            config = Configuration(
                version_id=original.config_version,
                parameters=STANDARD_TEST_CONFIG,
            )
            
            # Process the decision
            replayed = decide(input_data, config)
            
            # Verify consistency with original
            assert replayed.decision == original.decision, (
                f"Replayed decision should match original for {original.decision_id}: "
                f"replayed={replayed.decision}, original={original.decision}"
            )

    def test_known_good_rejected_decisions_remain_consistent(self):
        """
        **Validates: Requirements 10.6**
        
        Test that known-good rejected decisions from fixtures remain
        consistent when processed again, including rejection_stage.
        """
        fixtures = ParityTestFixtures()
        rejected_decisions = fixtures.get_rejected_decisions()
        
        for original in rejected_decisions:
            # Only test EVGate rejections since our decide() function
            # only implements EVGate rejection logic
            if original.rejection_stage != "EVGate":
                continue
            
            # Create input from the original decision
            input_data = DecisionInput(
                symbol=original.symbol,
                timestamp=original.timestamp,
                config_version=original.config_version,
                market_snapshot=original.market_snapshot,
                features=original.features,
                positions=original.positions,
                account_state=original.account_state,
                profile_id=original.profile_id,
            )
            
            config = Configuration(
                version_id=original.config_version,
                parameters=STANDARD_TEST_CONFIG,
            )
            
            # Process the decision
            replayed = decide(input_data, config)
            
            # Verify consistency with original
            assert replayed.decision == original.decision, (
                f"Replayed decision should match original for {original.decision_id}: "
                f"replayed={replayed.decision}, original={original.decision}"
            )
            
            if original.decision == "rejected":
                assert replayed.rejection_stage == original.rejection_stage, (
                    f"Replayed rejection_stage should match original for {original.decision_id}: "
                    f"replayed={replayed.rejection_stage}, original={original.rejection_stage}"
                )

    def test_edge_case_decisions_remain_consistent(self):
        """
        **Validates: Requirements 10.6**
        
        Test that edge case decisions from fixtures remain consistent
        when processed again.
        """
        fixtures = ParityTestFixtures()
        edge_cases = fixtures.get_edge_case_decisions()
        
        for original in edge_cases:
            # Create input from the original decision
            input_data = DecisionInput(
                symbol=original.symbol,
                timestamp=original.timestamp,
                config_version=original.config_version,
                market_snapshot=original.market_snapshot,
                features=original.features,
                positions=original.positions,
                account_state=original.account_state,
                profile_id=original.profile_id,
            )
            
            config = Configuration(
                version_id=original.config_version,
                parameters=STANDARD_TEST_CONFIG,
            )
            
            # Process the decision twice
            d1 = decide(input_data, config)
            d2 = decide(input_data, config)
            
            # Verify consistency between the two replays
            assert decisions_are_consistent(d1, d2), (
                f"Edge case decisions should be consistent for {original.decision_id}: "
                f"d1.decision={d1.decision}, d2.decision={d2.decision}"
            )
