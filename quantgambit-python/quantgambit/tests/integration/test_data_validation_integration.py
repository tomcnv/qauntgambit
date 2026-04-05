"""Integration tests for data validation.

Feature: backtest-data-validation
Tests the full validation flow including database operations.
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.backtesting.data_validator import (
    DataValidator,
    ValidationConfig,
    QualityReport,
    RuntimeQualityTracker,
    GapAnalyzer,
    MultiSourceChecker,
)


class TestFullValidationFlow:
    """Integration tests for the full validation flow.
    
    Task 12.1: Test validation with real database patterns.
    """
    
    @pytest.mark.asyncio
    async def test_validation_with_mock_database(self):
        """Test validation flow with mocked database."""
        # Create mock pool
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        pool_ctx = AsyncMock()
        pool_ctx.__aenter__.return_value = mock_conn
        pool_ctx.__aexit__.return_value = None
        mock_pool.acquire.return_value = pool_ctx
        
        # Mock decision events query
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        decision_rows = [
            {"ts": base_time + timedelta(minutes=i)}
            for i in range(100)
        ]
        
        # Mock orderbook events query
        orderbook_rows = [
            {"ts": base_time + timedelta(seconds=i * 10)}
            for i in range(600)
        ]
        
        # Mock candle data query
        candle_rows = [
            {"ts": base_time + timedelta(minutes=i * 5)}
            for i in range(20)
        ]
        
        # Configure mock to return different results for different queries
        async def mock_fetch(query, *args):
            if "decision_events" in query:
                return decision_rows
            elif "orderbook_events" in query:
                return orderbook_rows
            elif "market_candles" in query:
                return candle_rows
            return []
        
        mock_conn.fetch = mock_fetch
        
        # Create validator and run validation
        config = ValidationConfig(
            minimum_completeness_pct=50.0,
            max_critical_gaps=10,
            max_gap_duration_pct=20.0,
        )
        validator = DataValidator(mock_pool, config)
        
        report = await validator.validate(
            symbol="BTC-USDT-SWAP",
            start_date="2024-01-15",
            end_date="2024-01-16",
        )
        
        # Verify report structure
        assert report is not None
        assert report.symbol == "BTC-USDT-SWAP"
        assert report.data_quality_grade in ("A", "B", "C", "D", "F")
        assert report.recommendation in ("proceed", "proceed_with_caution", "insufficient_data")
        assert isinstance(report.passes_threshold, bool)
    
    @pytest.mark.asyncio
    async def test_validation_with_force_run(self):
        """Test that force_run overrides threshold failures."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        pool_ctx = AsyncMock()
        pool_ctx.__aenter__.return_value = mock_conn
        pool_ctx.__aexit__.return_value = None
        mock_pool.acquire.return_value = pool_ctx
        
        # Return empty data to trigger validation failure
        mock_conn.fetch = AsyncMock(return_value=[])
        
        config = ValidationConfig(minimum_completeness_pct=80.0)
        validator = DataValidator(mock_pool, config)
        
        # Without force_run, should fail
        report_no_force = await validator.validate(
            symbol="BTC-USDT-SWAP",
            start_date="2024-01-15",
            end_date="2024-01-16",
            force_run=False,
        )
        assert report_no_force.passes_threshold is False
        assert report_no_force.threshold_overridden is False
        
        # With force_run, should pass (overridden)
        report_force = await validator.validate(
            symbol="BTC-USDT-SWAP",
            start_date="2024-01-15",
            end_date="2024-01-16",
            force_run=True,
        )
        assert report_force.passes_threshold is True
        assert report_force.threshold_overridden is True
    
    @pytest.mark.asyncio
    async def test_validation_generates_warnings_for_low_completeness(self):
        """Test that warnings are generated for low source completeness."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        pool_ctx = AsyncMock()
        pool_ctx.__aenter__.return_value = mock_conn
        pool_ctx.__aexit__.return_value = None
        mock_pool.acquire.return_value = pool_ctx
        
        # Return sparse data
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        sparse_rows = [{"ts": base_time + timedelta(hours=i)} for i in range(5)]
        mock_conn.fetch = AsyncMock(return_value=sparse_rows)
        
        config = ValidationConfig(min_source_completeness_pct=50.0)
        validator = DataValidator(mock_pool, config)
        
        report = await validator.validate(
            symbol="BTC-USDT-SWAP",
            start_date="2024-01-15",
            end_date="2024-01-16",
        )
        
        # Should have warnings for low completeness
        assert len(report.warnings) > 0 or report.data_quality_grade in ("C", "D", "F")


class TestQualityMetricsInResults:
    """Integration tests for quality metrics storage.
    
    Task 12.2: Test quality metrics stored after backtest.
    """
    
    def test_runtime_tracker_degraded_status(self):
        """Test that degraded status is set when data quality is poor."""
        tracker = RuntimeQualityTracker()
        
        # Record 100 snapshots with 25% missing price (above 20% threshold)
        for i in range(100):
            has_price = i >= 25  # First 25 missing price
            tracker.record_snapshot(has_price=has_price, has_depth=True)
        
        metrics = tracker.get_metrics()
        
        assert metrics.total_snapshots == 100
        assert metrics.missing_price_count == 25
        assert metrics.missing_price_pct == 25.0
        assert tracker.should_degrade_status() is True
        assert metrics.is_degraded is True
    
    def test_runtime_tracker_not_degraded_when_quality_good(self):
        """Test that status is not degraded when quality is good."""
        tracker = RuntimeQualityTracker()
        
        # Record 100 snapshots with only 10% missing (below 20% threshold)
        for i in range(100):
            has_price = i >= 10  # First 10 missing price
            tracker.record_snapshot(has_price=has_price, has_depth=True)
        
        metrics = tracker.get_metrics()
        
        assert metrics.total_snapshots == 100
        assert metrics.missing_price_count == 10
        assert metrics.missing_price_pct == 10.0
        assert tracker.should_degrade_status() is False
        assert metrics.is_degraded is False
    
    def test_runtime_quality_grade_calculation(self):
        """Test runtime quality grade calculation."""
        tracker = RuntimeQualityTracker()
        
        # Record snapshots with 5% missing (should be grade A)
        for i in range(100):
            has_price = i >= 5
            has_depth = i >= 5
            tracker.record_snapshot(has_price=has_price, has_depth=has_depth)
        
        grade = tracker.get_quality_grade()
        assert grade == "A"  # 95% completeness
    
    def test_quality_report_to_dict(self):
        """Test QualityReport serialization for storage."""
        report = QualityReport(
            symbol="BTC-USDT-SWAP",
            start_date="2024-01-15",
            end_date="2024-01-16",
            overall_completeness_pct=85.5,
            data_quality_grade="B",
            recommendation="proceed_with_caution",
            total_gaps=3,
            critical_gaps=1,
            gap_duration_pct=5.2,
            decision_events_completeness=90.0,
            orderbook_events_completeness=80.0,
            candle_data_completeness=85.0,
            passes_threshold=True,
            warnings=["Test warning"],
        )
        
        report_dict = report.to_dict()
        
        # Verify all fields are present
        assert report_dict["symbol"] == "BTC-USDT-SWAP"
        assert report_dict["data_quality_grade"] == "B"
        assert report_dict["overall_completeness_pct"] == 85.5
        assert report_dict["total_gaps"] == 3
        assert report_dict["critical_gaps"] == 1
        assert report_dict["passes_threshold"] is True
        assert "Test warning" in report_dict["warnings"]


class TestGapAnalyzerIntegration:
    """Integration tests for gap analysis."""
    
    def test_gap_analyzer_with_real_timestamps(self):
        """Test gap analyzer with realistic timestamp patterns."""
        analyzer = GapAnalyzer(gap_threshold_minutes=5, critical_gap_minutes=15)
        
        # Create timestamps with a known gap
        base = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        timestamps = [
            base,
            base + timedelta(minutes=1),
            base + timedelta(minutes=2),
            # Gap of 20 minutes here
            base + timedelta(minutes=22),
            base + timedelta(minutes=23),
            base + timedelta(minutes=24),
        ]
        
        start_date = base - timedelta(minutes=1)
        end_date = base + timedelta(minutes=25)
        
        gaps, gap_pct = analyzer.analyze_gaps(timestamps, start_date, end_date)
        
        # Should detect the 20-minute gap
        internal_gaps = [g for g in gaps if g.duration_minutes > 15]
        assert len(internal_gaps) >= 1
        
        # The gap should be marked as critical (during trading hours, > 15 min)
        critical_gaps = [g for g in gaps if g.is_critical]
        assert len(critical_gaps) >= 1
    
    def test_gap_analyzer_overnight_not_critical(self):
        """Test that overnight gaps are not marked as critical."""
        analyzer = GapAnalyzer(gap_threshold_minutes=5, critical_gap_minutes=15)
        
        # Create timestamps during overnight hours (21:00-00:00 UTC)
        base = datetime(2024, 1, 15, 22, 0, 0, tzinfo=timezone.utc)
        timestamps = [
            base,
            base + timedelta(minutes=30),  # 30-minute gap during overnight
        ]
        
        start_date = base - timedelta(minutes=1)
        end_date = base + timedelta(minutes=31)
        
        gaps, gap_pct = analyzer.analyze_gaps(timestamps, start_date, end_date)
        
        # Gap during overnight should not be critical
        overnight_gaps = [g for g in gaps if g.session == "overnight"]
        for gap in overnight_gaps:
            assert gap.is_critical is False


class TestMultiSourceCheckerIntegration:
    """Integration tests for multi-source checking."""
    
    @pytest.mark.asyncio
    async def test_source_checker_generates_warnings(self):
        """Test that source checker generates appropriate warnings."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        pool_ctx = AsyncMock()
        pool_ctx.__aenter__.return_value = mock_conn
        pool_ctx.__aexit__.return_value = None
        mock_pool.acquire.return_value = pool_ctx
        
        # Return sparse data
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        sparse_rows = [{"ts": base_time}]
        mock_conn.fetch = AsyncMock(return_value=sparse_rows)
        
        checker = MultiSourceChecker(mock_pool)
        
        results = await checker.check_all_sources(
            symbol="BTC-USDT-SWAP",
            start_date=base_time,
            end_date=base_time + timedelta(hours=1),
        )
        
        warnings = checker.generate_source_warnings(results, min_completeness_pct=50.0)
        
        # Should have warnings for low completeness
        assert len(warnings) > 0
