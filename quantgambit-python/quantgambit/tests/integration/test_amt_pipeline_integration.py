"""
Integration tests for AMT fields in the decision pipeline.

Tests that AMT fields flow correctly through the pipeline:
1. AMTCalculatorStage calculates AMT levels from candle data
2. SnapshotBuilderStage reads AMT levels from ctx.data["amt_levels"]
3. MarketSnapshot contains all AMT fields
4. MarketSnapshot.to_dict() includes AMT fields for telemetry

**Validates: Requirements 1.4, 6.1, 6.2, 6.3, 6.4**
"""

import pytest
import time
from typing import List, Dict, Any

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.amt_calculator import (
    AMTCalculatorStage,
    AMTCalculatorConfig,
    AMTLevels,
    CandleCache,
)
from quantgambit.signals.stages.snapshot_builder import (
    SnapshotBuilderStage,
    SnapshotBuilderConfig,
)
from quantgambit.deeptrader_core.types import MarketSnapshot


def _generate_candles(
    count: int,
    base_price: float = 50000.0,
    base_volume: float = 100.0,
    start_ts: float = 1000.0,
    interval_sec: float = 300.0,
) -> List[Dict[str, Any]]:
    """
    Generate sample candle data for testing.
    
    Creates candles with varying prices and volumes to produce
    a realistic volume profile with distinct POC, VAH, and VAL.
    
    Args:
        count: Number of candles to generate
        base_price: Base price around which candles are generated
        base_volume: Base volume for candles
        start_ts: Starting timestamp
        interval_sec: Time interval between candles
        
    Returns:
        List of candle dictionaries
    """
    candles = []
    for i in range(count):
        # Create price variation that concentrates volume around base_price
        # This creates a bell-curve-like distribution for volume profile
        price_offset = (i % 10 - 5) * 50  # -250 to +200
        
        # Higher volume near the center (base_price)
        distance_from_center = abs(i % 10 - 5)
        volume_multiplier = 3.0 - (distance_from_center * 0.4)  # 3.0 at center, 1.0 at edges
        
        candles.append({
            "open": base_price + price_offset,
            "high": base_price + price_offset + 30,
            "low": base_price + price_offset - 30,
            "close": base_price + price_offset + 15,
            "volume": base_volume * max(1.0, volume_multiplier),
            "ts": start_ts + i * interval_sec,
        })
    return candles


class TestAMTPipelineIntegration:
    """Integration tests for AMT fields in the decision pipeline."""
    
    @pytest.fixture
    def sample_candles(self) -> List[Dict[str, Any]]:
        """Generate sample candle data with sufficient count for AMT calculation."""
        return _generate_candles(count=50, base_price=50000.0)
    
    @pytest.fixture
    def insufficient_candles(self) -> List[Dict[str, Any]]:
        """Generate insufficient candle data (less than min_candles)."""
        return _generate_candles(count=5, base_price=50000.0)
    
    @pytest.fixture
    def candle_cache(self, sample_candles: List[Dict[str, Any]]) -> CandleCache:
        """Create a CandleCache populated with sample candles."""
        cache = CandleCache(max_candles=500)
        for candle in sample_candles:
            cache.add_candle("BTCUSDT", candle)
        return cache
    
    @pytest.fixture
    def amt_config(self) -> AMTCalculatorConfig:
        """Create AMT calculator configuration for testing."""
        return AMTCalculatorConfig(
            lookback_candles=100,
            value_area_pct=68.0,
            bin_count=20,
            min_candles=10,
        )
    
    @pytest.mark.asyncio
    async def test_amt_calculator_stage_sets_amt_levels(
        self,
        sample_candles: List[Dict[str, Any]],
        amt_config: AMTCalculatorConfig,
    ):
        """
        Test that AMTCalculatorStage sets ctx.data['amt_levels'] with valid candle data.
        
        **Validates: Requirement 1.4** - AMT_Calculator_Stage SHALL store calculated 
        AMT levels in the stage context for downstream stages.
        """
        # Create stage context with candles and price
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 0.3,
                    "trend_direction": "up",
                    "trend_strength": 0.5,
                },
                "market_context": {},
            },
        )
        
        # Create and run AMTCalculatorStage
        stage = AMTCalculatorStage(config=amt_config)
        result = await stage.run(ctx)
        
        # Verify stage returns CONTINUE
        assert result == StageResult.CONTINUE
        
        # Verify amt_levels is set in context
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels is not None, "amt_levels should be set in ctx.data"
        assert isinstance(amt_levels, AMTLevels), "amt_levels should be AMTLevels instance"
        
        # Verify all AMT fields are populated
        assert amt_levels.point_of_control is not None
        assert amt_levels.value_area_high is not None
        assert amt_levels.value_area_low is not None
        assert amt_levels.position_in_value in ("above", "below", "inside")
        assert isinstance(amt_levels.distance_to_poc, float)
        assert isinstance(amt_levels.distance_to_vah, float)
        assert isinstance(amt_levels.distance_to_val, float)
        assert isinstance(amt_levels.rotation_factor, float)
        assert amt_levels.candle_count > 0
        assert amt_levels.calculation_ts > 0
    
    @pytest.mark.asyncio
    async def test_amt_calculator_stage_sets_none_with_insufficient_data(
        self,
        insufficient_candles: List[Dict[str, Any]],
        amt_config: AMTCalculatorConfig,
    ):
        """
        Test that AMTCalculatorStage sets ctx.data['amt_levels'] to None with insufficient data.
        
        **Validates: Requirement 1.5** - IF insufficient candle data is available, 
        THEN THE AMT_Calculator_Stage SHALL return None for AMT fields and continue processing.
        """
        # Create stage context with insufficient candles
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": insufficient_candles,
                "features": {
                    "price": 50000.0,
                },
                "market_context": {},
            },
        )
        
        # Create and run AMTCalculatorStage
        stage = AMTCalculatorStage(config=amt_config)
        result = await stage.run(ctx)
        
        # Verify stage returns CONTINUE (never blocks pipeline)
        assert result == StageResult.CONTINUE
        
        # Verify amt_levels is None
        assert ctx.data.get("amt_levels") is None, "amt_levels should be None with insufficient data"
    
    @pytest.mark.asyncio
    async def test_amt_fields_flow_from_calculator_to_snapshot_builder(
        self,
        sample_candles: List[Dict[str, Any]],
        amt_config: AMTCalculatorConfig,
    ):
        """
        Test that AMT fields flow from AMTCalculatorStage through SnapshotBuilderStage to MarketSnapshot.
        
        **Validates: Requirements 5.1, 5.2, 5.3** - SnapshotBuilderStage SHALL read AMT fields 
        from stage context (set by AMT_Calculator_Stage).
        """
        # Create stage context with candles and features
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "bid": 49999.0,
                    "ask": 50001.0,
                    "spread_bps": 4.0,
                    "timestamp": time.time(),
                    "orderflow_imbalance": 0.3,
                    "trend_direction": "up",
                    "trend_strength": 0.5,
                    "bid_depth_usd": 100000.0,
                    "ask_depth_usd": 100000.0,
                },
                "market_context": {
                    "volatility_regime": "normal",
                    "trend_direction": "up",
                    "trend_strength": 0.5,
                },
            },
        )
        
        # Run AMTCalculatorStage first
        amt_stage = AMTCalculatorStage(config=amt_config)
        amt_result = await amt_stage.run(ctx)
        assert amt_result == StageResult.CONTINUE
        
        # Capture AMT levels for comparison
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels is not None, "AMT levels should be set after AMTCalculatorStage"
        
        # Run SnapshotBuilderStage
        snapshot_stage = SnapshotBuilderStage()
        snapshot_result = await snapshot_stage.run(ctx)
        assert snapshot_result == StageResult.CONTINUE
        
        # Verify snapshot is created
        snapshot = ctx.data.get("snapshot")
        assert snapshot is not None, "snapshot should be set after SnapshotBuilderStage"
        assert isinstance(snapshot, MarketSnapshot)
        
        # Verify AMT fields in snapshot match AMT levels from calculator
        assert snapshot.poc_price == amt_levels.point_of_control
        assert snapshot.vah_price == amt_levels.value_area_high
        assert snapshot.val_price == amt_levels.value_area_low
        assert snapshot.position_in_value == amt_levels.position_in_value
        assert snapshot.distance_to_poc_bps == amt_levels.distance_to_poc_bps
        assert snapshot.distance_to_vah_bps == amt_levels.distance_to_vah_bps
        assert snapshot.distance_to_val_bps == amt_levels.distance_to_val_bps
        assert snapshot.rotation_factor == amt_levels.rotation_factor
    
    @pytest.mark.asyncio
    async def test_market_snapshot_to_dict_includes_amt_fields(
        self,
        sample_candles: List[Dict[str, Any]],
        amt_config: AMTCalculatorConfig,
    ):
        """
        Test that MarketSnapshot.to_dict() includes all AMT fields for telemetry persistence.
        
        **Validates: Requirements 6.1, 6.2, 6.3, 6.4** - WHEN publishing a decision event, 
        THE Telemetry_Pipeline SHALL include AMT fields in the snapshot payload.
        """
        # Create stage context
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "bid": 49999.0,
                    "ask": 50001.0,
                    "spread_bps": 4.0,
                    "timestamp": time.time(),
                    "orderflow_imbalance": 0.3,
                    "trend_direction": "up",
                    "trend_strength": 0.5,
                    "bid_depth_usd": 100000.0,
                    "ask_depth_usd": 100000.0,
                },
                "market_context": {
                    "volatility_regime": "normal",
                    "trend_direction": "up",
                    "trend_strength": 0.5,
                },
            },
        )
        
        # Run pipeline stages
        amt_stage = AMTCalculatorStage(config=amt_config)
        await amt_stage.run(ctx)
        
        snapshot_stage = SnapshotBuilderStage()
        await snapshot_stage.run(ctx)
        
        # Get snapshot and convert to dict
        snapshot = ctx.data.get("snapshot")
        assert snapshot is not None
        
        telemetry_dict = snapshot.to_dict()
        
        # Verify all AMT fields are present in telemetry dict
        # Requirement 6.1: poc_price, vah_price, val_price
        assert "poc_price" in telemetry_dict, "poc_price should be in telemetry payload"
        assert "vah_price" in telemetry_dict, "vah_price should be in telemetry payload"
        assert "val_price" in telemetry_dict, "val_price should be in telemetry payload"
        
        # Requirement 6.2: position_in_value
        assert "position_in_value" in telemetry_dict, "position_in_value should be in telemetry payload"
        
        # Requirement 6.3: distance fields (using _bps suffix per Requirement 2.3)
        assert "distance_to_poc_bps" in telemetry_dict, "distance_to_poc_bps should be in telemetry payload"
        assert "distance_to_vah_bps" in telemetry_dict, "distance_to_vah_bps should be in telemetry payload"
        assert "distance_to_val_bps" in telemetry_dict, "distance_to_val_bps should be in telemetry payload"
        
        # Requirement 6.4: rotation_factor
        assert "rotation_factor" in telemetry_dict, "rotation_factor should be in telemetry payload"
        
        # Verify values are not None (since we have valid candle data)
        assert telemetry_dict["poc_price"] is not None
        assert telemetry_dict["vah_price"] is not None
        assert telemetry_dict["val_price"] is not None
        assert telemetry_dict["position_in_value"] in ("above", "below", "inside")
        assert isinstance(telemetry_dict["distance_to_poc_bps"], (int, float))
        assert isinstance(telemetry_dict["distance_to_vah_bps"], (int, float))
        assert isinstance(telemetry_dict["distance_to_val_bps"], (int, float))
        assert isinstance(telemetry_dict["rotation_factor"], (int, float))
    
    @pytest.mark.asyncio
    async def test_snapshot_builder_fallback_when_amt_levels_none(self):
        """
        Test that SnapshotBuilderStage falls back to features dict when amt_levels is None.
        
        **Validates: Requirement 5.4** - SnapshotBuilderStage SHALL fall back to features dict 
        if stage context AMT fields are not available.
        """
        # Create stage context without AMT levels (simulating insufficient data)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "amt_levels": None,  # Explicitly set to None
                "features": {
                    "price": 50000.0,
                    "bid": 49999.0,
                    "ask": 50001.0,
                    "spread_bps": 4.0,
                    "timestamp": time.time(),
                    "orderflow_imbalance": 0.3,
                    "trend_direction": "up",
                    "trend_strength": 0.5,
                    "bid_depth_usd": 100000.0,
                    "ask_depth_usd": 100000.0,
                    # Legacy AMT fields in features dict
                    "point_of_control": 49900.0,
                    "value_area_high": 50100.0,
                    "value_area_low": 49700.0,
                    "position_in_value": "inside",
                },
                "market_context": {
                    "volatility_regime": "normal",
                    "trend_direction": "up",
                    "trend_strength": 0.5,
                },
            },
        )
        
        # Run SnapshotBuilderStage
        snapshot_stage = SnapshotBuilderStage()
        result = await snapshot_stage.run(ctx)
        assert result == StageResult.CONTINUE
        
        # Verify snapshot uses fallback values from features dict
        snapshot = ctx.data.get("snapshot")
        assert snapshot is not None
        
        # Should use values from features dict
        assert snapshot.poc_price == 49900.0
        assert snapshot.vah_price == 50100.0
        assert snapshot.val_price == 49700.0
        assert snapshot.position_in_value == "inside"
    
    @pytest.mark.asyncio
    async def test_amt_calculator_with_candle_cache(
        self,
        candle_cache: CandleCache,
        amt_config: AMTCalculatorConfig,
    ):
        """
        Test that AMTCalculatorStage correctly uses CandleCache.
        
        **Validates: Requirement 1.1** - AMT_Calculator_Stage SHALL calculate POC, VAH, 
        and VAL from the most recent candles.
        """
        # Create stage context without candles in data (should use cache)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 0.3,
                    "trend_direction": "up",
                    "trend_strength": 0.5,
                },
                "market_context": {},
            },
        )
        
        # Create stage with candle cache
        stage = AMTCalculatorStage(config=amt_config, candle_cache=candle_cache)
        result = await stage.run(ctx)
        
        # Verify stage returns CONTINUE
        assert result == StageResult.CONTINUE
        
        # Verify amt_levels is set (using candles from cache)
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels is not None, "amt_levels should be set using candle cache"
        assert isinstance(amt_levels, AMTLevels)
        assert amt_levels.candle_count > 0
    
    @pytest.mark.asyncio
    async def test_full_pipeline_amt_flow(
        self,
        sample_candles: List[Dict[str, Any]],
        amt_config: AMTCalculatorConfig,
    ):
        """
        Test full pipeline flow: AMTCalculatorStage -> SnapshotBuilderStage -> telemetry dict.
        
        This is an end-to-end test verifying the complete AMT data flow.
        
        **Validates: Requirements 1.4, 6.1, 6.2, 6.3, 6.4**
        """
        # Create stage context with all required data
        current_price = 50050.0  # Slightly above base price
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": current_price,
                    "bid": current_price - 1.0,
                    "ask": current_price + 1.0,
                    "spread_bps": 4.0,
                    "timestamp": time.time(),
                    "orderflow_imbalance": 0.4,
                    "trend_direction": "up",
                    "trend_strength": 0.6,
                    "bid_depth_usd": 150000.0,
                    "ask_depth_usd": 120000.0,
                },
                "market_context": {
                    "volatility_regime": "normal",
                    "trend_direction": "up",
                    "trend_strength": 0.6,
                },
            },
        )
        
        # Step 1: Run AMTCalculatorStage
        amt_stage = AMTCalculatorStage(config=amt_config)
        amt_result = await amt_stage.run(ctx)
        assert amt_result == StageResult.CONTINUE
        
        # Capture AMT levels
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels is not None
        
        # Step 2: Run SnapshotBuilderStage
        snapshot_stage = SnapshotBuilderStage()
        snapshot_result = await snapshot_stage.run(ctx)
        assert snapshot_result == StageResult.CONTINUE
        
        # Step 3: Get snapshot and verify
        snapshot = ctx.data.get("snapshot")
        assert snapshot is not None
        assert isinstance(snapshot, MarketSnapshot)
        
        # Verify snapshot has correct symbol and price
        assert snapshot.symbol == "BTCUSDT"
        assert snapshot.mid_price == current_price
        
        # Verify AMT fields match
        assert snapshot.poc_price == amt_levels.point_of_control
        assert snapshot.vah_price == amt_levels.value_area_high
        assert snapshot.val_price == amt_levels.value_area_low
        assert snapshot.position_in_value == amt_levels.position_in_value
        
        # Step 4: Convert to telemetry dict and verify
        telemetry_dict = snapshot.to_dict()
        
        # Verify all required fields are present
        required_fields = [
            "symbol", "mid_price", "spread_bps",
            "poc_price", "vah_price", "val_price", "position_in_value",
            "distance_to_poc_bps", "distance_to_vah_bps", "distance_to_val_bps",
            "rotation_factor",
        ]
        for field in required_fields:
            assert field in telemetry_dict, f"{field} should be in telemetry dict"
        
        # Verify AMT values in telemetry match snapshot
        assert telemetry_dict["poc_price"] == snapshot.poc_price
        assert telemetry_dict["vah_price"] == snapshot.vah_price
        assert telemetry_dict["val_price"] == snapshot.val_price
        assert telemetry_dict["position_in_value"] == snapshot.position_in_value
        assert telemetry_dict["distance_to_poc_bps"] == snapshot.distance_to_poc_bps
        assert telemetry_dict["distance_to_vah_bps"] == snapshot.distance_to_vah_bps
        assert telemetry_dict["distance_to_val_bps"] == snapshot.distance_to_val_bps
        assert telemetry_dict["rotation_factor"] == snapshot.rotation_factor
    
    @pytest.mark.asyncio
    async def test_amt_value_area_bounds_valid(
        self,
        sample_candles: List[Dict[str, Any]],
        amt_config: AMTCalculatorConfig,
    ):
        """
        Test that calculated AMT levels have valid value area bounds (VAL <= POC <= VAH).
        
        This validates the correctness of the volume profile calculation.
        """
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 0.0,
                    "trend_direction": None,
                    "trend_strength": 0.0,
                },
                "market_context": {},
            },
        )
        
        stage = AMTCalculatorStage(config=amt_config)
        await stage.run(ctx)
        
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels is not None
        
        # Verify value area bounds
        assert amt_levels.value_area_low <= amt_levels.point_of_control, \
            "VAL should be <= POC"
        assert amt_levels.point_of_control <= amt_levels.value_area_high, \
            "POC should be <= VAH"
        assert amt_levels.value_area_low <= amt_levels.value_area_high, \
            "VAL should be <= VAH"
    
    @pytest.mark.asyncio
    async def test_position_classification_consistency(
        self,
        sample_candles: List[Dict[str, Any]],
        amt_config: AMTCalculatorConfig,
    ):
        """
        Test that position_in_value classification is consistent with price and AMT levels.
        """
        # Test with price above VAH
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 60000.0,  # Well above typical VAH
                    "orderflow_imbalance": 0.0,
                    "trend_direction": None,
                    "trend_strength": 0.0,
                },
                "market_context": {},
            },
        )
        
        stage = AMTCalculatorStage(config=amt_config)
        await stage.run(ctx)
        
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels is not None
        
        # With price at 60000 (well above base_price of 50000), should be "above"
        if 60000.0 > amt_levels.value_area_high:
            assert amt_levels.position_in_value == "above"
        
        # Test with price below VAL
        ctx2 = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 40000.0,  # Well below typical VAL
                    "orderflow_imbalance": 0.0,
                    "trend_direction": None,
                    "trend_strength": 0.0,
                },
                "market_context": {},
            },
        )
        
        await stage.run(ctx2)
        
        amt_levels2 = ctx2.data.get("amt_levels")
        assert amt_levels2 is not None
        
        # With price at 40000 (well below base_price of 50000), should be "below"
        if 40000.0 < amt_levels2.value_area_low:
            assert amt_levels2.position_in_value == "below"


class TestAMTPipelineEdgeCases:
    """Edge case tests for AMT pipeline integration."""
    
    @pytest.mark.asyncio
    async def test_empty_candles_list(self):
        """Test with empty candles list."""
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": [],
                "features": {"price": 50000.0},
                "market_context": {},
            },
        )
        
        stage = AMTCalculatorStage()
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data.get("amt_levels") is None
    
    @pytest.mark.asyncio
    async def test_no_candles_key(self):
        """Test when candles key is missing from context."""
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": {"price": 50000.0},
                "market_context": {},
            },
        )
        
        stage = AMTCalculatorStage()
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data.get("amt_levels") is None
    
    @pytest.mark.asyncio
    async def test_snapshot_builder_with_missing_features(self):
        """Test SnapshotBuilderStage handles missing features gracefully."""
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "amt_levels": None,
                "features": {},  # Empty features
                "market_context": {},
            },
        )
        
        stage = SnapshotBuilderStage()
        result = await stage.run(ctx)
        
        # Should still return CONTINUE
        assert result == StageResult.CONTINUE
        
        # Snapshot should be created with defaults
        snapshot = ctx.data.get("snapshot")
        assert snapshot is not None
        assert snapshot.position_in_value == "inside"  # Default value
    
    @pytest.mark.asyncio
    async def test_rotation_factor_bounds(self):
        """Test that rotation factor is within expected bounds [-15, +15]."""
        candles = _generate_candles(count=50)
        
        # Test with extreme orderflow and trend values
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 1.0,  # Maximum
                    "trend_direction": "up",
                    "trend_strength": 1.0,  # Maximum
                },
                "market_context": {},
            },
        )
        
        stage = AMTCalculatorStage()
        await stage.run(ctx)
        
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels is not None
        assert -15.0 <= amt_levels.rotation_factor <= 15.0
        
        # Test with opposite extreme
        ctx2 = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": -1.0,  # Minimum
                    "trend_direction": "down",
                    "trend_strength": 1.0,  # Maximum
                },
                "market_context": {},
            },
        )
        
        await stage.run(ctx2)
        
        amt_levels2 = ctx2.data.get("amt_levels")
        assert amt_levels2 is not None
        assert -15.0 <= amt_levels2.rotation_factor <= 15.0
