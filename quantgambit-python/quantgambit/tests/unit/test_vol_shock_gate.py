"""
Unit tests for Vol Shock Conditional Gate (Requirement 6).

Tests the conditional vol shock handling in GlobalGateStage:
- Never hard rejects on vol_shock (Requirement 6.1)
- Applies strategy-specific size and EV multipliers (Requirement 6.2)
- Forces taker-only when spread is wide during vol shock (Requirement 6.3)
- Allows maker-first with reduced TTL otherwise (Requirement 6.4)
- Sets context data for downstream stages (Requirement 6.5)
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

import pytest

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.global_gate import (
    GlobalGateStage,
    GlobalGateConfig,
    VolShockConfig,
)
from quantgambit.deeptrader_core.types import MarketSnapshot


class TestVolShockConfig:
    """Tests for VolShockConfig dataclass."""
    
    def test_default_size_multipliers(self):
        """Should have correct default size multipliers by strategy type."""
        config = VolShockConfig()
        
        assert config.size_multiplier_by_strategy["mean_reversion"] == 0.50
        assert config.size_multiplier_by_strategy["breakout"] == 0.75
        assert config.size_multiplier_by_strategy["trend_pullback"] == 0.70
        assert config.size_multiplier_by_strategy["default"] == 0.50
    
    def test_default_ev_multipliers(self):
        """Should have correct default EV multipliers by strategy type."""
        config = VolShockConfig()
        
        assert config.ev_multiplier_by_strategy["mean_reversion"] == 1.50
        assert config.ev_multiplier_by_strategy["breakout"] == 1.25
        assert config.ev_multiplier_by_strategy["trend_pullback"] == 1.30
        assert config.ev_multiplier_by_strategy["default"] == 1.50
    
    def test_default_spread_threshold(self):
        """Should have correct default spread threshold for taker."""
        config = VolShockConfig()
        
        assert config.spread_threshold_for_taker == 0.80
    
    def test_default_reduced_maker_ttl(self):
        """Should have correct default reduced maker TTL."""
        config = VolShockConfig()
        
        assert config.reduced_maker_ttl_ms == 2000
    
    def test_custom_config(self):
        """Should allow custom configuration."""
        config = VolShockConfig(
            size_multiplier_by_strategy={"mean_reversion": 0.40, "default": 0.60},
            ev_multiplier_by_strategy={"mean_reversion": 1.60, "default": 1.40},
            spread_threshold_for_taker=0.90,
            reduced_maker_ttl_ms=3000,
        )
        
        assert config.size_multiplier_by_strategy["mean_reversion"] == 0.40
        assert config.ev_multiplier_by_strategy["mean_reversion"] == 1.60
        assert config.spread_threshold_for_taker == 0.90
        assert config.reduced_maker_ttl_ms == 3000


class TestGlobalGateVolShock:
    """Tests for GlobalGateStage vol shock conditional handling."""
    
    def _make_snapshot(self, **overrides) -> MarketSnapshot:
        """Create test snapshot with overrides."""
        defaults = {
            "symbol": "BTCUSDT",
            "exchange": "bybit",
            "timestamp_ns": int(time.time() * 1e9),
            "snapshot_age_ms": 50.0,
            "mid_price": 50000.0,
            "bid": 49999.0,
            "ask": 50001.0,
            "spread_bps": 4.0,
            "bid_depth_usd": 100000.0,
            "ask_depth_usd": 100000.0,
            "depth_imbalance": 0.0,
            "imb_1s": 0.0,
            "imb_5s": 0.0,
            "imb_30s": 0.0,
            "orderflow_persistence_sec": 0.0,
            "rv_1s": 0.01,
            "rv_10s": 0.005,
            "rv_1m": 0.003,
            "vol_shock": False,
            "vol_regime": "normal",
            "vol_regime_score": 0.5,
            "trend_direction": "neutral",
            "trend_strength": 0.0,
            "poc_price": 49950.0,
            "vah_price": 50100.0,
            "val_price": 49800.0,
            "position_in_value": "inside",
            "expected_fill_slippage_bps": 2.0,
            "typical_spread_bps": 3.5,
            "data_quality_score": 0.95,
            "ws_connected": True,
        }
        defaults.update(overrides)
        return MarketSnapshot(**defaults)
    
    def test_no_vol_shock_passes_normally(self):
        """Should pass normally when no vol shock."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"snapshot": self._make_snapshot(vol_shock=False)},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data.get("vol_shock_active") is None
        assert ctx.data.get("size_factor", 1.0) == 1.0
    
    def test_vol_shock_no_hard_reject_by_default(self):
        """Should NOT hard reject on vol_shock by default (Requirement 6.1)."""
        # Default config has block_on_vol_shock=False
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.5},
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should NOT reject
        assert result == StageResult.CONTINUE
        # Should set vol_shock_active
        assert ctx.data.get("vol_shock_active") is True
    
    def test_vol_shock_legacy_hard_reject_when_enabled(self):
        """Should hard reject on vol_shock when block_on_vol_shock=True (legacy)."""
        config = GlobalGateConfig(block_on_vol_shock=True)
        stage = GlobalGateStage(config=config)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"snapshot": self._make_snapshot(vol_shock=True)},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "vol_shock" in ctx.rejection_reason
    
    def test_vol_shock_applies_mean_reversion_multipliers(self):
        """Should apply mean_reversion strategy multipliers (Requirement 6.2)."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.5},
                "strategy_type": "mean_reversion",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["vol_shock_size_multiplier"] == 0.50
        assert ctx.data["vol_shock_ev_multiplier"] == 1.50
        # Size factor should be reduced
        assert ctx.data["size_factor"] == 0.50
    
    def test_vol_shock_applies_breakout_multipliers(self):
        """Should apply breakout strategy multipliers (Requirement 6.2)."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.5},
                "strategy_type": "breakout",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["vol_shock_size_multiplier"] == 0.75
        assert ctx.data["vol_shock_ev_multiplier"] == 1.25
        assert ctx.data["size_factor"] == 0.75
    
    def test_vol_shock_applies_trend_pullback_multipliers(self):
        """Should apply trend_pullback strategy multipliers (Requirement 6.2)."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.5},
                "strategy_type": "trend_pullback",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["vol_shock_size_multiplier"] == 0.70
        assert ctx.data["vol_shock_ev_multiplier"] == 1.30
        assert ctx.data["size_factor"] == 0.70
    
    def test_vol_shock_applies_default_multipliers_for_unknown_strategy(self):
        """Should apply default multipliers for unknown strategy type."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.5},
                "strategy_type": "unknown_strategy",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["vol_shock_size_multiplier"] == 0.50
        assert ctx.data["vol_shock_ev_multiplier"] == 1.50
    
    def test_vol_shock_forces_taker_when_spread_wide(self):
        """Should force taker-only when spread_percentile > threshold (Requirement 6.3)."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.85},  # > 0.80 threshold
                "strategy_type": "mean_reversion",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["vol_shock_execution_mode"] == "taker_only"
        assert ctx.data["force_taker"] is True
        assert "maker_ttl_ms" not in ctx.data
    
    def test_vol_shock_allows_maker_with_reduced_ttl_when_spread_acceptable(self):
        """Should allow maker-first with reduced TTL when spread acceptable (Requirement 6.4)."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.50},  # <= 0.80 threshold
                "strategy_type": "mean_reversion",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["vol_shock_execution_mode"] == "maker_first_reduced_ttl"
        assert ctx.data["maker_ttl_ms"] == 2000
        assert ctx.data.get("force_taker") is None
    
    def test_vol_shock_sets_context_data(self):
        """Should set all required context data for downstream stages (Requirement 6.5)."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.5},
                "strategy_type": "breakout",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        # All required context data should be set
        assert ctx.data["vol_shock_active"] is True
        assert "vol_shock_size_multiplier" in ctx.data
        assert "vol_shock_ev_multiplier" in ctx.data
        assert "vol_shock_execution_mode" in ctx.data
    
    def test_vol_shock_extracts_strategy_type_from_profile_params(self):
        """Should extract strategy type from profile_params."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.5},
                "profile_params": {"strategy_type": "breakout"},
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["vol_shock_size_multiplier"] == 0.75  # breakout multiplier
    
    def test_vol_shock_extracts_strategy_type_from_candidate_signal(self):
        """Should extract strategy type from candidate_signal.strategy_id."""
        stage = GlobalGateStage()
        
        # Create a mock candidate signal
        @dataclass
        class MockCandidate:
            strategy_id: str = "mean_reversion_fade_v2"
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.5},
                "candidate_signal": MockCandidate(),
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["vol_shock_size_multiplier"] == 0.50  # mean_reversion multiplier
    
    def test_vol_shock_with_custom_config(self):
        """Should use custom vol shock config."""
        vol_shock_config = VolShockConfig(
            size_multiplier_by_strategy={"mean_reversion": 0.30, "default": 0.40},
            ev_multiplier_by_strategy={"mean_reversion": 2.00, "default": 1.80},
            spread_threshold_for_taker=0.70,
            reduced_maker_ttl_ms=1500,
        )
        config = GlobalGateConfig(vol_shock_config=vol_shock_config)
        stage = GlobalGateStage(config=config)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.60},  # Between 0.70 threshold
                "strategy_type": "mean_reversion",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["vol_shock_size_multiplier"] == 0.30
        assert ctx.data["vol_shock_ev_multiplier"] == 2.00
        assert ctx.data["maker_ttl_ms"] == 1500
    
    def test_vol_shock_spread_at_threshold_boundary(self):
        """Should allow maker when spread_percentile equals threshold."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.80},  # Exactly at threshold
                "strategy_type": "mean_reversion",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        # At threshold, should still allow maker (> not >=)
        assert ctx.data["vol_shock_execution_mode"] == "maker_first_reduced_ttl"
    
    def test_vol_shock_spread_just_above_threshold(self):
        """Should force taker when spread_percentile just above threshold."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.81},  # Just above threshold
                "strategy_type": "mean_reversion",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["vol_shock_execution_mode"] == "taker_only"
        assert ctx.data["force_taker"] is True
    
    def test_vol_shock_with_missing_spread_percentile(self):
        """Should use default spread_percentile when missing."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {},  # No spread_percentile
                "strategy_type": "mean_reversion",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        # Default spread_percentile is 0.5, which is below threshold
        assert ctx.data["vol_shock_execution_mode"] == "maker_first_reduced_ttl"
    
    def test_vol_shock_metrics_recorded(self):
        """Should record vol shock metrics in gate decision."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(vol_shock=True),
                "market_context": {"spread_percentile": 0.5},
                "strategy_type": "breakout",
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        
        # Check gate decisions contain vol shock metrics
        gate_decisions = ctx.data.get("gate_decisions", [])
        assert len(gate_decisions) > 0
        
        metrics = gate_decisions[0].metrics
        assert metrics["vol_shock"] is True
        assert metrics["vol_shock_strategy_type"] == "breakout"
        assert metrics["vol_shock_size_multiplier"] == 0.75
        assert metrics["vol_shock_ev_multiplier"] == 1.25
        assert metrics["vol_shock_execution_mode"] == "maker_first_reduced_ttl"


class TestGetStrategyType:
    """Tests for _get_strategy_type helper method."""
    
    def _make_snapshot(self, **overrides) -> MarketSnapshot:
        """Create test snapshot with overrides."""
        defaults = {
            "symbol": "BTCUSDT",
            "exchange": "bybit",
            "timestamp_ns": int(time.time() * 1e9),
            "snapshot_age_ms": 50.0,
            "mid_price": 50000.0,
            "bid": 49999.0,
            "ask": 50001.0,
            "spread_bps": 4.0,
            "bid_depth_usd": 100000.0,
            "ask_depth_usd": 100000.0,
            "depth_imbalance": 0.0,
            "imb_1s": 0.0,
            "imb_5s": 0.0,
            "imb_30s": 0.0,
            "orderflow_persistence_sec": 0.0,
            "rv_1s": 0.01,
            "rv_10s": 0.005,
            "rv_1m": 0.003,
            "vol_shock": False,
            "vol_regime": "normal",
            "vol_regime_score": 0.5,
            "trend_direction": "neutral",
            "trend_strength": 0.0,
            "poc_price": 49950.0,
            "vah_price": 50100.0,
            "val_price": 49800.0,
            "position_in_value": "inside",
            "expected_fill_slippage_bps": 2.0,
            "typical_spread_bps": 3.5,
            "data_quality_score": 0.95,
            "ws_connected": True,
        }
        defaults.update(overrides)
        return MarketSnapshot(**defaults)
    
    def test_explicit_strategy_type_takes_precedence(self):
        """Should use explicit strategy_type from ctx.data."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(),
                "strategy_type": "breakout",
                "profile_params": {"strategy_type": "mean_reversion"},
            },
        )
        
        strategy_type = stage._get_strategy_type(ctx)
        
        assert strategy_type == "breakout"
    
    def test_profile_params_strategy_type(self):
        """Should use strategy_type from profile_params."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(),
                "profile_params": {"strategy_type": "trend_pullback"},
            },
        )
        
        strategy_type = stage._get_strategy_type(ctx)
        
        assert strategy_type == "trend_pullback"
    
    def test_extract_from_candidate_signal_mean_reversion(self):
        """Should extract mean_reversion from candidate signal strategy_id."""
        stage = GlobalGateStage()
        
        @dataclass
        class MockCandidate:
            strategy_id: str = "mean_reversion_fade"
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(),
                "candidate_signal": MockCandidate(),
            },
        )
        
        strategy_type = stage._get_strategy_type(ctx)
        
        assert strategy_type == "mean_reversion"
    
    def test_extract_from_candidate_signal_breakout(self):
        """Should extract breakout from candidate signal strategy_id."""
        stage = GlobalGateStage()
        
        @dataclass
        class MockCandidate:
            strategy_id: str = "breakout_scalp_v2"
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(),
                "candidate_signal": MockCandidate(),
            },
        )
        
        strategy_type = stage._get_strategy_type(ctx)
        
        assert strategy_type == "breakout"
    
    def test_extract_from_candidate_signal_trend_pullback(self):
        """Should extract trend_pullback from candidate signal strategy_id."""
        stage = GlobalGateStage()
        
        @dataclass
        class MockCandidate:
            strategy_id: str = "trend_pullback_entry"
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(),
                "candidate_signal": MockCandidate(),
            },
        )
        
        strategy_type = stage._get_strategy_type(ctx)
        
        assert strategy_type == "trend_pullback"
    
    def test_default_when_no_strategy_info(self):
        """Should return 'default' when no strategy info available."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"snapshot": self._make_snapshot()},
        )
        
        strategy_type = stage._get_strategy_type(ctx)
        
        assert strategy_type == "default"
