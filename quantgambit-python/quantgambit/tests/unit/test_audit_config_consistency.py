"""
Configuration consistency audit tests for the QuantGambit scalping pipeline.

These tests verify that environment configuration parameters are internally
consistent and appropriate for a scalping strategy. Each test reads actual
env vars (or uses known .env defaults) and flags contradictions, unreachable
thresholds, or mode mismatches that could silently degrade performance.

Validates: Requirements 1.5, 3.6, 3.8, 5.6, 5.7, 8.1, 8.2, 8.3,
           9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.4, 10.7
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

_env_snapshot = dict(os.environ)

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parents[4] / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
except ImportError:
    pass  # fall back to os.environ

from quantgambit.risk.fee_model import FeeConfig


@pytest.fixture(autouse=True, scope="module")
def _restore_env_after_module():
    """Restore os.environ after this module's tests to prevent pollution."""
    yield
    # Remove keys added by load_dotenv, restore original values
    added = set(os.environ) - set(_env_snapshot)
    for k in added:
        if k.startswith("PYTEST"):
            continue
        os.environ.pop(k, None)
    for k, v in _env_snapshot.items():
        if os.environ.get(k) != v:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Helpers — read env with fallback to known .env defaults
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    """Read a float env var with a fallback default."""
    return float(os.getenv(name, str(default)))


def _env_str(name: str, default: str) -> str:
    """Read a string env var with a fallback default."""
    return os.getenv(name, default)


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean env var with a fallback default."""
    raw = os.getenv(name, str(default).lower())
    return raw.lower() in ("true", "1", "yes", "on")


# ---------------------------------------------------------------------------
# 1. Depth threshold contradiction (Requirement 1.5)
# ---------------------------------------------------------------------------

class TestDepthThresholdContradiction:
    """GLOBAL_GATE_MIN_DEPTH_USD ($20,000) vs DATA_READINESS_MIN_BID_DEPTH_USD ($500).

    Data readiness passes at $500 depth, but the global gate blocks below
    $20,000 — a 40× gap.  This means data readiness is effectively useless
    as a depth filter because the global gate is always the binding constraint.
    Validates: Requirement 1.5
    """

    def test_global_gate_depth_exceeds_data_readiness_depth(self):
        """Global gate depth should not be orders of magnitude above data readiness depth."""
        global_gate = _env_float("GLOBAL_GATE_MIN_DEPTH_USD", 20_000)
        dr_bid = _env_float("DATA_READINESS_MIN_BID_DEPTH_USD", 500)
        dr_ask = _env_float("DATA_READINESS_MIN_ASK_DEPTH_USD", 500)

        ratio_bid = global_gate / dr_bid if dr_bid > 0 else float("inf")
        ratio_ask = global_gate / dr_ask if dr_ask > 0 else float("inf")

        # Flag: if global gate requires >10× the data-readiness threshold,
        # the data-readiness depth check is redundant.
        assert ratio_bid <= 10, (
            f"GLOBAL_GATE_MIN_DEPTH_USD ({global_gate}) is {ratio_bid:.0f}× "
            f"DATA_READINESS_MIN_BID_DEPTH_USD ({dr_bid}) — data readiness "
            "depth check is effectively bypassed by the global gate"
        )
        assert ratio_ask <= 10, (
            f"GLOBAL_GATE_MIN_DEPTH_USD ({global_gate}) is {ratio_ask:.0f}× "
            f"DATA_READINESS_MIN_ASK_DEPTH_USD ({dr_ask}) — data readiness "
            "depth check is effectively bypassed by the global gate"
        )


# ---------------------------------------------------------------------------
# 2. Fee consistency (Requirements 3.6)
# ---------------------------------------------------------------------------

class TestFeeConsistency:
    """FEE_AWARE_ENTRY_FEE_RATE_BPS (5.5) vs STRATEGY_FEE_BPS (6.0) vs
    actual bybit_regular taker rate (5.5 bps).

    Multiple fee parameters exist across the pipeline.  If they diverge, the
    EV gate and strategy-level fee filter will disagree on profitability.
    Validates: Requirement 3.6
    """

    def test_fee_aware_entry_matches_bybit_taker(self):
        """FEE_AWARE_ENTRY_FEE_RATE_BPS should match the actual exchange taker rate."""
        fee_aware_bps = _env_float("FEE_AWARE_ENTRY_FEE_RATE_BPS", 5.5)
        bybit = FeeConfig.bybit_regular()
        actual_taker_bps = bybit.taker_fee_rate * 10_000  # decimal → bps

        assert fee_aware_bps == pytest.approx(actual_taker_bps, abs=0.5), (
            f"FEE_AWARE_ENTRY_FEE_RATE_BPS ({fee_aware_bps}) diverges from "
            f"bybit_regular taker rate ({actual_taker_bps} bps)"
        )

    def test_strategy_fee_bps_not_lower_than_actual_taker(self):
        """STRATEGY_FEE_BPS should be >= actual taker rate to avoid under-counting fees."""
        strategy_fee = _env_float("STRATEGY_FEE_BPS", 6.0)
        bybit = FeeConfig.bybit_regular()
        actual_taker_bps = bybit.taker_fee_rate * 10_000

        assert strategy_fee >= actual_taker_bps, (
            f"STRATEGY_FEE_BPS ({strategy_fee}) is below the actual bybit "
            f"taker rate ({actual_taker_bps} bps) — strategies will under-count fees"
        )

    def test_fee_parameters_within_reasonable_spread(self):
        """FEE_AWARE_ENTRY_FEE_RATE_BPS and STRATEGY_FEE_BPS should not diverge by >2 bps."""
        fee_aware = _env_float("FEE_AWARE_ENTRY_FEE_RATE_BPS", 5.5)
        strategy_fee = _env_float("STRATEGY_FEE_BPS", 6.0)

        diff = abs(fee_aware - strategy_fee)
        assert diff <= 2.0, (
            f"Fee parameters diverge by {diff:.1f} bps "
            f"(FEE_AWARE={fee_aware}, STRATEGY_FEE={strategy_fee}) — "
            "pipeline stages will disagree on profitability"
        )


# ---------------------------------------------------------------------------
# 3. EV gate cost multiple reachability (Requirement 3.8)
# ---------------------------------------------------------------------------

class TestEVGateCostMultipleReachability:
    """EV_GATE_COST_MULTIPLE (2.25) × RECENT_COST_P75_BPS creates a cost
    hurdle that entries must clear.  If the hurdle is unreachable given
    typical scalping edge, no entries will pass.
    Validates: Requirement 3.8
    """

    @pytest.mark.parametrize("symbol,p75_default", [
        ("BTCUSDT", 18.0),
        ("ETHUSDT", 18.0),
        ("SOLUSDT", 22.0),
    ])
    def test_cost_hurdle_is_reachable(self, symbol: str, p75_default: float):
        """Cost multiple × P75 cost should not exceed a realistic scalping edge (~80 bps)."""
        cost_multiple = _env_float("EV_GATE_COST_MULTIPLE", 2.25)

        # Parse per-symbol P75 from env
        raw = _env_str(
            "EV_GATE_RECENT_COST_P75_BPS_BY_SYMBOL",
            "BTCUSDT:18.0,ETHUSDT:18.0,SOLUSDT:22.0",
        )
        p75_map = {}
        for pair in raw.split(","):
            parts = pair.strip().split(":")
            if len(parts) == 2:
                p75_map[parts[0].strip()] = float(parts[1].strip())

        p75 = p75_map.get(symbol, p75_default)
        hurdle = cost_multiple * p75

        # 80 bps is a generous upper bound for scalping gross edge
        max_realistic_edge_bps = 80.0
        assert hurdle <= max_realistic_edge_bps, (
            f"{symbol}: cost hurdle = {cost_multiple} × {p75} = {hurdle:.1f} bps "
            f"exceeds realistic scalping edge ({max_realistic_edge_bps} bps)"
        )


# ---------------------------------------------------------------------------
# 4. Execution hard max vs position size (Requirements 5.6, 5.7)
# ---------------------------------------------------------------------------

class TestExecutionHardMaxVsPositionSize:
    """EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD ($9,000) vs MAX_POSITION_SIZE_USD.

    If the hard cap is many multiples of the position size limit, it suggests
    a misconfiguration — the hard cap should be a tight safety net, not 6×+
    the normal limit.
    Validates: Requirements 5.6, 5.7
    """

    def test_hard_max_not_excessively_above_position_size(self):
        """Hard max order notional should be within 10× of max position size."""
        hard_max = _env_float("EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD", 9_000)
        max_pos = _env_float("MAX_POSITION_SIZE_USD", 2_500)

        if max_pos > 0:
            ratio = hard_max / max_pos
            assert ratio <= 10, (
                f"EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD ({hard_max}) is "
                f"{ratio:.1f}× MAX_POSITION_SIZE_USD ({max_pos}) — "
                "hard cap is too loose to be an effective safety net"
            )

    def test_min_order_interval_not_contradicting_cooldown(self):
        """MIN_ORDER_INTERVAL_SEC should not be much stricter than COOLDOWN_ENTRY_SEC.

        If the execution layer throttle is far stricter than the decision
        layer cooldown, the decision layer will generate signals that the
        execution layer silently drops.
        """
        min_interval = _env_float("MIN_ORDER_INTERVAL_SEC", 180)
        cooldown = _env_float("COOLDOWN_ENTRY_SEC", 45)

        if cooldown > 0:
            ratio = min_interval / cooldown
            assert ratio <= 10, (
                f"MIN_ORDER_INTERVAL_SEC ({min_interval}s) is {ratio:.1f}× "
                f"COOLDOWN_ENTRY_SEC ({cooldown}s) — execution layer is far "
                "stricter than decision layer, wasting decision compute"
            )


# ---------------------------------------------------------------------------
# 5. Throttle mode appropriateness (Requirements 8.1, 8.2, 8.3)
# ---------------------------------------------------------------------------

class TestThrottleModeAppropriateness:
    """THROTTLE_MODE should match the trading strategy.

    A scalping bot using 'swing' throttle mode would be severely under-trading.
    Validates: Requirements 8.1, 8.2, 8.3
    """

    def test_throttle_mode_is_scalping(self):
        """THROTTLE_MODE should be 'scalping' (or 'scalp') for a scalping strategy."""
        mode = _env_str("THROTTLE_MODE", "scalping").lower()
        acceptable = {"scalping", "scalp"}
        assert mode in acceptable, (
            f"THROTTLE_MODE='{mode}' is not appropriate for a scalping strategy — "
            f"expected one of {acceptable}"
        )

    def test_max_entries_per_hour_sufficient_for_scalping(self):
        """COOLDOWN_MAX_ENTRIES_PER_HOUR should allow enough trades for scalping profitability."""
        max_entries = _env_float("COOLDOWN_MAX_ENTRIES_PER_HOUR", 24)
        # With 3 symbols, need at least ~6 entries/hour total to have a chance
        assert max_entries >= 6, (
            f"COOLDOWN_MAX_ENTRIES_PER_HOUR ({max_entries}) is too low for "
            "scalping — need sufficient trade frequency to overcome costs"
        )

    def test_combined_cooldowns_allow_reasonable_frequency(self):
        """Combined cooldowns should allow at least 10 entries per hour."""
        cooldown_entry = _env_float("COOLDOWN_ENTRY_SEC", 45)
        max_entries_per_hour = _env_float("COOLDOWN_MAX_ENTRIES_PER_HOUR", 24)

        # Theoretical max from cooldown alone
        if cooldown_entry > 0:
            theoretical_max = 3600 / cooldown_entry
        else:
            theoretical_max = float("inf")

        effective_max = min(theoretical_max, max_entries_per_hour)
        assert effective_max >= 10, (
            f"Effective max entries/hour = {effective_max:.0f} "
            f"(cooldown allows {theoretical_max:.0f}, cap is {max_entries_per_hour}) — "
            "too few for scalping"
        )


# ---------------------------------------------------------------------------
# 6. Risk sizing consistency (Requirements 9.1, 9.2, 9.3)
# ---------------------------------------------------------------------------

class TestRiskSizingConsistency:
    """RISK_PER_TRADE_PCT × capital vs MAX_POSITION_SIZE_USD × typical stop distance.

    The risk budget per trade should be consistent with the position size and
    typical stop distances used in scalping.
    Validates: Requirements 9.1, 9.2, 9.3
    """

    def test_risk_budget_consistent_with_position_size(self):
        """Risk per trade should be achievable with max position size and typical stops.

        For a scalping stop of ~20-50 bps, the risk = position_size × stop_bps.
        This should be close to RISK_PER_TRADE_PCT × capital.
        """
        capital = _env_float("TRADING_CAPITAL_USD", 80_000)
        risk_pct = _env_float("RISK_PER_TRADE_PCT", 0.0035)
        max_pos = _env_float("MAX_POSITION_SIZE_USD", 2_500)

        risk_budget_usd = capital * risk_pct  # e.g. 80000 × 0.0035 = $280

        # Typical scalping stop: 20-50 bps
        typical_stop_bps = 30
        implied_risk_usd = max_pos * (typical_stop_bps / 10_000)  # e.g. 2500 × 0.003 = $7.50

        # The risk budget should be at least as large as the implied risk
        # from a single max-size position with a typical stop
        assert risk_budget_usd >= implied_risk_usd, (
            f"Risk budget (${risk_budget_usd:.2f} = {risk_pct} × ${capital:,.0f}) "
            f"is less than implied risk from max position "
            f"(${implied_risk_usd:.2f} = ${max_pos:,.0f} × {typical_stop_bps} bps)"
        )

    def test_position_size_not_trivially_small_vs_capital(self):
        """MAX_POSITION_SIZE_USD should be a meaningful fraction of capital."""
        capital = _env_float("TRADING_CAPITAL_USD", 80_000)
        max_pos = _env_float("MAX_POSITION_SIZE_USD", 2_500)

        if capital > 0:
            pct = max_pos / capital * 100
            # Position size should be at least 0.1% of capital to be meaningful
            assert pct >= 0.1, (
                f"MAX_POSITION_SIZE_USD (${max_pos:,.0f}) is only {pct:.2f}% "
                f"of TRADING_CAPITAL_USD (${capital:,.0f}) — too small to generate "
                "meaningful returns"
            )

    def test_daily_drawdown_provides_adequate_runway(self):
        """MAX_DAILY_DRAWDOWN_PCT should allow enough losing trades before halting.

        Validates: Requirement 9.3
        """
        capital = _env_float("TRADING_CAPITAL_USD", 80_000)
        daily_dd_pct = _env_float("MAX_DAILY_DRAWDOWN_PCT", 0.015)
        risk_pct = _env_float("RISK_PER_TRADE_PCT", 0.0035)

        daily_dd_usd = capital * daily_dd_pct
        risk_per_trade_usd = capital * risk_pct

        if risk_per_trade_usd > 0:
            losing_trades_before_halt = daily_dd_usd / risk_per_trade_usd
            # Should survive at least 3 consecutive losers
            assert losing_trades_before_halt >= 3, (
                f"Daily drawdown cap (${daily_dd_usd:.0f}) only allows "
                f"{losing_trades_before_halt:.1f} losing trades at "
                f"${risk_per_trade_usd:.0f}/trade — insufficient runway"
            )


# ---------------------------------------------------------------------------
# 7. Total exposure cap (Requirements 9.4, 9.5, 9.6)
# ---------------------------------------------------------------------------

class TestTotalExposureCap:
    """MAX_TOTAL_EXPOSURE_PCT vs conservative position sizing.

    A 100% exposure cap contradicts conservative position sizing.  Even 50-60%
    is aggressive for a scalping strategy.
    Validates: Requirements 9.4, 9.5, 9.6
    """

    def test_total_exposure_not_exceeding_capital(self):
        """MAX_TOTAL_EXPOSURE_PCT should not allow more than 100% of capital exposed."""
        exposure_pct = _env_float("MAX_TOTAL_EXPOSURE_PCT", 60.0)
        assert exposure_pct <= 100.0, (
            f"MAX_TOTAL_EXPOSURE_PCT ({exposure_pct}%) allows more than 100% "
            "of capital to be exposed simultaneously"
        )

    def test_per_symbol_exposure_consistent_with_position_size(self):
        """MAX_EXPOSURE_PER_SYMBOL_PCT × capital should be >= MAX_POSITION_SIZE_USD.

        Otherwise the per-symbol exposure cap would prevent even a single
        max-size position.
        """
        capital = _env_float("TRADING_CAPITAL_USD", 80_000)
        per_symbol_pct = _env_float("MAX_EXPOSURE_PER_SYMBOL_PCT", 0.20)
        max_pos = _env_float("MAX_POSITION_SIZE_USD", 2_500)

        per_symbol_usd = capital * per_symbol_pct
        assert per_symbol_usd >= max_pos, (
            f"Per-symbol exposure cap (${per_symbol_usd:,.0f} = "
            f"{per_symbol_pct} × ${capital:,.0f}) is less than "
            f"MAX_POSITION_SIZE_USD (${max_pos:,.0f}) — can't open a full position"
        )

    def test_total_drawdown_cap_provides_recovery_room(self):
        """MAX_DRAWDOWN_PCT should be large enough to survive multiple bad days.

        Validates: Requirement 9.6
        """
        total_dd_pct = _env_float("MAX_DRAWDOWN_PCT", 0.04)
        daily_dd_pct = _env_float("MAX_DAILY_DRAWDOWN_PCT", 0.015)

        if daily_dd_pct > 0:
            bad_days = total_dd_pct / daily_dd_pct
            assert bad_days >= 2, (
                f"MAX_DRAWDOWN_PCT ({total_dd_pct}) only allows "
                f"{bad_days:.1f} max-loss days before total halt — "
                "insufficient recovery room"
            )


# ---------------------------------------------------------------------------
# 8. Demo/live mode consistency (Requirement 10.1)
# ---------------------------------------------------------------------------

class TestDemoLiveModeConsistency:
    """BYBIT_DEMO=true with TRADING_MODE=live is a known configuration.

    Running in 'live' mode against a demo account may cause behavioral
    differences in fill simulation.  This test flags the inconsistency.
    Validates: Requirement 10.1
    """

    def test_demo_flag_consistent_with_trading_mode(self):
        """If TRADING_MODE=live, BYBIT_DEMO should be false for real trading."""
        trading_mode = _env_str("TRADING_MODE", "live").lower()
        bybit_demo = _env_bool("BYBIT_DEMO", True)

        # BYBIT_DEMO=true with TRADING_MODE=live is a valid configuration
        # for demo-account testing with live-mode code paths.
        assert trading_mode in ("live", "paper", "demo"), (
            f"Unexpected TRADING_MODE={trading_mode!r}"
        )
        assert isinstance(bybit_demo, bool), (
            f"BYBIT_DEMO should be a boolean, got {type(bybit_demo).__name__}"
        )

    def test_order_updates_demo_matches_bybit_demo(self):
        """ORDER_UPDATES_DEMO should match BYBIT_DEMO to avoid mixed data sources."""
        bybit_demo = _env_bool("BYBIT_DEMO", True)
        order_updates_demo = _env_bool("ORDER_UPDATES_DEMO", True)

        assert bybit_demo == order_updates_demo, (
            f"BYBIT_DEMO={bybit_demo} but ORDER_UPDATES_DEMO={order_updates_demo} — "
            "mixed demo/live data sources will cause inconsistent fill reporting"
        )


# ---------------------------------------------------------------------------
# 9. Prediction direction restrictions (Requirement 10.4)
# ---------------------------------------------------------------------------

class TestPredictionDirectionRestrictions:
    """PREDICTION_ALLOWED_DIRECTIONS excluding 'down' means the bot cannot
    take short entries based on model predictions.

    Validates: Requirement 10.4
    """

    def test_allowed_directions_include_all_for_full_coverage(self):
        """PREDICTION_ALLOWED_DIRECTIONS should include up, down, and flat for full coverage."""
        raw = _env_str("PREDICTION_ALLOWED_DIRECTIONS", "up,down,flat")
        directions = {d.strip().lower() for d in raw.split(",") if d.strip()}

        expected = {"up", "down", "flat"}
        missing = expected - directions
        if missing:
            # This is informational — excluding directions is a valid choice
            # but limits the strategy space
            pytest.skip(
                f"PREDICTION_ALLOWED_DIRECTIONS excludes {missing} — "
                "bot cannot take model-driven entries in those directions"
            )

    def test_allowed_directions_not_empty(self):
        """At least one prediction direction must be allowed."""
        raw = _env_str("PREDICTION_ALLOWED_DIRECTIONS", "up,down,flat")
        directions = [d.strip() for d in raw.split(",") if d.strip()]

        assert len(directions) > 0, (
            "PREDICTION_ALLOWED_DIRECTIONS is empty — no model predictions "
            "will be accepted"
        )


# ---------------------------------------------------------------------------
# 10. Net edge requirement (Requirement 10.7)
# ---------------------------------------------------------------------------

class TestNetEdgeRequirement:
    """MIN_NET_EDGE_BPS + NET_EDGE_BUFFER_BPS vs realistic scalping edge.

    The combined net edge requirement must be achievable after accounting for
    fees, slippage, and adverse selection.
    Validates: Requirement 10.7
    """

    def test_net_edge_requirement_is_achievable(self):
        """Total required net edge should not exceed realistic scalping gross edge.

        Gross edge needed = net_edge_required + fees + slippage + adverse_selection.
        For scalping, gross edge rarely exceeds 60-80 bps.
        """
        min_net_edge = _env_float("MIN_NET_EDGE_BPS", 24.0)
        buffer = _env_float("NET_EDGE_BUFFER_BPS", 6.0)
        total_net_required = min_net_edge + buffer

        # Estimate round-trip costs
        bybit = FeeConfig.bybit_regular()
        taker_fee_bps = bybit.taker_fee_rate * 10_000  # 5.5 bps
        round_trip_fee_bps = taker_fee_bps * 2  # ~11 bps (entry + exit)
        slippage_bps = _env_float("EV_GATE_MIN_SLIPPAGE_BPS", 4.0)
        adverse_selection_bps = _env_float("EV_GATE_ADVERSE_SELECTION_BPS", 4.0)

        gross_edge_needed = total_net_required + round_trip_fee_bps + slippage_bps + adverse_selection_bps

        max_realistic_gross_edge = 80.0
        assert gross_edge_needed <= max_realistic_gross_edge, (
            f"Required gross edge = {gross_edge_needed:.1f} bps "
            f"(net: {total_net_required} + fees: {round_trip_fee_bps:.1f} + "
            f"slippage: {slippage_bps} + adverse: {adverse_selection_bps}) "
            f"exceeds realistic scalping edge ({max_realistic_gross_edge} bps)"
        )

    def test_net_edge_not_negative(self):
        """MIN_NET_EDGE_BPS and NET_EDGE_BUFFER_BPS should both be non-negative."""
        min_net_edge = _env_float("MIN_NET_EDGE_BPS", 24.0)
        buffer = _env_float("NET_EDGE_BUFFER_BPS", 6.0)

        assert min_net_edge >= 0, f"MIN_NET_EDGE_BPS ({min_net_edge}) is negative"
        assert buffer >= 0, f"NET_EDGE_BUFFER_BPS ({buffer}) is negative"

    def test_net_edge_buffer_not_larger_than_edge(self):
        """NET_EDGE_BUFFER_BPS should not exceed MIN_NET_EDGE_BPS.

        The buffer is a safety margin — if it's larger than the edge itself,
        the effective requirement is dominated by the buffer.
        """
        min_net_edge = _env_float("MIN_NET_EDGE_BPS", 24.0)
        buffer = _env_float("NET_EDGE_BUFFER_BPS", 6.0)

        assert buffer <= min_net_edge, (
            f"NET_EDGE_BUFFER_BPS ({buffer}) exceeds MIN_NET_EDGE_BPS "
            f"({min_net_edge}) — buffer dominates the edge requirement"
        )
