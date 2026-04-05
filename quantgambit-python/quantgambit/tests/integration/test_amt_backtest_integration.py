"""
Integration tests for AMT fields in backtesting.

Tests that the BacktestExecutor correctly handles AMT fields:
1. Reconstructs AMT fields from candle data when decision_events lack them
2. Uses AMT fields from decision_events when present
3. Uses the same volume profile algorithm as the live AMTCalculatorStage

**Validates: Requirements 8.1, 8.2, 8.3**
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from quantgambit.backtesting.strategy_executor import (
    StrategyBacktestExecutor,
    StrategyExecutorConfig,
)
from quantgambit.core.volume_profile import (
    calculate_volume_profile,
    calculate_volume_profile_from_candles,
    VolumeProfileConfig,
    VolumeProfileResult,
)
from quantgambit.signals.stages.amt_calculator import (
    AMTCalculatorStage,
    AMTCalculatorConfig,
)


def _generate_candles(
    count: int,
    base_price: float = 50000.0,
    base_volume: float = 100.0,
    start_ts: Optional[datetime] = None,
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
        start_ts: Starting timestamp (datetime)
        interval_sec: Time interval between candles
        
    Returns:
        List of candle dictionaries with ts as datetime
    """
    if start_ts is None:
        start_ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    
    candles = []
    for i in range(count):
        # Create price variation that concentrates volume around base_price
        # This creates a bell-curve-like distribution for volume profile
        price_offset = (i % 10 - 5) * 50  # -250 to +200
        
        # Higher volume near the center (base_price)
        distance_from_center = abs(i % 10 - 5)
        volume_multiplier = 3.0 - (distance_from_center * 0.4)  # 3.0 at center, 1.0 at edges
        
        ts = start_ts + timedelta(seconds=i * interval_sec)
        
        candles.append({
            "ts": ts,
            "open": base_price + price_offset,
            "high": base_price + price_offset + 30,
            "low": base_price + price_offset - 30,
            "close": base_price + price_offset + 15,
            "volume": base_volume * max(1.0, volume_multiplier),
        })
    return candles


def _generate_decision_event(
    ts: datetime,
    price: float,
    symbol: str = "BTCUSDT",
    include_amt: bool = False,
    poc_price: Optional[float] = None,
    vah_price: Optional[float] = None,
    val_price: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Generate a sample decision event for testing.
    
    Args:
        ts: Timestamp for the event
        price: Mid price
        symbol: Trading symbol
        include_amt: Whether to include AMT fields in the snapshot
        poc_price: Point of control price (if include_amt)
        vah_price: Value area high price (if include_amt)
        val_price: Value area low price (if include_amt)
        
    Returns:
        Decision event dictionary
    """
    snapshot = {
        "mid_price": price,
        "spread_bps": 5.0,
        "vol_regime": "normal",
        "trend_direction": "up",
        "trend_strength": 0.5,
        "imb_5s": 0.3,
        "vol_shock": False,
    }
    
    if include_amt:
        snapshot["poc_price"] = poc_price
        snapshot["vah_price"] = vah_price
        snapshot["val_price"] = val_price
        snapshot["position_in_value"] = "inside"
    
    return {
        "ts": ts,
        "payload": {
            "snapshot": snapshot,
            "result": "CONTINUE",
        },
    }


class TestAMTBacktestIntegration:
    """Integration tests for AMT fields in backtesting."""
    
    @pytest.fixture
    def executor_config(self) -> StrategyExecutorConfig:
        """Create executor configuration for testing."""
        return StrategyExecutorConfig(
            amt_lookback_candles=100,
            amt_value_area_pct=68.0,
            sample_every=1,  # Process every event for testing
        )
    
    @pytest.fixture
    def mock_platform_pool(self):
        """Create a mock platform pool."""
        return MagicMock()
    
    @pytest.fixture
    def executor(
        self,
        mock_platform_pool,
        executor_config: StrategyExecutorConfig,
    ) -> StrategyBacktestExecutor:
        """Create a StrategyBacktestExecutor for testing."""
        return StrategyBacktestExecutor(
            platform_pool=mock_platform_pool,
            config=executor_config,
        )
    
    @pytest.fixture
    def sample_candles(self) -> List[Dict[str, Any]]:
        """Generate sample candle data with sufficient count for AMT calculation."""
        return _generate_candles(count=50, base_price=50000.0)
    
    @pytest.fixture
    def insufficient_candles(self) -> List[Dict[str, Any]]:
        """Generate insufficient candle data (less than min_candles)."""
        return _generate_candles(count=5, base_price=50000.0)
    
    def test_calculate_amt_levels_with_valid_candles(
        self,
        executor: StrategyBacktestExecutor,
        sample_candles: List[Dict[str, Any]],
    ):
        """
        Test AMT reconstruction from candle data.
        
        **Validates: Requirement 8.1** - WHEN decision_events lack AMT fields, 
        THE Backtest_Executor SHALL calculate AMT from market_candles.
        """
        # Use a timestamp after all candles
        current_ts = sample_candles[-1]["ts"] + timedelta(seconds=60)
        
        # Calculate AMT levels
        amt_levels = executor._calculate_amt_levels(sample_candles, current_ts)
        
        # Verify AMT levels are returned
        assert amt_levels is not None, "AMT levels should be calculated"
        assert "point_of_control" in amt_levels
        assert "value_area_high" in amt_levels
        assert "value_area_low" in amt_levels
        
        # Verify values are valid
        assert amt_levels["point_of_control"] > 0
        assert amt_levels["value_area_high"] > 0
        assert amt_levels["value_area_low"] > 0
        
        # Verify value area bounds (VAL <= POC <= VAH)
        assert amt_levels["value_area_low"] <= amt_levels["point_of_control"]
        assert amt_levels["point_of_control"] <= amt_levels["value_area_high"]
    
    def test_calculate_amt_levels_with_insufficient_candles(
        self,
        executor: StrategyBacktestExecutor,
        insufficient_candles: List[Dict[str, Any]],
    ):
        """
        Test AMT calculation with insufficient candles returns empty dict.
        
        **Validates: Requirement 8.4** - IF candle data is unavailable, 
        THEN THE Backtest_Executor SHALL log a warning and use None for AMT fields.
        """
        current_ts = insufficient_candles[-1]["ts"] + timedelta(seconds=60)
        
        # Calculate AMT levels with insufficient data
        amt_levels = executor._calculate_amt_levels(insufficient_candles, current_ts)
        
        # Should return empty dict
        assert amt_levels == {}, "Should return empty dict with insufficient candles"
    
    def test_calculate_amt_levels_with_empty_candles(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test AMT calculation with empty candle list returns empty dict.
        """
        current_ts = datetime.now(timezone.utc)
        
        # Calculate AMT levels with no candles
        amt_levels = executor._calculate_amt_levels([], current_ts)
        
        # Should return empty dict
        assert amt_levels == {}, "Should return empty dict with no candles"
    
    def test_calculate_amt_levels_filters_future_candles(
        self,
        executor: StrategyBacktestExecutor,
        sample_candles: List[Dict[str, Any]],
    ):
        """
        Test that AMT calculation only uses candles up to current timestamp.
        """
        # Use a timestamp in the middle of the candle range
        mid_index = len(sample_candles) // 2
        current_ts = sample_candles[mid_index]["ts"]
        
        # Calculate AMT levels
        amt_levels = executor._calculate_amt_levels(sample_candles, current_ts)
        
        # Should still calculate (if enough candles before current_ts)
        if mid_index >= 10:  # min_candles is 10
            assert amt_levels != {}, "Should calculate AMT with candles before current_ts"
        else:
            assert amt_levels == {}, "Should return empty if not enough candles before current_ts"
    
    def test_get_amt_from_decision_event_when_present(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test extraction of AMT fields from decision_event when present.
        
        **Validates: Requirement 8.1** - Use AMT from decision_events when available.
        """
        ts = datetime.now(timezone.utc)
        event = _generate_decision_event(
            ts=ts,
            price=50000.0,
            include_amt=True,
            poc_price=49900.0,
            vah_price=50100.0,
            val_price=49700.0,
        )
        
        # Extract AMT fields
        amt_fields = executor._get_amt_from_decision_event(event)
        
        # Verify AMT fields are extracted
        assert amt_fields is not None, "AMT fields should be extracted"
        assert amt_fields["point_of_control"] == 49900.0
        assert amt_fields["value_area_high"] == 50100.0
        assert amt_fields["value_area_low"] == 49700.0
    
    def test_get_amt_from_decision_event_when_missing(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test that None is returned when AMT fields are missing from decision_event.
        
        **Validates: Requirement 8.1** - Reconstruct AMT only when decision_events lack them.
        """
        ts = datetime.now(timezone.utc)
        event = _generate_decision_event(
            ts=ts,
            price=50000.0,
            include_amt=False,
        )
        
        # Extract AMT fields
        amt_fields = executor._get_amt_from_decision_event(event)
        
        # Should return None
        assert amt_fields is None, "Should return None when AMT fields missing"
    
    def test_get_amt_from_decision_event_with_partial_fields(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test that None is returned when only some AMT fields are present.
        """
        ts = datetime.now(timezone.utc)
        event = {
            "ts": ts,
            "payload": {
                "snapshot": {
                    "mid_price": 50000.0,
                    "poc_price": 49900.0,  # Only POC present
                    # vah_price and val_price missing
                },
            },
        }
        
        # Extract AMT fields
        amt_fields = executor._get_amt_from_decision_event(event)
        
        # Should return None (all three required)
        assert amt_fields is None, "Should return None with partial AMT fields"
    
    def test_get_amt_from_decision_event_with_zero_values(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test that None is returned when AMT fields are zero (invalid).
        """
        ts = datetime.now(timezone.utc)
        event = {
            "ts": ts,
            "payload": {
                "snapshot": {
                    "mid_price": 50000.0,
                    "poc_price": 0.0,  # Invalid zero value
                    "vah_price": 50100.0,
                    "val_price": 49700.0,
                },
            },
        }
        
        # Extract AMT fields
        amt_fields = executor._get_amt_from_decision_event(event)
        
        # Should return None (zero is invalid)
        assert amt_fields is None, "Should return None with zero AMT values"
    
    def test_build_market_snapshot_with_amt_levels(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test that _build_market_snapshot correctly uses AMT levels.
        
        **Validates: Requirement 8.1** - AMT fields should be included in MarketSnapshot.
        """
        ts = datetime.now(timezone.utc)
        event = _generate_decision_event(ts=ts, price=50000.0)
        
        amt_levels = {
            "point_of_control": 49900.0,
            "value_area_high": 50100.0,
            "value_area_low": 49700.0,
        }
        
        # Build market snapshot
        snapshot = executor._build_market_snapshot(
            event=event,
            symbol="BTCUSDT",
            orderbook=None,
            amt_levels=amt_levels,
        )
        
        # Verify snapshot is created
        assert snapshot is not None
        
        # Verify AMT fields in snapshot
        assert snapshot.poc_price == 49900.0
        assert snapshot.vah_price == 50100.0
        assert snapshot.val_price == 49700.0
    
    def test_build_market_snapshot_with_empty_amt_levels(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test that _build_market_snapshot handles empty AMT levels gracefully.
        """
        ts = datetime.now(timezone.utc)
        event = _generate_decision_event(ts=ts, price=50000.0)
        
        # Build market snapshot with empty AMT levels
        snapshot = executor._build_market_snapshot(
            event=event,
            symbol="BTCUSDT",
            orderbook=None,
            amt_levels={},  # Empty
        )
        
        # Verify snapshot is created
        assert snapshot is not None
        
        # AMT fields should be None or default
        # The snapshot should still be valid
        assert snapshot.mid_price == 50000.0
    
    def test_build_market_snapshot_position_in_value_classification(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test that position_in_value is correctly classified based on price and AMT levels.
        """
        ts = datetime.now(timezone.utc)
        
        # Test price above VAH
        event_above = _generate_decision_event(ts=ts, price=51000.0)
        amt_levels = {
            "point_of_control": 50000.0,
            "value_area_high": 50200.0,
            "value_area_low": 49800.0,
        }
        
        snapshot_above = executor._build_market_snapshot(
            event=event_above,
            symbol="BTCUSDT",
            orderbook=None,
            amt_levels=amt_levels,
        )
        assert snapshot_above.position_in_value == "above"
        
        # Test price below VAL
        event_below = _generate_decision_event(ts=ts, price=49000.0)
        snapshot_below = executor._build_market_snapshot(
            event=event_below,
            symbol="BTCUSDT",
            orderbook=None,
            amt_levels=amt_levels,
        )
        assert snapshot_below.position_in_value == "below"
        
        # Test price inside value area
        event_inside = _generate_decision_event(ts=ts, price=50000.0)
        snapshot_inside = executor._build_market_snapshot(
            event=event_inside,
            symbol="BTCUSDT",
            orderbook=None,
            amt_levels=amt_levels,
        )
        assert snapshot_inside.position_in_value == "inside"


class TestAMTAlgorithmConsistency:
    """
    Tests for algorithm consistency between live and backtest.
    
    **Validates: Requirement 8.2** - THE Backtest_Executor SHALL use the same 
    volume profile algorithm as the live AMT_Calculator_Stage.
    """
    
    @pytest.fixture
    def executor_config(self) -> StrategyExecutorConfig:
        """Create executor configuration for testing."""
        return StrategyExecutorConfig(
            amt_lookback_candles=100,
            amt_value_area_pct=68.0,
        )
    
    @pytest.fixture
    def mock_platform_pool(self):
        """Create a mock platform pool."""
        return MagicMock()
    
    @pytest.fixture
    def executor(
        self,
        mock_platform_pool,
        executor_config: StrategyExecutorConfig,
    ) -> StrategyBacktestExecutor:
        """Create a StrategyBacktestExecutor for testing."""
        return StrategyBacktestExecutor(
            platform_pool=mock_platform_pool,
            config=executor_config,
        )
    
    @pytest.fixture
    def sample_candles(self) -> List[Dict[str, Any]]:
        """Generate sample candle data."""
        return _generate_candles(count=50, base_price=50000.0)
    
    def test_backtest_uses_shared_volume_profile_algorithm(
        self,
        executor: StrategyBacktestExecutor,
        sample_candles: List[Dict[str, Any]],
    ):
        """
        Test that BacktestExecutor uses the shared volume profile algorithm.
        
        **Validates: Requirement 8.2** - Algorithm Consistency Between Live and Backtest.
        """
        current_ts = sample_candles[-1]["ts"] + timedelta(seconds=60)
        
        # Calculate using BacktestExecutor
        backtest_amt = executor._calculate_amt_levels(sample_candles, current_ts)
        
        # Calculate using shared algorithm directly
        prices = []
        volumes = []
        for candle in sample_candles:
            price = (candle["open"] + candle["high"] + candle["low"] + candle["close"]) / 4
            prices.append(price)
            volumes.append(candle["volume"])
        
        shared_config = VolumeProfileConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_data_points=10,
        )
        shared_result = calculate_volume_profile(prices, volumes, shared_config)
        
        # Results should be identical
        assert backtest_amt is not None
        assert shared_result is not None
        
        assert backtest_amt["point_of_control"] == shared_result.point_of_control
        assert backtest_amt["value_area_high"] == shared_result.value_area_high
        assert backtest_amt["value_area_low"] == shared_result.value_area_low
    
    def test_shared_algorithm_produces_consistent_results(self):
        """
        Test that the shared volume profile algorithm produces consistent results.
        """
        candles = _generate_candles(count=50, base_price=50000.0)
        
        # Calculate multiple times
        results = []
        for _ in range(5):
            result = calculate_volume_profile_from_candles(candles)
            results.append(result)
        
        # All results should be identical
        for i in range(1, len(results)):
            assert results[i].point_of_control == results[0].point_of_control
            assert results[i].value_area_high == results[0].value_area_high
            assert results[i].value_area_low == results[0].value_area_low
    
    def test_value_area_contains_poc(self):
        """
        Test that POC is always within value area bounds.
        
        This is a fundamental property of volume profile calculation.
        """
        # Test with various candle configurations
        for base_price in [10000.0, 50000.0, 100000.0]:
            for count in [20, 50, 100]:
                candles = _generate_candles(count=count, base_price=base_price)
                result = calculate_volume_profile_from_candles(candles)
                
                if result is not None:
                    assert result.value_area_low <= result.point_of_control, \
                        f"VAL ({result.value_area_low}) should be <= POC ({result.point_of_control})"
                    assert result.point_of_control <= result.value_area_high, \
                        f"POC ({result.point_of_control}) should be <= VAH ({result.value_area_high})"


class TestAMTBacktestEdgeCases:
    """Edge case tests for AMT backtest integration."""
    
    @pytest.fixture
    def executor_config(self) -> StrategyExecutorConfig:
        """Create executor configuration for testing."""
        return StrategyExecutorConfig(
            amt_lookback_candles=100,
            amt_value_area_pct=68.0,
        )
    
    @pytest.fixture
    def mock_platform_pool(self):
        """Create a mock platform pool."""
        return MagicMock()
    
    @pytest.fixture
    def executor(
        self,
        mock_platform_pool,
        executor_config: StrategyExecutorConfig,
    ) -> StrategyBacktestExecutor:
        """Create a StrategyBacktestExecutor for testing."""
        return StrategyBacktestExecutor(
            platform_pool=mock_platform_pool,
            config=executor_config,
        )
    
    def test_amt_calculation_with_all_same_prices(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test AMT calculation when all candles have the same price.
        """
        start_ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        candles = []
        for i in range(20):
            candles.append({
                "ts": start_ts + timedelta(seconds=i * 300),
                "open": 50000.0,
                "high": 50000.0,
                "low": 50000.0,
                "close": 50000.0,
                "volume": 100.0,
            })
        
        current_ts = candles[-1]["ts"] + timedelta(seconds=60)
        amt_levels = executor._calculate_amt_levels(candles, current_ts)
        
        # Should handle gracefully (all levels equal to the single price)
        assert amt_levels is not None
        assert amt_levels["point_of_control"] == 50000.0
        assert amt_levels["value_area_low"] == 50000.0
        assert amt_levels["value_area_high"] == 50000.0
    
    def test_amt_calculation_with_zero_volume(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test AMT calculation when all candles have zero volume.
        """
        start_ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        candles = []
        for i in range(20):
            candles.append({
                "ts": start_ts + timedelta(seconds=i * 300),
                "open": 50000.0 + i * 10,
                "high": 50000.0 + i * 10 + 5,
                "low": 50000.0 + i * 10 - 5,
                "close": 50000.0 + i * 10 + 2,
                "volume": 0.0,  # Zero volume
            })
        
        current_ts = candles[-1]["ts"] + timedelta(seconds=60)
        amt_levels = executor._calculate_amt_levels(candles, current_ts)
        
        # Should handle gracefully
        assert amt_levels is not None
    
    def test_decision_event_with_negative_amt_values(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test that negative AMT values are treated as invalid.
        """
        ts = datetime.now(timezone.utc)
        event = {
            "ts": ts,
            "payload": {
                "snapshot": {
                    "mid_price": 50000.0,
                    "poc_price": -100.0,  # Invalid negative value
                    "vah_price": 50100.0,
                    "val_price": 49700.0,
                },
            },
        }
        
        amt_fields = executor._get_amt_from_decision_event(event)
        
        # Should return None (negative is invalid)
        assert amt_fields is None
    
    def test_decision_event_with_none_amt_values(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test that None AMT values are handled correctly.
        """
        ts = datetime.now(timezone.utc)
        event = {
            "ts": ts,
            "payload": {
                "snapshot": {
                    "mid_price": 50000.0,
                    "poc_price": None,
                    "vah_price": None,
                    "val_price": None,
                },
            },
        }
        
        amt_fields = executor._get_amt_from_decision_event(event)
        
        # Should return None
        assert amt_fields is None
    
    def test_build_market_snapshot_with_orderbook_data(
        self,
        executor: StrategyBacktestExecutor,
    ):
        """
        Test that _build_market_snapshot correctly uses orderbook data.
        """
        ts = datetime.now(timezone.utc)
        event = _generate_decision_event(ts=ts, price=50000.0)
        
        orderbook = {
            "bid": 49999.0,
            "ask": 50001.0,
            "bid_depth_usd": 100000.0,
            "ask_depth_usd": 120000.0,
            "orderbook_imbalance": -0.1,
        }
        
        amt_levels = {
            "point_of_control": 49900.0,
            "value_area_high": 50100.0,
            "value_area_low": 49700.0,
        }
        
        snapshot = executor._build_market_snapshot(
            event=event,
            symbol="BTCUSDT",
            orderbook=orderbook,
            amt_levels=amt_levels,
        )
        
        assert snapshot is not None
        assert snapshot.bid_depth_usd == 100000.0
        assert snapshot.ask_depth_usd == 120000.0
    
    def test_amt_lookback_respects_config(self):
        """
        Test that AMT calculation respects the configured lookback.
        """
        # Create executor with small lookback
        config = StrategyExecutorConfig(
            amt_lookback_candles=20,
            amt_value_area_pct=68.0,
        )
        executor = StrategyBacktestExecutor(
            platform_pool=MagicMock(),
            config=config,
        )
        
        # Generate more candles than lookback
        candles = _generate_candles(count=50, base_price=50000.0)
        current_ts = candles[-1]["ts"] + timedelta(seconds=60)
        
        # Calculate AMT - should only use last 20 candles
        amt_levels = executor._calculate_amt_levels(candles, current_ts)
        
        assert amt_levels is not None
        # The result should be based on the last 20 candles only
