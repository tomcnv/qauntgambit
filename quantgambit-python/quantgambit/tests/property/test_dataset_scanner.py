"""
Property-based tests for DatasetScanner.

Feature: backtesting-api-integration, Property 4: Dataset Response Structure
Validates: Requirements R2.1, R2.2

Tests that for any dataset query, the response contains symbol, date range,
candle count, and quality metrics for each dataset.
"""

import json
import pytest
from datetime import datetime, timezone
from hypothesis import given, strategies as st, settings, assume
from unittest.mock import AsyncMock, MagicMock

from quantgambit.backtesting.dataset_scanner import (
    DatasetScanner,
    DatasetMetadata,
    ScanConfig,
)


# Strategies for generating test data
symbols = st.sampled_from([
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
    "DOGE-USDT-SWAP",
    "XRP-USDT-SWAP",
])

timestamps = st.floats(
    min_value=1704067200.0,  # 2024-01-01
    max_value=1735689600.0,  # 2025-01-01
    allow_nan=False,
    allow_infinity=False,
)

# Strategy for generating Redis stream entries
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


class MockRedis:
    """Mock Redis client for testing."""
    
    def __init__(self, entries: list[tuple] = None):
        self.entries = sorted(entries or [], key=lambda e: e[0])  # Sort by entry_id
        self._position = 0
    
    async def xrange(self, stream_key: str, min: str, max: str, count: int) -> list:
        """Mock xrange that returns entries in batches starting from min."""
        # Find starting position based on min
        start_idx = 0
        if min != "0":
            for i, entry in enumerate(self.entries):
                entry_id = entry[0].decode() if isinstance(entry[0], bytes) else entry[0]
                if entry_id > min:
                    start_idx = i
                    break
                elif entry_id == min:
                    start_idx = i
                    break
            else:
                # min is past all entries
                return []
        
        # Return batch from start_idx
        batch = self.entries[start_idx:start_idx + count]
        return batch


class TestDatasetMetadataStructure:
    """Property tests for DatasetMetadata structure."""
    
    @given(
        symbol=symbols,
        exchange=st.text(min_size=1, max_size=10),
        candle_count=st.integers(min_value=0, max_value=100000),
        gaps=st.integers(min_value=0, max_value=1000),
        completeness=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_metadata_to_dict_contains_all_fields(
        self, symbol, exchange, candle_count, gaps, completeness
    ):
        """
        Property 4: Dataset Response Structure
        For any DatasetMetadata, to_dict() should contain all required fields:
        symbol, exchange, earliest_date, latest_date, candle_count, gaps,
        gap_dates, completeness_pct, last_updated.
        
        **Validates: Requirements R2.1, R2.2**
        """
        metadata = DatasetMetadata(
            symbol=symbol,
            exchange=exchange,
            earliest_date="2024-01-01T00:00:00+00:00",
            latest_date="2024-01-02T00:00:00+00:00",
            candle_count=candle_count,
            gaps=gaps,
            gap_dates=[],
            completeness_pct=completeness,
            last_updated="2024-01-02T00:00:00+00:00",
        )
        
        result = metadata.to_dict()
        
        # All required fields must be present
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
        
        # Values should match
        assert result["symbol"] == symbol
        assert result["exchange"] == exchange
        assert result["candle_count"] == candle_count
        assert result["gaps"] == gaps
        assert result["completeness_pct"] == completeness


class TestDatasetScannerProperties:
    """Property-based tests for DatasetScanner."""
    
    @given(
        symbol=symbols,
        num_entries=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_scan_returns_valid_structure_for_any_data(
        self, symbol, num_entries
    ):
        """
        Property 4: Dataset Response Structure
        For any set of Redis entries, scan_datasets should return DatasetMetadata
        objects with all required fields populated.
        
        **Validates: Requirements R2.1, R2.2**
        """
        # Generate mock entries
        base_ts = 1704067200.0  # 2024-01-01
        entries = []
        for i in range(num_entries):
            ts = base_ts + i * 60  # 1 minute apart
            entries.append(generate_stream_entry(symbol, ts))
        
        # Create scanner with mock Redis
        mock_redis = MockRedis(entries)
        config = ScanConfig()
        scanner = DatasetScanner(mock_redis, config)
        
        # Scan datasets
        datasets = await scanner.scan_datasets()
        
        # Should have exactly one dataset for the symbol
        assert len(datasets) == 1
        
        dataset = datasets[0]
        
        # Verify structure
        assert dataset.symbol == symbol
        assert dataset.exchange == config.exchange
        assert dataset.candle_count == num_entries
        assert dataset.earliest_date != ""
        assert dataset.latest_date != ""
        assert 0 <= dataset.completeness_pct <= 100
        assert dataset.gaps >= 0
        assert isinstance(dataset.gap_dates, list)
        assert dataset.last_updated != ""
    
    @given(
        symbols_list=st.lists(symbols, min_size=1, max_size=5, unique=True),
        entries_per_symbol=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_scan_groups_by_symbol(
        self, symbols_list, entries_per_symbol
    ):
        """
        Property: For any set of entries with multiple symbols,
        scan_datasets should return one DatasetMetadata per unique symbol.
        
        **Validates: Requirements R2.1**
        """
        # Generate entries for multiple symbols with unique timestamps
        base_ts = 1704067200.0
        entries = []
        entry_idx = 0
        for sym in symbols_list:
            for i in range(entries_per_symbol):
                # Use unique timestamp for each entry to avoid ID collisions
                ts = base_ts + entry_idx * 60
                entries.append(generate_stream_entry(sym, ts))
                entry_idx += 1
        
        # Create scanner with mock Redis
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        # Scan datasets
        datasets = await scanner.scan_datasets()
        
        # Should have one dataset per symbol
        assert len(datasets) == len(symbols_list)
        
        # Each symbol should be represented
        found_symbols = {d.symbol for d in datasets}
        assert found_symbols == set(symbols_list)
        
        # Each dataset should have correct count
        for dataset in datasets:
            assert dataset.candle_count == entries_per_symbol
    
    @given(
        symbol=symbols,
        filter_symbol=symbols,
        num_entries=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_symbol_filter_works(
        self, symbol, filter_symbol, num_entries
    ):
        """
        Property: When a symbol filter is applied, only matching datasets
        should be returned.
        
        **Validates: Requirements R2.1**
        """
        # Generate entries
        base_ts = 1704067200.0
        entries = []
        for i in range(num_entries):
            ts = base_ts + i * 60
            entries.append(generate_stream_entry(symbol, ts))
        
        # Create scanner with mock Redis
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        # Scan with filter
        datasets = await scanner.scan_datasets(symbol_filter=filter_symbol)
        
        if symbol == filter_symbol:
            # Should find the dataset
            assert len(datasets) == 1
            assert datasets[0].symbol == symbol
        else:
            # Should not find any datasets
            assert len(datasets) == 0
    
    @given(
        symbol=symbols,
        gap_minutes=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_gap_detection(self, symbol, gap_minutes):
        """
        Property: Gaps larger than max_gap_minutes should be detected.
        
        **Validates: Requirements R2.2**
        """
        # Generate entries with a gap
        base_ts = 1704067200.0
        entries = [
            generate_stream_entry(symbol, base_ts),
            generate_stream_entry(symbol, base_ts + 60),  # 1 min later
            generate_stream_entry(symbol, base_ts + 60 + gap_minutes * 60),  # Gap
            generate_stream_entry(symbol, base_ts + 60 + gap_minutes * 60 + 60),  # 1 min after gap
        ]
        
        # Create scanner with 5-minute gap threshold
        config = ScanConfig(max_gap_minutes=5)
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, config)
        
        # Scan datasets
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 1
        dataset = datasets[0]
        
        if gap_minutes > config.max_gap_minutes:
            # Should detect the gap
            assert dataset.gaps >= 1, f"Gap of {gap_minutes} min not detected"
        else:
            # Should not detect a gap
            assert dataset.gaps == 0, f"False gap detected for {gap_minutes} min"
    
    @given(
        symbol=symbols,
        num_entries=st.integers(min_value=2, max_value=100),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_date_range_bounds(self, symbol, num_entries):
        """
        Property: earliest_date should be <= latest_date for any dataset.
        
        **Validates: Requirements R2.1**
        """
        # Generate entries
        base_ts = 1704067200.0
        entries = []
        for i in range(num_entries):
            ts = base_ts + i * 60
            entries.append(generate_stream_entry(symbol, ts))
        
        # Create scanner
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        # Scan datasets
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 1
        dataset = datasets[0]
        
        # Parse dates and compare
        earliest = datetime.fromisoformat(dataset.earliest_date)
        latest = datetime.fromisoformat(dataset.latest_date)
        
        assert earliest <= latest, \
            f"earliest_date ({earliest}) > latest_date ({latest})"
    
    @given(
        symbol=symbols,
        num_entries=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_completeness_bounded(self, symbol, num_entries):
        """
        Property: completeness_pct should always be between 0 and 100.
        
        **Validates: Requirements R2.2**
        """
        # Generate entries
        base_ts = 1704067200.0
        entries = []
        for i in range(num_entries):
            ts = base_ts + i * 60
            entries.append(generate_stream_entry(symbol, ts))
        
        # Create scanner
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        # Scan datasets
        datasets = await scanner.scan_datasets()
        
        assert len(datasets) == 1
        dataset = datasets[0]
        
        assert 0 <= dataset.completeness_pct <= 100, \
            f"completeness_pct out of bounds: {dataset.completeness_pct}"


class TestEmptyDatasets:
    """Tests for edge cases with empty data."""
    
    @pytest.mark.asyncio
    async def test_empty_stream_returns_empty_list(self):
        """
        Edge case: Empty Redis stream should return empty dataset list.
        """
        mock_redis = MockRedis([])
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        datasets = await scanner.scan_datasets()
        
        assert datasets == []
    
    @pytest.mark.asyncio
    async def test_filter_with_no_match_returns_empty(self):
        """
        Edge case: Filter that matches nothing should return empty list.
        """
        entries = [generate_stream_entry("BTC-USDT-SWAP", 1704067200.0)]
        mock_redis = MockRedis(entries)
        scanner = DatasetScanner(mock_redis, ScanConfig())
        
        datasets = await scanner.scan_datasets(symbol_filter="NONEXISTENT")
        
        assert datasets == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
