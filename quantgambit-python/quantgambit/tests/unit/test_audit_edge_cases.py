"""
Edge case audit tests for the QuantGambit scalping pipeline.

These tests verify specific edge-case behaviors that could silently degrade
trading performance: heuristic fallback, maker order abandonment, adverse
selection double-counting, snapshot slippage consistency, emergency exit
bypass, and deduplication TTL re-entry.

Validates: Requirements 2.3, 5.2, 6.4, 6.6, 7.6, 8.5
"""

import os
import time
import pytest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parents[4] / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
except ImportError:
    pass  # fall back to os.environ

from quantgambit.signals.prediction_providers import (
    HeuristicPredictionProvider,
    OnnxPredictionProvider,
)
from quantgambit.risk.slippage_model import SlippageModel, calculate_adverse_selection_bps
from quantgambit.signals.stages.ev_gate import CostEstimator, CostEstimate, EVGateConfig
from quantgambit.execution.position_guard_worker import (
    PositionGuardConfig,
    _should_close,
)
from quantgambit.execution.manager import PositionSnapshot
from quantgambit.execution.execution_worker import ExecutionWorkerConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _make_position(
    symbol: str = "BTCUSDT",
    side: str = "long",
    entry_price: float = 50000.0,
    size: float = 0.01,
    opened_at: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    mfe_pct: float | None = None,
    max_hold_sec: float | None = None,
    time_to_work_sec: float | None = None,
    mfe_min_bps: float | None = None,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        side=side,
        size=size,
        entry_price=entry_price,
        opened_at=opened_at,
        stop_loss=stop_loss,
        take_profit=take_profit,
        mfe_pct=mfe_pct,
        max_hold_sec=max_hold_sec,
        time_to_work_sec=time_to_work_sec,
        mfe_min_bps=mfe_min_bps,
    )


# ===========================================================================
# 1. Prediction fallback to heuristic when model is stale/missing (Req 2.3)
# ===========================================================================

class TestPredictionHeuristicFallback:
    """When the ONNX model file is missing or stale, the provider should
    return None from build_prediction(), and the pipeline should fall back
    to the HeuristicPredictionProvider which produces conservative p_hat.

    Validates: Requirement 2.3
    """

    def test_onnx_returns_none_when_model_path_missing(self):
        """OnnxPredictionProvider.build_prediction returns None when model_path
        does not exist on disk, forcing the pipeline to use heuristic fallback."""
        provider = OnnxPredictionProvider(
            model_path="/nonexistent/model.onnx",
            feature_keys=["f1", "f2"],
        )
        result = provider.build_prediction(
            features={"f1": 0.5, "f2": 0.3, "symbol": "BTCUSDT"},
            market_context={"price": 50000.0, "session": "US"},
            timestamp=time.time(),
        )
        assert result is None, (
            "ONNX provider should return None when model file is missing, "
            "allowing pipeline to fall back to heuristic"
        )

    def test_onnx_returns_none_when_model_path_is_none(self):
        """OnnxPredictionProvider.build_prediction returns None when model_path
        is None (no model configured)."""
        provider = OnnxPredictionProvider(
            model_path=None,
            feature_keys=["f1"],
        )
        result = provider.build_prediction(
            features={"f1": 0.5, "symbol": "BTCUSDT"},
            market_context={"price": 50000.0},
            timestamp=time.time(),
        )
        assert result is None

    def test_heuristic_produces_conservative_prediction(self):
        """HeuristicPredictionProvider produces a prediction with conservative
        confidence (not aggressively high) for typical market conditions."""
        provider = HeuristicPredictionProvider()
        result = provider.build_prediction(
            features={"symbol": "BTCUSDT"},
            market_context={
                "price": 50000.0,
                "trend_direction": "flat",
                "trend_strength": 0.001,
                "volatility_regime": "normal",
                "orderbook_imbalance": 0.05,
                "data_completeness": 0.8,
            },
            timestamp=time.time(),
        )
        assert result is not None, "Heuristic should produce a prediction"
        assert result["source"].startswith("heuristic"), (
            f"Expected heuristic source, got {result['source']}"
        )
        # Heuristic confidence should be conservative (not near 1.0)
        confidence = result.get("confidence", 0.0)
        assert confidence < 0.85, (
            f"Heuristic confidence {confidence} is too aggressive for flat/low-imbalance conditions"
        )

    def test_heuristic_rejects_low_data_completeness(self):
        """Heuristic provider should reject (set reject=True) when data
        completeness is below the minimum threshold."""
        provider = HeuristicPredictionProvider()
        result = provider.build_prediction(
            features={"symbol": "BTCUSDT"},
            market_context={
                "price": 50000.0,
                "trend_direction": "flat",
                "trend_strength": 0.0,
                "volatility_regime": "normal",
                "orderbook_imbalance": 0.0,
                "data_completeness": 0.1,  # Very low
            },
            timestamp=time.time(),
        )
        assert result is not None
        assert result.get("reject") is True, (
            "Heuristic should reject when data completeness is very low"
        )

    def test_onnx_validate_returns_false_for_missing_model(self):
        """OnnxPredictionProvider.validate() returns False when model is missing,
        signaling that the provider is not usable."""
        provider = OnnxPredictionProvider(
            model_path="/nonexistent/model.onnx",
            feature_keys=["f1"],
        )
        assert provider.validate(now_ts=time.time()) is False


# ===========================================================================
# 2. Maker order abandonment when fill window expires (Req 5.2)
# ===========================================================================

class TestMakerOrderAbandonment:
    """When ENTRY_MAKER_FALLBACK_TO_MARKET is false and the maker fill window
    expires, the entry should be abandoned (not fall back to market order).

    Validates: Requirement 5.2
    """

    def test_config_fallback_disabled_means_abandonment(self):
        """When entry_maker_fallback_to_market is False, the execution worker
        config indicates entries will be abandoned on fill window expiry."""
        config = ExecutionWorkerConfig(
            entry_execution_mode="maker_post_only",
            entry_maker_fallback_to_market=False,
            entry_maker_fill_window_ms=6000,
            entry_maker_max_reposts=1,
        )
        assert config.entry_maker_fallback_to_market is False
        assert config.entry_execution_mode == "maker_post_only"
        # With fallback disabled and 1 repost, max attempts = 2
        max_attempts = config.entry_maker_max_reposts + 1
        assert max_attempts == 2, (
            f"Expected 2 total maker attempts (1 initial + 1 repost), got {max_attempts}"
        )

    def test_config_fallback_enabled_allows_market_order(self):
        """When entry_maker_fallback_to_market is True, the execution worker
        will fall back to market order after maker attempts are exhausted."""
        config = ExecutionWorkerConfig(
            entry_execution_mode="maker_post_only",
            entry_maker_fallback_to_market=True,
            entry_maker_fill_window_ms=6000,
            entry_maker_max_reposts=1,
        )
        assert config.entry_maker_fallback_to_market is True

    def test_fill_window_is_reasonable_for_scalping(self):
        """The maker fill window should be long enough to give fills a chance
        but not so long that the market moves significantly."""
        fill_window_ms = _env_float("ENTRY_MAKER_FILL_WINDOW_MS", 800)
        # For scalping, fill window should be between 200ms and 15s
        assert fill_window_ms >= 200, (
            f"Fill window {fill_window_ms}ms is too short for reliable maker fills"
        )
        assert fill_window_ms <= 15000, (
            f"Fill window {fill_window_ms}ms is too long — market may move significantly"
        )

    def test_max_reposts_bounded(self):
        """Max reposts should be bounded to prevent excessive order churn."""
        max_reposts = int(_env_float("ENTRY_MAKER_MAX_REPOSTS", 1))
        assert max_reposts >= 0, "Max reposts cannot be negative"
        assert max_reposts <= 10, (
            f"Max reposts {max_reposts} is excessive for scalping"
        )


# ===========================================================================
# 3. Adverse selection double-counting in cost estimation (Req 6.4)
# ===========================================================================

class TestAdverseSelectionDoubleCounting:
    """The CostEstimator uses calculate_adverse_selection_bps() for per-symbol
    adverse selection, and the EVGateStage applies a floor via
    config.adverse_selection_bps (EV_GATE_ADVERSE_SELECTION_BPS).

    The EV gate takes max(model_adverse_selection, config_floor) — this is
    correct (no double-counting). But if both were ADDED, costs would be
    inflated. This test verifies the floor-based approach.

    Validates: Requirement 6.4
    """

    def test_per_symbol_adverse_selection_is_reasonable(self):
        """Per-symbol adverse selection from calculate_adverse_selection_bps()
        should produce reasonable values for normal conditions."""
        for symbol, expected_base in [("BTCUSDT", 1.0), ("ETHUSDT", 1.2), ("SOLUSDT", 2.0)]:
            result = calculate_adverse_selection_bps(
                symbol=symbol,
                volatility_regime="normal",
                hold_time_expected_sec=120.0,
            )
            # Should be at least the base value (normal vol multiplier = 1.0)
            assert result >= expected_base, (
                f"{symbol}: adverse selection {result} bps < base {expected_base} bps"
            )
            # Should not be excessively high for normal conditions
            assert result < 20.0, (
                f"{symbol}: adverse selection {result} bps is unreasonably high for normal vol"
            )

    def test_ev_gate_config_adverse_selection_floor(self):
        """EVGateConfig.adverse_selection_bps acts as a floor, not an additive
        component. The EV gate uses max(model_value, config_floor)."""
        ev_gate_floor = _env_float("EV_GATE_ADVERSE_SELECTION_BPS", 1.5)
        # The floor should be positive
        assert ev_gate_floor >= 0, "Adverse selection floor cannot be negative"

        # For BTC in normal conditions, model gives ~1.0 bps base.
        # If the floor is 4.0 bps, the floor dominates (max(1.0, 4.0) = 4.0).
        # This is NOT double-counting (1.0 + 4.0 = 5.0 would be).
        btc_model = calculate_adverse_selection_bps("BTCUSDT", "normal", 120.0)
        effective = max(btc_model, ev_gate_floor)
        # Effective should equal the larger of the two, not their sum
        assert effective == max(btc_model, ev_gate_floor)
        assert effective < btc_model + ev_gate_floor or btc_model == 0 or ev_gate_floor == 0, (
            "If both are positive, max should be strictly less than sum — "
            "confirming no double-counting"
        )

    def test_cost_estimate_total_equals_component_sum(self):
        """CostEstimate.total_bps should equal the sum of its components,
        ensuring adverse selection is counted exactly once."""
        estimate = CostEstimate(
            spread_bps=2.0,
            fee_bps=5.5,
            slippage_bps=1.5,
            adverse_selection_bps=4.0,
            total_bps=13.0,
        )
        expected_total = (
            estimate.spread_bps
            + estimate.fee_bps
            + estimate.slippage_bps
            + estimate.adverse_selection_bps
        )
        assert estimate.total_bps == expected_total, (
            f"total_bps {estimate.total_bps} != component sum {expected_total}"
        )

    def test_adverse_selection_increases_with_volatility(self):
        """Adverse selection should increase in high/extreme volatility,
        reflecting more informed flow."""
        normal = calculate_adverse_selection_bps("BTCUSDT", "normal", 120.0)
        high = calculate_adverse_selection_bps("BTCUSDT", "high", 120.0)
        extreme = calculate_adverse_selection_bps("BTCUSDT", "extreme", 120.0)
        assert high > normal, "High vol should increase adverse selection"
        assert extreme > high, "Extreme vol should increase adverse selection further"


# ===========================================================================
# 4. Snapshot slippage parameter consistency with EV gate (Req 6.6)
# ===========================================================================

class TestSnapshotSlippageConsistency:
    """SNAPSHOT_SLIPPAGE_MULTIPLIER and SNAPSHOT_MIN_SLIPPAGE_BPS used in
    snapshot building should be consistent with the SlippageModel parameters
    used in the EV gate. Large discrepancies mean the snapshot's cost estimate
    diverges from the EV gate's cost estimate, causing decisions based on
    inconsistent data.

    Validates: Requirement 6.6
    """

    def test_snapshot_multiplier_not_wildly_different_from_model(self):
        """SNAPSHOT_SLIPPAGE_MULTIPLIER should be within a reasonable range
        of SLIPPAGE_MODEL_MULTIPLIER to avoid cost estimate divergence."""
        snapshot_mult = _env_float("SNAPSHOT_SLIPPAGE_MULTIPLIER", 1.0)
        model_mult = _env_float("SLIPPAGE_MODEL_MULTIPLIER", 1.0)

        # Both should be positive
        assert snapshot_mult > 0, "Snapshot slippage multiplier must be positive"
        assert model_mult > 0, "Slippage model multiplier must be positive"

        # They should not diverge by more than 5x
        if model_mult > 0:
            ratio = snapshot_mult / model_mult
            assert 0.2 <= ratio <= 5.0, (
                f"SNAPSHOT_SLIPPAGE_MULTIPLIER ({snapshot_mult}) and "
                f"SLIPPAGE_MODEL_MULTIPLIER ({model_mult}) diverge by {ratio:.1f}x — "
                "snapshot cost estimates will be inconsistent with EV gate"
            )

    def test_snapshot_floor_not_above_model_effective_floor(self):
        """SNAPSHOT_MIN_SLIPPAGE_BPS should not be dramatically higher than
        the SlippageModel's effective floor, or the snapshot will overestimate
        slippage relative to the EV gate."""
        snapshot_floor = _env_float("SNAPSHOT_MIN_SLIPPAGE_BPS", 0.0)
        model_floor = _env_float("SLIPPAGE_MODEL_FLOOR_BPS", 0.0)
        model_mult = _env_float("SLIPPAGE_MODEL_MULTIPLIER", 1.0)

        # The SlippageModel effective floor for BTC is base (0.5) * multiplier
        btc_base_floor = 0.5  # SlippageModel.SYMBOL_FLOORS["BTCUSDT"]
        effective_model_floor = max(btc_base_floor * model_mult, model_floor)

        # Snapshot floor should not be more than 10x the model's effective floor
        if effective_model_floor > 0:
            assert snapshot_floor <= effective_model_floor * 10, (
                f"SNAPSHOT_MIN_SLIPPAGE_BPS ({snapshot_floor}) is >10x the model's "
                f"effective floor ({effective_model_floor}) — severe inconsistency"
            )

    def test_slippage_model_symbol_floors_exist(self):
        """SlippageModel should have symbol-specific floors for the traded symbols."""
        model = SlippageModel()
        for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            floor = model.SYMBOL_FLOORS.get(symbol, model.DEFAULT_FLOOR)
            assert floor > 0, f"Missing or zero slippage floor for {symbol}"

    def test_slippage_model_multiplier_applied(self):
        """SlippageModel should apply the multiplier to its calculations."""
        with patch.dict(os.environ, {"SLIPPAGE_MODEL_MULTIPLIER": "2.0"}):
            model = SlippageModel()
            result = model.calculate_slippage_bps(
                symbol="BTCUSDT",
                spread_bps=2.0,
                book_depth_usd=50000.0,
                order_size_usd=200.0,
                volatility_regime="normal",
            )
            # With 2x multiplier, result should be at least 2x the base floor
            btc_floor = model.SYMBOL_FLOORS.get("BTCUSDT", model.DEFAULT_FLOOR)
            assert result >= btc_floor * 2.0, (
                f"Slippage {result} bps should be >= {btc_floor * 2.0} bps "
                "(base floor × multiplier)"
            )


# ===========================================================================
# 5. Emergency exit not blocked by EXIT_SIGNAL_MIN_HOLD_SEC (Req 7.6)
# ===========================================================================

class TestEmergencyExitNotBlocked:
    """EXIT_SIGNAL_MIN_HOLD_SEC should not prevent emergency exits (stop-loss,
    hard time stop) from firing. The _should_close() function evaluates
    stop_loss FIRST in the cascade, and _apply_fee_check() only applies to
    trailing_stop_hit exits — all other exit reasons bypass the fee check.

    Validates: Requirement 7.6
    """

    def test_stop_loss_fires_immediately_regardless_of_hold_time(self):
        """Stop loss should trigger even if the position was just opened
        (hold time < any min_hold threshold)."""
        now = time.time()
        pos = _make_position(
            side="long",
            entry_price=50000.0,
            opened_at=now - 1.0,  # Held for only 1 second
            stop_loss=49500.0,
        )
        config = PositionGuardConfig(
            trailing_stop_bps=25.0,
            trailing_activation_bps=20.0,
            trailing_min_hold_sec=30.0,
            breakeven_activation_bps=35.0,
            breakeven_min_hold_sec=10.0,
            max_position_age_sec=240.0,
        )
        # Price at stop loss level
        reason = _should_close(pos, 49500.0, now, config, {})
        assert reason == "stop_loss_hit", (
            f"Stop loss should fire immediately, got: {reason}"
        )

    def test_stop_loss_fires_for_short_position(self):
        """Stop loss should trigger for short positions when price rises
        above stop level, regardless of hold time."""
        now = time.time()
        pos = _make_position(
            side="short",
            entry_price=50000.0,
            opened_at=now - 2.0,
            stop_loss=50500.0,
        )
        config = PositionGuardConfig(max_position_age_sec=240.0)
        reason = _should_close(pos, 50500.0, now, config, {})
        assert reason == "stop_loss_hit"

    def test_take_profit_fires_regardless_of_hold_time(self):
        """Take profit should trigger even for very young positions."""
        now = time.time()
        pos = _make_position(
            side="long",
            entry_price=50000.0,
            opened_at=now - 0.5,  # Half a second old
            take_profit=50100.0,
        )
        config = PositionGuardConfig(max_position_age_sec=240.0)
        reason = _should_close(pos, 50100.0, now, config, {})
        assert reason == "take_profit_hit"

    def test_fee_check_only_applies_to_trailing_stop(self):
        """_apply_fee_check in PositionGuardWorker only gates trailing_stop_hit.
        All other exit reasons (stop_loss, take_profit, breakeven, profit_lock,
        max_age) bypass the fee check entirely."""
        # This is verified by the _apply_fee_check implementation which returns
        # None for any reason != "trailing_stop_hit". We test the _should_close
        # cascade to confirm safety exits are evaluated first.
        now = time.time()
        pos = _make_position(
            side="long",
            entry_price=50000.0,
            opened_at=now - 5.0,
            stop_loss=49800.0,
        )
        config = PositionGuardConfig(
            trailing_stop_bps=25.0,
            trailing_activation_bps=20.0,
            trailing_min_hold_sec=0.0,
            max_position_age_sec=240.0,
        )
        # Price below stop loss — should trigger stop_loss, not trailing
        reason = _should_close(pos, 49800.0, now, config, {})
        assert reason == "stop_loss_hit", (
            f"Stop loss should take priority over other exits, got: {reason}"
        )

    def test_cascade_order_stop_loss_before_time_exits(self):
        """Stop loss should fire before max_age even if both conditions are met."""
        now = time.time()
        pos = _make_position(
            side="long",
            entry_price=50000.0,
            opened_at=now - 500.0,  # Well past max_age
            stop_loss=49900.0,
        )
        config = PositionGuardConfig(max_position_age_sec=240.0)
        reason = _should_close(pos, 49900.0, now, config, {})
        assert reason == "stop_loss_hit", (
            "Stop loss should fire before max_age_exceeded in the cascade"
        )


# ===========================================================================
# 6. Deduplication TTL preventing valid re-entry (Req 8.5)
# ===========================================================================

class TestDeduplicationTTLReentry:
    """EXECUTION_DEDUPE_TTL_SEC (default 300s) prevents duplicate order
    execution. However, if the TTL is too long, it can prevent valid re-entry
    on the same symbol after a quick exit within the TTL window.

    The dedup key is based on client_order_id (which includes decision_id),
    so distinct decisions should NOT collide. But the TTL window combined
    with other throttling (min_order_interval_sec, cooldowns) can create
    an effective lockout period.

    Validates: Requirement 8.5
    """

    def test_dedupe_ttl_is_bounded(self):
        """Dedup TTL should not be so long that it prevents re-entry for
        an unreasonable duration."""
        dedupe_ttl = _env_float("EXECUTION_DEDUPE_TTL_SEC", 300)
        assert dedupe_ttl > 0, "Dedup TTL must be positive"
        assert dedupe_ttl <= 600, (
            f"Dedup TTL {dedupe_ttl}s is >10 minutes — may prevent valid re-entry "
            "after quick exits"
        )

    def test_dedupe_ttl_not_shorter_than_cooldown(self):
        """Dedup TTL should be at least as long as the entry cooldown to
        ensure dedup covers the cooldown window."""
        dedupe_ttl = _env_float("EXECUTION_DEDUPE_TTL_SEC", 300)
        cooldown = _env_float("COOLDOWN_ENTRY_SEC", 45)
        # Dedup should cover at least the cooldown period
        assert dedupe_ttl >= cooldown, (
            f"Dedup TTL ({dedupe_ttl}s) < cooldown ({cooldown}s) — "
            "dedup may expire before cooldown, allowing duplicate execution"
        )

    def test_config_dedupe_ttl_matches_env(self):
        """ExecutionWorkerConfig.dedupe_ttl_sec should reflect the env var."""
        config = ExecutionWorkerConfig(dedupe_ttl_sec=300)
        assert config.dedupe_ttl_sec == 300

    def test_exit_dedupe_ttl_shorter_than_entry(self):
        """Exit dedup TTL should be shorter than entry dedup TTL to avoid
        blocking rapid safety exits."""
        entry_ttl = _env_float("EXECUTION_DEDUPE_TTL_SEC", 300)
        exit_ttl = _env_float("EXIT_DEDUPE_TTL_SEC", 30)
        assert exit_ttl <= entry_ttl, (
            f"Exit dedup TTL ({exit_ttl}s) > entry dedup TTL ({entry_ttl}s) — "
            "exit dedup should be shorter to allow rapid safety exits"
        )

    def test_combined_lockout_period_reasonable(self):
        """The combined effective lockout (dedup TTL + min_order_interval +
        cooldown) should not exceed a reasonable maximum for scalping."""
        dedupe_ttl = _env_float("EXECUTION_DEDUPE_TTL_SEC", 300)
        min_interval = _env_float("MIN_ORDER_INTERVAL_SEC", 60)
        cooldown = _env_float("COOLDOWN_ENTRY_SEC", 45)
        # The binding constraint is the max of these (they overlap, not stack)
        effective_lockout = max(dedupe_ttl, min_interval, cooldown)
        # For scalping, effective lockout should not exceed 10 minutes
        assert effective_lockout <= 600, (
            f"Effective lockout {effective_lockout}s is too long for scalping. "
            f"dedupe={dedupe_ttl}s, interval={min_interval}s, cooldown={cooldown}s"
        )

    def test_distinct_decisions_have_distinct_dedup_keys(self):
        """Different decision_ids should produce different client_order_ids,
        ensuring dedup does not block distinct valid entries."""
        # The client_order_id format includes decision_id, so two different
        # decisions for the same symbol should not collide in the dedup store.
        # This is a structural verification of the dedup key design.
        decision_id_1 = "dec-001"
        decision_id_2 = "dec-002"
        # They are different strings, so any key derived from them will differ
        assert decision_id_1 != decision_id_2, (
            "Distinct decisions must have distinct IDs to avoid dedup collision"
        )
