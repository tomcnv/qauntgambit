"""
Unit tests for Flow Rotation functionality.

Tests the FlowRotationConfig, FlowRotationCalculator, and _calculate_trend_bias
functions added as part of Strategy Signal Architecture Fixes - Requirement 3.

Requirements tested:
- 3.1: flow_rotation as pure orderflow imbalance signal using EWMA smoothing
- 3.2: flow_rotation_config with ewma_span, clip_min, clip_max, scale_factor
- 3.3: flow_rotation calculation formula
- 3.4: trend_bias as separate HTF trend indicator
- 3.8: flow_rotation_raw (pre-EWMA) field
- 3.9: rotation_factor retained for backward compatibility (deprecated)
- 3.12: flow_rotation_config configurable via environment variables
"""

import os
import pytest
from unittest.mock import patch

from quantgambit.signals.stages.amt_calculator import (
    FlowRotationConfig,
    FlowRotationCalculator,
    _calculate_trend_bias,
    AMTLevels,
)


class TestFlowRotationConfig:
    """Tests for FlowRotationConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values. (Requirement 3.2)"""
        config = FlowRotationConfig()
        
        assert config.ewma_span == 10
        assert config.clip_min == -5.0
        assert config.clip_max == 5.0
        assert config.scale_factor == 5.0

    def test_custom_values(self):
        """Test custom configuration values."""
        config = FlowRotationConfig(
            ewma_span=20,
            clip_min=-10.0,
            clip_max=10.0,
            scale_factor=3.0,
        )
        
        assert config.ewma_span == 20
        assert config.clip_min == -10.0
        assert config.clip_max == 10.0
        assert config.scale_factor == 3.0

    def test_from_env_with_defaults(self):
        """Test from_env() uses defaults when env vars not set. (Requirement 3.12)"""
        # Clear any existing env vars
        env_vars = [
            "FLOW_ROTATION_EWMA_SPAN",
            "FLOW_ROTATION_CLIP_MIN",
            "FLOW_ROTATION_CLIP_MAX",
            "FLOW_ROTATION_SCALE_FACTOR",
        ]
        with patch.dict(os.environ, {}, clear=True):
            for var in env_vars:
                os.environ.pop(var, None)
            
            config = FlowRotationConfig.from_env()
            
            assert config.ewma_span == 10
            assert config.clip_min == -5.0
            assert config.clip_max == 5.0
            assert config.scale_factor == 5.0

    def test_from_env_with_custom_values(self):
        """Test from_env() reads from environment variables. (Requirement 3.12)"""
        env_vars = {
            "FLOW_ROTATION_EWMA_SPAN": "20",
            "FLOW_ROTATION_CLIP_MIN": "-10.0",
            "FLOW_ROTATION_CLIP_MAX": "10.0",
            "FLOW_ROTATION_SCALE_FACTOR": "3.0",
        }
        with patch.dict(os.environ, env_vars):
            config = FlowRotationConfig.from_env()
            
            assert config.ewma_span == 20
            assert config.clip_min == -10.0
            assert config.clip_max == 10.0
            assert config.scale_factor == 3.0


class TestFlowRotationCalculator:
    """Tests for FlowRotationCalculator class."""

    def test_calculate_returns_tuple(self):
        """Test calculate() returns tuple of (smoothed, raw). (Requirement 3.8)"""
        calculator = FlowRotationCalculator()
        
        result = calculator.calculate("BTCUSDT", 0.5)
        
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_raw_value_is_scaled_orderflow(self):
        """Test raw value is orderflow_imbalance * scale_factor. (Requirement 3.3)"""
        config = FlowRotationConfig(scale_factor=5.0)
        calculator = FlowRotationCalculator(config)
        
        smoothed, raw = calculator.calculate("BTCUSDT", 0.5)
        
        # Raw should be 0.5 * 5.0 = 2.5
        assert raw == pytest.approx(2.5)

    def test_first_call_initializes_ewma(self):
        """Test first call initializes EWMA state with raw value."""
        calculator = FlowRotationCalculator()
        
        smoothed, raw = calculator.calculate("BTCUSDT", 0.5)
        
        # First call: smoothed should equal raw (EWMA initialized)
        assert smoothed == pytest.approx(raw, rel=0.01)

    def test_ewma_smoothing_applied(self):
        """Test EWMA smoothing is applied on subsequent calls. (Requirement 3.1)"""
        config = FlowRotationConfig(ewma_span=10, scale_factor=1.0)
        calculator = FlowRotationCalculator(config)
        
        # First call with value 1.0
        smoothed1, _ = calculator.calculate("BTCUSDT", 1.0)
        
        # Second call with value 0.0
        smoothed2, raw2 = calculator.calculate("BTCUSDT", 0.0)
        
        # EWMA should be between 0 and 1 (smoothed)
        # alpha = 2 / (10 + 1) = 0.1818
        # ewma = 0.1818 * 0 + 0.8182 * 1.0 = 0.8182
        assert smoothed2 < smoothed1
        assert smoothed2 > raw2

    def test_ewma_alpha_calculation(self):
        """Test EWMA alpha is calculated correctly from span."""
        config = FlowRotationConfig(ewma_span=10)
        calculator = FlowRotationCalculator(config)
        
        # alpha = 2 / (span + 1) = 2 / 11 = 0.1818
        expected_alpha = 2.0 / 11.0
        assert calculator._alpha == pytest.approx(expected_alpha)

    def test_clipping_to_max(self):
        """Test smoothed value is clipped to clip_max. (Requirement 3.2)"""
        config = FlowRotationConfig(clip_max=5.0, scale_factor=10.0)
        calculator = FlowRotationCalculator(config)
        
        # Large positive orderflow should be clipped
        smoothed, raw = calculator.calculate("BTCUSDT", 1.0)
        
        # Raw = 1.0 * 10.0 = 10.0
        assert raw == pytest.approx(10.0)
        # Smoothed should be clipped to 5.0
        assert smoothed == pytest.approx(5.0)

    def test_clipping_to_min(self):
        """Test smoothed value is clipped to clip_min. (Requirement 3.2)"""
        config = FlowRotationConfig(clip_min=-5.0, scale_factor=10.0)
        calculator = FlowRotationCalculator(config)
        
        # Large negative orderflow should be clipped
        smoothed, raw = calculator.calculate("BTCUSDT", -1.0)
        
        # Raw = -1.0 * 10.0 = -10.0
        assert raw == pytest.approx(-10.0)
        # Smoothed should be clipped to -5.0
        assert smoothed == pytest.approx(-5.0)

    def test_separate_state_per_symbol(self):
        """Test EWMA state is maintained separately per symbol."""
        calculator = FlowRotationCalculator()
        
        # Initialize BTC with positive value
        calculator.calculate("BTCUSDT", 0.8)
        
        # Initialize ETH with negative value
        calculator.calculate("ETHUSDT", -0.8)
        
        # BTC state should be positive
        assert calculator.get_ewma_state("BTCUSDT") > 0
        # ETH state should be negative
        assert calculator.get_ewma_state("ETHUSDT") < 0

    def test_reset_specific_symbol(self):
        """Test reset() clears state for specific symbol."""
        calculator = FlowRotationCalculator()
        
        calculator.calculate("BTCUSDT", 0.5)
        calculator.calculate("ETHUSDT", 0.5)
        
        calculator.reset("BTCUSDT")
        
        assert calculator.get_ewma_state("BTCUSDT") is None
        assert calculator.get_ewma_state("ETHUSDT") is not None

    def test_reset_all_symbols(self):
        """Test reset() with no argument clears all state."""
        calculator = FlowRotationCalculator()
        
        calculator.calculate("BTCUSDT", 0.5)
        calculator.calculate("ETHUSDT", 0.5)
        
        calculator.reset()
        
        assert calculator.get_ewma_state("BTCUSDT") is None
        assert calculator.get_ewma_state("ETHUSDT") is None

    def test_get_ewma_state_returns_none_for_unknown_symbol(self):
        """Test get_ewma_state() returns None for unknown symbol."""
        calculator = FlowRotationCalculator()
        
        assert calculator.get_ewma_state("UNKNOWN") is None

    def test_zero_orderflow_imbalance(self):
        """Test calculation with zero orderflow imbalance."""
        calculator = FlowRotationCalculator()
        
        smoothed, raw = calculator.calculate("BTCUSDT", 0.0)
        
        assert raw == 0.0
        assert smoothed == 0.0

    def test_typical_market_values(self):
        """Test with typical market orderflow values in [-1, 1]."""
        calculator = FlowRotationCalculator()
        
        # Simulate a series of orderflow values
        values = [0.3, 0.5, 0.2, -0.1, -0.3, 0.1]
        
        for val in values:
            smoothed, raw = calculator.calculate("BTCUSDT", val)
            
            # Smoothed should be within clip range
            assert -5.0 <= smoothed <= 5.0
            # Raw should be scaled
            assert raw == pytest.approx(val * 5.0)


class TestCalculateTrendBias:
    """Tests for _calculate_trend_bias function."""

    def test_uptrend_returns_positive(self):
        """Test uptrend returns positive trend_strength. (Requirement 3.4)"""
        result = _calculate_trend_bias(
            trend_direction="up",
            trend_strength=0.8,
        )
        
        assert result == pytest.approx(0.8)

    def test_downtrend_returns_negative(self):
        """Test downtrend returns negative trend_strength. (Requirement 3.4)"""
        result = _calculate_trend_bias(
            trend_direction="down",
            trend_strength=0.8,
        )
        
        assert result == pytest.approx(-0.8)

    def test_none_direction_returns_zero(self):
        """Test None trend_direction returns zero."""
        result = _calculate_trend_bias(
            trend_direction=None,
            trend_strength=0.8,
        )
        
        assert result == 0.0

    def test_unknown_direction_returns_zero(self):
        """Test unknown trend_direction returns zero."""
        result = _calculate_trend_bias(
            trend_direction="sideways",
            trend_strength=0.8,
        )
        
        assert result == 0.0

    def test_zero_strength_returns_zero(self):
        """Test zero trend_strength returns zero regardless of direction."""
        assert _calculate_trend_bias("up", 0.0) == 0.0
        assert _calculate_trend_bias("down", 0.0) == 0.0

    def test_full_strength_uptrend(self):
        """Test full strength uptrend returns 1.0."""
        result = _calculate_trend_bias("up", 1.0)
        assert result == pytest.approx(1.0)

    def test_full_strength_downtrend(self):
        """Test full strength downtrend returns -1.0."""
        result = _calculate_trend_bias("down", 1.0)
        assert result == pytest.approx(-1.0)


class TestAMTLevelsWithFlowRotation:
    """Tests for AMTLevels dataclass with flow_rotation fields."""

    def test_amt_levels_has_flow_rotation_field(self):
        """Test AMTLevels has flow_rotation field. (Requirement 3.8)"""
        levels = AMTLevels(
            point_of_control=100.0,
            value_area_high=101.0,
            value_area_low=99.0,
            position_in_value="inside",
            distance_to_poc=0.0,
            distance_to_vah=1.0,
            distance_to_val=1.0,
            flow_rotation=2.5,
        )
        
        assert hasattr(levels, "flow_rotation")
        assert levels.flow_rotation == 2.5

    def test_amt_levels_has_flow_rotation_raw_field(self):
        """Test AMTLevels has flow_rotation_raw field. (Requirement 3.8)"""
        levels = AMTLevels(
            point_of_control=100.0,
            value_area_high=101.0,
            value_area_low=99.0,
            position_in_value="inside",
            distance_to_poc=0.0,
            distance_to_vah=1.0,
            distance_to_val=1.0,
            flow_rotation_raw=3.0,
        )
        
        assert hasattr(levels, "flow_rotation_raw")
        assert levels.flow_rotation_raw == 3.0

    def test_amt_levels_has_trend_bias_field(self):
        """Test AMTLevels has trend_bias field. (Requirement 3.4)"""
        levels = AMTLevels(
            point_of_control=100.0,
            value_area_high=101.0,
            value_area_low=99.0,
            position_in_value="inside",
            distance_to_poc=0.0,
            distance_to_vah=1.0,
            distance_to_val=1.0,
            trend_bias=0.5,
        )
        
        assert hasattr(levels, "trend_bias")
        assert levels.trend_bias == 0.5

    def test_amt_levels_has_rotation_factor_for_backward_compat(self):
        """Test AMTLevels retains rotation_factor for backward compatibility. (Requirement 3.9)"""
        levels = AMTLevels(
            point_of_control=100.0,
            value_area_high=101.0,
            value_area_low=99.0,
            position_in_value="inside",
            distance_to_poc=0.0,
            distance_to_vah=1.0,
            distance_to_val=1.0,
            rotation_factor=4.0,
        )
        
        assert hasattr(levels, "rotation_factor")
        assert levels.rotation_factor == 4.0

    def test_amt_levels_default_values(self):
        """Test AMTLevels has correct default values for new fields."""
        levels = AMTLevels(
            point_of_control=100.0,
            value_area_high=101.0,
            value_area_low=99.0,
            position_in_value="inside",
            distance_to_poc=0.0,
            distance_to_vah=1.0,
            distance_to_val=1.0,
        )
        
        assert levels.flow_rotation == 0.0
        assert levels.flow_rotation_raw == 0.0
        assert levels.trend_bias == 0.0
        assert levels.rotation_factor == 0.0


class TestAMTCalculatorStageFlowRotationIntegration:
    """Integration tests for AMTCalculatorStage with flow_rotation."""

    @pytest.fixture
    def sample_candles(self):
        """Generate sample candle data for testing."""
        candles = []
        base_price = 50000.0
        for i in range(20):
            price_offset = (i % 5) * 100 - 200
            candles.append({
                "open": base_price + price_offset,
                "high": base_price + price_offset + 50,
                "low": base_price + price_offset - 50,
                "close": base_price + price_offset + 25,
                "volume": 100 + (i % 3) * 50,
                "ts": 1000 + i * 300,
            })
        return candles

    @pytest.mark.asyncio
    async def test_stage_calculates_flow_rotation(self, sample_candles):
        """Test that AMTCalculatorStage calculates flow_rotation."""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        stage = AMTCalculatorStage()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 0.5,
                    "trend_direction": "up",
                    "trend_strength": 0.7,
                },
            },
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels is not None
        
        # flow_rotation should be calculated (EWMA smoothed)
        # First call: raw = 0.5 * 5.0 = 2.5, smoothed = 2.5 (initialized)
        assert amt_levels.flow_rotation == pytest.approx(2.5)
        assert amt_levels.flow_rotation_raw == pytest.approx(2.5)

    @pytest.mark.asyncio
    async def test_stage_calculates_trend_bias(self, sample_candles):
        """Test that AMTCalculatorStage calculates trend_bias."""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        stage = AMTCalculatorStage()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 0.3,
                    "trend_direction": "up",
                    "trend_strength": 0.7,
                },
            },
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels is not None
        
        # trend_bias should be trend_strength for uptrend
        assert amt_levels.trend_bias == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_stage_calculates_trend_bias_downtrend(self, sample_candles):
        """Test trend_bias is negative for downtrend."""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        stage = AMTCalculatorStage()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 0.3,
                    "trend_direction": "down",
                    "trend_strength": 0.6,
                },
            },
        )
        
        result = await stage.run(ctx)
        
        amt_levels = ctx.data.get("amt_levels")
        assert amt_levels.trend_bias == pytest.approx(-0.6)

    @pytest.mark.asyncio
    async def test_stage_ewma_smoothing_across_calls(self, sample_candles):
        """Test EWMA smoothing is applied across multiple calls."""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        stage = AMTCalculatorStage()
        
        # First call with high orderflow
        ctx1 = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 1.0,
                    "trend_direction": None,
                    "trend_strength": 0.0,
                },
            },
        )
        await stage.run(ctx1)
        flow1 = ctx1.data["amt_levels"].flow_rotation
        
        # Second call with zero orderflow (should be smoothed)
        ctx2 = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 0.0,
                    "trend_direction": None,
                    "trend_strength": 0.0,
                },
            },
        )
        await stage.run(ctx2)
        flow2 = ctx2.data["amt_levels"].flow_rotation
        
        # flow2 should be between 0 and flow1 (EWMA smoothed)
        assert flow2 < flow1
        assert flow2 > 0

    @pytest.mark.asyncio
    async def test_stage_uses_custom_flow_rotation_config(self, sample_candles):
        """Test stage uses custom FlowRotationConfig."""
        from quantgambit.signals.stages.amt_calculator import (
            AMTCalculatorStage,
            FlowRotationConfig,
        )
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        config = FlowRotationConfig(
            ewma_span=5,
            clip_min=-3.0,
            clip_max=3.0,
            scale_factor=2.0,
        )
        stage = AMTCalculatorStage(flow_rotation_config=config)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 1.0,  # Would be 5.0 with default scale
                    "trend_direction": None,
                    "trend_strength": 0.0,
                },
            },
        )
        
        result = await stage.run(ctx)
        
        amt_levels = ctx.data.get("amt_levels")
        # raw = 1.0 * 2.0 = 2.0 (custom scale_factor)
        assert amt_levels.flow_rotation_raw == pytest.approx(2.0)
        # smoothed should be clipped to 3.0 max (but 2.0 < 3.0, so no clipping)
        assert amt_levels.flow_rotation == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_stage_clipping_applied(self, sample_candles):
        """Test flow_rotation is clipped to configured range."""
        from quantgambit.signals.stages.amt_calculator import (
            AMTCalculatorStage,
            FlowRotationConfig,
        )
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        config = FlowRotationConfig(
            clip_min=-2.0,
            clip_max=2.0,
            scale_factor=10.0,  # Large scale to exceed clip range
        )
        stage = AMTCalculatorStage(flow_rotation_config=config)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 1.0,  # raw = 10.0
                    "trend_direction": None,
                    "trend_strength": 0.0,
                },
            },
        )
        
        await stage.run(ctx)
        
        amt_levels = ctx.data.get("amt_levels")
        # raw = 1.0 * 10.0 = 10.0
        assert amt_levels.flow_rotation_raw == pytest.approx(10.0)
        # smoothed should be clipped to 2.0
        assert amt_levels.flow_rotation == pytest.approx(2.0)
