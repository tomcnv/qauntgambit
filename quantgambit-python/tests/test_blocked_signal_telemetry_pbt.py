"""
Property-based tests for BlockedSignalTelemetry completeness.

Feature: trading-loss-fixes
Tests correctness properties for:
- Property 7: Blocked Signal Telemetry Completeness

**Validates: Requirements 6.1, 6.2**
"""

import pytest
import asyncio
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, Any, Optional

from quantgambit.observability.blocked_signal_telemetry import (
    BlockedSignalTelemetry,
    BlockedSignalRecord,
    BlockedSignalRepository,
    VALID_GATES,
    BLOCKED_SIGNAL_RETENTION_SECONDS,
)


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Symbols
symbol = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"])

# Directions
direction = st.sampled_from(["long", "short"])

# Strategy IDs
strategy_id = st.sampled_from([
    "mean_reversion_fade",
    "trend_following",
    "momentum_breakout",
    "scalping",
])

# Confidence values in 0-1 range
confidence_value = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Rejection reasons (must be valid gate names)
rejection_reason = st.sampled_from([
    "low_confidence",
    "confidence_gate",
    "strategy_trend_mismatch",
    "fee_trap",
    "session_mismatch",
    "execution_throttle",
    "cooldown",
    "hysteresis",
    "fee_check",
    "hourly_limit",
])

# Rejection stages
rejection_stage = st.sampled_from([
    "confidence_gate",
    "strategy_trend_alignment",
    "fee_aware_entry",
    "session_filter",
    "execution_throttle",
])

# Profile IDs
profile_id = st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('L', 'N', 'P')))

# Snapshot metrics (simplified)
snapshot_metrics = st.fixed_dictionaries({
    "trend": st.sampled_from(["up", "down", "flat"]),
    "volatility": st.sampled_from(["low", "medium", "high"]),
    "session": st.sampled_from(["asia", "europe", "us", "overnight"]),
})

# Optional fee trap fields
expected_edge_usd = st.one_of(st.none(), st.floats(min_value=0.0, max_value=1000.0, allow_nan=False))
round_trip_fee_usd = st.one_of(st.none(), st.floats(min_value=0.0, max_value=100.0, allow_nan=False))

# Optional trend fields
trend = st.one_of(st.none(), st.sampled_from(["up", "down", "flat"]))
signal_side = st.one_of(st.none(), st.sampled_from(["long", "short"]))

# Optional session fields
session = st.one_of(st.none(), st.sampled_from(["asia", "europe", "us", "overnight"]))
utc_hour = st.one_of(st.none(), st.integers(min_value=0, max_value=23))


# =============================================================================
# Property 7: Blocked Signal Telemetry Completeness
# Feature: trading-loss-fixes, Property 7: Blocked Signal Telemetry Completeness
# Validates: Requirements 6.1, 6.2
# =============================================================================

@settings(max_examples=100)
@given(
    sym=symbol,
    dir=direction,
    strat_id=strategy_id,
    conf=confidence_value,
    rej_reason=rejection_reason,
    rej_stage=rejection_stage,
    prof_id=profile_id,
    snap_metrics=snapshot_metrics,
)
def test_property_7_blocked_signal_record_contains_required_fields(
    sym: str,
    dir: str,
    strat_id: str,
    conf: float,
    rej_reason: str,
    rej_stage: str,
    prof_id: str,
    snap_metrics: Dict[str, Any],
):
    """
    Property 7: Blocked Signal Telemetry Completeness
    
    *For any* rejected signal, the blocked signal record SHALL contain:
    timestamp, symbol, direction, confidence, rejection_reason, profile_id, 
    and snapshot_metrics.
    
    **Validates: Requirements 6.1, 6.2**
    """
    # Create a BlockedSignalRecord using the factory method
    record = BlockedSignalRecord.create(
        symbol=sym,
        direction=dir,
        strategy_id=strat_id,
        confidence=conf,
        rejection_reason=rej_reason,
        rejection_stage=rej_stage,
        profile_id=prof_id,
        snapshot_metrics=snap_metrics,
    )
    
    # Property: All required fields are present and have correct values
    assert record.id is not None and len(record.id) > 0, \
        "Record must have a non-empty ID"
    assert record.timestamp > 0, \
        "Record must have a positive timestamp"
    assert record.symbol == sym, \
        f"Symbol should be {sym}, got {record.symbol}"
    assert record.direction == dir, \
        f"Direction should be {dir}, got {record.direction}"
    assert record.strategy_id == strat_id, \
        f"Strategy ID should be {strat_id}, got {record.strategy_id}"
    assert record.confidence == conf, \
        f"Confidence should be {conf}, got {record.confidence}"
    assert record.rejection_reason == rej_reason, \
        f"Rejection reason should be {rej_reason}, got {record.rejection_reason}"
    assert record.rejection_stage == rej_stage, \
        f"Rejection stage should be {rej_stage}, got {record.rejection_stage}"
    assert record.profile_id == prof_id, \
        f"Profile ID should be {prof_id}, got {record.profile_id}"
    assert record.snapshot_metrics == snap_metrics, \
        f"Snapshot metrics should be {snap_metrics}, got {record.snapshot_metrics}"


@settings(max_examples=100)
@given(
    sym=symbol,
    dir=direction,
    strat_id=strategy_id,
    conf=confidence_value,
    rej_reason=rejection_reason,
    rej_stage=rejection_stage,
    prof_id=profile_id,
    snap_metrics=snapshot_metrics,
)
def test_property_7_blocked_signal_record_to_dict_completeness(
    sym: str,
    dir: str,
    strat_id: str,
    conf: float,
    rej_reason: str,
    rej_stage: str,
    prof_id: str,
    snap_metrics: Dict[str, Any],
):
    """
    Property 7: Blocked Signal Record Serialization Completeness
    
    *For any* BlockedSignalRecord, converting to dict SHALL preserve all
    required fields for database persistence.
    
    **Validates: Requirements 6.1, 6.2**
    """
    # Create a BlockedSignalRecord
    record = BlockedSignalRecord.create(
        symbol=sym,
        direction=dir,
        strategy_id=strat_id,
        confidence=conf,
        rejection_reason=rej_reason,
        rejection_stage=rej_stage,
        profile_id=prof_id,
        snapshot_metrics=snap_metrics,
    )
    
    # Convert to dict
    record_dict = record.to_dict()
    
    # Property: All required fields are present in the dict
    required_fields = [
        "id", "timestamp", "symbol", "direction", "strategy_id",
        "confidence", "rejection_reason", "rejection_stage",
        "profile_id", "snapshot_metrics"
    ]
    
    for field in required_fields:
        assert field in record_dict, \
            f"Required field '{field}' missing from record dict"
    
    # Property: Values match the original record
    assert record_dict["symbol"] == sym
    assert record_dict["direction"] == dir
    assert record_dict["strategy_id"] == strat_id
    assert record_dict["confidence"] == conf
    assert record_dict["rejection_reason"] == rej_reason
    assert record_dict["rejection_stage"] == rej_stage
    assert record_dict["profile_id"] == prof_id
    assert record_dict["snapshot_metrics"] == snap_metrics


@settings(max_examples=100)
@given(
    sym=symbol,
    dir=direction,
    strat_id=strategy_id,
    conf=confidence_value,
    rej_stage=rejection_stage,
    prof_id=profile_id,
    snap_metrics=snapshot_metrics,
    edge_usd=expected_edge_usd,
    fee_usd=round_trip_fee_usd,
)
def test_property_7_fee_trap_specific_fields(
    sym: str,
    dir: str,
    strat_id: str,
    conf: float,
    rej_stage: str,
    prof_id: str,
    snap_metrics: Dict[str, Any],
    edge_usd: Optional[float],
    fee_usd: Optional[float],
):
    """
    Property 7: Fee Trap Specific Fields
    
    *For any* fee_trap rejection, the record SHALL include expected_edge_usd
    and round_trip_fee_usd fields when provided.
    
    **Validates: Requirements 6.2**
    """
    # Create a BlockedSignalRecord with fee trap fields
    record = BlockedSignalRecord.create(
        symbol=sym,
        direction=dir,
        strategy_id=strat_id,
        confidence=conf,
        rejection_reason="fee_trap",
        rejection_stage=rej_stage,
        profile_id=prof_id,
        snapshot_metrics=snap_metrics,
        expected_edge_usd=edge_usd,
        round_trip_fee_usd=fee_usd,
    )
    
    # Property: Fee trap fields are preserved
    assert record.expected_edge_usd == edge_usd, \
        f"Expected edge USD should be {edge_usd}, got {record.expected_edge_usd}"
    assert record.round_trip_fee_usd == fee_usd, \
        f"Round trip fee USD should be {fee_usd}, got {record.round_trip_fee_usd}"
    
    # Property: Fields are in dict representation
    record_dict = record.to_dict()
    assert record_dict["expected_edge_usd"] == edge_usd
    assert record_dict["round_trip_fee_usd"] == fee_usd


@settings(max_examples=100)
@given(
    sym=symbol,
    dir=direction,
    strat_id=strategy_id,
    conf=confidence_value,
    rej_stage=rejection_stage,
    prof_id=profile_id,
    snap_metrics=snapshot_metrics,
    trnd=trend,
    sig_side=signal_side,
)
def test_property_7_strategy_trend_specific_fields(
    sym: str,
    dir: str,
    strat_id: str,
    conf: float,
    rej_stage: str,
    prof_id: str,
    snap_metrics: Dict[str, Any],
    trnd: Optional[str],
    sig_side: Optional[str],
):
    """
    Property 7: Strategy-Trend Specific Fields
    
    *For any* strategy_trend_mismatch rejection, the record SHALL include
    trend and signal_side fields when provided.
    
    **Validates: Requirements 6.2**
    """
    # Create a BlockedSignalRecord with strategy-trend fields
    record = BlockedSignalRecord.create(
        symbol=sym,
        direction=dir,
        strategy_id=strat_id,
        confidence=conf,
        rejection_reason="strategy_trend_mismatch",
        rejection_stage=rej_stage,
        profile_id=prof_id,
        snapshot_metrics=snap_metrics,
        trend=trnd,
        signal_side=sig_side,
    )
    
    # Property: Strategy-trend fields are preserved
    assert record.trend == trnd, \
        f"Trend should be {trnd}, got {record.trend}"
    assert record.signal_side == sig_side, \
        f"Signal side should be {sig_side}, got {record.signal_side}"
    
    # Property: Fields are in dict representation
    record_dict = record.to_dict()
    assert record_dict["trend"] == trnd
    assert record_dict["signal_side"] == sig_side


@settings(max_examples=100)
@given(
    sym=symbol,
    dir=direction,
    strat_id=strategy_id,
    conf=confidence_value,
    rej_stage=rejection_stage,
    prof_id=profile_id,
    snap_metrics=snapshot_metrics,
    sess=session,
    hour=utc_hour,
)
def test_property_7_session_specific_fields(
    sym: str,
    dir: str,
    strat_id: str,
    conf: float,
    rej_stage: str,
    prof_id: str,
    snap_metrics: Dict[str, Any],
    sess: Optional[str],
    hour: Optional[int],
):
    """
    Property 7: Session Specific Fields
    
    *For any* session_mismatch rejection, the record SHALL include
    session and utc_hour fields when provided.
    
    **Validates: Requirements 6.2**
    """
    # Create a BlockedSignalRecord with session fields
    record = BlockedSignalRecord.create(
        symbol=sym,
        direction=dir,
        strategy_id=strat_id,
        confidence=conf,
        rejection_reason="session_mismatch",
        rejection_stage=rej_stage,
        profile_id=prof_id,
        snapshot_metrics=snap_metrics,
        session=sess,
        utc_hour=hour,
    )
    
    # Property: Session fields are preserved
    assert record.session == sess, \
        f"Session should be {sess}, got {record.session}"
    assert record.utc_hour == hour, \
        f"UTC hour should be {hour}, got {record.utc_hour}"
    
    # Property: Fields are in dict representation
    record_dict = record.to_dict()
    assert record_dict["session"] == sess
    assert record_dict["utc_hour"] == hour


@settings(max_examples=100)
@given(
    sym=symbol,
    dir=direction,
    strat_id=strategy_id,
    conf=confidence_value,
    rej_reason=rejection_reason,
    rej_stage=rejection_stage,
    prof_id=profile_id,
    snap_metrics=snapshot_metrics,
)
def test_property_7_repository_persistence_completeness(
    sym: str,
    dir: str,
    strat_id: str,
    conf: float,
    rej_reason: str,
    rej_stage: str,
    prof_id: str,
    snap_metrics: Dict[str, Any],
):
    """
    Property 7: Repository Persistence Completeness
    
    *For any* BlockedSignalRecord persisted to the repository, the record
    SHALL be retrievable with all fields intact.
    
    **Validates: Requirements 6.1, 6.2**
    """
    # Create an in-memory repository
    repository = BlockedSignalRepository(connection_string=None)
    
    # Create a BlockedSignalRecord
    record = BlockedSignalRecord.create(
        symbol=sym,
        direction=dir,
        strategy_id=strat_id,
        confidence=conf,
        rejection_reason=rej_reason,
        rejection_stage=rej_stage,
        profile_id=prof_id,
        snapshot_metrics=snap_metrics,
    )
    
    # Persist the record (use sync method for in-memory)
    result = repository._persist_to_memory(record)
    
    # Property: Persistence succeeds
    assert result is True, "Persistence should succeed"
    
    # Property: Record is retrievable
    records = repository.get_in_memory_records()
    assert len(records) >= 1, "At least one record should be stored"
    
    # Find our record
    stored_record = next((r for r in records if r.id == record.id), None)
    assert stored_record is not None, "Our record should be in storage"
    
    # Property: All fields are preserved
    assert stored_record.symbol == sym
    assert stored_record.direction == dir
    assert stored_record.strategy_id == strat_id
    assert stored_record.confidence == conf
    assert stored_record.rejection_reason == rej_reason
    assert stored_record.rejection_stage == rej_stage
    assert stored_record.profile_id == prof_id
    assert stored_record.snapshot_metrics == snap_metrics


@settings(max_examples=100)
@given(
    sym=symbol,
    dir=direction,
    strat_id=strategy_id,
    conf=confidence_value,
    rej_reason=rejection_reason,
    rej_stage=rejection_stage,
    prof_id=profile_id,
    snap_metrics=snapshot_metrics,
)
def test_property_7_telemetry_records_blocked_signal(
    sym: str,
    dir: str,
    strat_id: str,
    conf: float,
    rej_reason: str,
    rej_stage: str,
    prof_id: str,
    snap_metrics: Dict[str, Any],
):
    """
    Property 7: Telemetry Records Blocked Signal
    
    *For any* BlockedSignalRecord recorded via telemetry, the telemetry
    system SHALL track the rejection and persist the record.
    
    **Validates: Requirements 6.1, 6.2**
    """
    # Create repository and telemetry
    repository = BlockedSignalRepository(connection_string=None)
    telemetry = BlockedSignalTelemetry(repository=repository)
    
    # Create a BlockedSignalRecord
    record = BlockedSignalRecord.create(
        symbol=sym,
        direction=dir,
        strategy_id=strat_id,
        confidence=conf,
        rejection_reason=rej_reason,
        rejection_stage=rej_stage,
        profile_id=prof_id,
        snapshot_metrics=snap_metrics,
    )
    
    # Record via telemetry (use asyncio.run for proper event loop handling)
    async def record_signal():
        return await telemetry.record_blocked_signal(record)
    
    result = asyncio.run(record_signal())
    
    # Property: Recording succeeds
    assert result is True, "Recording should succeed"
    
    # Property: Record is in repository
    records = repository.get_in_memory_records()
    stored_record = next((r for r in records if r.id == record.id), None)
    assert stored_record is not None, "Record should be persisted to repository"


@settings(max_examples=50)
@given(
    num_records=st.integers(min_value=1, max_value=10),
    rej_reason=rejection_reason,
)
def test_property_7_counts_by_reason_accuracy(
    num_records: int,
    rej_reason: str,
):
    """
    Property 7: Counts by Reason Accuracy
    
    *For any* set of blocked signals with the same rejection reason,
    the count returned by get_counts_by_reason SHALL equal the number
    of records persisted.
    
    **Validates: Requirements 6.1**
    """
    # Create repository
    repository = BlockedSignalRepository(connection_string=None)
    
    # Persist multiple records with the same rejection reason (use sync method)
    for i in range(num_records):
        record = BlockedSignalRecord.create(
            symbol=f"TEST{i}USDT",
            direction="long",
            strategy_id="test_strategy",
            confidence=0.5,
            rejection_reason=rej_reason,
            rejection_stage="test_stage",
            profile_id=f"profile_{i}",
            snapshot_metrics={},
        )
        repository._persist_to_memory(record)
    
    # Get counts
    counts = repository._get_memory_counts_by_reason()
    
    # Property: Count matches number of records
    assert counts.get(rej_reason, 0) == num_records, \
        f"Count for {rej_reason} should be {num_records}, got {counts.get(rej_reason, 0)}"
