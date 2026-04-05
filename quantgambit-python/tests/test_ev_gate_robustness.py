"""
Tests for EVGate Robustness with Conservative Fallbacks.

Tests the robustness functionality implemented in Task 6:
- 6.1: Updated required fields (only entry_price, side, SL, TP)
- 6.2: Conservative p_hat fallbacks
- 6.3: compute_defaults method
- 6.4: _get_ev_min_adjusted_for_calibration method
- 6.5: Integration tests for EVGate robustness

Requirements: 5.1-5.10 from Strategy Signal Architecture Fixes spec
"""

import pytest
import asyncio
from types import SimpleNamespace
from quantgambit.signals.stages.ev_gate import (
    EVGateStage,
    EVGateConfig,
    EVGateRejectCode,
    REGIME_P_HAT_DEFAULTS_CONSERVATIVE,
    P_MARGIN_UNCALIBRATED_DEFAULT,
)
from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.services.calibration_state import CalibrationState


import time

def make_context(symbol: str, signal: dict, market_context: dict = None, features: dict = None, prediction: dict = None) -> StageContext:
    """Helper to create a StageContext with the required data structure."""
    market_context = market_context or {}
    # Add timestamp if not present (required for staleness checks)
    if "timestamp_ms" not in market_context and "book_timestamp_ms" not in market_context:
        market_context["timestamp_ms"] = time.time() * 1000
    
    ctx = StageContext(
        symbol=symbol,
        data={
            "market_context": market_context,
            "features": features or {},
            "prediction": prediction or {},
        }
    )
    ctx.signal = signal
    return ctx


class TestConservativePHatDefaults:
    """Tests for conservative p_hat fallback values (Requirement 5.3)."""
    
    def test_conservative_defaults_values(self):
        """Verify conservative p_hat defaults are lower than before."""
        assert REGIME_P_HAT_DEFAULTS_CONSERVATIVE["mean_reversion"] == 0.48
        assert REGIME_P_HAT_DEFAULTS_CONSERVATIVE["breakout"] == 0.45
        assert REGIME_P_HAT_DEFAULTS_CONSERVATIVE["trend_pullback"] == 0.47
        assert REGIME_P_HAT_DEFAULTS_CONSERVATIVE["low_vol_grind"] == 0.48
        assert REGIME_P_HAT_DEFAULTS_CONSERVATIVE["default"] == 0.45
    
    def test_p_margin_uncalibrated_default(self):
        """Verify p_margin_uncalibrated is 0.03 (Requirement 5.4)."""
        assert P_MARGIN_UNCALIBRATED_DEFAULT == 0.03
    
    def test_config_p_margin_uncalibrated(self):
        """Verify EVGateConfig has updated p_margin_uncalibrated."""
        config = EVGateConfig()
        assert config.p_margin_uncalibrated == 0.03


class TestRequiredFieldsUpdate:
    """Tests for updated required fields (Requirement 5.1)."""
    
    def test_accepts_signal_with_sl_distance_bps(self):
        """Signal with sl_distance_bps should be accepted."""
        config = EVGateConfig(mode="enforce", ev_min=0.0, ev_min_floor=0.0)
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "sl_distance_bps": 100.0,  # 1% stop loss
                "tp_distance_bps": 200.0,  # 2% take profit
            },
            market_context={
                "price": 50000.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should not be rejected for missing fields
        if ctx.rejection_stage == "ev_gate":
            assert ctx.rejection_reason != "MISSING_REQUIRED_FIELD"
    
    def test_accepts_signal_with_sl_price(self):
        """Signal with sl_price should be accepted."""
        config = EVGateConfig(mode="enforce", ev_min=0.0, ev_min_floor=0.0)
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "sl_price": 49500.0,  # Stop loss price
                "tp_price": 51000.0,  # Take profit price
            },
            market_context={
                "price": 50000.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should not be rejected for missing fields
        if ctx.rejection_stage == "ev_gate":
            assert ctx.rejection_reason != "MISSING_REQUIRED_FIELD"
    
    def test_accepts_signal_with_stop_loss(self):
        """Signal with stop_loss (legacy field) should be accepted."""
        config = EVGateConfig(mode="enforce", ev_min=0.0, ev_min_floor=0.0)
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49500.0,
                "take_profit": 51000.0,
            },
            market_context={
                "price": 50000.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should not be rejected for missing fields
        if ctx.rejection_stage == "ev_gate":
            assert ctx.rejection_reason != "MISSING_REQUIRED_FIELD"
    
    def test_rejects_signal_without_sl(self):
        """Signal without any SL field should be rejected."""
        config = EVGateConfig(mode="enforce")
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                # No SL field
                "tp_distance_bps": 200.0,
            },
            market_context={
                "price": 50000.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert ctx.rejection_stage == "ev_gate"
        assert ctx.rejection_reason == "MISSING_REQUIRED_FIELD"
        assert "sl_distance_bps or sl_price" in ctx.rejection_detail.get("reject_reason", "")
    
    def test_rejects_signal_without_tp(self):
        """Signal without any TP field should be rejected."""
        config = EVGateConfig(mode="enforce")
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "sl_distance_bps": 100.0,
                # No TP field
            },
            market_context={
                "price": 50000.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert ctx.rejection_stage == "ev_gate"
        assert ctx.rejection_reason == "MISSING_REQUIRED_FIELD"
        assert "tp_distance_bps or tp_price" in ctx.rejection_detail.get("reject_reason", "")
    
    def test_does_not_reject_for_missing_bid_ask(self):
        """Signal without bid/ask should NOT be rejected (defaults applied)."""
        config = EVGateConfig(mode="enforce", ev_min=0.0, ev_min_floor=0.0)
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "sl_distance_bps": 100.0,
                "tp_distance_bps": 200.0,
            },
            market_context={
                "price": 50000.0,
                # No bid/ask - should be defaulted
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should not be rejected for missing bid/ask
        if ctx.rejection_stage == "ev_gate":
            assert "best_bid" not in ctx.rejection_detail.get("reject_reason", "")
            assert "best_ask" not in ctx.rejection_detail.get("reject_reason", "")
    
    def test_does_not_reject_for_missing_confidence(self):
        """Signal without prediction confidence should NOT be rejected (defaults applied)."""
        config = EVGateConfig(mode="enforce", ev_min=0.0, ev_min_floor=0.0)
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "sl_distance_bps": 100.0,
                "tp_distance_bps": 200.0,
            },
            market_context={
                "price": 50000.0,
            },
            prediction={},  # No confidence - should use conservative fallback
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should not be rejected for missing confidence
        if ctx.rejection_stage == "ev_gate":
            assert "confidence" not in ctx.rejection_detail.get("reject_reason", "")


class TestComputeDefaults:
    """Tests for compute_defaults method (Requirement 5.7)."""
    
    def test_defaults_p_hat_for_mean_reversion(self):
        """p_hat should be defaulted to conservative value for mean_reversion."""
        config = EVGateConfig(mode="shadow")  # Shadow mode to see result without rejection
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49500.0,
                "take_profit": 51000.0,
                "strategy_id": "mean_reversion_fade",
            },
            market_context={
                "price": 50000.0,
                "best_bid": 49999.5,
                "best_ask": 50000.5,
                "spread_timestamp_ms": time.time() * 1000,
            },
            prediction={},  # No confidence
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Check that p_hat was defaulted
        ev_result = ctx.data.get("ev_gate_result")
        if ev_result:
            assert ev_result.p_calibrated == pytest.approx(0.48, abs=0.01)
            # calibration_method now reflects the calibration state (cold/warming/ok)
            # With 0 trades, it should be "cold"
            assert ev_result.calibration_method == "cold"
    
    def test_defaults_p_hat_for_breakout(self):
        """p_hat should be defaulted to conservative value for breakout."""
        config = EVGateConfig(mode="shadow")
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49500.0,
                "take_profit": 51000.0,
                "strategy_id": "breakout_scalp",
            },
            market_context={
                "price": 50000.0,
            },
            prediction={},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        ev_result = ctx.data.get("ev_gate_result")
        if ev_result:
            assert ev_result.p_calibrated == pytest.approx(0.45, abs=0.01)
    
    def test_defaults_cost_estimate(self):
        """cost_estimate should be defaulted from context."""
        config = EVGateConfig(mode="shadow")
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49500.0,
                "take_profit": 51000.0,
            },
            market_context={
                "price": 50000.0,
                "spread_bps": 2.0,  # Custom spread
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Cost estimate should include spread + fee + slippage
        ev_result = ctx.data.get("ev_gate_result")
        if ev_result:
            # Should have some cost estimate
            assert ev_result.total_cost_bps > 0
    
    def test_converts_sl_price_to_distance(self):
        """SL price should be converted to distance."""
        config = EVGateConfig(mode="shadow")
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "sl_price": 49500.0,  # 1% below entry
                "tp_price": 51000.0,  # 2% above entry
            },
            market_context={
                "price": 50000.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        ev_result = ctx.data.get("ev_gate_result")
        if ev_result:
            # L should be approximately 100 bps (1%)
            assert ev_result.L_bps == pytest.approx(100.0, rel=0.1)
            # G should be approximately 200 bps (2%)
            assert ev_result.G_bps == pytest.approx(200.0, rel=0.1)
    
    def test_converts_tp_price_to_distance(self):
        """TP price should be converted to distance."""
        config = EVGateConfig(mode="shadow")
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "short",
                "entry_price": 50000.0,
                "sl_price": 50500.0,  # 1% above entry (stop for short)
                "tp_price": 49000.0,  # 2% below entry (target for short)
            },
            market_context={
                "price": 50000.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        ev_result = ctx.data.get("ev_gate_result")
        if ev_result:
            # L should be approximately 100 bps (1%)
            assert ev_result.L_bps == pytest.approx(100.0, rel=0.1)
            # G should be approximately 200 bps (2%)
            assert ev_result.G_bps == pytest.approx(200.0, rel=0.1)


class TestEVMinAdjustedForCalibration:
    """Tests for _get_ev_min_adjusted_for_calibration method (Requirement 5.4)."""
    
    def test_increases_ev_min_for_uncalibrated_p_hat(self):
        """ev_min should be increased by p_margin_uncalibrated when p_hat is uncalibrated."""
        config = EVGateConfig(
            mode="enforce",
            ev_min=0.02,
            p_margin_uncalibrated=0.03,
        )
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49500.0,
                "take_profit": 51000.0,
                "strategy_id": "mean_reversion_fade",
            },
            market_context={
                "price": 50000.0,
            },
            prediction={},  # No confidence - will use uncalibrated fallback
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Check that ev_min was adjusted
        if ctx.rejection_detail:
            ev_min_adjusted = ctx.rejection_detail.get("ev_min_adjusted", 0)
            # Should include the uncalibrated margin
            assert ev_min_adjusted >= config.ev_min + config.p_margin_uncalibrated
    
    def test_no_increase_for_calibrated_p_hat(self):
        """ev_min should NOT be increased when p_hat is calibrated."""
        config = EVGateConfig(
            mode="enforce",
            ev_min=0.02,
            p_margin_uncalibrated=0.03,
        )
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49500.0,
                "take_profit": 51000.0,
                "p_hat": 0.55,  # Explicitly provided p_hat
                "p_hat_source": "calibrated",
            },
            market_context={
                "price": 50000.0,
            },
            prediction={"confidence": 0.55},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Check that ev_min was NOT adjusted for uncalibrated margin
        if ctx.rejection_detail:
            ev_min_adjusted = ctx.rejection_detail.get("ev_min_adjusted", 0)
            # Should NOT include the uncalibrated margin (just base ev_min)
            assert ev_min_adjusted < config.ev_min + config.p_margin_uncalibrated


class TestIntegrationEVGateRobustness:
    """Integration tests for EVGate robustness (Requirement 5)."""
    
    def test_signal_with_minimal_fields_passes(self):
        """Signal with only required fields should pass with defaults."""
        config = EVGateConfig(
            mode="enforce",
            ev_min=0.0,  # Disable EV threshold for this test
            ev_min_floor=0.0,
        )
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "sl_distance_bps": 100.0,
                "tp_distance_bps": 200.0,
            },
            market_context={
                "price": 50000.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should pass (not rejected)
        assert result == StageResult.CONTINUE
    
    def test_signal_with_distance_based_sl_tp(self):
        """Signal with distance-based SL/TP should work correctly."""
        config = EVGateConfig(
            mode="shadow",
        )
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "sl_distance_bps": 100.0,  # 1% stop
                "tp_distance_bps": 200.0,  # 2% target
            },
            market_context={
                "price": 50000.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        ev_result = ctx.data.get("ev_gate_result")
        if ev_result:
            assert ev_result.L_bps == pytest.approx(100.0, rel=0.1)
            assert ev_result.G_bps == pytest.approx(200.0, rel=0.1)
            assert ev_result.R == pytest.approx(2.0, rel=0.1)
    
    def test_signal_with_price_based_sl_tp(self):
        """Signal with price-based SL/TP should work correctly."""
        config = EVGateConfig(
            mode="shadow",
        )
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "sl_price": 49500.0,  # 1% below
                "tp_price": 51000.0,  # 2% above
            },
            market_context={
                "price": 50000.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        ev_result = ctx.data.get("ev_gate_result")
        if ev_result:
            assert ev_result.L_bps == pytest.approx(100.0, rel=0.1)
            assert ev_result.G_bps == pytest.approx(200.0, rel=0.1)
            assert ev_result.R == pytest.approx(2.0, rel=0.1)
    
    def test_calibration_method_set_correctly(self):
        """calibration_method should be set to calibration state when using fallback."""
        config = EVGateConfig(mode="shadow")
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49500.0,
                "take_profit": 51000.0,
                "strategy_id": "mean_reversion_fade",
            },
            market_context={
                "price": 50000.0,
            },
            prediction={},  # No confidence
        )
        
        result = asyncio.run(stage.run(ctx))
        
        ev_result = ctx.data.get("ev_gate_result")
        if ev_result:
            # calibration_method now reflects the calibration state (cold/warming/ok)
            # With 0 trades (default), it should be "cold"
            assert ev_result.calibration_method == "cold"
    
    def test_defaulted_fields_tracked(self):
        """Defaulted fields should be tracked in result."""
        config = EVGateConfig(mode="shadow")
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49500.0,
                "take_profit": 51000.0,
            },
            market_context={
                "price": 50000.0,
            },
            prediction={},  # No confidence - will be defaulted
        )
        
        result = asyncio.run(stage.run(ctx))
        
        ev_result = ctx.data.get("ev_gate_result")
        if ev_result and ev_result.defaulted_fields:
            # p_hat should be in defaulted fields
            assert "p_hat" in ev_result.defaulted_fields


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing signals."""
    
    def test_legacy_stop_loss_take_profit_fields(self):
        """Legacy stop_loss and take_profit fields should still work."""
        config = EVGateConfig(mode="shadow")
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49500.0,  # Legacy field
                "take_profit": 51000.0,  # Legacy field
            },
            market_context={
                "price": 50000.0,
            },
            prediction={"confidence": 0.55},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should work without errors
        assert result == StageResult.CONTINUE
        
        ev_result = ctx.data.get("ev_gate_result")
        if ev_result:
            assert ev_result.L_bps > 0
            assert ev_result.G_bps > 0
    
    def test_target_price_field(self):
        """target_price field should be accepted as TP."""
        config = EVGateConfig(mode="shadow")
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "entry_price": 50000.0,
                "stop_loss": 49500.0,
                "target_price": 51000.0,  # Alternative TP field
            },
            market_context={
                "price": 50000.0,
            },
            prediction={"confidence": 0.55},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should work without errors
        assert result == StageResult.CONTINUE


def test_mean_reversion_fade_uses_uncalibrated_buffer_to_clear_p_min(monkeypatch):
    monkeypatch.setenv("EV_GATE_COST_MULTIPLE", "0")
    from quantgambit.signals.stages import ev_gate as ev_gate_module

    monkeypatch.setattr(
        ev_gate_module,
        "evaluate_calibration",
        lambda **kwargs: SimpleNamespace(
            state=CalibrationState.COLD,
            p_effective=0.44,
            reliability=0.0,
            size_multiplier=1.0,
            min_edge_bps_adjustment=4.0,
        ),
    )
    config = EVGateConfig(mode="shadow", ev_min=0.0, ev_min_floor=0.0)
    stage = EVGateStage(config=config)

    ctx = make_context(
        symbol="SOLUSDT",
        signal={
            "side": "long",
            "strategy_id": "mean_reversion_fade",
            "entry_price": 100.0,
            "stop_loss": 99.2,
            "take_profit": 101.2,
            "p_hat": 0.28,
        },
        market_context={
            "price": 100.0,
            "best_bid": 99.995,
            "best_ask": 100.005,
            "spread_timestamp_ms": time.time() * 1000,
        },
        prediction={"confidence": 0.28},
    )
    ctx.data["calibration"] = {"SOLUSDT:mean_reversion_fade": {"n_trades": 0, "reliability": 0.0}}

    result = asyncio.run(stage.run(ctx))

    assert result == StageResult.CONTINUE
    ev_result = ctx.data.get("ev_gate_result")
    assert ev_result is not None
    assert ev_result.p_hat_source == "calibrated_floor_mean_reversion_buffer"
    assert ctx.data.get("calibration_pmin_override") is True


def test_mean_reversion_fade_allows_borderline_pmin_when_ev_is_breakeven(monkeypatch):
    monkeypatch.setenv("EV_GATE_COST_MULTIPLE", "0")
    from quantgambit.signals.stages import ev_gate as ev_gate_module

    monkeypatch.setattr(
        ev_gate_module,
        "evaluate_calibration",
        lambda **kwargs: SimpleNamespace(
            state=CalibrationState.COLD,
            p_effective=0.44,
            reliability=0.0,
            size_multiplier=1.0,
            min_edge_bps_adjustment=0.0,
        ),
    )
    config = EVGateConfig(mode="enforce", ev_min=0.02, ev_min_floor=0.0)
    stage = EVGateStage(config=config)

    ctx = make_context(
        symbol="SOLUSDT",
        signal={
            "side": "long",
            "strategy_id": "mean_reversion_fade",
            "entry_price": 100.0,
            "stop_loss": 99.2,
            "take_profit": 101.2,
            "p_hat": 0.28,
        },
        market_context={
            "price": 100.0,
            "best_bid": 99.995,
            "best_ask": 100.005,
            "spread_timestamp_ms": time.time() * 1000,
        },
        prediction={"confidence": 0.28},
    )
    ctx.data["calibration"] = {"SOLUSDT:mean_reversion_fade": {"n_trades": 0, "reliability": 0.0}}

    result = asyncio.run(stage.run(ctx))

    assert result == StageResult.CONTINUE
    ev_result = ctx.data.get("ev_gate_result")
    assert ev_result is not None
    assert ev_result.ev_min_adjusted == 0.0
    assert "mean_reversion_borderline_pmin_relax" in str(ev_result.adjustment_reason or "")


def test_mean_reversion_fade_allows_small_positive_ev_miss_when_cold(monkeypatch):
    monkeypatch.setenv("EV_GATE_COST_MULTIPLE", "0")
    monkeypatch.setenv("EV_GATE_MEAN_REVERSION_EXPECTED_EDGE_TOLERANCE_BPS_BY_SYMBOL", "BTCUSDT:8.0")
    from quantgambit.signals.stages import ev_gate as ev_gate_module

    monkeypatch.setattr(
        ev_gate_module,
        "evaluate_calibration",
        lambda **kwargs: SimpleNamespace(
            state=CalibrationState.COLD,
            p_effective=0.4554,
            reliability=0.0,
            size_multiplier=1.0,
            min_edge_bps_adjustment=0.0,
        ),
    )
    config = EVGateConfig(mode="enforce", ev_min=0.02, ev_min_floor=0.0)
    stage = EVGateStage(config=config)

    ctx = make_context(
        symbol="BTCUSDT",
        signal={
            "side": "long",
            "strategy_id": "mean_reversion_fade",
            "entry_price": 100.0,
            "stop_loss": 99.2,
            "take_profit": 101.2,
            "p_hat": 0.4554,
        },
        market_context={
            "price": 100.0,
            "best_bid": 99.995,
            "best_ask": 100.005,
            "spread_timestamp_ms": time.time() * 1000,
        },
        prediction={"confidence": 0.4554},
    )
    ctx.data["calibration"] = {"BTCUSDT:mean_reversion_fade": {"n_trades": 0, "reliability": 0.0}}

    result = asyncio.run(stage.run(ctx))

    assert result == StageResult.CONTINUE
    ev_result = ctx.data.get("ev_gate_result")
    assert ev_result is not None
    assert ev_result.EV == pytest.approx(ev_result.ev_min_adjusted)
    adjustment_reason = str(ev_result.adjustment_reason or "")
    assert (
        "mean_reversion_ev_tolerance" in adjustment_reason
        or "mean_reversion_borderline_pmin_relax" in adjustment_reason
    )


def test_vwap_reversion_allows_borderline_pmin_when_cold(monkeypatch):
    monkeypatch.setenv("EV_GATE_COST_MULTIPLE", "0")
    monkeypatch.setenv("EV_GATE_MEAN_REVERSION_PMIN_TOLERANCE_BY_SYMBOL", "SOLUSDT:0.08")
    from quantgambit.signals.stages import ev_gate as ev_gate_module

    monkeypatch.setattr(
        ev_gate_module,
        "evaluate_calibration",
        lambda **kwargs: SimpleNamespace(
            state=CalibrationState.COLD,
            p_effective=0.4339,
            reliability=0.0,
            size_multiplier=1.0,
            min_edge_bps_adjustment=0.0,
        ),
    )
    config = EVGateConfig(mode="enforce", ev_min=0.02, ev_min_floor=0.0)
    stage = EVGateStage(config=config)

    ctx = make_context(
        symbol="SOLUSDT",
        signal={
            "side": "long",
            "strategy_id": "vwap_reversion",
            "entry_price": 100.0,
            "stop_loss": 99.2,
            "take_profit": 101.2,
            "p_hat": 0.4339,
        },
        market_context={
            "price": 100.0,
            "best_bid": 99.99,
            "best_ask": 100.01,
            "spread_timestamp_ms": time.time() * 1000,
        },
        prediction={"confidence": 0.4339},
    )
    ctx.data["calibration"] = {"SOLUSDT:vwap_reversion": {"n_trades": 0, "reliability": 0.0}}

    result = asyncio.run(stage.run(ctx))

    assert result == StageResult.CONTINUE
    ev_result = ctx.data.get("ev_gate_result")
    assert ev_result is not None
    assert ev_result.ev_min_adjusted == 0.0
    assert "vwap_reversion_borderline_pmin_relax" in str(ev_result.adjustment_reason or "")
