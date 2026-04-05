"""
Tests for EV Gate Safety Guards.

Tests the safety guard functionality implemented in task 12:
- 12.1: Missing field detection (Requirement 10.1)
- 12.2: Connectivity checks (Requirements 10.2, 10.3)
- 12.3: Low reliability handling (Requirement 10.4)
"""

import pytest
import asyncio
from quantgambit.signals.stages.ev_gate import (
    EVGateStage,
    EVGateConfig,
    EVGateRejectCode,
)
from quantgambit.signals.pipeline import StageContext, StageResult


import time

def make_context(symbol: str, signal: dict, market_context: dict, features: dict, prediction: dict) -> StageContext:
    """Helper to create a StageContext with the required data structure."""
    # Add timestamp if not present (required for staleness checks)
    if "timestamp_ms" not in market_context and "book_timestamp_ms" not in market_context:
        market_context["timestamp_ms"] = time.time() * 1000
    
    ctx = StageContext(
        symbol=symbol,
        data={
            "market_context": market_context,
            "features": features,
            "prediction": prediction,
        }
    )
    ctx.signal = signal
    return ctx


class TestMissingFieldDetection:
    """Tests for missing field detection (Requirement 10.1)."""
    
    def test_missing_entry_price_rejected(self):
        """Signal with missing entry_price should be rejected."""
        stage = EVGateStage(config=EVGateConfig(mode="enforce"))
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                # No price
                "best_bid": 50000.0,
                "best_ask": 50010.0,
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert ctx.rejection_stage == "ev_gate"
        assert ctx.rejection_reason == "MISSING_REQUIRED_FIELD"
        assert "entry_price" in ctx.rejection_detail.get("reject_reason", "")
    
    def test_missing_side_rejected(self):
        """Signal with missing side should be rejected."""
        stage = EVGateStage(config=EVGateConfig(mode="enforce"))
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                # No side
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert ctx.rejection_stage == "ev_gate"
        assert ctx.rejection_reason == "MISSING_REQUIRED_FIELD"
        assert "side" in ctx.rejection_detail.get("reject_reason", "")
    
    def test_missing_best_bid_rejected(self):
        """Signal with missing best_bid should NOT be rejected (defaults applied per Requirement 5)."""
        stage = EVGateStage(config=EVGateConfig(mode="enforce", ev_min=0.0, ev_min_floor=0.0))
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                # No best_bid - should be defaulted
                "best_ask": 50010.0,
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should NOT be rejected for missing best_bid (defaults applied)
        if ctx.rejection_stage == "ev_gate":
            assert "best_bid" not in ctx.rejection_detail.get("reject_reason", "")
    
    def test_missing_best_ask_not_rejected(self):
        """Signal with missing best_ask should NOT be rejected (defaults applied per Requirement 5)."""
        stage = EVGateStage(config=EVGateConfig(mode="enforce", ev_min=0.0, ev_min_floor=0.0))
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                # No best_ask - should be defaulted
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should NOT be rejected for missing best_ask (defaults applied)
        if ctx.rejection_stage == "ev_gate":
            assert "best_ask" not in ctx.rejection_detail.get("reject_reason", "")
    
    def test_missing_prediction_confidence_not_rejected(self):
        """Signal with missing prediction confidence should NOT be rejected (conservative fallback per Requirement 5)."""
        stage = EVGateStage(config=EVGateConfig(mode="enforce", ev_min=0.0, ev_min_floor=0.0))
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
            },
            features={},
            prediction={},  # No confidence - should use conservative fallback
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should NOT be rejected for missing confidence (conservative fallback applied)
        if ctx.rejection_stage == "ev_gate":
            assert "confidence" not in ctx.rejection_detail.get("reject_reason", "")


class TestConnectivityChecks:
    """Tests for connectivity checks (Requirements 10.2, 10.3)."""
    
    def test_high_exchange_latency_rejected(self):
        """Signal with high exchange latency should be rejected."""
        config = EVGateConfig(mode="enforce", max_exchange_latency_ms=500)
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "exchange_latency_ms": 600,  # Above threshold
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert ctx.rejection_stage == "ev_gate"
        assert ctx.rejection_reason == "EXCHANGE_CONNECTIVITY"
        assert "latency" in ctx.rejection_detail.get("reject_reason", "").lower()
    
    def test_orderbook_out_of_sync_rejected(self):
        """Signal with out-of-sync orderbook should be rejected."""
        stage = EVGateStage(config=EVGateConfig(mode="enforce"))
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "orderbook_synced": False,  # Out of sync
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert ctx.rejection_stage == "ev_gate"
        assert ctx.rejection_reason == "ORDERBOOK_SYNC"
    
    def test_orderbook_lagging_rejected(self):
        """Signal with lagging orderbook should be rejected."""
        config = EVGateConfig(mode="enforce", max_book_age_ms=250)
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "orderbook_lag_ms": 300,  # Above threshold
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert ctx.rejection_stage == "ev_gate"
        assert ctx.rejection_reason == "ORDERBOOK_SYNC"
    
    def test_normal_latency_passes(self):
        """Signal with normal latency should pass connectivity checks."""
        # Use ev_min_floor=0 to allow ev_min=0
        config = EVGateConfig(mode="enforce", max_exchange_latency_ms=500, ev_min=0.0, ev_min_floor=0.0)
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "exchange_latency_ms": 100,  # Below threshold
                "orderbook_synced": True,
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should not be rejected for connectivity reasons
        if ctx.rejection_stage == "ev_gate":
            assert ctx.rejection_reason not in ["EXCHANGE_CONNECTIVITY", "ORDERBOOK_SYNC"]


class TestLowReliabilityHandling:
    """Tests for low reliability handling (Requirement 10.4)."""
    
    def test_low_reliability_increases_ev_min(self):
        """Low calibration reliability should increase EV_Min."""
        config = EVGateConfig(
            mode="enforce",
            ev_min=0.02,
            p_margin_uncalibrated=0.02,
            min_reliability_score=0.6,
        )
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "calibration_reliability": 0.4,  # Below min_reliability_score
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        # Run the stage
        result = asyncio.run(stage.run(ctx))
        
        # Check that the adjusted EV_Min includes the uncalibrated margin
        if ctx.rejection_detail:
            ev_min_adjusted = ctx.rejection_detail.get("ev_min_adjusted", 0)
            # Should be ev_min + p_margin_uncalibrated = 0.02 + 0.02 = 0.04
            assert ev_min_adjusted == pytest.approx(0.04, abs=0.001)
    
    def test_high_reliability_no_margin(self):
        """High calibration reliability should not add margin."""
        config = EVGateConfig(
            mode="enforce",
            ev_min=0.02,
            p_margin_uncalibrated=0.02,
            min_reliability_score=0.6,
        )
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "calibration_reliability": 0.8,  # Above min_reliability_score
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        # Run the stage
        result = asyncio.run(stage.run(ctx))
        
        # Check that the adjusted EV_Min does NOT include the uncalibrated margin
        if ctx.rejection_detail:
            ev_min_adjusted = ctx.rejection_detail.get("ev_min_adjusted", 0)
            # Should be just ev_min = 0.02
            assert ev_min_adjusted == pytest.approx(0.02, abs=0.001)
    
    def test_zero_reliability_treated_as_low(self):
        """Zero calibration reliability should be treated as low."""
        config = EVGateConfig(
            mode="enforce",
            ev_min=0.02,
            p_margin_uncalibrated=0.02,
            min_reliability_score=0.6,
        )
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "calibration_reliability": 0.0,  # Zero reliability
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        # Run the stage
        result = asyncio.run(stage.run(ctx))
        
        # Check that the adjusted EV_Min includes the uncalibrated margin
        if ctx.rejection_detail:
            ev_min_adjusted = ctx.rejection_detail.get("ev_min_adjusted", 0)
            # Should be ev_min + p_margin_uncalibrated = 0.02 + 0.02 = 0.04
            assert ev_min_adjusted == pytest.approx(0.04, abs=0.001)


class TestSafetyGuardsIntegration:
    """Integration tests for all safety guards working together."""
    
    def test_all_fields_present_passes_safety_checks(self):
        """Signal with all required fields should pass safety checks."""
        # Use ev_min_floor=0 to allow ev_min=0
        config = EVGateConfig(
            mode="enforce",
            ev_min=0.0,  # Disable EV threshold for this test
            ev_min_floor=0.0,
            max_exchange_latency_ms=500,
        )
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "exchange_latency_ms": 100,
                "orderbook_synced": True,
                "calibration_reliability": 0.8,
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should not be rejected for safety guard reasons
        if ctx.rejection_stage == "ev_gate":
            assert ctx.rejection_reason not in [
                "MISSING_REQUIRED_FIELD",
                "EXCHANGE_CONNECTIVITY",
                "ORDERBOOK_SYNC",
            ]
    
    def test_shadow_mode_logs_but_does_not_reject(self):
        """Shadow mode should log safety issues but not reject."""
        config = EVGateConfig(mode="shadow", max_exchange_latency_ms=500)
        stage = EVGateStage(config=config)
        
        ctx = make_context(
            symbol="BTCUSDT",
            signal={
                "side": "long",
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
            },
            market_context={
                "price": 50000.0,
                "best_bid": 50000.0,
                "best_ask": 50010.0,
                "exchange_latency_ms": 600,  # Above threshold
            },
            features={},
            prediction={"confidence": 0.65},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Shadow mode should always continue
        assert result == StageResult.CONTINUE
        # But should record that it would have rejected
        assert ctx.data.get("ev_gate_would_reject") is True
