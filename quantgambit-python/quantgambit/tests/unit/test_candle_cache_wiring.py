"""
Unit tests for CandleCache wiring between FeatureWorker and DecisionEngine.

This test verifies that:
1. CandleCache can be shared between FeatureWorker and DecisionEngine
2. Candles added by FeatureWorker are available to AMTCalculatorStage
3. The wiring works correctly in the runtime configuration

Requirements: 1.1 (AMT Calculator Stage)
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from quantgambit.config.loss_prevention import load_loss_prevention_config
from quantgambit.signals.stages.amt_calculator import CandleCache, AMTCalculatorStage
from quantgambit.signals.decision_engine import DecisionEngine


class TestCandleCacheWiring:
    """Test CandleCache wiring between components."""

    def test_candle_cache_shared_between_components(self):
        """Verify CandleCache can be shared between FeatureWorker and DecisionEngine."""
        # Create a shared candle cache
        candle_cache = CandleCache(max_candles=100)
        
        # Add candles (simulating FeatureWorker behavior)
        for i in range(20):
            candle_cache.add_candle("BTCUSDT", {
                "open": 50000 + i * 10,
                "high": 50050 + i * 10,
                "low": 49950 + i * 10,
                "close": 50025 + i * 10,
                "volume": 100.0,
                "ts": 1000000 + i * 300,
            })
        
        # Verify candles are available
        candles = candle_cache.get_recent_candles("BTCUSDT", count=20)
        assert len(candles) == 20
        assert candles[0]["open"] == 50000
        assert candles[-1]["open"] == 50190

    def test_decision_engine_accepts_candle_cache(self):
        """Verify DecisionEngine accepts candle_cache parameter."""
        candle_cache = CandleCache(max_candles=100)
        loss_prevention_config = load_loss_prevention_config()
        
        # Create DecisionEngine with candle_cache
        engine = DecisionEngine(
            candle_cache=candle_cache,
            ev_gate_config=loss_prevention_config.ev_gate,
            ev_position_sizer_config=loss_prevention_config.ev_position_sizer,
            cost_data_quality_config=loss_prevention_config.cost_data_quality,
        )
        
        # Verify the engine was created successfully
        assert engine is not None
        assert engine.orchestrator is not None

    def test_amt_calculator_stage_uses_candle_cache(self):
        """Verify AMTCalculatorStage uses the provided candle cache."""
        candle_cache = CandleCache(max_candles=100)
        
        # Add candles to cache
        for i in range(20):
            candle_cache.add_candle("BTCUSDT", {
                "open": 50000 + i * 10,
                "high": 50050 + i * 10,
                "low": 49950 + i * 10,
                "close": 50025 + i * 10,
                "volume": 100.0,
                "ts": 1000000 + i * 300,
            })
        
        # Create AMTCalculatorStage with candle cache
        stage = AMTCalculatorStage(candle_cache=candle_cache)
        
        # Verify stage has the candle cache
        assert stage._candle_cache is candle_cache
        
        # Verify candles are accessible through the stage's cache
        candles = stage._candle_cache.get_recent_candles("BTCUSDT", count=20)
        assert len(candles) == 20

    @pytest.mark.asyncio
    async def test_amt_calculator_stage_calculates_from_cache(self):
        """Verify AMTCalculatorStage calculates AMT levels from cached candles."""
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        candle_cache = CandleCache(max_candles=100)
        
        # Add candles with varying prices and volumes
        for i in range(20):
            candle_cache.add_candle("BTCUSDT", {
                "open": 50000 + i * 10,
                "high": 50050 + i * 10,
                "low": 49950 + i * 10,
                "close": 50025 + i * 10,
                "volume": 100.0 + i * 10,  # Varying volume
                "ts": 1000000 + i * 300,
            })
        
        # Create stage with candle cache
        stage = AMTCalculatorStage(candle_cache=candle_cache)
        
        # Create context with price
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": {"price": 50100},
                "market_context": {},
            },
        )
        
        # Run the stage
        result = await stage.run(ctx)
        
        # Verify result
        assert result == StageResult.CONTINUE
        
        # Verify AMT levels were calculated
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels is not None
        assert amt_levels.point_of_control is not None
        assert amt_levels.value_area_high is not None
        assert amt_levels.value_area_low is not None
        assert amt_levels.position_in_value in ("above", "below", "inside")
        assert amt_levels.candle_count == 20


class TestFeatureWorkerCandleCacheIntegration:
    """Test FeatureWorker integration with CandleCache."""

    def test_feature_worker_accepts_candle_cache(self):
        """Verify FeaturePredictionWorker accepts candle_cache parameter."""
        from quantgambit.signals.feature_worker import FeaturePredictionWorker
        
        # Create mock redis client
        mock_redis = MagicMock()
        mock_redis.redis = MagicMock()
        
        candle_cache = CandleCache(max_candles=100)
        
        # Create FeatureWorker with candle_cache
        worker = FeaturePredictionWorker(
            redis_client=mock_redis,
            bot_id="test_bot",
            exchange="binance",
            candle_cache=candle_cache,
        )
        
        # Verify the worker has the candle cache
        assert worker._candle_cache is candle_cache

    @pytest.mark.asyncio
    async def test_feature_worker_populates_candle_cache(self):
        """Verify FeatureWorker populates candle cache when handling candles."""
        import json
        from quantgambit.signals.feature_worker import FeaturePredictionWorker
        
        # Create mock redis client
        mock_redis = MagicMock()
        mock_redis.redis = MagicMock()
        mock_redis.redis.hgetall = AsyncMock(return_value={})
        
        candle_cache = CandleCache(max_candles=100)
        
        # Create FeatureWorker with candle_cache
        worker = FeaturePredictionWorker(
            redis_client=mock_redis,
            bot_id="test_bot",
            exchange="binance",
            candle_cache=candle_cache,
        )
        
        # Simulate handling a candle event with all required fields
        # The payload needs to be wrapped in a "data" field as JSON
        ts_us = 1000000 * 1000000
        event_data = {
            "event_id": "test-event-1",
            "event_type": "candle",
            "schema_version": "v1",
            "timestamp": "1000000",
            "ts_recv_us": ts_us,
            "ts_canon_us": ts_us,
            "ts_exchange_s": None,
            "bot_id": "test_bot",
            "symbol": "BTCUSDT",
            "exchange": "binance",
            "payload": {
                "symbol": "BTCUSDT",
                "timestamp": 1000000,
                "ts_recv_us": ts_us,
                "ts_canon_us": ts_us,
                "ts_exchange_s": None,
                "open": 50000,
                "high": 50050,
                "low": 49950,
                "close": 50025,
                "volume": 100.0,
                "candle_count": 1,
            },
        }
        candle_payload = {"data": json.dumps(event_data)}
        
        await worker._handle_candle(candle_payload)
        
        # Verify candle was added to cache
        candles = candle_cache.get_recent_candles("BTCUSDT", count=10)
        assert len(candles) == 1
        assert candles[0]["open"] == 50000
        assert candles[0]["close"] == 50025
        assert candles[0]["ts"] == 1000000
