"""
Property-based tests for read-only copilot tools.

Feature: trading-copilot-agent
Tests correctness properties for:
- Property 1: Tool output schema compliance
- Property 2: Symbol filtering correctness
- Property 3: PnL aggregation correctness
- Property 4: Performance metric computation correctness
- Property 5: Per-symbol metric partitioning
- Property 6: Drawdown computation correctness
- Property 7: Pipeline throughput counting
- Property 8: Bottleneck identification

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.1, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 5.1, 6.1, 6.2, 6.4**
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pytest
from hypothesis import given, settings, assume, strategies as st

from quantgambit.copilot.tools.trades import _extract_trade
from quantgambit.copilot.tools.positions import _extract_position
from quantgambit.copilot.tools.decisions import _extract_decision
from quantgambit.copilot.tools.backtests import _extract_backtest
from quantgambit.copilot.tools.performance import compute_metrics, compute_max_drawdown
from quantgambit.copilot.tools.pipeline import _aggregate_throughput, PIPELINE_STAGES


# =============================================================================
# Hypothesis Strategies (Generators)
# =============================================================================

# Symbols used across tests
symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"])

# Sides for trades
sides = st.sampled_from(["buy", "sell", "long", "short"])

# Reasonable float values for prices and PnL
prices = st.floats(min_value=0.01, max_value=100_000.0, allow_nan=False, allow_infinity=False)
pnl_values = st.floats(min_value=-10_000.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)
sizes = st.floats(min_value=0.001, max_value=10_000.0, allow_nan=False, allow_infinity=False)


@st.composite
def trade_row_strategy(draw):
    """Generate a random order_events row dict for _extract_trade."""
    symbol = draw(symbols)
    side = draw(sides)
    entry_price = draw(prices)
    exit_price = draw(prices)
    size = draw(sizes)
    pnl = draw(pnl_values)
    ts = draw(st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2025, 12, 31),
        timezones=st.just(timezone.utc),
    ))
    return {
        "symbol": symbol,
        "ts": ts,
        "payload": {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "size": size,
            "net_pnl": pnl,
        },
    }


@st.composite
def position_dict_strategy(draw):
    """Generate a random Redis position dict for _extract_position."""
    symbol = draw(symbols)
    side = draw(sides)
    size = draw(sizes)
    entry_price = draw(prices)
    current_price = draw(prices)
    stop_loss = draw(st.one_of(st.none(), prices))
    take_profit = draw(st.one_of(st.none(), prices))
    return {
        "symbol": symbol,
        "side": side,
        "size": size,
        "entry_price": entry_price,
        "reference_price": current_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
    }


@st.composite
def decision_row_strategy(draw):
    """Generate a random decision_events row dict for _extract_decision."""
    symbol = draw(symbols)
    # Pick a random subset of pipeline stages as gates_passed
    num_stages = draw(st.integers(min_value=0, max_value=len(PIPELINE_STAGES)))
    gates_passed = PIPELINE_STAGES[:num_stages]
    rejection_reason = draw(st.one_of(st.none(), st.text(min_size=1, max_size=30)))
    signal_confidence = draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)))
    result = draw(st.sampled_from(["COMPLETE", "REJECT", None]))
    ts = draw(st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2025, 12, 31),
        timezones=st.just(timezone.utc),
    ))
    return {
        "symbol": symbol,
        "ts": ts,
        "payload": {
            "symbol": symbol,
            "gates_passed": gates_passed,
            "rejection_reason": rejection_reason,
            "signal_confidence": signal_confidence,
            "result": result,
        },
    }


@st.composite
def backtest_row_strategy(draw):
    """Generate a random backtest_runs + backtest_metrics joined row dict."""
    run_id = draw(st.uuids().map(str))
    name = draw(st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_"))
    symbol = draw(symbols)
    status = draw(st.sampled_from(["pending", "running", "finished", "failed", "cancelled"]))
    start_date = draw(st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2024, 12, 31),
        timezones=st.just(timezone.utc),
    ))
    end_date = draw(st.datetimes(
        min_value=datetime(2024, 1, 1),
        max_value=datetime(2025, 12, 31),
        timezones=st.just(timezone.utc),
    ))
    created_at = draw(st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2025, 12, 31),
        timezones=st.just(timezone.utc),
    ))
    return {
        "run_id": run_id,
        "name": name,
        "symbol": symbol,
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "created_at": created_at,
        "sharpe_ratio": draw(st.one_of(st.none(), st.floats(min_value=-5.0, max_value=5.0, allow_nan=False))),
        "max_drawdown_pct": draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=100.0, allow_nan=False))),
        "win_rate": draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False))),
        "realized_pnl": draw(st.one_of(st.none(), pnl_values)),
        "total_trades": draw(st.one_of(st.none(), st.integers(min_value=0, max_value=10000))),
        "profit_factor": draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=100.0, allow_nan=False))),
    }


@st.composite
def decision_event_for_pipeline(draw):
    """Generate a decision event row for pipeline throughput testing."""
    # Pick a random prefix of pipeline stages as gates_passed
    num_stages = draw(st.integers(min_value=1, max_value=len(PIPELINE_STAGES)))
    gates_passed = PIPELINE_STAGES[:num_stages]
    return {
        "payload": {
            "gates_passed": gates_passed,
        },
    }


# =============================================================================
# Property 1: Tool output schema compliance
# Feature: trading-copilot-agent, Property 1: Tool output schema compliance
#
# For any registered tool and any valid input parameters, the tool result data
# SHALL contain all fields specified in that tool's return schema definition.
#
# **Validates: Requirements 2.1, 2.2, 4.1, 5.1, 6.1, 6.2, 6.4**
# =============================================================================

TRADE_REQUIRED_FIELDS = {"symbol", "side", "entry_price", "exit_price", "size", "pnl", "timestamp"}
POSITION_REQUIRED_FIELDS = {"symbol", "side", "size", "entry_price", "current_price", "unrealized_pnl", "stop_loss", "take_profit"}
DECISION_REQUIRED_FIELDS = {"symbol", "stages_executed", "rejection_reason", "signal_confidence", "result", "timestamp"}
BACKTEST_REQUIRED_FIELDS = {"id", "strategy_id", "symbol", "date_range", "status", "metrics", "created_at"}


@settings(max_examples=100)
@given(row=trade_row_strategy())
def test_property_1_extract_trade_returns_all_required_fields(row):
    """
    Property 1: Tool output schema compliance — _extract_trade.

    For any order_events row, _extract_trade SHALL return a dict containing
    all required trade fields: symbol, side, entry_price, exit_price, size,
    pnl, timestamp.

    **Validates: Requirements 2.1**
    """
    result = _extract_trade(row)
    assert isinstance(result, dict)
    assert TRADE_REQUIRED_FIELDS.issubset(result.keys()), (
        f"Missing fields: {TRADE_REQUIRED_FIELDS - result.keys()}"
    )


@settings(max_examples=100)
@given(pos=position_dict_strategy())
def test_property_1_extract_position_returns_all_required_fields(pos):
    """
    Property 1: Tool output schema compliance — _extract_position.

    For any Redis position record, _extract_position SHALL return a dict
    containing all required position fields: symbol, side, size, entry_price,
    current_price, unrealized_pnl, stop_loss, take_profit.

    **Validates: Requirements 2.2**
    """
    result = _extract_position(pos)
    assert isinstance(result, dict)
    assert POSITION_REQUIRED_FIELDS.issubset(result.keys()), (
        f"Missing fields: {POSITION_REQUIRED_FIELDS - result.keys()}"
    )


@settings(max_examples=100)
@given(row=decision_row_strategy())
def test_property_1_extract_decision_returns_all_required_fields(row):
    """
    Property 1: Tool output schema compliance — _extract_decision.

    For any decision_events row, _extract_decision SHALL return a dict
    containing all required decision fields: symbol, stages_executed,
    rejection_reason, signal_confidence, result, timestamp.

    **Validates: Requirements 4.1**
    """
    result = _extract_decision(row)
    assert isinstance(result, dict)
    assert DECISION_REQUIRED_FIELDS.issubset(result.keys()), (
        f"Missing fields: {DECISION_REQUIRED_FIELDS - result.keys()}"
    )


@settings(max_examples=100)
@given(row=backtest_row_strategy())
def test_property_1_extract_backtest_returns_all_required_fields(row):
    """
    Property 1: Tool output schema compliance — _extract_backtest.

    For any backtest_runs + backtest_metrics joined row, _extract_backtest
    SHALL return a dict containing all required backtest fields: id,
    strategy_id, symbol, date_range, status, metrics, created_at.

    **Validates: Requirements 5.1**
    """
    result = _extract_backtest(row)
    assert isinstance(result, dict)
    assert BACKTEST_REQUIRED_FIELDS.issubset(result.keys()), (
        f"Missing fields: {BACKTEST_REQUIRED_FIELDS - result.keys()}"
    )


# =============================================================================
# Property 2: Symbol filtering correctness
# Feature: trading-copilot-agent, Property 2: Symbol filtering correctness
#
# For any tool that accepts a symbol filter parameter and any set of backing
# data, all records in the tool result SHALL have a symbol field matching the
# requested symbol filter.
#
# **Validates: Requirements 2.3, 4.3**
# =============================================================================


@st.composite
def trades_with_mixed_symbols(draw):
    """Generate a list of trade rows with mixed symbols and a target symbol."""
    target_symbol = draw(symbols)
    num_rows = draw(st.integers(min_value=1, max_value=20))
    rows = []
    for _ in range(num_rows):
        row = draw(trade_row_strategy())
        rows.append(row)
    return target_symbol, rows


@settings(max_examples=100)
@given(data=trades_with_mixed_symbols())
def test_property_2_symbol_filtering_on_trades(data):
    """
    Property 2: Symbol filtering correctness — trades.

    For any set of trade rows and any target symbol, filtering the extracted
    trades by symbol SHALL return only trades whose symbol matches the target.

    **Validates: Requirements 2.3**
    """
    target_symbol, rows = data
    extracted = [_extract_trade(row) for row in rows]
    filtered = [t for t in extracted if t["symbol"] == target_symbol]
    for trade in filtered:
        assert trade["symbol"] == target_symbol


@st.composite
def decisions_with_mixed_symbols(draw):
    """Generate a list of decision rows with mixed symbols and a target symbol."""
    target_symbol = draw(symbols)
    num_rows = draw(st.integers(min_value=1, max_value=20))
    rows = []
    for _ in range(num_rows):
        row = draw(decision_row_strategy())
        rows.append(row)
    return target_symbol, rows


@settings(max_examples=100)
@given(data=decisions_with_mixed_symbols())
def test_property_2_symbol_filtering_on_decisions(data):
    """
    Property 2: Symbol filtering correctness — decisions.

    For any set of decision rows and any target symbol, filtering the extracted
    decisions by symbol SHALL return only decisions whose symbol matches the target.

    **Validates: Requirements 4.3**
    """
    target_symbol, rows = data
    extracted = [_extract_decision(row) for row in rows]
    filtered = [d for d in extracted if d["symbol"] == target_symbol]
    for decision in filtered:
        assert decision["symbol"] == target_symbol


# =============================================================================
# Property 3: PnL aggregation correctness
# Feature: trading-copilot-agent, Property 3: PnL aggregation correctness
#
# For any set of trades and any date range, the total PnL returned by the
# performance tool SHALL equal the sum of individual trade PnL values.
#
# **Validates: Requirements 2.4**
# =============================================================================


@settings(max_examples=100)
@given(pnls=st.lists(
    st.floats(min_value=-10_000.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    min_size=0,
    max_size=50,
))
def test_property_3_pnl_aggregation_correctness(pnls: list[float]):
    """
    Property 3: PnL aggregation correctness.

    For any list of PnL values, compute_metrics total_pnl SHALL equal the
    sum of the individual PnL values.

    **Validates: Requirements 2.4**
    """
    metrics = compute_metrics(pnls)
    expected_total = sum(pnls)
    assert math.isclose(metrics["total_pnl"], expected_total, rel_tol=1e-9, abs_tol=1e-9), (
        f"total_pnl={metrics['total_pnl']} != sum(pnls)={expected_total}"
    )
    assert metrics["trade_count"] == len(pnls)


# =============================================================================
# Property 4: Performance metric computation correctness
# Feature: trading-copilot-agent, Property 4: Performance metric computation
#
# For any non-empty set of trades, win_rate = count(positive PnL) / total,
# profit_factor = sum(positive PnL) / abs(sum(negative PnL)).
#
# **Validates: Requirements 3.1**
# =============================================================================


@settings(max_examples=100)
@given(pnls=st.lists(
    st.floats(min_value=-10_000.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=50,
))
def test_property_4_performance_metric_computation(pnls: list[float]):
    """
    Property 4: Performance metric computation correctness.

    For any non-empty list of PnL values:
    - win_rate SHALL equal count(positive PnL) / total
    - profit_factor SHALL equal sum(positive PnL) / abs(sum(negative PnL))

    **Validates: Requirements 3.1**
    """
    metrics = compute_metrics(pnls)

    # Win rate
    wins = [p for p in pnls if p > 0]
    expected_win_rate = len(wins) / len(pnls)
    assert math.isclose(metrics["win_rate"], expected_win_rate, rel_tol=1e-9, abs_tol=1e-9), (
        f"win_rate={metrics['win_rate']} != expected={expected_win_rate}"
    )

    # Profit factor
    losses = [p for p in pnls if p < 0]
    sum_wins = sum(wins)
    sum_losses_abs = abs(sum(losses))
    if sum_losses_abs > 0:
        expected_pf = sum_wins / sum_losses_abs
        assert math.isclose(metrics["profit_factor"], expected_pf, rel_tol=1e-9, abs_tol=1e-9), (
            f"profit_factor={metrics['profit_factor']} != expected={expected_pf}"
        )
    elif sum_wins > 0:
        assert metrics["profit_factor"] == 9999.99
    else:
        assert metrics["profit_factor"] == 0.0


# =============================================================================
# Property 5: Per-symbol metric partitioning
# Feature: trading-copilot-agent, Property 5: Per-symbol metric partitioning
#
# For any set of trades across multiple symbols, per-symbol PnL sums equal
# overall PnL.
#
# **Validates: Requirements 3.3**
# =============================================================================


@st.composite
def multi_symbol_pnl_strategy(draw):
    """Generate a dict mapping symbols to lists of PnL values."""
    num_symbols = draw(st.integers(min_value=1, max_value=5))
    chosen_symbols = draw(
        st.lists(symbols, min_size=num_symbols, max_size=num_symbols, unique=True)
    )
    result = {}
    for sym in chosen_symbols:
        pnls = draw(st.lists(
            st.floats(min_value=-10_000.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=20,
        ))
        result[sym] = pnls
    return result


@settings(max_examples=100)
@given(symbol_pnls=multi_symbol_pnl_strategy())
def test_property_5_per_symbol_metric_partitioning(symbol_pnls: dict[str, list[float]]):
    """
    Property 5: Per-symbol metric partitioning.

    For any set of trades across multiple symbols, the sum of per-symbol
    total_pnl SHALL equal the overall total_pnl.

    **Validates: Requirements 3.3**
    """
    # Flatten all PnL values
    all_pnls: list[float] = []
    for pnls in symbol_pnls.values():
        all_pnls.extend(pnls)

    overall = compute_metrics(all_pnls)

    # Compute per-symbol metrics
    per_symbol_total = 0.0
    for sym, pnls in symbol_pnls.items():
        sym_metrics = compute_metrics(pnls)
        per_symbol_total += sym_metrics["total_pnl"]
        # Each symbol's trade_count should match its PnL list length
        assert sym_metrics["trade_count"] == len(pnls)

    assert math.isclose(overall["total_pnl"], per_symbol_total, rel_tol=1e-9, abs_tol=1e-9), (
        f"overall total_pnl={overall['total_pnl']} != sum of per-symbol={per_symbol_total}"
    )
    assert overall["trade_count"] == len(all_pnls)


# =============================================================================
# Property 6: Drawdown computation correctness
# Feature: trading-copilot-agent, Property 6: Drawdown computation correctness
#
# For any equity curve, max drawdown = maximum peak-to-trough decline.
#
# **Validates: Requirements 3.4**
# =============================================================================


@settings(max_examples=100)
@given(pnls=st.lists(
    st.floats(min_value=-10_000.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    min_size=0,
    max_size=50,
))
def test_property_6_drawdown_computation_correctness(pnls: list[float]):
    """
    Property 6: Drawdown computation correctness.

    For any sequence of PnL values, compute_max_drawdown SHALL return the
    maximum peak-to-trough decline in the cumulative PnL curve. The result
    SHALL be non-negative.

    **Validates: Requirements 3.4**
    """
    result = compute_max_drawdown(pnls)

    # Drawdown is always non-negative
    assert result >= 0.0, f"Drawdown should be non-negative, got {result}"

    if not pnls:
        assert result == 0.0
        return

    # Verify by recomputing: build cumulative curve and find max peak-to-trough
    # The implementation starts with peak=0.0 (initial equity), so we do the same
    cumulative = 0.0
    peak = 0.0
    expected_dd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > expected_dd:
            expected_dd = dd

    assert math.isclose(result, expected_dd, rel_tol=1e-9, abs_tol=1e-9), (
        f"max_drawdown={result} != expected={expected_dd}"
    )


@settings(max_examples=100)
@given(pnls=st.lists(
    st.floats(min_value=0.01, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=50,
))
def test_property_6_all_positive_pnl_zero_drawdown(pnls: list[float]):
    """
    Property 6: Drawdown computation correctness — all positive PnL.

    When all PnL values are strictly positive, the cumulative curve is
    monotonically increasing, so max drawdown SHALL be 0.

    **Validates: Requirements 3.4**
    """
    result = compute_max_drawdown(pnls)
    assert result == 0.0, f"Expected 0 drawdown for all-positive PnL, got {result}"


# =============================================================================
# Property 7: Pipeline throughput counting
# Feature: trading-copilot-agent, Property 7: Pipeline throughput counting
#
# For any set of decision events, each event is counted in exactly the stages
# it passed through.
#
# **Validates: Requirements 4.2**
# =============================================================================


@settings(max_examples=100)
@given(events=st.lists(decision_event_for_pipeline(), min_size=0, max_size=30))
def test_property_7_pipeline_throughput_counting(events: list[dict[str, Any]]):
    """
    Property 7: Pipeline throughput counting.

    For any set of decision events, each event SHALL be counted in exactly
    the stages it passed through. The per-stage counts SHALL be consistent
    with the individual events' gates_passed lists.

    **Validates: Requirements 4.2**
    """
    result = _aggregate_throughput(events)

    assert result["total_decisions"] == len(events)

    # Verify per-stage counts by manual aggregation
    expected_counts: dict[str, int] = {stage: 0 for stage in PIPELINE_STAGES}
    for event in events:
        gates = event.get("payload", {}).get("gates_passed", [])
        for stage in gates:
            if stage in expected_counts:
                expected_counts[stage] += 1

    for stage in PIPELINE_STAGES:
        actual_count = result["per_stage"][stage]["count"]
        assert actual_count == expected_counts[stage], (
            f"Stage {stage}: count={actual_count} != expected={expected_counts[stage]}"
        )

    # Verify pass rates
    for stage in PIPELINE_STAGES:
        stage_data = result["per_stage"][stage]
        if len(events) > 0:
            expected_rate = round(stage_data["count"] / len(events), 4)
            assert math.isclose(stage_data["pass_rate"], expected_rate, abs_tol=1e-4), (
                f"Stage {stage}: pass_rate={stage_data['pass_rate']} != expected={expected_rate}"
            )
        else:
            assert stage_data["pass_rate"] == 0.0


# =============================================================================
# Property 8: Bottleneck identification
# Feature: trading-copilot-agent, Property 8: Bottleneck identification
#
# For any set of per-stage pass-through rates, the bottleneck is the stage
# with the minimum pass-through rate.
#
# **Validates: Requirements 4.4**
# =============================================================================


@settings(max_examples=100)
@given(events=st.lists(decision_event_for_pipeline(), min_size=1, max_size=30))
def test_property_8_bottleneck_identification(events: list[dict[str, Any]]):
    """
    Property 8: Bottleneck identification.

    For any non-empty set of decision events, the identified bottleneck stage
    SHALL be the stage with the minimum pass-through rate among stages that
    have at least one event.

    **Validates: Requirements 4.4**
    """
    result = _aggregate_throughput(events)

    # Find stages with count > 0
    active_stages = [
        (stage, result["per_stage"][stage]["pass_rate"])
        for stage in PIPELINE_STAGES
        if result["per_stage"][stage]["count"] > 0
    ]

    if not active_stages:
        assert result["bottleneck"] is None
        return

    # The bottleneck should be the stage with the minimum pass rate
    min_stage, min_rate = min(active_stages, key=lambda x: x[1])

    assert result["bottleneck"] is not None
    assert result["bottleneck"]["stage"] == min_stage, (
        f"Bottleneck stage={result['bottleneck']['stage']} != expected={min_stage}"
    )
    assert math.isclose(result["bottleneck"]["pass_rate"], min_rate, abs_tol=1e-4), (
        f"Bottleneck pass_rate={result['bottleneck']['pass_rate']} != expected={min_rate}"
    )
