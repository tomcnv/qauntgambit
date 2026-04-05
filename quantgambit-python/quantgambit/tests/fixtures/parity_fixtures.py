"""Parity test fixtures for integration testing framework.

This module provides known-good decision sequences and test configurations
for verifying backtest/live parity in the trading pipeline integration.

Feature: trading-pipeline-integration
Requirements: 10.5 - THE System SHALL provide test fixtures with known-good
              decision sequences for regression testing

The fixtures include:
- Known-good accepted decisions with signals
- Known-good rejected decisions with specific rejection stages
- Edge case decisions (boundary conditions)
- Standard and modified test configurations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from quantgambit.integration.decision_recording import RecordedDecision
from quantgambit.integration.config_version import ConfigVersion


# =============================================================================
# Standard Test Configuration
# =============================================================================

# Standard configuration for baseline parity testing.
# This configuration represents the default live trading parameters
# that should be used as the baseline for parity comparisons.
STANDARD_TEST_CONFIG: Dict[str, Any] = {
    "ev_gate": {
        "ev_min": 0.0015,
        "ev_min_floor": 0.0005,
        "enabled": True,
    },
    "threshold_calculator": {
        "k": 0.5,
        "b": 0.001,
        "floor_bps": 5.0,
    },

    "fee_model": {
        "model_type": "flat",
        "maker_fee_bps": 2.0,
        "taker_fee_bps": 4.0,
    },
    "slippage_model": {
        "model_type": "flat",
        "base_slippage_bps": 1.0,
    },
    "pipeline_stages": [
        "DataReadiness",
        "GlobalGate",
        "EVGate",
        "ExecutionFeasibility",
        "Confirmation",
        "Arbitration",
    ],
    "risk_limits": {
        "max_position_size_usd": 10000.0,
        "max_daily_loss_pct": 0.02,
        "max_drawdown_pct": 0.05,
    },
}


# =============================================================================
# Modified Test Configuration (for parity testing)
# =============================================================================

# Modified configuration for testing parity enforcement.
# Contains intentional differences from STANDARD_TEST_CONFIG to verify
# that the parity checker correctly identifies configuration differences.
MODIFIED_TEST_CONFIG: Dict[str, Any] = {
    "ev_gate": {
        "ev_min": 0.002,  # Different from standard (0.0015)
        "ev_min_floor": 0.0005,
        "enabled": True,
    },
    "threshold_calculator": {
        "k": 0.6,  # Different from standard (0.5)
        "b": 0.001,
        "floor_bps": 5.0,
    },
    "fee_model": {
        "model_type": "flat",
        "maker_fee_bps": 2.0,
        "taker_fee_bps": 4.0,
    },
    "slippage_model": {
        "model_type": "flat",
        "base_slippage_bps": 1.5,  # Different from standard (1.0)
    },
    "pipeline_stages": [
        "DataReadiness",
        "GlobalGate",
        "EVGate",
        "ExecutionFeasibility",
        "Confirmation",
        "Arbitration",
    ],
    "risk_limits": {
        "max_position_size_usd": 10000.0,
        "max_daily_loss_pct": 0.02,
        "max_drawdown_pct": 0.05,
    },
}


# =============================================================================
# Parity Test Configuration (identical to standard)
# =============================================================================

# Configuration that should pass parity checks.
# This is identical to STANDARD_TEST_CONFIG and should be used
# when testing that parity verification passes correctly.
PARITY_TEST_CONFIG: Dict[str, Any] = {
    "ev_gate": {
        "ev_min": 0.0015,
        "ev_min_floor": 0.0005,
        "enabled": True,
    },
    "threshold_calculator": {
        "k": 0.5,
        "b": 0.001,
        "floor_bps": 5.0,
    },
    "fee_model": {
        "model_type": "flat",
        "maker_fee_bps": 2.0,
        "taker_fee_bps": 4.0,
    },
    "slippage_model": {
        "model_type": "flat",
        "base_slippage_bps": 1.0,
    },
    "pipeline_stages": [
        "DataReadiness",
        "GlobalGate",
        "EVGate",
        "ExecutionFeasibility",
        "Confirmation",
        "Arbitration",
    ],
    "risk_limits": {
        "max_position_size_usd": 10000.0,
        "max_daily_loss_pct": 0.02,
        "max_drawdown_pct": 0.05,
    },
}


# =============================================================================
# Known-Good Decision Sequences - Accepted Decisions
# =============================================================================

def _create_base_timestamp() -> datetime:
    """Create a base timestamp for test fixtures."""
    return datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _create_market_snapshot(
    price: float = 50000.0,
    bid: float = 49995.0,
    ask: float = 50005.0,
    spread_bps: float = 2.0,
    volume_24h: float = 1000000.0,
) -> Dict[str, Any]:
    """Create a market snapshot for test fixtures."""
    return {
        "price": price,
        "bid": bid,
        "ask": ask,
        "spread_bps": spread_bps,
        "volume_24h": volume_24h,
        "bid_depth_usd": 500000.0,
        "ask_depth_usd": 500000.0,
        "timestamp": _create_base_timestamp().isoformat(),
    }


def _create_features(
    ev: float = 0.002,
    trend_strength: float = 0.6,
    volatility: float = 0.02,
    momentum: float = 0.5,
) -> Dict[str, Any]:
    """Create features for test fixtures."""
    return {
        "ev": ev,
        "trend_strength": trend_strength,
        "volatility": volatility,
        "momentum": momentum,
        "signal_strength": 0.7,
        "regime": "trending",
    }


def _create_stage_results_accepted() -> List[Dict[str, Any]]:
    """Create stage results for an accepted decision."""
    return [
        {"stage": "DataReadiness", "passed": True, "reason": None},
        {"stage": "GlobalGate", "passed": True, "reason": None},
        {"stage": "EVGate", "passed": True, "ev": 0.002, "threshold": 0.0015},
        {"stage": "ExecutionFeasibility", "passed": True, "reason": None},
        {"stage": "Confirmation", "passed": True, "confidence": 0.85},
        {"stage": "Arbitration", "passed": True, "selected_signal": "long"},
    ]


def _create_signal(
    side: str = "long",
    entry_price: float = 50000.0,
    size: float = 0.1,
    stop_loss: float = 49500.0,
    take_profit: float = 51000.0,
) -> Dict[str, Any]:
    """Create a signal for test fixtures."""
    return {
        "side": side,
        "entry_price": entry_price,
        "size": size,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "confidence": 0.85,
        "ev": 0.002,
    }


# Known-good accepted decisions with signals
KNOWN_GOOD_ACCEPTED_DECISIONS: List[RecordedDecision] = [
    # Decision 1: Standard long entry with good EV
    RecordedDecision(
        decision_id="dec_accepted_001",
        timestamp=_create_base_timestamp(),
        symbol="BTCUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=50000.0),
        features=_create_features(ev=0.002, trend_strength=0.6),
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=_create_stage_results_accepted(),
        rejection_stage=None,
        rejection_reason=None,
        decision="accepted",
        signal=_create_signal(side="long", entry_price=50000.0),
        profile_id="micro_range_mean_reversion",
    ),
    # Decision 2: Short entry with high EV
    RecordedDecision(
        decision_id="dec_accepted_002",
        timestamp=_create_base_timestamp() + timedelta(minutes=5),
        symbol="ETHUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=3000.0, bid=2998.0, ask=3002.0),
        features=_create_features(ev=0.003, trend_strength=-0.7),
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=[
            {"stage": "DataReadiness", "passed": True, "reason": None},
            {"stage": "GlobalGate", "passed": True, "reason": None},
            {"stage": "EVGate", "passed": True, "ev": 0.003, "threshold": 0.0015},
            {"stage": "ExecutionFeasibility", "passed": True, "reason": None},
            {"stage": "Confirmation", "passed": True, "confidence": 0.9},
            {"stage": "Arbitration", "passed": True, "selected_signal": "short"},
        ],
        rejection_stage=None,
        rejection_reason=None,
        decision="accepted",
        signal=_create_signal(side="short", entry_price=3000.0, stop_loss=3050.0, take_profit=2900.0),
        profile_id="momentum_breakout",
    ),
    # Decision 3: Entry with existing position (adding to position)
    RecordedDecision(
        decision_id="dec_accepted_003",
        timestamp=_create_base_timestamp() + timedelta(minutes=10),
        symbol="BTCUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=50500.0),
        features=_create_features(ev=0.0025, trend_strength=0.65),
        positions=[{"symbol": "BTCUSDT", "side": "long", "size": 0.1, "entry_price": 50000.0}],
        account_state={"equity": 100500.0, "margin_used": 5000.0},
        stage_results=_create_stage_results_accepted(),
        rejection_stage=None,
        rejection_reason=None,
        decision="accepted",
        signal=_create_signal(side="long", entry_price=50500.0, size=0.05),
        profile_id="micro_range_mean_reversion",
    ),
]


# =============================================================================
# Known-Good Decision Sequences - Rejected Decisions
# =============================================================================

def _create_stage_results_rejected_ev() -> List[Dict[str, Any]]:
    """Create stage results for a decision rejected at EVGate."""
    return [
        {"stage": "DataReadiness", "passed": True, "reason": None},
        {"stage": "GlobalGate", "passed": True, "reason": None},
        {"stage": "EVGate", "passed": False, "ev": 0.0008, "threshold": 0.0015},
    ]


def _create_stage_results_rejected_data() -> List[Dict[str, Any]]:
    """Create stage results for a decision rejected at DataReadiness."""
    return [
        {"stage": "DataReadiness", "passed": False, "reason": "insufficient_candle_history"},
    ]


def _create_stage_results_rejected_global() -> List[Dict[str, Any]]:
    """Create stage results for a decision rejected at GlobalGate."""
    return [
        {"stage": "DataReadiness", "passed": True, "reason": None},
        {"stage": "GlobalGate", "passed": False, "reason": "risk_limit_exceeded"},
    ]


def _create_stage_results_rejected_feasibility() -> List[Dict[str, Any]]:
    """Create stage results for a decision rejected at ExecutionFeasibility."""
    return [
        {"stage": "DataReadiness", "passed": True, "reason": None},
        {"stage": "GlobalGate", "passed": True, "reason": None},
        {"stage": "EVGate", "passed": True, "ev": 0.002, "threshold": 0.0015},
        {"stage": "ExecutionFeasibility", "passed": False, "reason": "insufficient_liquidity"},
    ]


# Known-good rejected decisions with specific rejection stages
KNOWN_GOOD_REJECTED_DECISIONS: List[RecordedDecision] = [
    # Rejection 1: Low EV - rejected at EVGate
    RecordedDecision(
        decision_id="dec_rejected_001",
        timestamp=_create_base_timestamp() + timedelta(minutes=15),
        symbol="BTCUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=50000.0),
        features=_create_features(ev=0.0008, trend_strength=0.3),
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=_create_stage_results_rejected_ev(),
        rejection_stage="EVGate",
        rejection_reason="EV 0.0008 below threshold 0.0015",
        decision="rejected",
        signal=None,
        profile_id="micro_range_mean_reversion",
    ),
    # Rejection 2: Insufficient data - rejected at DataReadiness
    RecordedDecision(
        decision_id="dec_rejected_002",
        timestamp=_create_base_timestamp() + timedelta(minutes=20),
        symbol="SOLUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=100.0, bid=99.9, ask=100.1),
        features={},  # No features due to insufficient data
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=_create_stage_results_rejected_data(),
        rejection_stage="DataReadiness",
        rejection_reason="insufficient_candle_history",
        decision="rejected",
        signal=None,
        profile_id=None,
    ),
    # Rejection 3: Risk limit exceeded - rejected at GlobalGate
    RecordedDecision(
        decision_id="dec_rejected_003",
        timestamp=_create_base_timestamp() + timedelta(minutes=25),
        symbol="BTCUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=50000.0),
        features=_create_features(ev=0.002, trend_strength=0.6),
        positions=[
            {"symbol": "BTCUSDT", "side": "long", "size": 0.5, "entry_price": 49000.0},
            {"symbol": "ETHUSDT", "side": "long", "size": 5.0, "entry_price": 2900.0},
        ],
        account_state={"equity": 100000.0, "margin_used": 40000.0},
        stage_results=_create_stage_results_rejected_global(),
        rejection_stage="GlobalGate",
        rejection_reason="risk_limit_exceeded",
        decision="rejected",
        signal=None,
        profile_id="micro_range_mean_reversion",
    ),
    # Rejection 4: Insufficient liquidity - rejected at ExecutionFeasibility
    RecordedDecision(
        decision_id="dec_rejected_004",
        timestamp=_create_base_timestamp() + timedelta(minutes=30),
        symbol="BTCUSDT",
        config_version="live_test_v1",
        market_snapshot={
            **_create_market_snapshot(price=50000.0),
            "bid_depth_usd": 1000.0,  # Very low liquidity
            "ask_depth_usd": 1000.0,
        },
        features=_create_features(ev=0.002, trend_strength=0.6),
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=_create_stage_results_rejected_feasibility(),
        rejection_stage="ExecutionFeasibility",
        rejection_reason="insufficient_liquidity",
        decision="rejected",
        signal=None,
        profile_id="micro_range_mean_reversion",
    ),
]


# =============================================================================
# Known-Good Decision Sequences - Edge Cases
# =============================================================================

# Edge case decisions for boundary condition testing
KNOWN_GOOD_EDGE_CASE_DECISIONS: List[RecordedDecision] = [
    # Edge Case 1: EV exactly at threshold (should pass)
    RecordedDecision(
        decision_id="dec_edge_001",
        timestamp=_create_base_timestamp() + timedelta(minutes=35),
        symbol="BTCUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=50000.0),
        features=_create_features(ev=0.0015, trend_strength=0.5),  # Exactly at threshold
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=[
            {"stage": "DataReadiness", "passed": True, "reason": None},
            {"stage": "GlobalGate", "passed": True, "reason": None},
            {"stage": "EVGate", "passed": True, "ev": 0.0015, "threshold": 0.0015},
            {"stage": "ExecutionFeasibility", "passed": True, "reason": None},
            {"stage": "Confirmation", "passed": True, "confidence": 0.75},
            {"stage": "Arbitration", "passed": True, "selected_signal": "long"},
        ],
        rejection_stage=None,
        rejection_reason=None,
        decision="accepted",
        signal=_create_signal(side="long", entry_price=50000.0, size=0.05),
        profile_id="micro_range_mean_reversion",
    ),
    # Edge Case 2: EV just below threshold (should fail)
    RecordedDecision(
        decision_id="dec_edge_002",
        timestamp=_create_base_timestamp() + timedelta(minutes=40),
        symbol="BTCUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=50000.0),
        features=_create_features(ev=0.00149, trend_strength=0.5),  # Just below threshold
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=[
            {"stage": "DataReadiness", "passed": True, "reason": None},
            {"stage": "GlobalGate", "passed": True, "reason": None},
            {"stage": "EVGate", "passed": False, "ev": 0.00149, "threshold": 0.0015},
        ],
        rejection_stage="EVGate",
        rejection_reason="EV 0.00149 below threshold 0.0015",
        decision="rejected",
        signal=None,
        profile_id="micro_range_mean_reversion",
    ),
    # Edge Case 3: Maximum position size boundary
    RecordedDecision(
        decision_id="dec_edge_003",
        timestamp=_create_base_timestamp() + timedelta(minutes=45),
        symbol="BTCUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=50000.0),
        features=_create_features(ev=0.002, trend_strength=0.6),
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=_create_stage_results_accepted(),
        rejection_stage=None,
        rejection_reason=None,
        decision="accepted",
        signal=_create_signal(side="long", entry_price=50000.0, size=0.2),  # Max size
        profile_id="micro_range_mean_reversion",
    ),
    # Edge Case 4: Zero spread (unusual market condition)
    RecordedDecision(
        decision_id="dec_edge_004",
        timestamp=_create_base_timestamp() + timedelta(minutes=50),
        symbol="BTCUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=50000.0, bid=50000.0, ask=50000.0, spread_bps=0.0),
        features=_create_features(ev=0.002, trend_strength=0.6),
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=_create_stage_results_accepted(),
        rejection_stage=None,
        rejection_reason=None,
        decision="accepted",
        signal=_create_signal(side="long", entry_price=50000.0),
        profile_id="micro_range_mean_reversion",
    ),
    # Edge Case 5: Very high volatility
    RecordedDecision(
        decision_id="dec_edge_005",
        timestamp=_create_base_timestamp() + timedelta(minutes=55),
        symbol="BTCUSDT",
        config_version="live_test_v1",
        market_snapshot=_create_market_snapshot(price=50000.0, spread_bps=10.0),
        features=_create_features(ev=0.003, trend_strength=0.8, volatility=0.1),  # High volatility
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=_create_stage_results_accepted(),
        rejection_stage=None,
        rejection_reason=None,
        decision="accepted",
        signal=_create_signal(side="long", entry_price=50000.0, stop_loss=49000.0),  # Wider stop
        profile_id="momentum_breakout",
    ),
]


# =============================================================================
# Helper Functions
# =============================================================================

def create_test_decision(
    decision_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    symbol: str = "BTCUSDT",
    config_version: str = "live_test_v1",
    decision: str = "accepted",
    ev: float = 0.002,
    rejection_stage: Optional[str] = None,
    rejection_reason: Optional[str] = None,
    profile_id: Optional[str] = "micro_range_mean_reversion",
) -> RecordedDecision:
    """Create a test decision with customizable parameters.
    
    This helper function creates a RecordedDecision with sensible defaults
    that can be overridden for specific test scenarios.
    
    Feature: trading-pipeline-integration
    Requirements: 10.5
    
    Args:
        decision_id: Unique decision ID (auto-generated if None)
        timestamp: Decision timestamp (defaults to base timestamp)
        symbol: Trading symbol
        config_version: Configuration version ID
        decision: Decision outcome ("accepted", "rejected", "shadow")
        ev: Expected value for features
        rejection_stage: Stage that rejected (if rejected)
        rejection_reason: Reason for rejection (if rejected)
        profile_id: Trading profile ID
        
    Returns:
        RecordedDecision instance
    """
    if decision_id is None:
        decision_id = f"dec_test_{uuid4().hex[:8]}"
    
    if timestamp is None:
        timestamp = _create_base_timestamp()
    
    # Create appropriate stage results based on decision
    if decision == "accepted":
        stage_results = _create_stage_results_accepted()
        signal = _create_signal()
    else:
        if rejection_stage == "EVGate":
            stage_results = _create_stage_results_rejected_ev()
        elif rejection_stage == "DataReadiness":
            stage_results = _create_stage_results_rejected_data()
        elif rejection_stage == "GlobalGate":
            stage_results = _create_stage_results_rejected_global()
        elif rejection_stage == "ExecutionFeasibility":
            stage_results = _create_stage_results_rejected_feasibility()
        else:
            stage_results = _create_stage_results_rejected_ev()
            rejection_stage = "EVGate"
            rejection_reason = rejection_reason or "EV below threshold"
        signal = None
    
    return RecordedDecision(
        decision_id=decision_id,
        timestamp=timestamp,
        symbol=symbol,
        config_version=config_version,
        market_snapshot=_create_market_snapshot(),
        features=_create_features(ev=ev),
        positions=[],
        account_state={"equity": 100000.0, "margin_used": 0.0},
        stage_results=stage_results,
        rejection_stage=rejection_stage,
        rejection_reason=rejection_reason,
        decision=decision,
        signal=signal,
        profile_id=profile_id,
    )


def create_test_config(
    version_id: Optional[str] = None,
    created_by: str = "live",
    parameters: Optional[Dict[str, Any]] = None,
) -> ConfigVersion:
    """Create a test configuration version.
    
    This helper function creates a ConfigVersion with sensible defaults
    that can be overridden for specific test scenarios.
    
    Feature: trading-pipeline-integration
    Requirements: 10.5
    
    Args:
        version_id: Configuration version ID (auto-generated if None)
        created_by: Source of configuration ("live", "backtest", "optimizer")
        parameters: Configuration parameters (defaults to STANDARD_TEST_CONFIG)
        
    Returns:
        ConfigVersion instance
    """
    if version_id is None:
        version_id = f"{created_by}_test_{uuid4().hex[:8]}"
    
    if parameters is None:
        parameters = STANDARD_TEST_CONFIG.copy()
    
    return ConfigVersion.create(
        version_id=version_id,
        created_by=created_by,
        parameters=parameters,
        created_at=_create_base_timestamp(),
    )


def create_decision_sequence(
    count: int = 10,
    accepted_ratio: float = 0.5,
    symbol: str = "BTCUSDT",
    config_version: str = "live_test_v1",
    start_timestamp: Optional[datetime] = None,
    interval_minutes: int = 5,
) -> List[RecordedDecision]:
    """Create a sequence of test decisions.
    
    Generates a sequence of decisions with a specified ratio of accepted
    to rejected decisions, useful for testing decision consistency.
    
    Feature: trading-pipeline-integration
    Requirements: 10.5
    
    Args:
        count: Number of decisions to generate
        accepted_ratio: Ratio of accepted decisions (0.0 to 1.0)
        symbol: Trading symbol for all decisions
        config_version: Configuration version ID
        start_timestamp: Starting timestamp (defaults to base timestamp)
        interval_minutes: Minutes between decisions
        
    Returns:
        List of RecordedDecision instances
    """
    if start_timestamp is None:
        start_timestamp = _create_base_timestamp()
    
    decisions: List[RecordedDecision] = []
    accepted_count = int(count * accepted_ratio)
    
    for i in range(count):
        timestamp = start_timestamp + timedelta(minutes=i * interval_minutes)
        is_accepted = i < accepted_count
        
        if is_accepted:
            ev = 0.002 + (i * 0.0001)  # Varying EV above threshold
            decision = create_test_decision(
                decision_id=f"dec_seq_{i:03d}",
                timestamp=timestamp,
                symbol=symbol,
                config_version=config_version,
                decision="accepted",
                ev=ev,
            )
        else:
            ev = 0.0008 + (i * 0.00005)  # Varying EV below threshold
            decision = create_test_decision(
                decision_id=f"dec_seq_{i:03d}",
                timestamp=timestamp,
                symbol=symbol,
                config_version=config_version,
                decision="rejected",
                ev=ev,
                rejection_stage="EVGate",
                rejection_reason=f"EV {ev:.5f} below threshold 0.0015",
            )
        
        decisions.append(decision)
    
    return decisions


def get_expected_outcome(
    ev: float,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[str]]:
    """Get the expected decision outcome for a given EV.
    
    Determines whether a decision should be accepted or rejected based
    on the EV value and configuration thresholds.
    
    Feature: trading-pipeline-integration
    Requirements: 10.5
    
    Args:
        ev: Expected value
        config: Configuration dictionary (defaults to STANDARD_TEST_CONFIG)
        
    Returns:
        Tuple of (decision, rejection_stage) where rejection_stage is None
        if decision is "accepted"
    """
    if config is None:
        config = STANDARD_TEST_CONFIG
    
    ev_min = config.get("ev_gate", {}).get("ev_min", 0.0015)
    
    if ev >= ev_min:
        return ("accepted", None)
    else:
        return ("rejected", "EVGate")


# =============================================================================
# Fixture Class for Organized Access
# =============================================================================

@dataclass
class ParityTestFixtures:
    """Container class for parity test fixtures.
    
    Provides organized access to all parity test fixtures including
    decision sequences, configurations, and helper methods.
    
    Feature: trading-pipeline-integration
    Requirements: 10.5
    
    Example:
        >>> fixtures = ParityTestFixtures()
        >>> accepted = fixtures.get_accepted_decisions()
        >>> rejected = fixtures.get_rejected_decisions()
        >>> config = fixtures.get_standard_config()
    """
    
    @staticmethod
    def get_accepted_decisions() -> List[RecordedDecision]:
        """Get all known-good accepted decisions.
        
        Returns:
            List of RecordedDecision instances that should be accepted
        """
        return KNOWN_GOOD_ACCEPTED_DECISIONS.copy()
    
    @staticmethod
    def get_rejected_decisions() -> List[RecordedDecision]:
        """Get all known-good rejected decisions.
        
        Returns:
            List of RecordedDecision instances that should be rejected
        """
        return KNOWN_GOOD_REJECTED_DECISIONS.copy()
    
    @staticmethod
    def get_edge_case_decisions() -> List[RecordedDecision]:
        """Get all edge case decisions.
        
        Returns:
            List of RecordedDecision instances for boundary testing
        """
        return KNOWN_GOOD_EDGE_CASE_DECISIONS.copy()
    
    @staticmethod
    def get_all_decisions() -> List[RecordedDecision]:
        """Get all known-good decisions.
        
        Returns:
            Combined list of all decision fixtures
        """
        return (
            KNOWN_GOOD_ACCEPTED_DECISIONS.copy()
            + KNOWN_GOOD_REJECTED_DECISIONS.copy()
            + KNOWN_GOOD_EDGE_CASE_DECISIONS.copy()
        )
    
    @staticmethod
    def get_standard_config() -> ConfigVersion:
        """Get the standard test configuration.
        
        Returns:
            ConfigVersion with standard parameters
        """
        return create_test_config(
            version_id="live_test_v1",
            created_by="live",
            parameters=STANDARD_TEST_CONFIG,
        )
    
    @staticmethod
    def get_modified_config() -> ConfigVersion:
        """Get the modified test configuration.
        
        Returns:
            ConfigVersion with modified parameters for parity testing
        """
        return create_test_config(
            version_id="backtest_test_v1",
            created_by="backtest",
            parameters=MODIFIED_TEST_CONFIG,
        )
    
    @staticmethod
    def get_parity_config() -> ConfigVersion:
        """Get the parity test configuration (identical to standard).
        
        Returns:
            ConfigVersion with parameters identical to standard
        """
        return create_test_config(
            version_id="parity_test_v1",
            created_by="backtest",
            parameters=PARITY_TEST_CONFIG,
        )
    
    @staticmethod
    def get_decisions_by_rejection_stage(stage: str) -> List[RecordedDecision]:
        """Get decisions rejected at a specific stage.
        
        Args:
            stage: Rejection stage name (e.g., "EVGate", "DataReadiness")
            
        Returns:
            List of decisions rejected at the specified stage
        """
        return [
            d for d in KNOWN_GOOD_REJECTED_DECISIONS
            if d.rejection_stage == stage
        ]
    
    @staticmethod
    def get_decisions_by_symbol(symbol: str) -> List[RecordedDecision]:
        """Get decisions for a specific symbol.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            
        Returns:
            List of decisions for the specified symbol
        """
        all_decisions = (
            KNOWN_GOOD_ACCEPTED_DECISIONS
            + KNOWN_GOOD_REJECTED_DECISIONS
            + KNOWN_GOOD_EDGE_CASE_DECISIONS
        )
        return [d for d in all_decisions if d.symbol == symbol]
    
    @staticmethod
    def create_custom_sequence(
        count: int = 10,
        accepted_ratio: float = 0.5,
        **kwargs,
    ) -> List[RecordedDecision]:
        """Create a custom decision sequence.
        
        Args:
            count: Number of decisions
            accepted_ratio: Ratio of accepted decisions
            **kwargs: Additional arguments passed to create_decision_sequence
            
        Returns:
            List of RecordedDecision instances
        """
        return create_decision_sequence(
            count=count,
            accepted_ratio=accepted_ratio,
            **kwargs,
        )
    
    @staticmethod
    def get_config_diff_expected() -> Dict[str, Tuple[Any, Any]]:
        """Get expected configuration differences between standard and modified.
        
        Returns:
            Dictionary mapping parameter paths to (standard_value, modified_value)
        """
        return {
            "ev_gate.ev_min": (0.0015, 0.002),
            "threshold_calculator.k": (0.5, 0.6),
            "slippage_model.base_slippage_bps": (1.0, 1.5),
        }
