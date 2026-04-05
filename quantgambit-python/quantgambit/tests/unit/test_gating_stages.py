"""
Unit tests for pre-trade gating stages.

Tests each stage in isolation:
- DataReadinessStage
- SnapshotBuilderStage
- GlobalGateStage
- CandidateGenerationStage
- CandidateVetoStage
- CooldownStage
"""

import asyncio
import os
import pytest
import time
from unittest.mock import patch

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages import (
    DataReadinessStage,
    SnapshotBuilderStage,
    GlobalGateStage,
    CostDataQualityStage,
    CandidateGenerationStage,
    CandidateVetoStage,
    CooldownStage,
)
from quantgambit.signals.stages.data_readiness import DataReadinessConfig
from quantgambit.signals.stages.cost_data_quality import CostDataQualityConfig
from quantgambit.signals.stages.global_gate import GlobalGateConfig
from quantgambit.signals.stages.candidate_veto import CandidateVetoConfig
from quantgambit.signals.stages.cooldown import CooldownConfig, CooldownManager
from quantgambit.deeptrader_core.types import MarketSnapshot, TradeCandidate


def make_features(
    price=50000.0,
    bid=49999.0,
    ask=50001.0,
    spread_bps=4.0,
    bid_depth_usd=50000.0,
    ask_depth_usd=50000.0,
    orderflow_imbalance=0.0,
    timestamp=None,
):
    """Create test features dict."""
    return {
        "symbol": "BTCUSDT",
        "price": price,
        "bid": bid,
        "ask": ask,
        "spread": (ask - bid) / price,
        "spread_bps": spread_bps,
        "bid_depth_usd": bid_depth_usd,
        "ask_depth_usd": ask_depth_usd,
        "orderflow_imbalance": orderflow_imbalance,
        "timestamp": timestamp or time.time(),
        "rotation_factor": 0.5,
        "position_in_value": "inside",
        "distance_to_val_bps": 100.0,
        "distance_to_vah_bps": 100.0,
        "distance_to_poc_bps": 50.0,
        "point_of_control": 49950.0,
        "value_area_low": 49800.0,
        "value_area_high": 50100.0,
        "ema_fast_15m": 50000.0,
        "ema_slow_15m": 49950.0,
        "trend_strength": 0.001,
        "atr_5m": 50.0,
        "atr_5m_baseline": 45.0,
        "atr_ratio": 1.1,
        "vwap": 49980.0,
        "trades_per_second": 10.0,
        "price_change_1s": 0.0001,
        "price_change_5s": 0.0003,
        "price_change_30s": 0.001,
        "price_change_1m": 0.002,
        "price_change_5m": 0.005,
    }


def make_market_context(
    price=50000.0,
    spread_bps=4.0,
    trend_direction="neutral",
    trend_strength=0.0,
    volatility_regime="normal",
    orderflow_imbalance=0.0,
    timestamp=None,
):
    """Create test market context dict."""
    return {
        "symbol": "BTCUSDT",
        "price": price,
        "spread_bps": spread_bps,
        "trend_direction": trend_direction,
        "trend_strength": trend_strength,
        "volatility_regime": volatility_regime,
        "orderflow_imbalance": orderflow_imbalance,
        "data_quality_score": 0.95,
        "data_quality_status": "synced",
        "trade_sync_state": "synced",
        "orderbook_sync_state": "synced",
        "timestamp": timestamp or time.time(),
    }


class TestDataReadinessStage:
    """Tests for DataReadinessStage."""
    
    def test_pass_with_valid_data(self):
        """Should pass with valid features."""
        stage = DataReadinessStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": make_features(),
                "market_context": make_market_context(),
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.rejection_reason is None
    
    def test_reject_no_features(self):
        """Should reject when features missing."""
        stage = DataReadinessStage()
        ctx = StageContext(symbol="BTCUSDT", data={})
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "no_features"
    
    def test_reject_no_price(self):
        """Should reject when price is missing."""
        stage = DataReadinessStage()
        features = make_features()
        features["price"] = None
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"features": features, "market_context": make_market_context()},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "no_price" in ctx.rejection_reason
    
    def test_reject_low_depth(self):
        """Should reject when depth is too low."""
        config = DataReadinessConfig(min_bid_depth_usd=100000.0)
        stage = DataReadinessStage(config=config)
        features = make_features(bid_depth_usd=50000.0)  # Below threshold
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"features": features, "market_context": make_market_context()},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "bid_depth_low" in ctx.rejection_reason
    
    def test_reject_stale_data(self):
        """Should reject when data is stale."""
        config = DataReadinessConfig(max_trade_age_sec=1.0)
        stage = DataReadinessStage(config=config)
        features = make_features(timestamp=time.time() - 5.0)  # 5 seconds old
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"features": features, "market_context": make_market_context()},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "trade_stale" in ctx.rejection_reason

    def test_trade_timestamp_alias_does_not_false_block_fresh_trade_feed(self):
        """Should not block when trade receive freshness is current but trade timestamp is stale."""
        config = DataReadinessConfig(max_trade_age_sec=1.0)
        stage = DataReadinessStage(config=config)
        now_ms = int(time.time() * 1000)
        features = make_features(timestamp=time.time())
        features["trade_ts_ms"] = now_ms - 5000
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": features,
                "market_context": {
                    **make_market_context(),
                    "trade_recv_ms": now_ms,
                    "feed_staleness": {"orderbook": 0.0, "trade": 0.0},
                },
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE
        assert ctx.rejection_reason is None

    def test_trade_age_fallback_does_not_false_block_when_recv_timestamps_missing(self):
        """Should use local trade age fallback when recv timestamps and feed staleness are absent."""
        config = DataReadinessConfig(
            max_trade_age_sec=1.0,
            trade_lag_yellow_ms=4000,
            trade_lag_red_ms=6000,
        )
        stage = DataReadinessStage(config=config)
        now_ms = int(time.time() * 1000)
        features = make_features(timestamp=time.time())
        features["trade_ts_ms"] = now_ms - 5000
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": features,
                "market_context": {
                    **make_market_context(),
                    "trade_age_sec": 0.15,
                },
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE
        assert ctx.rejection_reason is None

    def test_trade_lag_uses_local_age_when_raw_timestamp_is_divergent(self):
        """Should trust fresh local trade age over a badly lagging upstream trade timestamp."""
        config = DataReadinessConfig(
            max_trade_age_sec=1.0,
            trade_gap_green_ms=2000,
            trade_lag_yellow_ms=4000,
            trade_lag_red_ms=6000,
        )
        stage = DataReadinessStage(config=config)
        now_ms = int(time.time() * 1000)
        features = make_features(timestamp=time.time())
        features["trade_ts_ms"] = now_ms - 8000
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": features,
                "market_context": {
                    **make_market_context(),
                    "trade_age_sec": 0.12,
                },
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE
        assert ctx.rejection_reason is None

    def test_fresh_orderbook_prevents_false_trade_lag_emergency_for_brief_lull(self):
        """A brief trade lull with a fresh book should degrade, not trigger EMERGENCY."""
        config = DataReadinessConfig(
            trade_lag_green_ms=200,
            trade_lag_yellow_ms=400,
            trade_lag_red_ms=1000,
            book_gap_green_ms=2000,
        )
        stage = DataReadinessStage(config=config)
        now_ms = int(time.time() * 1000)
        ctx = StageContext(
            symbol="ETHUSDT",
            data={
                "features": make_features(timestamp=time.time()),
                "market_context": {
                    **make_market_context(),
                    "book_recv_ms": now_ms,
                    "trade_recv_ms": now_ms - 1122,
                    "feed_staleness": {"orderbook": 0.0, "trade": 1.122},
                    "trade_age_sec": 1.122,
                },
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "trade_lag_red:1122ms>400ms"
        readiness = ctx.data["readiness_level"]
        assert getattr(readiness, "value", readiness) == "red"
        gate_decision = ctx.data["gate_decisions"][-1]
        assert gate_decision.metrics["trade_lag_ms"] == 1122

    def test_reject_hard_orderbook_exchange_lag_from_market_context(self):
        """Should hard-reject when MDS exchange lag exceeds hard cap."""
        config = DataReadinessConfig(
            use_cts_latency_gates=True,
            max_orderbook_exchange_lag_ms=3000,
            # Keep tier limits very loose so only the hard cap triggers.
            book_lag_red_ms=10000,
        )
        stage = DataReadinessStage(config=config)
        features = make_features()
        # No local cts_ms required; rely on MDS health lag projection.
        market_context = make_market_context()
        market_context["orderbook_exchange_lag_ms"] = 4200
        market_context["orderbook_exchange_lag_source"] = "matching_engine"
        market_context["feed_staleness"] = {"orderbook": 0.2, "trade": 0.2}
        market_context["book_recv_ms"] = int(time.time() * 1000)
        market_context["trade_recv_ms"] = int(time.time() * 1000)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"features": features, "market_context": market_context},
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.REJECT
        assert "orderbook_exchange_lag_hard_block" in ctx.rejection_reason


class TestSnapshotBuilderStage:
    """Tests for SnapshotBuilderStage."""
    
    def test_builds_snapshot(self):
        """Should create MarketSnapshot from features."""
        stage = SnapshotBuilderStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": make_features(),
                "market_context": make_market_context(),
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert "snapshot" in ctx.data
        
        snapshot = ctx.data["snapshot"]
        assert isinstance(snapshot, MarketSnapshot)
        assert snapshot.symbol == "BTCUSDT"
        assert snapshot.mid_price == 50000.0
    
    def test_snapshot_includes_orderflow(self):
        """Should include multi-timeframe orderflow."""
        stage = SnapshotBuilderStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": make_features(orderflow_imbalance=0.3),
                "market_context": make_market_context(orderflow_imbalance=0.3),
                "imb_1s": 0.35,
                "imb_5s": 0.3,
                "imb_30s": 0.25,
                "orderflow_persistence_sec": 8.0,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        snapshot = ctx.data["snapshot"]
        assert snapshot.imb_1s == 0.35
        assert snapshot.imb_5s == 0.3
        assert snapshot.imb_30s == 0.25
        assert snapshot.orderflow_persistence_sec == 8.0

    def test_reads_amt_from_context(self):
        """Should read AMT levels from ctx.data['amt_levels'] when available (Requirement 5.3)."""
        from quantgambit.signals.stages.amt_calculator import AMTLevels
        
        stage = SnapshotBuilderStage()
        
        # Create AMTLevels object as would be set by AMTCalculatorStage
        amt_levels = AMTLevels(
            point_of_control=49900.0,
            value_area_high=50200.0,
            value_area_low=49600.0,
            position_in_value="above",
            distance_to_poc=100.0,  # Legacy field
            distance_to_vah=-200.0,  # Legacy field
            distance_to_val=400.0,  # Legacy field
            distance_to_poc_bps=100.0,  # New _bps field (Requirement 2.3)
            distance_to_vah_bps=-200.0,  # New _bps field (Requirement 2.3)
            distance_to_val_bps=400.0,  # New _bps field (Requirement 2.3)
            rotation_factor=5.5,
            candle_count=100,
            calculation_ts=time.time(),
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": make_features(),  # Features have different AMT values
                "market_context": make_market_context(),
                "amt_levels": amt_levels,  # AMT levels from AMTCalculatorStage
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        snapshot = ctx.data["snapshot"]
        
        # Should use AMT levels from ctx.data, not features
        assert snapshot.poc_price == 49900.0
        assert snapshot.vah_price == 50200.0
        assert snapshot.val_price == 49600.0
        assert snapshot.position_in_value == "above"
        
        # Should also include distance and rotation fields (Requirements 5.1, 5.2)
        # Using _bps suffix per Requirement 2.3
        assert snapshot.distance_to_poc_bps == 100.0
        assert snapshot.distance_to_vah_bps == -200.0
        assert snapshot.distance_to_val_bps == 400.0
        assert snapshot.rotation_factor == 5.5

    def test_falls_back_to_features_when_amt_levels_none(self):
        """Should fall back to features dict when amt_levels is None (Requirement 5.4)."""
        stage = SnapshotBuilderStage()
        
        # Features have AMT values, but amt_levels is None
        features = make_features()
        features["point_of_control"] = 49950.0
        features["value_area_high"] = 50100.0
        features["value_area_low"] = 49800.0
        features["position_in_value"] = "inside"
        features["orderflow_imbalance"] = 0.3
        features["trend_strength"] = 0.6  # Override trend_strength in features
        
        market_context = make_market_context()
        market_context["trend_direction"] = "up"
        market_context["trend_strength"] = 0.6
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": features,
                "market_context": market_context,
                "amt_levels": None,  # Explicitly None
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        snapshot = ctx.data["snapshot"]
        
        # Should use AMT values from features dict
        assert snapshot.poc_price == 49950.0
        assert snapshot.vah_price == 50100.0
        assert snapshot.val_price == 49800.0
        assert snapshot.position_in_value == "inside"
        
        # Should calculate distance and rotation fields in fallback path
        # price is 50000.0 from make_features()
        # Using _bps suffix per Requirement 2.3
        # BPS formula: (price - level) / mid_price * 10000
        # distance_to_poc_bps = (50000 - 49950) / 50000 * 10000 = 10.0
        # distance_to_vah_bps = |50000 - 50100| / 50000 * 10000 = 20.0
        # distance_to_val_bps = |50000 - 49800| / 50000 * 10000 = 40.0
        assert snapshot.distance_to_poc_bps == 10.0
        assert snapshot.distance_to_vah_bps == 20.0
        assert snapshot.distance_to_val_bps == 40.0
        # rotation_factor = (0.3 * 5.0) + (0.6 * 5.0) = 1.5 + 3.0 = 4.5
        assert snapshot.rotation_factor == 4.5

    def test_falls_back_to_features_when_amt_levels_not_set(self):
        """Should fall back to features dict when amt_levels is not in ctx.data (Requirement 5.4)."""
        stage = SnapshotBuilderStage()
        
        # Features have AMT values, amt_levels not in ctx.data at all
        features = make_features()
        features["point_of_control"] = 49950.0
        features["value_area_high"] = 50100.0
        features["value_area_low"] = 49800.0
        features["position_in_value"] = "below"
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": features,
                "market_context": make_market_context(),
                # No amt_levels key at all
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        snapshot = ctx.data["snapshot"]
        
        # Should use AMT values from features dict
        assert snapshot.poc_price == 49950.0
        assert snapshot.vah_price == 50100.0
        assert snapshot.val_price == 49800.0
        assert snapshot.position_in_value == "below"


class TestGlobalGateStage:
    """Tests for GlobalGateStage."""
    
    def _make_snapshot(self, **overrides):
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
    
    def test_pass_with_good_conditions(self):
        """Should pass with good market conditions."""
        stage = GlobalGateStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"snapshot": self._make_snapshot()},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data.get("size_factor", 1.0) == 1.0
    
    def test_reject_stale_snapshot(self):
        """Should reject when snapshot is too old."""
        config = GlobalGateConfig(snapshot_age_block_ms=500.0)
        stage = GlobalGateStage(config=config)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"snapshot": self._make_snapshot(snapshot_age_ms=800.0)},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "snapshot_too_old" in ctx.rejection_reason
    
    def test_reject_wide_spread(self):
        """Should reject when spread is too wide."""
        config = GlobalGateConfig(max_spread_bps=5.0)
        stage = GlobalGateStage(config=config)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"snapshot": self._make_snapshot(spread_bps=12.0)},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "spread_too_wide" in ctx.rejection_reason
    
    def test_reject_thin_depth(self):
        """Should reject when depth is too thin."""
        config = GlobalGateConfig(min_depth_per_side_usd=50000.0)
        stage = GlobalGateStage(config=config)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"snapshot": self._make_snapshot(bid_depth_usd=20000.0)},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "depth_too_thin" in ctx.rejection_reason
    
    def test_reject_vol_shock(self):
        """Should reject during vol shock."""
        config = GlobalGateConfig(block_on_vol_shock=True)
        stage = GlobalGateStage(config=config)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"snapshot": self._make_snapshot(vol_shock=True)},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "vol_shock" in ctx.rejection_reason
    
    def test_reduce_size_stale_data(self):
        """Should reduce size factor when data is moderately stale."""
        config = GlobalGateConfig(
            snapshot_age_ok_ms=100.0,
            snapshot_age_reduce_ms=300.0,
            snapshot_age_block_ms=750.0,
            stale_data_size_factor=0.5,
        )
        stage = GlobalGateStage(config=config)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"snapshot": self._make_snapshot(snapshot_age_ms=400.0)},  # Moderately stale
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        assert ctx.data["size_factor"] == 0.5


class TestCandidateVetoStage:
    """Tests for CandidateVetoStage."""

    @pytest.fixture(autouse=True)
    def _clear_candidate_veto_env(self, monkeypatch):
        monkeypatch.delenv("DISABLE_MEAN_REVERSION_SYMBOLS", raising=False)
        monkeypatch.delenv("DISABLE_STRATEGIES", raising=False)
        monkeypatch.delenv("MIN_NET_EDGE_BPS", raising=False)
        monkeypatch.delenv("FEE_BPS", raising=False)
        monkeypatch.delenv("SLIPPAGE_BPS_MULTIPLIER", raising=False)
        monkeypatch.delenv("NET_EDGE_BUFFER_BPS", raising=False)
        monkeypatch.delenv("EXECUTION_MAX_SPREAD_BPS", raising=False)
        monkeypatch.delenv("EXECUTION_MIN_DEPTH_USD", raising=False)
        monkeypatch.delenv("EXECUTION_MAX_SLIPPAGE_BPS", raising=False)
        monkeypatch.delenv("EXECUTION_MIN_DATA_QUALITY_SCORE", raising=False)
        monkeypatch.delenv("EXECUTION_MAX_SNAPSHOT_AGE_MS", raising=False)
        monkeypatch.delenv("CANDIDATE_VETO_TREND_BLOCK_MEAN_REVERSION", raising=False)
        monkeypatch.delenv("CANDIDATE_VETO_TREND_BLOCK_TREND_FOLLOWING", raising=False)
        monkeypatch.delenv("BREAKOUT_ALLOWED_VOL_REGIMES", raising=False)
        monkeypatch.delenv("CANDIDATE_VETO_REQUIRE_GREEN_READINESS", raising=False)
        monkeypatch.delenv("CANDIDATE_VETO_ENFORCE_SIDE_QUALITY_GATE", raising=False)
        monkeypatch.delenv("CANDIDATE_VETO_SIDE_QUALITY_FAIL_CLOSED", raising=False)
        monkeypatch.delenv("CANDIDATE_VETO_SIDE_QUALITY_MIN_SAMPLES", raising=False)
        monkeypatch.delenv("CANDIDATE_VETO_MIN_DIRECTIONAL_ACCURACY_LONG", raising=False)
        monkeypatch.delenv("CANDIDATE_VETO_MIN_DIRECTIONAL_ACCURACY_SHORT", raising=False)
        monkeypatch.delenv("CANDIDATE_VETO_DISABLE_SHORT_ENTRIES", raising=False)
        monkeypatch.delenv("CANDIDATE_VETO_MIN_GROSS_EDGE_TO_COST_RATIO", raising=False)
    
    def _make_snapshot(self, **overrides):
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
    
    def _make_candidate(self, **overrides):
        """Create test candidate with overrides."""
        defaults = {
            "symbol": "BTCUSDT",
            "side": "long",
            "strategy_id": "poc_magnet_scalp",
            "profile_id": "micro_range_mean_reversion",
            "expected_edge_bps": 25.0,
            "confidence": 0.7,
            "entry_price": 50000.0,
            "stop_loss": 49800.0,
            "take_profit": 50300.0,
            "max_position_usd": 5000.0,
            "generation_reason": "test",
            "snapshot_timestamp_ns": int(time.time() * 1e9),
        }
        defaults.update(overrides)
        return TradeCandidate(**defaults)
    
    def test_pass_with_good_conditions(self):
        """Should pass with favorable conditions."""
        stage = CandidateVetoStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(imb_5s=0.2),  # Favorable orderflow
                "candidate": self._make_candidate(side="long", expected_edge_bps=25.0),
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
    
    def test_veto_adverse_orderflow_long(self):
        """Should veto long when orderflow is strongly negative."""
        config = CandidateVetoConfig(orderflow_veto_base=0.5)
        stage = CandidateVetoStage(config=config)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(imb_5s=-0.65),  # Strong sell pressure
                "candidate": self._make_candidate(side="long"),
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "orderflow_veto_long" in ctx.rejection_reason
    
    def test_veto_adverse_orderflow_short(self):
        """Should veto short when orderflow is strongly positive."""
        config = CandidateVetoConfig(orderflow_veto_base=0.5)
        stage = CandidateVetoStage(config=config)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(imb_5s=0.65),  # Strong buy pressure
                "candidate": self._make_candidate(side="short"),
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "orderflow_veto_short" in ctx.rejection_reason

    def test_mean_reversion_fade_uses_symbol_specific_orderflow_cap_for_short(self):
        """Mean reversion fade should honor symbol-specific adverse-orderflow allowance."""
        with patch.dict(
            os.environ,
            {"MEAN_REVERSION_MAX_ADVERSE_ORDERFLOW_BY_SYMBOL": "BTCUSDT:0.85"},
            clear=False,
        ):
            stage = CandidateVetoStage(config=CandidateVetoConfig(orderflow_veto_base=0.5))
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(imb_5s=0.76),
                "candidate": self._make_candidate(side="short", strategy_id="mean_reversion_fade"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE

    def test_pre_entry_invalidation_veto_uses_market_context_orderflow(self):
        """Should veto when raw market_context orderflow already hits invalidation threshold."""
        stage = CandidateVetoStage(config=CandidateVetoConfig(orderflow_veto_base=0.9))
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "market_context": {"orderflow_imbalance": -0.80},
                "snapshot": self._make_snapshot(imb_5s=-0.10),  # benign smoothed flow
                "candidate": self._make_candidate(side="long"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.REJECT
        assert ctx.rejection_reason.startswith("pre_entry_invalidation_risk:")
        assert "orderflow_sell_pressure" in ctx.rejection_reason

    def test_pre_entry_invalidation_veto_blocks_long_at_vah_resistance(self):
        """Should veto long when already at VAH resistance."""
        stage = CandidateVetoStage(config=CandidateVetoConfig())
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(
                    mid_price=50000.0,
                    vah_price=50010.0,
                    distance_to_vah_bps=2.0,  # ~0.02% away
                ),
                "candidate": self._make_candidate(side="long"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.REJECT
        assert ctx.rejection_reason.startswith("pre_entry_invalidation_risk:")
        assert "price_at_resistance_vah" in ctx.rejection_reason

    def test_pre_entry_invalidation_allows_scalper_profile_on_flow_and_support(self):
        """Scalper profile should not be blocked by mirrored invalidation exits."""
        stage = CandidateVetoStage(config=CandidateVetoConfig())
        ctx = StageContext(
            symbol="SOLUSDT",
            data={
                "market_context": {"orderflow_imbalance": 0.82, "distance_to_val_pct": 0.0005},
                "snapshot": self._make_snapshot(
                    imb_5s=0.0,
                    mid_price=100.0,
                    val_price=99.90,
                    distance_to_val_bps=5.0,
                ),
                "candidate": self._make_candidate(
                    side="short",
                    strategy_id="scalper",
                    profile_id="scalper",
                ),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE

    def test_pre_entry_invalidation_allows_mean_reversion_on_flow_alone(self):
        """Mean reversion should not be vetoed by adverse flow alone."""
        stage = CandidateVetoStage(config=CandidateVetoConfig())
        ctx = StageContext(
            symbol="ETHUSDT",
            data={
                "market_context": {"orderflow_imbalance": -0.92},
                "snapshot": self._make_snapshot(
                    imb_5s=-0.10,
                    mid_price=50000.0,
                    vah_price=50150.0,
                    distance_to_vah_bps=30.0,
                ),
                "candidate": self._make_candidate(side="long", strategy_id="mean_reversion_fade"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE

    def test_pre_entry_invalidation_allows_mean_reversion_on_level_alone(self):
        """Mean reversion should not be vetoed by level alone."""
        stage = CandidateVetoStage(config=CandidateVetoConfig())
        ctx = StageContext(
            symbol="SOLUSDT",
            data={
                "snapshot": self._make_snapshot(
                    imb_5s=0.0,
                    mid_price=100.0,
                    vah_price=100.10,
                    distance_to_vah_bps=5.0,
                ),
                "candidate": self._make_candidate(side="long", strategy_id="mean_reversion_fade"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE

    def test_pre_entry_invalidation_allows_mean_reversion_on_moderate_flow_and_level(self):
        """Mean reversion should require stronger adverse flow before level+flow invalidation."""
        stage = CandidateVetoStage(config=CandidateVetoConfig())
        ctx = StageContext(
            symbol="ETHUSDT",
            data={
                "market_context": {"orderflow_imbalance": 0.84},
                "snapshot": self._make_snapshot(
                    imb_5s=0.20,
                    mid_price=100.0,
                    val_price=99.90,
                    distance_to_val_bps=5.0,
                ),
                "candidate": self._make_candidate(side="short", strategy_id="mean_reversion_fade"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE

    def test_pre_entry_invalidation_respects_symbol_flow_threshold_override(self):
        """Symbol-specific threshold should allow a borderline mean-reversion invalidation case."""
        stage = CandidateVetoStage(
            config=CandidateVetoConfig(
                pre_entry_invalidation_flow_threshold_by_symbol={"SOLUSDT": 1.10}
            )
        )
        ctx = StageContext(
            symbol="SOLUSDT",
            data={
                "market_context": {"orderflow_imbalance": 1.00, "distance_to_val_pct": 0.0005, "symbol": "SOLUSDT"},
                "snapshot": self._make_snapshot(
                    imb_5s=0.0,
                    mid_price=100.0,
                    val_price=99.90,
                    distance_to_val_bps=5.0,
                    symbol="SOLUSDT",
                ),
                "candidate": self._make_candidate(side="short", strategy_id="mean_reversion_fade"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE

    def test_pre_entry_invalidation_allows_spot_dip_accumulator_on_level_alone(self):
        """Spot dip accumulation should not be vetoed by level alone."""
        stage = CandidateVetoStage(config=CandidateVetoConfig())
        ctx = StageContext(
            symbol="SOLUSDT",
            data={
                "snapshot": self._make_snapshot(
                    imb_5s=0.0,
                    mid_price=100.0,
                    vah_price=100.10,
                    distance_to_vah_bps=5.0,
                ),
                "candidate": self._make_candidate(side="long", strategy_id="spot_dip_accumulator"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE

    def test_require_green_readiness_blocks_non_green(self):
        """Should veto entries when readiness is not green and guard is enabled."""
        stage = CandidateVetoStage(
            config=CandidateVetoConfig(
                require_green_readiness=True,
                enforce_side_quality_gate=False,
            )
        )
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "readiness_level": "yellow",
                "snapshot": self._make_snapshot(),
                "candidate": self._make_candidate(side="long"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "execution_veto:readiness_yellow"

    def test_side_quality_gate_blocks_low_long_accuracy(self):
        """Should veto long entries when long directional accuracy is below threshold."""
        stage = CandidateVetoStage(
            config=CandidateVetoConfig(
                enforce_side_quality_gate=True,
                side_quality_fail_closed=True,
                side_quality_min_samples=100,
                min_directional_accuracy_long=0.55,
                min_directional_accuracy_short=0.55,
            )
        )
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "readiness_level": "green",
                "market_context": {
                    "prediction_score_gate_metrics": {
                        "samples": 220,
                        "directional_accuracy_long": 0.49,
                        "directional_accuracy_short": 0.61,
                    }
                },
                "snapshot": self._make_snapshot(),
                "candidate": self._make_candidate(side="long"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.REJECT
        assert "side_quality_veto:long_directional_accuracy" in (ctx.rejection_reason or "")

    def test_side_quality_gate_fail_closed_when_metrics_missing(self):
        """Should fail closed when side quality metrics are missing and fail-closed is enabled."""
        stage = CandidateVetoStage(
            config=CandidateVetoConfig(
                enforce_side_quality_gate=True,
                side_quality_fail_closed=True,
                side_quality_min_samples=100,
            )
        )
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "readiness_level": "green",
                "market_context": {},
                "snapshot": self._make_snapshot(),
                "candidate": self._make_candidate(side="short"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "side_quality_veto:metrics_missing"

    def test_orderflow_veto_symbol_session_override_relaxes_threshold(self, monkeypatch):
        """Should allow per-symbol/session threshold override for orderflow veto."""
        monkeypatch.setenv(
            "CANDIDATE_VETO_ORDERFLOW_BASE_BY_SYMBOL_SESSION",
            "ETHUSDT@EUROPE:0.6",
        )
        stage = CandidateVetoStage(config=CandidateVetoConfig(orderflow_veto_base=0.5))
        ctx = StageContext(
            symbol="ETHUSDT",
            data={
                "market_context": {"session": "europe"},
                "snapshot": self._make_snapshot(imb_5s=0.53),  # Above 0.5, below 0.6
                "candidate": self._make_candidate(symbol="ETHUSDT", side="short"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE
    
    def test_veto_mean_reversion_in_trend(self):
        """Should veto mean reversion strategy in strong trend."""
        stage = CandidateVetoStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(
                    trend_direction="up",
                    trend_strength=0.8,  # Strong trend
                ),
                "candidate": self._make_candidate(
                    strategy_id="mean_reversion_fade",  # Mean reversion
                ),
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "regime_veto" in ctx.rejection_reason
    
    def test_veto_low_edge(self):
        """Should veto when edge doesn't cover costs."""
        config = CandidateVetoConfig(min_net_edge_bps=10.0, fee_bps=3.0)
        stage = CandidateVetoStage(config=config)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(expected_fill_slippage_bps=3.0),
                "candidate": self._make_candidate(expected_edge_bps=5.0),
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "tradeability_veto" in ctx.rejection_reason

    def test_tradeability_prefers_ev_gate_costs(self):
        """Should use EVGate-derived costs when available."""
        from quantgambit.signals.stages.ev_gate import EVGateResult

        config = CandidateVetoConfig(min_net_edge_bps=10.0)
        stage = CandidateVetoStage(config=config)
        ev_gate_result = EVGateResult(
            decision="ACCEPT",
            G_bps=15.0,
            total_cost_bps=10.0,
        )
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(),
                "candidate": self._make_candidate(expected_edge_bps=25.0),
                "ev_gate_result": ev_gate_result,
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.REJECT
        assert "tradeability_veto" in ctx.rejection_reason

    def test_tradeability_vetoes_low_gross_to_cost_ratio(self):
        """Should reject when gross edge is too small relative to total costs."""
        from quantgambit.signals.stages.ev_gate import EVGateResult

        stage = CandidateVetoStage(
            config=CandidateVetoConfig(
                min_net_edge_bps=1.0,
                min_gross_edge_to_cost_ratio=1.5,
            )
        )
        ev_gate_result = EVGateResult(
            decision="ACCEPT",
            G_bps=7.0,
            total_cost_bps=6.0,
        )
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(),
                "candidate": self._make_candidate(expected_edge_bps=25.0),
                "ev_gate_result": ev_gate_result,
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.REJECT
        assert "tradeability_veto:gross_cost_ratio" in (ctx.rejection_reason or "")

    def test_tradeability_allows_gross_to_cost_ratio_at_threshold(self):
        """Should not reject when gross-to-cost ratio is exactly at threshold."""
        from quantgambit.signals.stages.ev_gate import EVGateResult

        stage = CandidateVetoStage(
            config=CandidateVetoConfig(
                min_net_edge_bps=1.0,
                min_gross_edge_to_cost_ratio=1.4,
            )
        )
        ev_gate_result = EVGateResult(
            decision="ACCEPT",
            G_bps=14.0,
            total_cost_bps=10.0,
        )
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(),
                "candidate": self._make_candidate(expected_edge_bps=25.0),
                "ev_gate_result": ev_gate_result,
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE

    def test_execution_quality_allows_small_slippage_overshoot_with_tolerance(self):
        stage = CandidateVetoStage(
            config=CandidateVetoConfig(
                max_slippage_bps=6.0,
                slippage_tolerance_bps=0.25,
            )
        )
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(expected_fill_slippage_bps=6.15),
                "candidate": self._make_candidate(expected_edge_bps=25.0),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE

    def test_short_entries_can_be_hard_disabled(self):
        """Should reject short candidates when explicit short disable is enabled."""
        stage = CandidateVetoStage(
            config=CandidateVetoConfig(
                disable_short_entries=True,
            )
        )
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(),
                "candidate": self._make_candidate(side="short"),
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "direction_policy_blocked:short_disabled"
    
    def test_exit_signal_bypasses_veto(self):
        """Exit signals should bypass candidate veto."""
        stage = CandidateVetoStage()
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "snapshot": self._make_snapshot(imb_5s=-0.8),  # Bad orderflow
            },
            signal={"is_exit_signal": True, "side": "sell"},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE


class TestCooldownStage:
    """Tests for CooldownStage."""
    
    def test_pass_no_cooldown(self):
        """Should pass when no cooldown active."""
        manager = CooldownManager()
        stage = CooldownStage(manager=manager)
        
        candidate = TradeCandidate(
            symbol="BTCUSDT",
            side="long",
            strategy_id="test_strategy",
            profile_id="test_profile",
            expected_edge_bps=20.0,
            confidence=0.7,
            entry_price=50000.0,
            stop_loss=49800.0,
            take_profit=50300.0,
            max_position_usd=5000.0,
            generation_reason="test",
            snapshot_timestamp_ns=int(time.time() * 1e9),
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
    
    def test_reject_entry_cooldown(self):
        """Should reject when entry cooldown is active."""
        config = CooldownConfig(default_entry_cooldown_sec=60.0)
        manager = CooldownManager()
        manager.record_entry("BTCUSDT", "test_strategy", "long")  # Just entered
        
        stage = CooldownStage(config=config, manager=manager)
        
        candidate = TradeCandidate(
            symbol="BTCUSDT",
            side="long",
            strategy_id="test_strategy",
            profile_id="test_profile",
            expected_edge_bps=20.0,
            confidence=0.7,
            entry_price=50000.0,
            stop_loss=49800.0,
            take_profit=50300.0,
            max_position_usd=5000.0,
            generation_reason="test",
            snapshot_timestamp_ns=int(time.time() * 1e9),
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "entry_cooldown" in ctx.rejection_reason
    
    def test_reject_exit_cooldown(self):
        """Should reject entry shortly after exit."""
        config = CooldownConfig(exit_cooldown_sec=30.0)
        manager = CooldownManager()
        manager.record_exit("BTCUSDT")  # Just exited
        
        stage = CooldownStage(config=config, manager=manager)
        
        candidate = TradeCandidate(
            symbol="BTCUSDT",
            side="long",
            strategy_id="new_strategy",
            profile_id="test_profile",
            expected_edge_bps=20.0,
            confidence=0.7,
            entry_price=50000.0,
            stop_loss=49800.0,
            take_profit=50300.0,
            max_position_usd=5000.0,
            generation_reason="test",
            snapshot_timestamp_ns=int(time.time() * 1e9),
        )
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "exit_cooldown" in ctx.rejection_reason
    
    def test_exit_signal_bypasses_cooldown(self):
        """Exit signals should bypass cooldown and record exit."""
        manager = CooldownManager()
        stage = CooldownStage(manager=manager)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={},
            signal={"is_exit_signal": True, "side": "sell"},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
        # Should have recorded exit
        assert manager.get_time_since_exit("BTCUSDT") is not None


class TestCostDataQualityStage:
    """Tests for CostDataQualityStage."""

    def test_prefers_fresh_book_over_stale_spread_timestamp(self):
        """Spread age should follow the freshest orderbook-derived source."""
        stage = CostDataQualityStage(
            config=CostDataQualityConfig(max_spread_age_ms=5000, max_book_age_ms=5000)
        )
        now_ms = int(time.time() * 1000)
        ctx = StageContext(
            symbol="SOLUSDT",
            data={
                "features": make_features(),
                "market_context": {
                    **make_market_context(),
                    "book_recv_ms": now_ms,
                    "book_timestamp_ms": now_ms,
                    "timestamp_ms": now_ms,
                    "spread_timestamp_ms": now_ms - 7000,
                    "best_bid": 49999.0,
                    "best_ask": 50001.0,
                    "spread": 2.0,
                },
            },
            signal={"side": "long"},
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE
        quality = ctx.data["cost_data_quality_result"]
        assert quality.spread_age_ms <= 10.0
        assert quality.book_age_ms <= 10.0


class TestDataReadinessStageSolFreshness:
    """Regression coverage for SOL freshness handling."""

    def test_sol_allows_slightly_lagging_trade_feed_when_book_is_fresh(self):
        """SOL should not hard-block when the orderbook is fresh and trade lag is only feed-sparse."""
        config = DataReadinessConfig(
            trade_lag_green_ms=2000,
            trade_lag_yellow_ms=4000,
            trade_lag_red_ms=6000,
        )
        stage = DataReadinessStage(config=config)
        now_ms = int(time.time() * 1000)
        features = make_features(timestamp=time.time())
        features["trade_ts_ms"] = now_ms - 6800
        ctx = StageContext(
            symbol="SOLUSDT",
            data={
                "features": features,
                "market_context": {
                    **make_market_context(),
                    "book_recv_ms": now_ms,
                    "trade_recv_ms": now_ms - 6800,
                    "feed_staleness": {"orderbook": 0.0, "trade": 6.8},
                    "trade_age_sec": 0.12,
                },
            },
        )

        result = asyncio.run(stage.run(ctx))

        assert result == StageResult.CONTINUE
        assert ctx.rejection_reason is None
