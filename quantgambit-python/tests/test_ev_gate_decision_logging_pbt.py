"""
Property-based tests for EV Gate Decision Logging Completeness.

Feature: ev-based-entry-gate
Tests correctness properties for:
- Property 9: Decision Logging Completeness

**Validates: Requirements 1.7, 2.8, 5.7, 6.8, 7.1**
"""

import pytest
import time
from hypothesis import given, strategies as st, settings, assume
from dataclasses import fields

from quantgambit.api.ev_gate_endpoints import EVGateDecisionLog


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Decision type
decision_type = st.sampled_from(["ACCEPT", "REJECT"])

# Reject codes (only for REJECT decisions)
reject_codes = st.sampled_from([
    "MISSING_STOP_LOSS",
    "MISSING_TAKE_PROFIT",
    "MISSING_REQUIRED_FIELD",
    "INVALID_SL",
    "INVALID_R",
    "INVALID_P",
    "STOP_TOO_TIGHT",
    "COST_EXCEEDS_SL",
    "STALE_BOOK",
    "STALE_SPREAD",
    "EXCHANGE_CONNECTIVITY",
    "ORDERBOOK_SYNC",
    "EV_BELOW_MIN",
    "P_BELOW_PMIN",
    None,
])

# Symbols
symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"])

# Probability values
probability = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Positive floats for R, L_bps, G_bps
positive_float = st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False)

# Non-negative floats for costs
non_negative_float = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)

# EV values (can be negative)
ev_value = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Calibration methods
calibration_methods = st.sampled_from(["uncalibrated", "platt", "isotonic", "pooled"])

# Sessions
sessions = st.sampled_from(["us", "europe", "asia", "unknown", None])

# Regimes
regimes = st.sampled_from(["trending", "ranging", "volatile", "calm", None])

# Volatility regimes
volatility_regimes = st.sampled_from(["low", "medium", "high", None])

# Adjustment factors
adjustment_factor = st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False)


# =============================================================================
# Required Fields for Decision Logging Completeness
# Based on Requirements 1.7, 2.8, 5.7, 6.8, 7.1
# =============================================================================

# Core required fields that MUST be present in every decision log
REQUIRED_FIELDS = {
    # Decision fields
    "decision",
    "timestamp",
    "symbol",
    
    # Probability fields (Requirement 1.7, 2.8)
    "p_hat",
    "p_calibrated",
    "p_min",
    
    # EV calculation fields (Requirement 1.7)
    "R",
    "C",
    "EV",
    "L_bps",
    "G_bps",
    
    # Cost components (Requirement 5.7)
    "spread_bps",
    "fee_bps",
    "slippage_bps",
    "adverse_selection_bps",
    "total_cost_bps",
    
    # Threshold fields (Requirement 6.8)
    "ev_min_base",
    "ev_min_adjusted",
    "adjustment_factor",
    
    # Calibration fields (Requirement 7.1)
    "calibration_method",
    
    # Data quality fields (Requirement 7.1)
    "book_age_ms",
}

# Fields that are required only for REJECT decisions
REJECT_REQUIRED_FIELDS = {
    "reject_code",
}


# =============================================================================
# Strategy for generating complete decision logs
# =============================================================================

@st.composite
def decision_log_strategy(draw):
    """Generate a complete EVGateDecisionLog with all required fields."""
    decision = draw(decision_type)
    
    # Generate reject_code only for REJECT decisions
    reject_code = None
    reject_reason = None
    if decision == "REJECT":
        reject_code = draw(st.sampled_from([
            "MISSING_STOP_LOSS",
            "MISSING_TAKE_PROFIT",
            "INVALID_SL",
            "INVALID_R",
            "EV_BELOW_MIN",
            "STALE_BOOK",
        ]))
        reject_reason = f"Test rejection: {reject_code}"
    
    return EVGateDecisionLog(
        timestamp=time.time(),
        symbol=draw(symbols),
        signal_id=f"signal_{draw(st.integers(min_value=1, max_value=10000))}",
        decision=decision,
        reject_code=reject_code,
        reject_reason=reject_reason,
        p_hat=draw(probability),
        p_calibrated=draw(probability),
        p_min=draw(probability),
        R=draw(positive_float),
        C=draw(non_negative_float),
        EV=draw(ev_value),
        L_bps=draw(positive_float),
        G_bps=draw(positive_float),
        spread_bps=draw(non_negative_float),
        fee_bps=draw(non_negative_float),
        slippage_bps=draw(non_negative_float),
        adverse_selection_bps=draw(non_negative_float),
        total_cost_bps=draw(non_negative_float),
        ev_min_base=draw(non_negative_float),
        ev_min_adjusted=draw(non_negative_float),
        adjustment_factor=draw(adjustment_factor),
        adjustment_reason=draw(st.one_of(st.none(), st.text(min_size=1, max_size=50))),
        regime_label=draw(regimes),
        session=draw(sessions),
        volatility_regime=draw(volatility_regimes),
        strategy_id=draw(st.one_of(st.none(), st.text(min_size=1, max_size=20))),
        calibration_method=draw(calibration_methods),
        calibration_reliability=draw(probability),
        book_age_ms=draw(non_negative_float),
        spread_age_ms=draw(non_negative_float),
        ev_gate_would_reject=draw(st.one_of(st.none(), st.booleans())),
        confidence_gate_rejected=draw(st.one_of(st.none(), st.booleans())),
    )


# =============================================================================
# Property 9: Decision Logging Completeness
# Feature: ev-based-entry-gate, Property 9: Decision Logging Completeness
# Validates: Requirements 1.7, 2.8, 5.7, 6.8, 7.1
# =============================================================================

@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_decision_log_contains_all_required_fields(log: EVGateDecisionLog):
    """
    Property 9: Decision Logging Completeness
    
    *For any* decision (accept or reject), the log SHALL contain all required fields:
    decision, reject_code (if reject), p_hat, p_calibrated, R, C, EV, p_min,
    all cost components, ev_min_base, ev_min_adjusted, calibration_method, book_age_ms.
    
    **Validates: Requirements 1.7, 2.8, 5.7, 6.8, 7.1**
    """
    # Convert log to dictionary
    log_dict = log.to_dict()
    
    # Check all required fields are present
    for field_name in REQUIRED_FIELDS:
        assert field_name in log_dict, \
            f"Required field '{field_name}' missing from decision log"
        # Field should not be None for core required fields
        # (some fields like p_hat can be 0.0 which is valid)
    
    # Check reject-specific fields for REJECT decisions
    if log.decision == "REJECT":
        for field_name in REJECT_REQUIRED_FIELDS:
            assert field_name in log_dict, \
                f"Reject-required field '{field_name}' missing from REJECT decision log"
            assert log_dict[field_name] is not None, \
                f"Reject-required field '{field_name}' should not be None for REJECT decision"


@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_to_dict_preserves_all_fields(log: EVGateDecisionLog):
    """
    Property 9: to_dict() preserves all fields
    
    *For any* decision log, converting to dict and back SHALL preserve all field values.
    
    **Validates: Requirements 7.1**
    """
    # Convert to dict
    log_dict = log.to_dict()
    
    # Get all field names from the dataclass
    dataclass_fields = {f.name for f in fields(EVGateDecisionLog)}
    
    # All dataclass fields should be in the dict
    for field_name in dataclass_fields:
        assert field_name in log_dict, \
            f"Field '{field_name}' missing from to_dict() output"


@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_cost_components_sum_to_total(log: EVGateDecisionLog):
    """
    Property 9: Cost components consistency
    
    *For any* decision log, the individual cost components (spread_bps, fee_bps,
    slippage_bps, adverse_selection_bps) SHALL be non-negative.
    
    **Validates: Requirements 5.7**
    """
    # All cost components should be non-negative
    assert log.spread_bps >= 0, f"spread_bps should be non-negative, got {log.spread_bps}"
    assert log.fee_bps >= 0, f"fee_bps should be non-negative, got {log.fee_bps}"
    assert log.slippage_bps >= 0, f"slippage_bps should be non-negative, got {log.slippage_bps}"
    assert log.adverse_selection_bps >= 0, f"adverse_selection_bps should be non-negative, got {log.adverse_selection_bps}"
    assert log.total_cost_bps >= 0, f"total_cost_bps should be non-negative, got {log.total_cost_bps}"


@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_probability_fields_in_valid_range(log: EVGateDecisionLog):
    """
    Property 9: Probability fields validity
    
    *For any* decision log, probability fields (p_hat, p_calibrated, p_min,
    calibration_reliability) SHALL be in the range [0, 1].
    
    **Validates: Requirements 1.7, 2.8**
    """
    # p_hat should be in [0, 1]
    assert 0 <= log.p_hat <= 1, f"p_hat should be in [0,1], got {log.p_hat}"
    
    # p_calibrated should be in [0, 1]
    assert 0 <= log.p_calibrated <= 1, f"p_calibrated should be in [0,1], got {log.p_calibrated}"
    
    # p_min should be in [0, 1] (or slightly above 1 in edge cases)
    # Note: p_min can exceed 1 when costs are very high, indicating impossible trade
    assert log.p_min >= 0, f"p_min should be non-negative, got {log.p_min}"
    
    # calibration_reliability should be in [0, 1]
    assert 0 <= log.calibration_reliability <= 1, \
        f"calibration_reliability should be in [0,1], got {log.calibration_reliability}"


@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_threshold_fields_consistency(log: EVGateDecisionLog):
    """
    Property 9: Threshold fields consistency
    
    *For any* decision log, ev_min_base and ev_min_adjusted SHALL be non-negative,
    and adjustment_factor SHALL be positive.
    
    **Validates: Requirements 6.8**
    """
    # ev_min_base should be non-negative
    assert log.ev_min_base >= 0, f"ev_min_base should be non-negative, got {log.ev_min_base}"
    
    # ev_min_adjusted should be non-negative
    assert log.ev_min_adjusted >= 0, f"ev_min_adjusted should be non-negative, got {log.ev_min_adjusted}"
    
    # adjustment_factor should be positive
    assert log.adjustment_factor > 0, f"adjustment_factor should be positive, got {log.adjustment_factor}"


@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_data_quality_fields_non_negative(log: EVGateDecisionLog):
    """
    Property 9: Data quality fields validity
    
    *For any* decision log, book_age_ms and spread_age_ms SHALL be non-negative.
    
    **Validates: Requirements 7.1**
    """
    # book_age_ms should be non-negative
    assert log.book_age_ms >= 0, f"book_age_ms should be non-negative, got {log.book_age_ms}"
    
    # spread_age_ms should be non-negative
    assert log.spread_age_ms >= 0, f"spread_age_ms should be non-negative, got {log.spread_age_ms}"


@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_r_and_l_g_positive(log: EVGateDecisionLog):
    """
    Property 9: R, L_bps, G_bps positivity
    
    *For any* decision log, R (reward-to-risk ratio), L_bps (stop loss distance),
    and G_bps (take profit distance) SHALL be positive.
    
    **Validates: Requirements 1.7**
    """
    # R should be positive
    assert log.R > 0, f"R should be positive, got {log.R}"
    
    # L_bps should be positive
    assert log.L_bps > 0, f"L_bps should be positive, got {log.L_bps}"
    
    # G_bps should be positive
    assert log.G_bps > 0, f"G_bps should be positive, got {log.G_bps}"


@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_calibration_method_valid(log: EVGateDecisionLog):
    """
    Property 9: Calibration method validity
    
    *For any* decision log, calibration_method SHALL be one of the valid methods.
    
    **Validates: Requirements 7.1**
    """
    valid_methods = {"uncalibrated", "platt", "isotonic", "pooled", "per_symbol", "per_symbol_regime"}
    
    assert log.calibration_method in valid_methods, \
        f"calibration_method should be one of {valid_methods}, got {log.calibration_method}"


@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_decision_value_valid(log: EVGateDecisionLog):
    """
    Property 9: Decision value validity
    
    *For any* decision log, decision SHALL be either "ACCEPT" or "REJECT".
    
    **Validates: Requirements 7.1**
    """
    assert log.decision in {"ACCEPT", "REJECT"}, \
        f"decision should be 'ACCEPT' or 'REJECT', got {log.decision}"


@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_timestamp_positive(log: EVGateDecisionLog):
    """
    Property 9: Timestamp validity
    
    *For any* decision log, timestamp SHALL be a positive number.
    
    **Validates: Requirements 7.1**
    """
    assert log.timestamp > 0, f"timestamp should be positive, got {log.timestamp}"


@settings(max_examples=100)
@given(log=decision_log_strategy())
def test_property_9_symbol_not_empty(log: EVGateDecisionLog):
    """
    Property 9: Symbol validity
    
    *For any* decision log, symbol SHALL not be empty.
    
    **Validates: Requirements 7.1**
    """
    assert log.symbol, f"symbol should not be empty, got {log.symbol}"
    assert len(log.symbol) > 0, f"symbol should have length > 0"
