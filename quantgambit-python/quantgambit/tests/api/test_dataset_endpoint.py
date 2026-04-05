"""
Unit tests for the Dataset API endpoint.

Feature: backtesting-api-integration
Requirements: R2.1, R2.2

Tests:
- Response structure validation
- Symbol filtering
- Quality metrics presence
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.api.backtest_endpoints import (
    DatasetInfo,
    DatasetListResponse,
)
from quantgambit.backtesting.dataset_scanner import (
    DatasetScanner,
    DatasetMetadata,
    ScanConfig,
)


# ============================================================================
# Mock Redis Client
# ============================================================================

class MockRedis:
    """Mock Redis client for testing."""
    
    def __init__(self, entries: list = None):
        self.entries = entries or []
    
    async def xrange(self, stream_key: str, min: str, max: str, count: int) -> list:
        """Mock xrange that returns entries."""
        return self.entries[:count]


def generate_stream_entry(symbol: str, timestamp: float) -> tuple:
    """Generate a mock Redis stream entry."""
    entry_id = f"{int(timestamp * 1000)}-0"
    data = {
        b"data": json.dumps({
            "symbol": symbol,
            "timestamp": timestamp,
            "payload": {
                "symbol": symbol,
                "timestamp": timestamp,
            }
        }).encode()
    }
    return (entry_id.encode(), data)


# ============================================================================
# Test Response Structure
# ============================================================================

class TestDatasetResponseStructure:
    """Tests for dataset endpoint response structure."""
    
    @pytest.mark.asyncio
    async def test_response_contains_required_fields(self):
        """
        Test that the response contains all required fields.
        
        **Validates: Requirements R2.1**
        """
        # Generate mock entries
        base_ts = 1704067200.0  # 2024-01-01
        entries = [
            generate_stream_entry("BTC-USDT-SWAP", base_ts),
            generate_stream_entry("BTC-USDT-SWAP", base_ts + 60),
            generate_stream_entry("BTC-USDT-SWAP", base_ts + 120),
        ]
        
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 1
        dataset = datasets[0]
        
        # Verify all required fields are present
        assert hasattr(dataset, 'symbol')
        assert hasattr(dataset, 'exchange')
        assert hasattr(dataset, 'earliest_date')
        assert hasattr(dataset, 'latest_date')
        assert hasattr(dataset, 'candle_count')
        assert hasattr(dataset, 'gaps')
        assert hasattr(dataset, 'gap_dates')
        assert hasattr(dataset, 'completeness_pct')
        assert hasattr(dataset, 'last_updated')
    
    @pytest.mark.asyncio
    async def test_response_to_dict_structure(self):
        """
        Test that to_dict() returns all required fields.
        
        **Validates: Requirements R2.1**
        """
        metadata = DatasetMetadata(
            symbol="BTC-USDT-SWAP",
            exchange="OKX",
            earliest_date="2024-01-01T00:00:00+00:00",
            latest_date="2024-01-02T00:00:00+00:00",
            candle_count=1440,
            gaps=0,
            gap_dates=[],
            completeness_pct=100.0,
            last_updated="2024-01-02T00:00:00+00:00",
        )
        
        result = metadata.to_dict()
        
        required_fields = [
            "symbol",
            "exchange",
            "earliest_date",
            "latest_date",
            "candle_count",
            "gaps",
            "gap_dates",
            "completeness_pct",
            "last_updated",
        ]
        
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"
    
    @pytest.mark.asyncio
    async def test_dataset_info_model_validation(self):
        """
        Test that DatasetInfo model validates correctly.
        
        **Validates: Requirements R2.1**
        """
        dataset_info = DatasetInfo(
            symbol="ETH-USDT-SWAP",
            exchange="OKX",
            earliest_date="2024-01-01T00:00:00+00:00",
            latest_date="2024-01-31T00:00:00+00:00",
            candle_count=43200,
            gaps=2,
            gap_dates=["2024-01-15T00:00:00+00:00", "2024-01-20T00:00:00+00:00"],
            completeness_pct=98.5,
            last_updated="2024-01-31T00:00:00+00:00",
        )
        
        assert dataset_info.symbol == "ETH-USDT-SWAP"
        assert dataset_info.exchange == "OKX"
        assert dataset_info.candle_count == 43200
        assert dataset_info.gaps == 2
        assert len(dataset_info.gap_dates) == 2
        assert dataset_info.completeness_pct == 98.5


# ============================================================================
# Test Symbol Filtering
# ============================================================================

class TestSymbolFiltering:
    """Tests for symbol filtering functionality."""
    
    @pytest.mark.asyncio
    async def test_filter_returns_matching_symbol(self):
        """
        Test that filtering by symbol returns only matching datasets.
        
        **Validates: Requirements R2.1**
        """
        base_ts = 1704067200.0
        entries = [
            generate_stream_entry("BTC-USDT-SWAP", base_ts),
            generate_stream_entry("BTC-USDT-SWAP", base_ts + 60),
            generate_stream_entry("ETH-USDT-SWAP", base_ts + 120),
            generate_stream_entry("ETH-USDT-SWAP", base_ts + 180),
        ]
        
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        # Filter for BTC only
        datasets = await scanner.scan_datasets(symbol_filter="BTC-USDT-SWAP")
        
        assert len(datasets) == 1
        assert datasets[0].symbol == "BTC-USDT-SWAP"
    
    @pytest.mark.asyncio
    async def test_filter_returns_empty_for_no_match(self):
        """
        Test that filtering with no match returns empty list.
        
        **Validates: Requirements R2.1**
        """
        base_ts = 1704067200.0
        entries = [
            generate_stream_entry("BTC-USDT-SWAP", base_ts),
            generate_stream_entry("ETH-USDT-SWAP", base_ts + 60),
        ]
        
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        # Filter for non-existent symbol
        datasets = await scanner.scan_datasets(symbol_filter="DOGE-USDT-SWAP")
        
        assert len(datasets) == 0
    
    @pytest.mark.asyncio
    async def test_no_filter_returns_all_symbols(self):
        """
        Test that no filter returns all available symbols.
        
        **Validates: Requirements R2.1**
        """
        base_ts = 1704067200.0
        entries = [
            generate_stream_entry("BTC-USDT-SWAP", base_ts),
            generate_stream_entry("ETH-USDT-SWAP", base_ts + 60),
            generate_stream_entry("SOL-USDT-SWAP", base_ts + 120),
        ]
        
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        # No filter
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 3
        symbols = {d.symbol for d in datasets}
        assert symbols == {"BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"}


# ============================================================================
# Test Quality Metrics
# ============================================================================

class TestQualityMetrics:
    """Tests for data quality metrics."""
    
    @pytest.mark.asyncio
    async def test_completeness_calculated(self):
        """
        Test that completeness percentage is calculated.
        
        **Validates: Requirements R2.2**
        """
        base_ts = 1704067200.0
        # 10 entries, 1 minute apart = 100% completeness
        entries = [
            generate_stream_entry("BTC-USDT-SWAP", base_ts + i * 60)
            for i in range(10)
        ]
        
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 1
        assert datasets[0].completeness_pct > 0
        assert datasets[0].completeness_pct <= 100
    
    @pytest.mark.asyncio
    async def test_gaps_detected(self):
        """
        Test that data gaps are detected.
        
        **Validates: Requirements R2.2**
        """
        base_ts = 1704067200.0
        # Create entries with a 10-minute gap (default threshold is 5 minutes)
        entries = [
            generate_stream_entry("BTC-USDT-SWAP", base_ts),
            generate_stream_entry("BTC-USDT-SWAP", base_ts + 60),
            generate_stream_entry("BTC-USDT-SWAP", base_ts + 660),  # 10 min gap
            generate_stream_entry("BTC-USDT-SWAP", base_ts + 720),
        ]
        
        mock_redis = MockRedis(entries)
        config = ScanConfig(max_gap_minutes=5)
        scanner = DatasetScanner(mock_redis, config)
        
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 1
        assert datasets[0].gaps >= 1
    
    @pytest.mark.asyncio
    async def test_no_gaps_when_continuous(self):
        """
        Test that no gaps are detected for continuous data.
        
        **Validates: Requirements R2.2**
        """
        base_ts = 1704067200.0
        # Continuous entries, 1 minute apart
        entries = [
            generate_stream_entry("BTC-USDT-SWAP", base_ts + i * 60)
            for i in range(10)
        ]
        
        mock_redis = MockRedis(entries)
        config = ScanConfig(max_gap_minutes=5)
        scanner = DatasetScanner(mock_redis, config)
        
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 1
        assert datasets[0].gaps == 0
    
    @pytest.mark.asyncio
    async def test_date_range_calculated(self):
        """
        Test that date range is correctly calculated.
        
        **Validates: Requirements R2.2**
        """
        base_ts = 1704067200.0  # 2024-01-01 00:00:00 UTC
        end_ts = base_ts + 3600  # 1 hour later
        
        entries = [
            generate_stream_entry("BTC-USDT-SWAP", base_ts),
            generate_stream_entry("BTC-USDT-SWAP", end_ts),
        ]
        
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 1
        assert datasets[0].earliest_date != ""
        assert datasets[0].latest_date != ""
        assert datasets[0].earliest_date < datasets[0].latest_date
    
    @pytest.mark.asyncio
    async def test_candle_count_accurate(self):
        """
        Test that candle count matches number of entries.
        
        **Validates: Requirements R2.2**
        """
        base_ts = 1704067200.0
        num_entries = 15
        
        entries = [
            generate_stream_entry("BTC-USDT-SWAP", base_ts + i * 60)
            for i in range(num_entries)
        ]
        
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 1
        assert datasets[0].candle_count == num_entries


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases."""
    
    @pytest.mark.asyncio
    async def test_empty_stream_returns_empty_list(self):
        """
        Test that empty Redis stream returns empty dataset list.
        """
        mock_redis = MockRedis([])
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        datasets = await scanner.scan_datasets()
        
        assert datasets == []
    
    @pytest.mark.asyncio
    async def test_single_entry_returns_valid_dataset(self):
        """
        Test that a single entry still returns a valid dataset.
        """
        base_ts = 1704067200.0
        entries = [generate_stream_entry("BTC-USDT-SWAP", base_ts)]
        
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 1
        assert datasets[0].candle_count == 1
        assert datasets[0].gaps == 0


# ============================================================================
# Test DatasetListResponse Model
# ============================================================================

class TestDatasetListResponse:
    """Tests for DatasetListResponse model."""
    
    def test_response_model_creation(self):
        """
        Test that DatasetListResponse can be created with valid data.
        """
        datasets = [
            DatasetInfo(
                symbol="BTC-USDT-SWAP",
                exchange="OKX",
                earliest_date="2024-01-01T00:00:00+00:00",
                latest_date="2024-01-31T00:00:00+00:00",
                candle_count=43200,
                gaps=0,
                gap_dates=[],
                completeness_pct=100.0,
                last_updated="2024-01-31T00:00:00+00:00",
            ),
            DatasetInfo(
                symbol="ETH-USDT-SWAP",
                exchange="OKX",
                earliest_date="2024-01-01T00:00:00+00:00",
                latest_date="2024-01-31T00:00:00+00:00",
                candle_count=43000,
                gaps=2,
                gap_dates=["2024-01-15T00:00:00+00:00"],
                completeness_pct=99.5,
                last_updated="2024-01-31T00:00:00+00:00",
            ),
        ]
        
        response = DatasetListResponse(
            datasets=datasets,
            total=len(datasets),
        )
        
        assert response.total == 2
        assert len(response.datasets) == 2
        assert response.datasets[0].symbol == "BTC-USDT-SWAP"
        assert response.datasets[1].symbol == "ETH-USDT-SWAP"
    
    def test_empty_response(self):
        """
        Test that empty response is valid.
        """
        response = DatasetListResponse(
            datasets=[],
            total=0,
        )
        
        assert response.total == 0
        assert len(response.datasets) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
