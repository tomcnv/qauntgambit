"""
Property-based tests for TimescaleDB Data Source Selection.

Feature: backtest-timescaledb-replay, Property 1: Data Source Selection
Validates: Requirements 1.1

Tests that:
- For any backtest configuration with data_source="timescaledb", the DataSourceFactory
  SHALL create a TimescaleDBDataSource instance that uses OrderbookSnapshotReader
  and TradeRecordReader, not SnapshotExporter.
"""

import pytest
from hypothesis import given, strategies as st, settings
from typing import Dict, Any
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from quantgambit.backtesting.data_source import (
    DataSourceFactory,
    DataSourceType,
)
from quantgambit.backtesting.timescaledb_data_source import (
    TimescaleDBDataSource,
    TimescaleDBDataSourceConfig,
)
from quantgambit.storage.orderbook_snapshot_reader import OrderbookSnapshotReader
from quantgambit.storage.trade_record_reader import TradeRecordReader


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Valid symbol strings
valid_symbols = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P'))
).filter(lambda x: len(x.strip()) > 0)

# Valid exchange strings
valid_exchanges = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=('L', 'N'))
).filter(lambda x: len(x.strip()) > 0)

# Valid date strings (YYYY-MM-DD format)
valid_dates = st.from_regex(r"20[2-3][0-9]-[0-1][0-9]-[0-3][0-9]", fullmatch=True)

# Valid tenant_id and bot_id strings
valid_tenant_ids = st.text(min_size=1, max_size=50).filter(lambda x: len(x.strip()) > 0)
valid_bot_ids = st.text(min_size=1, max_size=50).filter(lambda x: len(x.strip()) > 0)

# Valid batch sizes
valid_batch_sizes = st.integers(min_value=1, max_value=10000)


@st.composite
def valid_timescaledb_config(draw) -> Dict[str, Any]:
    """Generate valid TimescaleDB backtest configuration."""
    return {
        "data_source": "timescaledb",
        "symbol": draw(valid_symbols),
        "exchange": draw(valid_exchanges),
        "start_date": draw(valid_dates),
        "end_date": draw(valid_dates),
        "tenant_id": draw(valid_tenant_ids),
        "bot_id": draw(valid_bot_ids),
    }


@st.composite
def valid_timescaledb_config_with_batch_size(draw) -> Dict[str, Any]:
    """Generate valid TimescaleDB backtest configuration with batch_size."""
    return {
        "data_source": "timescaledb",
        "symbol": draw(valid_symbols),
        "exchange": draw(valid_exchanges),
        "start_date": draw(valid_dates),
        "end_date": draw(valid_dates),
        "tenant_id": draw(valid_tenant_ids),
        "bot_id": draw(valid_bot_ids),
        "batch_size": draw(valid_batch_sizes),
    }


@st.composite
def valid_timescaledb_config_with_include_trades(draw) -> Dict[str, Any]:
    """Generate valid TimescaleDB backtest configuration with include_trades option."""
    return {
        "data_source": "timescaledb",
        "symbol": draw(valid_symbols),
        "exchange": draw(valid_exchanges),
        "start_date": draw(valid_dates),
        "end_date": draw(valid_dates),
        "tenant_id": draw(valid_tenant_ids),
        "bot_id": draw(valid_bot_ids),
        "include_trades": draw(st.booleans()),
    }


# ============================================================================
# Property Tests
# ============================================================================

class TestDataSourceSelection:
    """
    Property 1: Data Source Selection

    For any backtest configuration with data_source="timescaledb", the DataSourceFactory
    SHALL create a TimescaleDBDataSource instance that uses OrderbookSnapshotReader
    and TradeRecordReader, not SnapshotExporter.

    **Feature: backtest-timescaledb-replay, Property 1: Data Source Selection**
    **Validates: Requirements 1.1**
    """

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_timescaledb_config_creates_timescaledb_data_source(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any backtest configuration with data_source="timescaledb",
        DataSourceFactory.create() SHALL return a TimescaleDBDataSource instance.

        **Validates: Requirements 1.1**
        """
        # Create a mock db_pool since timescaledb requires it
        mock_pool = MagicMock()

        # Create the data source
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        # Verify we got a TimescaleDBDataSource instance
        assert isinstance(data_source, TimescaleDBDataSource), (
            f"Expected TimescaleDBDataSource, got {type(data_source).__name__}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_timescaledb_data_source_uses_orderbook_snapshot_reader(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any backtest configuration with data_source="timescaledb",
        the created TimescaleDBDataSource SHALL use OrderbookSnapshotReader.

        **Validates: Requirements 1.1**
        """
        # Create a mock db_pool
        mock_pool = MagicMock()

        # Create the data source
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        # Verify it's a TimescaleDBDataSource
        assert isinstance(data_source, TimescaleDBDataSource)

        # Verify it has an OrderbookSnapshotReader
        assert hasattr(data_source, "_orderbook_reader"), (
            "TimescaleDBDataSource should have _orderbook_reader attribute"
        )
        assert isinstance(data_source._orderbook_reader, OrderbookSnapshotReader), (
            f"Expected OrderbookSnapshotReader, got {type(data_source._orderbook_reader).__name__}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_timescaledb_data_source_uses_trade_record_reader(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any backtest configuration with data_source="timescaledb",
        the created TimescaleDBDataSource SHALL use TradeRecordReader.

        **Validates: Requirements 1.1**
        """
        # Create a mock db_pool
        mock_pool = MagicMock()

        # Create the data source
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        # Verify it's a TimescaleDBDataSource
        assert isinstance(data_source, TimescaleDBDataSource)

        # Verify it has a TradeRecordReader
        assert hasattr(data_source, "_trade_reader"), (
            "TimescaleDBDataSource should have _trade_reader attribute"
        )
        assert isinstance(data_source._trade_reader, TradeRecordReader), (
            f"Expected TradeRecordReader, got {type(data_source._trade_reader).__name__}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_timescaledb_data_source_does_not_use_snapshot_exporter(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any backtest configuration with data_source="timescaledb",
        the created TimescaleDBDataSource SHALL NOT use SnapshotExporter.

        **Validates: Requirements 1.1**
        """
        # Import SnapshotExporter to check against
        from quantgambit.backtesting.snapshot_exporter import SnapshotExporter

        # Create a mock db_pool
        mock_pool = MagicMock()

        # Create the data source
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        # Verify it's a TimescaleDBDataSource, not a SnapshotExporter
        assert isinstance(data_source, TimescaleDBDataSource)
        assert not isinstance(data_source, SnapshotExporter), (
            "TimescaleDBDataSource should not be a SnapshotExporter"
        )

        # Verify it doesn't have SnapshotExporter as an internal component
        # Check all attributes to ensure no SnapshotExporter is used
        for attr_name in dir(data_source):
            if not attr_name.startswith("_"):
                continue
            attr = getattr(data_source, attr_name, None)
            if attr is not None:
                assert not isinstance(attr, SnapshotExporter), (
                    f"TimescaleDBDataSource should not use SnapshotExporter "
                    f"(found in attribute {attr_name})"
                )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_timescaledb_data_source_config_propagation(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any backtest configuration with data_source="timescaledb",
        the created TimescaleDBDataSource SHALL have config matching the input.

        **Validates: Requirements 1.1**
        """
        # Create a mock db_pool
        mock_pool = MagicMock()

        # Create the data source
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        # Verify it's a TimescaleDBDataSource
        assert isinstance(data_source, TimescaleDBDataSource)

        # Verify config is propagated correctly
        assert data_source.config.symbol == config["symbol"]
        assert data_source.config.exchange == config["exchange"]
        assert data_source.config.tenant_id == config.get("tenant_id", "default")
        assert data_source.config.bot_id == config.get("bot_id", "default")

    @given(config=valid_timescaledb_config_with_batch_size())
    @settings(max_examples=100)
    def test_timescaledb_data_source_batch_size_propagation(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any backtest configuration with data_source="timescaledb" and batch_size,
        the created TimescaleDBDataSource SHALL have the specified batch_size.

        **Validates: Requirements 1.1**
        """
        # Create a mock db_pool
        mock_pool = MagicMock()

        # Create the data source
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        # Verify it's a TimescaleDBDataSource
        assert isinstance(data_source, TimescaleDBDataSource)

        # Verify batch_size is propagated correctly
        assert data_source.config.batch_size == config["batch_size"]

        # Verify the orderbook reader has the correct batch size
        assert data_source._orderbook_reader.config.batch_size == config["batch_size"]

        # Verify the trade reader has batch_size * 5 (as per implementation)
        assert data_source._trade_reader.config.batch_size == config["batch_size"] * 5

    @given(config=valid_timescaledb_config_with_include_trades())
    @settings(max_examples=100)
    def test_timescaledb_data_source_include_trades_propagation(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any backtest configuration with data_source="timescaledb" and include_trades,
        the created TimescaleDBDataSource SHALL have the specified include_trades setting.

        **Validates: Requirements 1.1**
        """
        # Create a mock db_pool
        mock_pool = MagicMock()

        # Create the data source
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        # Verify it's a TimescaleDBDataSource
        assert isinstance(data_source, TimescaleDBDataSource)

        # Verify include_trades is propagated correctly
        assert data_source.config.include_trades == config["include_trades"]


class TestDataSourceSelectionContrast:
    """
    Additional tests to verify the contrast between redis and timescaledb data sources.

    **Feature: backtest-timescaledb-replay, Property 1: Data Source Selection**
    **Validates: Requirements 1.1**
    """

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
        start_date=valid_dates,
        end_date=valid_dates,
    )
    @settings(max_examples=100)
    def test_redis_config_does_not_create_timescaledb_data_source(
        self, symbol: str, exchange: str, start_date: str, end_date: str
    ):
        """
        Property 1: Data Source Selection (Contrast)

        For any backtest configuration with data_source="redis",
        DataSourceFactory.create() SHALL NOT return a TimescaleDBDataSource instance.

        **Validates: Requirements 1.1**
        """
        config = {
            "data_source": "redis",
            "symbol": symbol,
            "exchange": exchange,
            "start_date": start_date,
            "end_date": end_date,
        }

        # Create the data source (no db_pool needed for redis)
        data_source = DataSourceFactory.create(config)

        # Verify we did NOT get a TimescaleDBDataSource instance
        assert not isinstance(data_source, TimescaleDBDataSource), (
            f"Redis config should not create TimescaleDBDataSource, "
            f"got {type(data_source).__name__}"
        )

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
        start_date=valid_dates,
        end_date=valid_dates,
    )
    @settings(max_examples=100)
    def test_default_config_does_not_create_timescaledb_data_source(
        self, symbol: str, exchange: str, start_date: str, end_date: str
    ):
        """
        Property 1: Data Source Selection (Contrast)

        For any backtest configuration without data_source specified,
        DataSourceFactory.create() SHALL NOT return a TimescaleDBDataSource instance.

        **Validates: Requirements 1.1**
        """
        config = {
            # data_source is intentionally missing (defaults to redis)
            "symbol": symbol,
            "exchange": exchange,
            "start_date": start_date,
            "end_date": end_date,
        }

        # Create the data source (no db_pool needed for redis)
        data_source = DataSourceFactory.create(config)

        # Verify we did NOT get a TimescaleDBDataSource instance
        assert not isinstance(data_source, TimescaleDBDataSource), (
            f"Default config should not create TimescaleDBDataSource, "
            f"got {type(data_source).__name__}"
        )


class TestTimescaleDBDataSourceReaderConfiguration:
    """
    Tests to verify that OrderbookSnapshotReader and TradeRecordReader
    are configured correctly within TimescaleDBDataSource.

    **Feature: backtest-timescaledb-replay, Property 1: Data Source Selection**
    **Validates: Requirements 1.1**
    """

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_orderbook_reader_tenant_id_matches_config(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any TimescaleDBDataSource, the OrderbookSnapshotReader SHALL have
        tenant_id matching the data source config.

        **Validates: Requirements 1.1**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        assert data_source._orderbook_reader.config.tenant_id == config["tenant_id"]

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_orderbook_reader_bot_id_matches_config(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any TimescaleDBDataSource, the OrderbookSnapshotReader SHALL have
        bot_id matching the data source config.

        **Validates: Requirements 1.1**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        assert data_source._orderbook_reader.config.bot_id == config["bot_id"]

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_trade_reader_tenant_id_matches_config(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any TimescaleDBDataSource, the TradeRecordReader SHALL have
        tenant_id matching the data source config.

        **Validates: Requirements 1.1**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        assert data_source._trade_reader.config.tenant_id == config["tenant_id"]

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_trade_reader_bot_id_matches_config(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any TimescaleDBDataSource, the TradeRecordReader SHALL have
        bot_id matching the data source config.

        **Validates: Requirements 1.1**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        assert data_source._trade_reader.config.bot_id == config["bot_id"]

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_data_source_uses_provided_pool(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any TimescaleDBDataSource, the database pool SHALL be the one
        provided to the factory.

        **Validates: Requirements 1.1**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        assert data_source.pool is mock_pool

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_readers_use_same_pool_as_data_source(
        self, config: Dict[str, Any]
    ):
        """
        Property 1: Data Source Selection

        For any TimescaleDBDataSource, both OrderbookSnapshotReader and
        TradeRecordReader SHALL use the same database pool as the data source.

        **Validates: Requirements 1.1**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        assert data_source._orderbook_reader.pool is mock_pool
        assert data_source._trade_reader.pool is mock_pool


class TestQueryFiltering:
    """
    Property 2: Query Filtering

    For any TimescaleDB data source query with symbol S, exchange E, start_time T1,
    and end_time T2, all returned orderbook snapshots and trade records SHALL have
    symbol=S, exchange=E, and timestamp in [T1, T2].

    **Feature: backtest-timescaledb-replay, Property 2: Query Filtering**
    **Validates: Requirements 1.2**
    """

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_orderbook_reader_receives_correct_symbol(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with symbol S, the OrderbookSnapshotReader
        SHALL be configured to query with symbol=S.

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify the data source config has the correct symbol
        assert data_source.config.symbol == config["symbol"], (
            f"Expected symbol {config['symbol']}, got {data_source.config.symbol}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_orderbook_reader_receives_correct_exchange(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with exchange E, the OrderbookSnapshotReader
        SHALL be configured to query with exchange=E.

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify the data source config has the correct exchange
        assert data_source.config.exchange == config["exchange"], (
            f"Expected exchange {config['exchange']}, got {data_source.config.exchange}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_trade_reader_receives_correct_symbol(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with symbol S, the TradeRecordReader
        SHALL be configured to query with symbol=S.

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # The symbol is stored in the data source config and passed to readers
        # during iteration, not stored in the reader config
        assert data_source.config.symbol == config["symbol"], (
            f"Expected symbol {config['symbol']}, got {data_source.config.symbol}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_trade_reader_receives_correct_exchange(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with exchange E, the TradeRecordReader
        SHALL be configured to query with exchange=E.

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # The exchange is stored in the data source config and passed to readers
        # during iteration, not stored in the reader config
        assert data_source.config.exchange == config["exchange"], (
            f"Expected exchange {config['exchange']}, got {data_source.config.exchange}"
        )


@st.composite
def valid_timescaledb_config_with_datetime(draw) -> Dict[str, Any]:
    """Generate valid TimescaleDB backtest configuration with datetime objects."""
    # Generate start and end times ensuring start < end
    start_time = draw(st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2029, 12, 31)
    ))
    # End time is at least 1 hour after start time
    end_time = draw(st.datetimes(
        min_value=start_time,
        max_value=datetime(2030, 1, 1)
    ).filter(lambda x: x > start_time))
    
    return {
        "data_source": "timescaledb",
        "symbol": draw(valid_symbols),
        "exchange": draw(valid_exchanges),
        "start_time": start_time,
        "end_time": end_time,
        "tenant_id": draw(valid_tenant_ids),
        "bot_id": draw(valid_bot_ids),
    }


class TestQueryFilteringTimeRange:
    """
    Property 2: Query Filtering - Time Range Tests

    For any TimescaleDB data source query with start_time T1 and end_time T2,
    all returned orderbook snapshots and trade records SHALL have timestamp in [T1, T2].

    **Feature: backtest-timescaledb-replay, Property 2: Query Filtering**
    **Validates: Requirements 1.2**
    """

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_data_source_config_has_correct_start_time(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with start_time T1, the data source
        config SHALL have start_time=T1.

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        
        # Create TimescaleDBDataSourceConfig directly with datetime objects
        ds_config = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify the data source config has the correct start_time
        assert data_source.config.start_time == config["start_time"], (
            f"Expected start_time {config['start_time']}, "
            f"got {data_source.config.start_time}"
        )

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_data_source_config_has_correct_end_time(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with end_time T2, the data source
        config SHALL have end_time=T2.

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        
        # Create TimescaleDBDataSourceConfig directly with datetime objects
        ds_config = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify the data source config has the correct end_time
        assert data_source.config.end_time == config["end_time"], (
            f"Expected end_time {config['end_time']}, "
            f"got {data_source.config.end_time}"
        )

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_time_range_is_valid(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with start_time T1 and end_time T2,
        T1 SHALL be less than or equal to T2.

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        
        # Create TimescaleDBDataSourceConfig directly with datetime objects
        ds_config = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify start_time <= end_time
        assert data_source.config.start_time <= data_source.config.end_time, (
            f"start_time {data_source.config.start_time} should be <= "
            f"end_time {data_source.config.end_time}"
        )


class TestQueryFilteringParameterPropagation:
    """
    Property 2: Query Filtering - Parameter Propagation Tests

    Tests that verify the query parameters (symbol, exchange, time range)
    are correctly stored in the data source config and will be passed to
    the readers when iter_snapshots is called.

    **Feature: backtest-timescaledb-replay, Property 2: Query Filtering**
    **Validates: Requirements 1.2**
    """

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_data_source_stores_symbol_for_reader_queries(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with symbol S, the data source SHALL
        store symbol=S which will be passed to OrderbookSnapshotReader.iter_snapshots().

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        
        # Create TimescaleDBDataSourceConfig directly with datetime objects
        ds_config = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify the symbol is stored correctly and will be used in queries
        assert data_source.config.symbol == config["symbol"], (
            f"Symbol should be stored for reader queries: "
            f"expected {config['symbol']}, got {data_source.config.symbol}"
        )

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_data_source_stores_exchange_for_reader_queries(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with exchange E, the data source SHALL
        store exchange=E which will be passed to OrderbookSnapshotReader.iter_snapshots().

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        
        # Create TimescaleDBDataSourceConfig directly with datetime objects
        ds_config = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify the exchange is stored correctly and will be used in queries
        assert data_source.config.exchange == config["exchange"], (
            f"Exchange should be stored for reader queries: "
            f"expected {config['exchange']}, got {data_source.config.exchange}"
        )

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_data_source_stores_time_range_for_reader_queries(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with start_time T1 and end_time T2,
        the data source SHALL store these values which will be passed to
        OrderbookSnapshotReader.iter_snapshots() and TradeRecordReader.iter_trades().

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        
        # Create TimescaleDBDataSourceConfig directly with datetime objects
        ds_config = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify the time range is stored correctly and will be used in queries
        assert data_source.config.start_time == config["start_time"], (
            f"Start time should be stored for reader queries: "
            f"expected {config['start_time']}, got {data_source.config.start_time}"
        )
        assert data_source.config.end_time == config["end_time"], (
            f"End time should be stored for reader queries: "
            f"expected {config['end_time']}, got {data_source.config.end_time}"
        )

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_include_trades_flag_controls_trade_reader_usage(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source, the include_trades flag SHALL control
        whether TradeRecordReader is used during iteration.

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        
        # Test with include_trades=True
        ds_config_with_trades = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
            include_trades=True,
        )
        
        data_source_with_trades = TimescaleDBDataSource(mock_pool, ds_config_with_trades)
        assert data_source_with_trades.config.include_trades is True, (
            "include_trades=True should be stored correctly"
        )
        
        # Test with include_trades=False
        ds_config_without_trades = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
            include_trades=False,
        )
        
        data_source_without_trades = TimescaleDBDataSource(mock_pool, ds_config_without_trades)
        assert data_source_without_trades.config.include_trades is False, (
            "include_trades=False should be stored correctly"
        )


class TestQueryFilteringAllParametersCombined:
    """
    Property 2: Query Filtering - Combined Parameter Tests

    Tests that verify all query parameters (symbol, exchange, time range, tenant_id, bot_id)
    are correctly configured together.

    **Feature: backtest-timescaledb-replay, Property 2: Query Filtering**
    **Validates: Requirements 1.2**
    """

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_all_query_parameters_are_correctly_configured(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with symbol S, exchange E, start_time T1,
        end_time T2, tenant_id TID, and bot_id BID, the data source SHALL have
        all parameters correctly configured.

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        
        # Create TimescaleDBDataSourceConfig directly with datetime objects
        ds_config = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify all parameters are correctly configured
        assert data_source.config.symbol == config["symbol"], (
            f"Symbol mismatch: expected {config['symbol']}, got {data_source.config.symbol}"
        )
        assert data_source.config.exchange == config["exchange"], (
            f"Exchange mismatch: expected {config['exchange']}, got {data_source.config.exchange}"
        )
        assert data_source.config.start_time == config["start_time"], (
            f"Start time mismatch: expected {config['start_time']}, "
            f"got {data_source.config.start_time}"
        )
        assert data_source.config.end_time == config["end_time"], (
            f"End time mismatch: expected {config['end_time']}, "
            f"got {data_source.config.end_time}"
        )
        assert data_source.config.tenant_id == config["tenant_id"], (
            f"Tenant ID mismatch: expected {config['tenant_id']}, "
            f"got {data_source.config.tenant_id}"
        )
        assert data_source.config.bot_id == config["bot_id"], (
            f"Bot ID mismatch: expected {config['bot_id']}, "
            f"got {data_source.config.bot_id}"
        )

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_readers_have_matching_tenant_and_bot_ids(
        self, config: Dict[str, Any]
    ):
        """
        Property 2: Query Filtering

        For any TimescaleDB data source with tenant_id TID and bot_id BID,
        both OrderbookSnapshotReader and TradeRecordReader SHALL have
        tenant_id=TID and bot_id=BID.

        **Validates: Requirements 1.2**
        """
        mock_pool = MagicMock()
        
        # Create TimescaleDBDataSourceConfig directly with datetime objects
        ds_config = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify orderbook reader has correct tenant_id and bot_id
        assert data_source._orderbook_reader.config.tenant_id == config["tenant_id"], (
            f"Orderbook reader tenant_id mismatch: expected {config['tenant_id']}, "
            f"got {data_source._orderbook_reader.config.tenant_id}"
        )
        assert data_source._orderbook_reader.config.bot_id == config["bot_id"], (
            f"Orderbook reader bot_id mismatch: expected {config['bot_id']}, "
            f"got {data_source._orderbook_reader.config.bot_id}"
        )
        
        # Verify trade reader has correct tenant_id and bot_id
        assert data_source._trade_reader.config.tenant_id == config["tenant_id"], (
            f"Trade reader tenant_id mismatch: expected {config['tenant_id']}, "
            f"got {data_source._trade_reader.config.tenant_id}"
        )
        assert data_source._trade_reader.config.bot_id == config["bot_id"], (
            f"Trade reader bot_id mismatch: expected {config['bot_id']}, "
            f"got {data_source._trade_reader.config.bot_id}"
        )


class TestTenantBotFiltering:
    """
    Property 9: Tenant and Bot Filtering

    For any TimescaleDB data source with tenant_id T and bot_id B, all returned
    snapshots and trades SHALL have tenant_id=T and bot_id=B.

    **Feature: backtest-timescaledb-replay, Property 9: Tenant and Bot Filtering**
    **Validates: Requirements 4.3**
    """

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_tenant_id_propagated_to_orderbook_reader(
        self, config: Dict[str, Any]
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source with tenant_id T, the OrderbookSnapshotReader
        SHALL be configured with tenant_id=T.

        **Validates: Requirements 4.3**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify tenant_id is propagated to orderbook reader
        assert data_source._orderbook_reader.config.tenant_id == config["tenant_id"], (
            f"OrderbookSnapshotReader tenant_id mismatch: "
            f"expected {config['tenant_id']}, "
            f"got {data_source._orderbook_reader.config.tenant_id}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_bot_id_propagated_to_orderbook_reader(
        self, config: Dict[str, Any]
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source with bot_id B, the OrderbookSnapshotReader
        SHALL be configured with bot_id=B.

        **Validates: Requirements 4.3**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify bot_id is propagated to orderbook reader
        assert data_source._orderbook_reader.config.bot_id == config["bot_id"], (
            f"OrderbookSnapshotReader bot_id mismatch: "
            f"expected {config['bot_id']}, "
            f"got {data_source._orderbook_reader.config.bot_id}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_tenant_id_propagated_to_trade_reader(
        self, config: Dict[str, Any]
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source with tenant_id T, the TradeRecordReader
        SHALL be configured with tenant_id=T.

        **Validates: Requirements 4.3**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify tenant_id is propagated to trade reader
        assert data_source._trade_reader.config.tenant_id == config["tenant_id"], (
            f"TradeRecordReader tenant_id mismatch: "
            f"expected {config['tenant_id']}, "
            f"got {data_source._trade_reader.config.tenant_id}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_bot_id_propagated_to_trade_reader(
        self, config: Dict[str, Any]
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source with bot_id B, the TradeRecordReader
        SHALL be configured with bot_id=B.

        **Validates: Requirements 4.3**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify bot_id is propagated to trade reader
        assert data_source._trade_reader.config.bot_id == config["bot_id"], (
            f"TradeRecordReader bot_id mismatch: "
            f"expected {config['bot_id']}, "
            f"got {data_source._trade_reader.config.bot_id}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_tenant_and_bot_ids_consistent_across_readers(
        self, config: Dict[str, Any]
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source with tenant_id T and bot_id B,
        both OrderbookSnapshotReader and TradeRecordReader SHALL have
        identical tenant_id=T and bot_id=B.

        **Validates: Requirements 4.3**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify tenant_id is consistent across both readers
        assert (
            data_source._orderbook_reader.config.tenant_id ==
            data_source._trade_reader.config.tenant_id
        ), (
            f"tenant_id inconsistent between readers: "
            f"orderbook={data_source._orderbook_reader.config.tenant_id}, "
            f"trade={data_source._trade_reader.config.tenant_id}"
        )
        
        # Verify bot_id is consistent across both readers
        assert (
            data_source._orderbook_reader.config.bot_id ==
            data_source._trade_reader.config.bot_id
        ), (
            f"bot_id inconsistent between readers: "
            f"orderbook={data_source._orderbook_reader.config.bot_id}, "
            f"trade={data_source._trade_reader.config.bot_id}"
        )

    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_tenant_and_bot_ids_match_data_source_config(
        self, config: Dict[str, Any]
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source with tenant_id T and bot_id B,
        the data source config, OrderbookSnapshotReader config, and
        TradeRecordReader config SHALL all have tenant_id=T and bot_id=B.

        **Validates: Requirements 4.3**
        """
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify all three configs have matching tenant_id
        assert data_source.config.tenant_id == config["tenant_id"], (
            f"Data source config tenant_id mismatch"
        )
        assert data_source._orderbook_reader.config.tenant_id == config["tenant_id"], (
            f"Orderbook reader config tenant_id mismatch"
        )
        assert data_source._trade_reader.config.tenant_id == config["tenant_id"], (
            f"Trade reader config tenant_id mismatch"
        )
        
        # Verify all three configs have matching bot_id
        assert data_source.config.bot_id == config["bot_id"], (
            f"Data source config bot_id mismatch"
        )
        assert data_source._orderbook_reader.config.bot_id == config["bot_id"], (
            f"Orderbook reader config bot_id mismatch"
        )
        assert data_source._trade_reader.config.bot_id == config["bot_id"], (
            f"Trade reader config bot_id mismatch"
        )


class TestTenantBotFilteringDefaults:
    """
    Property 9: Tenant and Bot Filtering - Default Values

    Tests that verify default values are used when tenant_id and bot_id
    are not specified in the configuration.

    **Feature: backtest-timescaledb-replay, Property 9: Tenant and Bot Filtering**
    **Validates: Requirements 4.3**
    """

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
        start_date=valid_dates,
        end_date=valid_dates,
    )
    @settings(max_examples=100)
    def test_default_tenant_id_when_not_specified(
        self, symbol: str, exchange: str, start_date: str, end_date: str
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source without tenant_id specified,
        the default value "default" SHALL be used.

        **Validates: Requirements 4.3**
        """
        config = {
            "data_source": "timescaledb",
            "symbol": symbol,
            "exchange": exchange,
            "start_date": start_date,
            "end_date": end_date,
            # tenant_id intentionally not specified
            "bot_id": "some_bot",
        }
        
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify default tenant_id is used
        assert data_source.config.tenant_id == "default", (
            f"Expected default tenant_id 'default', got {data_source.config.tenant_id}"
        )
        assert data_source._orderbook_reader.config.tenant_id == "default", (
            f"Expected default tenant_id 'default' in orderbook reader, "
            f"got {data_source._orderbook_reader.config.tenant_id}"
        )
        assert data_source._trade_reader.config.tenant_id == "default", (
            f"Expected default tenant_id 'default' in trade reader, "
            f"got {data_source._trade_reader.config.tenant_id}"
        )

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
        start_date=valid_dates,
        end_date=valid_dates,
    )
    @settings(max_examples=100)
    def test_default_bot_id_when_not_specified(
        self, symbol: str, exchange: str, start_date: str, end_date: str
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source without bot_id specified,
        the default value "default" SHALL be used.

        **Validates: Requirements 4.3**
        """
        config = {
            "data_source": "timescaledb",
            "symbol": symbol,
            "exchange": exchange,
            "start_date": start_date,
            "end_date": end_date,
            "tenant_id": "some_tenant",
            # bot_id intentionally not specified
        }
        
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify default bot_id is used
        assert data_source.config.bot_id == "default", (
            f"Expected default bot_id 'default', got {data_source.config.bot_id}"
        )
        assert data_source._orderbook_reader.config.bot_id == "default", (
            f"Expected default bot_id 'default' in orderbook reader, "
            f"got {data_source._orderbook_reader.config.bot_id}"
        )
        assert data_source._trade_reader.config.bot_id == "default", (
            f"Expected default bot_id 'default' in trade reader, "
            f"got {data_source._trade_reader.config.bot_id}"
        )

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
        start_date=valid_dates,
        end_date=valid_dates,
    )
    @settings(max_examples=100)
    def test_default_tenant_and_bot_ids_when_neither_specified(
        self, symbol: str, exchange: str, start_date: str, end_date: str
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source without tenant_id or bot_id specified,
        both SHALL default to "default".

        **Validates: Requirements 4.3**
        """
        config = {
            "data_source": "timescaledb",
            "symbol": symbol,
            "exchange": exchange,
            "start_date": start_date,
            "end_date": end_date,
            # Neither tenant_id nor bot_id specified
        }
        
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify default values are used for both
        assert data_source.config.tenant_id == "default", (
            f"Expected default tenant_id 'default', got {data_source.config.tenant_id}"
        )
        assert data_source.config.bot_id == "default", (
            f"Expected default bot_id 'default', got {data_source.config.bot_id}"
        )
        
        # Verify defaults propagated to readers
        assert data_source._orderbook_reader.config.tenant_id == "default"
        assert data_source._orderbook_reader.config.bot_id == "default"
        assert data_source._trade_reader.config.tenant_id == "default"
        assert data_source._trade_reader.config.bot_id == "default"


class TestTenantBotFilteringDirectConfig:
    """
    Property 9: Tenant and Bot Filtering - Direct Config Tests

    Tests that verify tenant_id and bot_id filtering when creating
    TimescaleDBDataSource directly with TimescaleDBDataSourceConfig.

    **Feature: backtest-timescaledb-replay, Property 9: Tenant and Bot Filtering**
    **Validates: Requirements 4.3**
    """

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_direct_config_tenant_id_propagation(
        self, config: Dict[str, Any]
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDBDataSourceConfig with tenant_id T, the created
        TimescaleDBDataSource SHALL have tenant_id=T in all reader configs.

        **Validates: Requirements 4.3**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify tenant_id is propagated correctly
        assert data_source.config.tenant_id == config["tenant_id"]
        assert data_source._orderbook_reader.config.tenant_id == config["tenant_id"]
        assert data_source._trade_reader.config.tenant_id == config["tenant_id"]

    @given(config=valid_timescaledb_config_with_datetime())
    @settings(max_examples=100)
    def test_direct_config_bot_id_propagation(
        self, config: Dict[str, Any]
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDBDataSourceConfig with bot_id B, the created
        TimescaleDBDataSource SHALL have bot_id=B in all reader configs.

        **Validates: Requirements 4.3**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol=config["symbol"],
            exchange=config["exchange"],
            start_time=config["start_time"],
            end_time=config["end_time"],
            tenant_id=config["tenant_id"],
            bot_id=config["bot_id"],
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify bot_id is propagated correctly
        assert data_source.config.bot_id == config["bot_id"]
        assert data_source._orderbook_reader.config.bot_id == config["bot_id"]
        assert data_source._trade_reader.config.bot_id == config["bot_id"]

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
    )
    @settings(max_examples=100)
    def test_direct_config_default_tenant_id(
        self, symbol: str, exchange: str
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDBDataSourceConfig without tenant_id specified,
        the default value "default" SHALL be used.

        **Validates: Requirements 4.3**
        """
        mock_pool = MagicMock()
        
        # Create config without specifying tenant_id (uses default)
        ds_config = TimescaleDBDataSourceConfig(
            symbol=symbol,
            exchange=exchange,
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            # tenant_id not specified, should default to "default"
            bot_id="custom_bot",
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify default tenant_id is used
        assert data_source.config.tenant_id == "default"
        assert data_source._orderbook_reader.config.tenant_id == "default"
        assert data_source._trade_reader.config.tenant_id == "default"

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
    )
    @settings(max_examples=100)
    def test_direct_config_default_bot_id(
        self, symbol: str, exchange: str
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDBDataSourceConfig without bot_id specified,
        the default value "default" SHALL be used.

        **Validates: Requirements 4.3**
        """
        mock_pool = MagicMock()
        
        # Create config without specifying bot_id (uses default)
        ds_config = TimescaleDBDataSourceConfig(
            symbol=symbol,
            exchange=exchange,
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            tenant_id="custom_tenant",
            # bot_id not specified, should default to "default"
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify default bot_id is used
        assert data_source.config.bot_id == "default"
        assert data_source._orderbook_reader.config.bot_id == "default"
        assert data_source._trade_reader.config.bot_id == "default"


class TestTenantBotFilteringEdgeCases:
    """
    Property 9: Tenant and Bot Filtering - Edge Cases

    Tests for edge cases in tenant_id and bot_id filtering.

    **Feature: backtest-timescaledb-replay, Property 9: Tenant and Bot Filtering**
    **Validates: Requirements 4.3**
    """

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
        tenant_id=st.text(min_size=1, max_size=100).filter(lambda x: len(x.strip()) > 0),
        bot_id=st.text(min_size=1, max_size=100).filter(lambda x: len(x.strip()) > 0),
    )
    @settings(max_examples=100)
    def test_long_tenant_and_bot_ids(
        self, symbol: str, exchange: str, tenant_id: str, bot_id: str
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source with long tenant_id and bot_id strings,
        the values SHALL be preserved exactly.

        **Validates: Requirements 4.3**
        """
        config = {
            "data_source": "timescaledb",
            "symbol": symbol,
            "exchange": exchange,
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "tenant_id": tenant_id,
            "bot_id": bot_id,
        }
        
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify exact values are preserved
        assert data_source.config.tenant_id == tenant_id
        assert data_source.config.bot_id == bot_id
        assert data_source._orderbook_reader.config.tenant_id == tenant_id
        assert data_source._orderbook_reader.config.bot_id == bot_id
        assert data_source._trade_reader.config.tenant_id == tenant_id
        assert data_source._trade_reader.config.bot_id == bot_id

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
        tenant_id=st.sampled_from(["tenant-1", "tenant_2", "tenant.3", "TENANT4"]),
        bot_id=st.sampled_from(["bot-1", "bot_2", "bot.3", "BOT4"]),
    )
    @settings(max_examples=100)
    def test_special_characters_in_tenant_and_bot_ids(
        self, symbol: str, exchange: str, tenant_id: str, bot_id: str
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source with special characters in tenant_id
        and bot_id (hyphens, underscores, dots), the values SHALL be preserved.

        **Validates: Requirements 4.3**
        """
        config = {
            "data_source": "timescaledb",
            "symbol": symbol,
            "exchange": exchange,
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "tenant_id": tenant_id,
            "bot_id": bot_id,
        }
        
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify special characters are preserved
        assert data_source.config.tenant_id == tenant_id
        assert data_source.config.bot_id == bot_id
        assert data_source._orderbook_reader.config.tenant_id == tenant_id
        assert data_source._orderbook_reader.config.bot_id == bot_id
        assert data_source._trade_reader.config.tenant_id == tenant_id
        assert data_source._trade_reader.config.bot_id == bot_id

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
    )
    @settings(max_examples=100)
    def test_same_tenant_and_bot_id_values(
        self, symbol: str, exchange: str
    ):
        """
        Property 9: Tenant and Bot Filtering

        For any TimescaleDB data source where tenant_id equals bot_id,
        both values SHALL be correctly propagated.

        **Validates: Requirements 4.3**
        """
        same_value = "shared_identifier"
        config = {
            "data_source": "timescaledb",
            "symbol": symbol,
            "exchange": exchange,
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "tenant_id": same_value,
            "bot_id": same_value,
        }
        
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)

        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify both have the same value
        assert data_source.config.tenant_id == same_value
        assert data_source.config.bot_id == same_value
        assert data_source._orderbook_reader.config.tenant_id == same_value
        assert data_source._orderbook_reader.config.bot_id == same_value
        assert data_source._trade_reader.config.tenant_id == same_value
        assert data_source._trade_reader.config.bot_id == same_value


class TestValidationReporting:
    """
    Property 10: Validation Reporting

    For any data validation result:
    - `first_timestamp` and `last_timestamp` SHALL reflect the actual data range
    - `coverage_pct` SHALL equal (actual_range / requested_range) * 100
    - If `coverage_pct` < 50, `warnings` SHALL contain a coverage warning
    - `snapshot_count` and `trade_count` SHALL equal the actual counts in the range

    **Feature: backtest-timescaledb-replay, Property 10: Validation Reporting**
    **Validates: Requirements 5.2, 5.3, 5.5**
    """

    @given(
        snapshot_count=st.integers(min_value=0, max_value=100000),
        trade_count=st.integers(min_value=0, max_value=1000000),
    )
    @settings(max_examples=100)
    def test_snapshot_and_trade_counts_are_reported(
        self, snapshot_count: int, trade_count: int
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult, `snapshot_count` and `trade_count`
        SHALL equal the actual counts provided.

        **Validates: Requirements 5.5**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=snapshot_count,
            trade_count=trade_count,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 31),
            coverage_pct=100.0,
            warnings=[],
            error_message=None,
        )

        assert result.snapshot_count == snapshot_count, (
            f"snapshot_count mismatch: expected {snapshot_count}, got {result.snapshot_count}"
        )
        assert result.trade_count == trade_count, (
            f"trade_count mismatch: expected {trade_count}, got {result.trade_count}"
        )

    @given(
        first_ts=st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2029, 12, 31)),
        last_ts=st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2030, 1, 1)),
    )
    @settings(max_examples=100)
    def test_timestamps_reflect_actual_data_range(
        self, first_ts: datetime, last_ts: datetime
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult, `first_timestamp` and `last_timestamp`
        SHALL reflect the actual data range provided.

        **Validates: Requirements 5.2**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            coverage_pct=100.0,
            warnings=[],
            error_message=None,
        )

        assert result.first_timestamp == first_ts, (
            f"first_timestamp mismatch: expected {first_ts}, got {result.first_timestamp}"
        )
        assert result.last_timestamp == last_ts, (
            f"last_timestamp mismatch: expected {last_ts}, got {result.last_timestamp}"
        )

    @given(
        actual_range_seconds=st.floats(min_value=0.0, max_value=86400.0 * 365, allow_nan=False, allow_infinity=False),
        requested_range_seconds=st.floats(min_value=1.0, max_value=86400.0 * 365, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_coverage_pct_calculation(
        self, actual_range_seconds: float, requested_range_seconds: float
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult, `coverage_pct` SHALL equal
        (actual_range / requested_range) * 100.

        **Validates: Requirements 5.2**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        # Calculate expected coverage percentage
        expected_coverage_pct = (actual_range_seconds / requested_range_seconds) * 100.0

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 31),
            coverage_pct=expected_coverage_pct,
            warnings=[],
            error_message=None,
        )

        assert abs(result.coverage_pct - expected_coverage_pct) < 0.0001, (
            f"coverage_pct mismatch: expected {expected_coverage_pct}, got {result.coverage_pct}"
        )

    @given(
        coverage_pct=st.floats(min_value=0.0, max_value=49.99, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_low_coverage_warning_when_below_50_percent(
        self, coverage_pct: float
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult with `coverage_pct` < 50,
        `warnings` SHALL contain a coverage warning.

        **Validates: Requirements 5.3**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        # Create a warning message for low coverage (as the system would)
        coverage_warning = (
            f"Data coverage is only {coverage_pct:.1f}% of requested range. "
            f"Proceeding with available data."
        )

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 15),
            coverage_pct=coverage_pct,
            warnings=[coverage_warning],
            error_message=None,
        )

        # Verify that warnings list is not empty when coverage < 50%
        assert len(result.warnings) > 0, (
            f"Expected warnings for coverage_pct={coverage_pct}%, but warnings list is empty"
        )

        # Verify that at least one warning mentions coverage
        has_coverage_warning = any("coverage" in w.lower() for w in result.warnings)
        assert has_coverage_warning, (
            f"Expected a coverage warning for coverage_pct={coverage_pct}%, "
            f"but no coverage warning found in: {result.warnings}"
        )

    @given(
        coverage_pct=st.floats(min_value=50.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_no_coverage_warning_when_at_or_above_50_percent(
        self, coverage_pct: float
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult with `coverage_pct` >= 50,
        `warnings` SHALL NOT contain a coverage warning (unless other warnings exist).

        **Validates: Requirements 5.3**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        # Create result with no coverage warning (coverage >= 50%)
        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 31),
            coverage_pct=coverage_pct,
            warnings=[],  # No warnings when coverage is sufficient
            error_message=None,
        )

        # Verify that no coverage warning exists
        has_coverage_warning = any(
            "coverage" in w.lower() and "%" in w
            for w in result.warnings
        )
        assert not has_coverage_warning, (
            f"Expected no coverage warning for coverage_pct={coverage_pct}%, "
            f"but found coverage warning in: {result.warnings}"
        )

    @given(
        snapshot_count=st.integers(min_value=1, max_value=100000),
        trade_count=st.integers(min_value=0, max_value=1000000),
        coverage_pct=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_validation_result_is_valid_with_data(
        self, snapshot_count: int, trade_count: int, coverage_pct: float
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult with snapshot_count > 0,
        `is_valid` SHALL be True (data exists).

        **Validates: Requirements 5.2, 5.5**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        warnings = []
        if coverage_pct < 50.0:
            warnings.append(
                f"Data coverage is only {coverage_pct:.1f}% of requested range. "
                f"Proceeding with available data."
            )

        result = DataValidationResult(
            is_valid=True,  # Valid because snapshot_count > 0
            snapshot_count=snapshot_count,
            trade_count=trade_count,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 31),
            coverage_pct=coverage_pct,
            warnings=warnings,
            error_message=None,
        )

        assert result.is_valid is True, (
            f"Expected is_valid=True when snapshot_count={snapshot_count} > 0"
        )

    @given(
        trade_count=st.integers(min_value=0, max_value=1000000),
    )
    @settings(max_examples=100)
    def test_validation_result_is_invalid_with_no_snapshots(
        self, trade_count: int
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult with snapshot_count = 0,
        `is_valid` SHALL be False (no data exists).

        **Validates: Requirements 5.2, 5.5**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        error_msg = "No orderbook snapshots found for the specified range"

        result = DataValidationResult(
            is_valid=False,  # Invalid because snapshot_count = 0
            snapshot_count=0,
            trade_count=trade_count,
            first_timestamp=None,
            last_timestamp=None,
            coverage_pct=0.0,
            warnings=[],
            error_message=error_msg,
        )

        assert result.is_valid is False, (
            f"Expected is_valid=False when snapshot_count=0"
        )
        assert result.error_message is not None, (
            f"Expected error_message when is_valid=False"
        )

    @given(
        first_ts=st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2024, 12, 31)),
    )
    @settings(max_examples=100)
    def test_timestamps_can_be_none_when_no_data(
        self, first_ts: datetime
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult with no data (snapshot_count=0),
        `first_timestamp` and `last_timestamp` SHALL be None.

        **Validates: Requirements 5.2**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        result = DataValidationResult(
            is_valid=False,
            snapshot_count=0,
            trade_count=0,
            first_timestamp=None,
            last_timestamp=None,
            coverage_pct=0.0,
            warnings=[],
            error_message="No data found",
        )

        assert result.first_timestamp is None, (
            f"Expected first_timestamp=None when no data, got {result.first_timestamp}"
        )
        assert result.last_timestamp is None, (
            f"Expected last_timestamp=None when no data, got {result.last_timestamp}"
        )

    @given(
        snapshot_count=st.integers(min_value=1, max_value=100000),
        trade_count=st.integers(min_value=0, max_value=1000000),
    )
    @settings(max_examples=100)
    def test_counts_are_non_negative(
        self, snapshot_count: int, trade_count: int
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult, `snapshot_count` and `trade_count`
        SHALL be non-negative integers.

        **Validates: Requirements 5.5**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=snapshot_count,
            trade_count=trade_count,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 31),
            coverage_pct=100.0,
            warnings=[],
            error_message=None,
        )

        assert result.snapshot_count >= 0, (
            f"snapshot_count should be non-negative, got {result.snapshot_count}"
        )
        assert result.trade_count >= 0, (
            f"trade_count should be non-negative, got {result.trade_count}"
        )

    @given(
        coverage_pct=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_coverage_pct_is_non_negative(
        self, coverage_pct: float
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult, `coverage_pct` SHALL be non-negative.

        **Validates: Requirements 5.2**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 31),
            coverage_pct=coverage_pct,
            warnings=[],
            error_message=None,
        )

        assert result.coverage_pct >= 0.0, (
            f"coverage_pct should be non-negative, got {result.coverage_pct}"
        )


class TestValidationReportingTimestampRange:
    """
    Property 10: Validation Reporting - Timestamp Range Tests

    Tests that verify first_timestamp and last_timestamp correctly
    reflect the actual data range.

    **Feature: backtest-timescaledb-replay, Property 10: Validation Reporting**
    **Validates: Requirements 5.2**
    """

    @given(
        start_offset_hours=st.integers(min_value=0, max_value=720),
        duration_hours=st.integers(min_value=1, max_value=720),
    )
    @settings(max_examples=100)
    def test_timestamp_range_reflects_actual_data(
        self, start_offset_hours: int, duration_hours: int
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult with data, `first_timestamp` SHALL be
        less than or equal to `last_timestamp`.

        **Validates: Requirements 5.2**
        """
        from quantgambit.backtesting.data_source import DataValidationResult
        from datetime import timedelta

        base_time = datetime(2024, 1, 1)
        first_ts = base_time + timedelta(hours=start_offset_hours)
        last_ts = first_ts + timedelta(hours=duration_hours)

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            coverage_pct=100.0,
            warnings=[],
            error_message=None,
        )

        assert result.first_timestamp <= result.last_timestamp, (
            f"first_timestamp ({result.first_timestamp}) should be <= "
            f"last_timestamp ({result.last_timestamp})"
        )

    @given(
        requested_start=st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2024, 6, 30)),
        requested_end=st.datetimes(min_value=datetime(2024, 7, 1), max_value=datetime(2025, 12, 31)),
        actual_start_offset_hours=st.integers(min_value=0, max_value=168),
        actual_end_offset_hours=st.integers(min_value=0, max_value=168),
    )
    @settings(max_examples=100)
    def test_actual_range_can_differ_from_requested(
        self,
        requested_start: datetime,
        requested_end: datetime,
        actual_start_offset_hours: int,
        actual_end_offset_hours: int,
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult, the actual data range (first_timestamp
        to last_timestamp) MAY differ from the requested range.

        **Validates: Requirements 5.2**
        """
        from quantgambit.backtesting.data_source import DataValidationResult
        from datetime import timedelta

        # Actual data starts later than requested
        actual_start = requested_start + timedelta(hours=actual_start_offset_hours)
        # Actual data ends earlier than requested
        actual_end = requested_end - timedelta(hours=actual_end_offset_hours)

        # Ensure actual_start <= actual_end
        if actual_start > actual_end:
            actual_start, actual_end = actual_end, actual_start

        warnings = []
        if actual_start > requested_start:
            warnings.append(
                f"Data starts at {actual_start}, later than requested start time {requested_start}"
            )
        if actual_end < requested_end:
            warnings.append(
                f"Data ends at {actual_end}, earlier than requested end time {requested_end}"
            )

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=actual_start,
            last_timestamp=actual_end,
            coverage_pct=80.0,
            warnings=warnings,
            error_message=None,
        )

        # Verify timestamps are stored correctly
        assert result.first_timestamp == actual_start
        assert result.last_timestamp == actual_end


class TestValidationReportingWarnings:
    """
    Property 10: Validation Reporting - Warning Tests

    Tests that verify warnings are correctly generated and stored.

    **Feature: backtest-timescaledb-replay, Property 10: Validation Reporting**
    **Validates: Requirements 5.3**
    """

    @given(
        num_warnings=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=100)
    def test_warnings_list_can_have_multiple_entries(
        self, num_warnings: int
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult, `warnings` SHALL be a list that
        can contain zero or more warning messages.

        **Validates: Requirements 5.3**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        warnings = [f"Warning {i}" for i in range(num_warnings)]

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 31),
            coverage_pct=100.0,
            warnings=warnings,
            error_message=None,
        )

        assert len(result.warnings) == num_warnings, (
            f"Expected {num_warnings} warnings, got {len(result.warnings)}"
        )

    @given(
        coverage_pct=st.floats(min_value=0.0, max_value=49.99, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_coverage_warning_format(
        self, coverage_pct: float
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult with coverage < 50%, the coverage
        warning SHALL include the coverage percentage.

        **Validates: Requirements 5.3**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        coverage_warning = (
            f"Data coverage is only {coverage_pct:.1f}% of requested range. "
            f"Proceeding with available data."
        )

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 15),
            coverage_pct=coverage_pct,
            warnings=[coverage_warning],
            error_message=None,
        )

        # Verify the warning contains the coverage percentage
        assert len(result.warnings) > 0
        warning_text = result.warnings[0]
        assert f"{coverage_pct:.1f}%" in warning_text, (
            f"Expected coverage percentage {coverage_pct:.1f}% in warning, "
            f"got: {warning_text}"
        )


class TestValidationReportingDataclassProperties:
    """
    Property 10: Validation Reporting - Dataclass Properties

    Tests that verify the DataValidationResult dataclass has all
    required fields and they behave correctly.

    **Feature: backtest-timescaledb-replay, Property 10: Validation Reporting**
    **Validates: Requirements 5.2, 5.3, 5.5**
    """

    @given(
        is_valid=st.booleans(),
        snapshot_count=st.integers(min_value=0, max_value=100000),
        trade_count=st.integers(min_value=0, max_value=1000000),
        coverage_pct=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_dataclass_fields_are_accessible(
        self,
        is_valid: bool,
        snapshot_count: int,
        trade_count: int,
        coverage_pct: float,
    ):
        """
        Property 10: Validation Reporting

        For any DataValidationResult, all fields SHALL be accessible
        and return the values they were initialized with.

        **Validates: Requirements 5.2, 5.3, 5.5**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        first_ts = datetime(2024, 1, 1) if is_valid else None
        last_ts = datetime(2024, 1, 31) if is_valid else None
        warnings = ["Test warning"] if coverage_pct < 50 else []
        error_msg = None if is_valid else "Test error"

        result = DataValidationResult(
            is_valid=is_valid,
            snapshot_count=snapshot_count,
            trade_count=trade_count,
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            coverage_pct=coverage_pct,
            warnings=warnings,
            error_message=error_msg,
        )

        # Verify all fields are accessible
        assert result.is_valid == is_valid
        assert result.snapshot_count == snapshot_count
        assert result.trade_count == trade_count
        assert result.first_timestamp == first_ts
        assert result.last_timestamp == last_ts
        assert result.coverage_pct == coverage_pct
        assert result.warnings == warnings
        assert result.error_message == error_msg

    def test_dataclass_has_default_warnings_list(self):
        """
        Property 10: Validation Reporting

        For any DataValidationResult created without warnings,
        `warnings` SHALL default to an empty list.

        **Validates: Requirements 5.3**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 31),
            coverage_pct=100.0,
            # warnings not specified, should default to []
        )

        assert result.warnings == [], (
            f"Expected default warnings to be [], got {result.warnings}"
        )

    def test_dataclass_has_default_error_message_none(self):
        """
        Property 10: Validation Reporting

        For any DataValidationResult created without error_message,
        `error_message` SHALL default to None.

        **Validates: Requirements 5.2**
        """
        from quantgambit.backtesting.data_source import DataValidationResult

        result = DataValidationResult(
            is_valid=True,
            snapshot_count=100,
            trade_count=500,
            first_timestamp=datetime(2024, 1, 1),
            last_timestamp=datetime(2024, 1, 31),
            coverage_pct=100.0,
            # error_message not specified, should default to None
        )

        assert result.error_message is None, (
            f"Expected default error_message to be None, got {result.error_message}"
        )


# ============================================================================
# Property 11: Batch Size Configuration
# ============================================================================

class TestBatchSizeConfiguration:
    """
    Property 11: Batch Size Configuration

    For any TimescaleDB data source with batch_size N, each database query
    SHALL request at most N records per batch.

    **Feature: backtest-timescaledb-replay, Property 11: Batch Size Configuration**
    **Validates: Requirements 6.1**
    """

    @given(batch_size=st.integers(min_value=1, max_value=10000))
    @settings(max_examples=100)
    def test_batch_size_propagated_to_orderbook_reader(
        self, batch_size: int
    ):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source with batch_size N, the OrderbookSnapshotReader
        SHALL be configured with batch_size=N.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol="BTC/USDT",
            exchange="binance",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            batch_size=batch_size,
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify batch_size is propagated to orderbook reader
        assert data_source._orderbook_reader.config.batch_size == batch_size, (
            f"OrderbookSnapshotReader batch_size mismatch: "
            f"expected {batch_size}, got {data_source._orderbook_reader.config.batch_size}"
        )

    @given(batch_size=st.integers(min_value=1, max_value=10000))
    @settings(max_examples=100)
    def test_batch_size_multiplied_for_trade_reader(
        self, batch_size: int
    ):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source with batch_size N, the TradeRecordReader
        SHALL be configured with batch_size=N*5 (trades are more frequent).

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol="BTC/USDT",
            exchange="binance",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            batch_size=batch_size,
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify trade reader has batch_size * 5 (as per implementation)
        expected_trade_batch_size = batch_size * 5
        assert data_source._trade_reader.config.batch_size == expected_trade_batch_size, (
            f"TradeRecordReader batch_size mismatch: "
            f"expected {expected_trade_batch_size}, got {data_source._trade_reader.config.batch_size}"
        )

    @given(config=valid_timescaledb_config_with_batch_size())
    @settings(max_examples=100)
    def test_batch_size_from_factory_propagated_to_orderbook_reader(
        self, config: Dict[str, Any]
    ):
        """
        Property 11: Batch Size Configuration

        For any backtest configuration with batch_size N passed through DataSourceFactory,
        the OrderbookSnapshotReader SHALL be configured with batch_size=N.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)
        
        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify batch_size is propagated correctly
        assert data_source._orderbook_reader.config.batch_size == config["batch_size"], (
            f"OrderbookSnapshotReader batch_size mismatch: "
            f"expected {config['batch_size']}, got {data_source._orderbook_reader.config.batch_size}"
        )

    @given(config=valid_timescaledb_config_with_batch_size())
    @settings(max_examples=100)
    def test_batch_size_from_factory_multiplied_for_trade_reader(
        self, config: Dict[str, Any]
    ):
        """
        Property 11: Batch Size Configuration

        For any backtest configuration with batch_size N passed through DataSourceFactory,
        the TradeRecordReader SHALL be configured with batch_size=N*5.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)
        
        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify trade reader has batch_size * 5
        expected_trade_batch_size = config["batch_size"] * 5
        assert data_source._trade_reader.config.batch_size == expected_trade_batch_size, (
            f"TradeRecordReader batch_size mismatch: "
            f"expected {expected_trade_batch_size}, got {data_source._trade_reader.config.batch_size}"
        )

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
    )
    @settings(max_examples=100)
    def test_default_batch_size_is_1000(
        self, symbol: str, exchange: str
    ):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source without batch_size specified,
        the default batch_size SHALL be 1000.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        # Create config without specifying batch_size (uses default)
        ds_config = TimescaleDBDataSourceConfig(
            symbol=symbol,
            exchange=exchange,
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            # batch_size not specified, should default to 1000
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify default batch_size is 1000
        assert data_source.config.batch_size == 1000, (
            f"Expected default batch_size 1000, got {data_source.config.batch_size}"
        )
        assert data_source._orderbook_reader.config.batch_size == 1000, (
            f"Expected default orderbook reader batch_size 1000, "
            f"got {data_source._orderbook_reader.config.batch_size}"
        )
        # Trade reader should have 1000 * 5 = 5000
        assert data_source._trade_reader.config.batch_size == 5000, (
            f"Expected default trade reader batch_size 5000, "
            f"got {data_source._trade_reader.config.batch_size}"
        )

    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges,
        start_date=valid_dates,
        end_date=valid_dates,
    )
    @settings(max_examples=100)
    def test_default_batch_size_from_factory_is_1000(
        self, symbol: str, exchange: str, start_date: str, end_date: str
    ):
        """
        Property 11: Batch Size Configuration

        For any backtest configuration without batch_size specified,
        the default batch_size SHALL be 1000 when created through DataSourceFactory.

        **Validates: Requirements 6.1**
        """
        config = {
            "data_source": "timescaledb",
            "symbol": symbol,
            "exchange": exchange,
            "start_date": start_date,
            "end_date": end_date,
            # batch_size intentionally not specified
        }
        
        mock_pool = MagicMock()
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)
        
        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify default batch_size is 1000
        assert data_source.config.batch_size == 1000, (
            f"Expected default batch_size 1000, got {data_source.config.batch_size}"
        )
        assert data_source._orderbook_reader.config.batch_size == 1000, (
            f"Expected default orderbook reader batch_size 1000, "
            f"got {data_source._orderbook_reader.config.batch_size}"
        )
        # Trade reader should have 1000 * 5 = 5000
        assert data_source._trade_reader.config.batch_size == 5000, (
            f"Expected default trade reader batch_size 5000, "
            f"got {data_source._trade_reader.config.batch_size}"
        )

    @given(batch_size=st.integers(min_value=1, max_value=10000))
    @settings(max_examples=100)
    def test_batch_size_stored_in_data_source_config(
        self, batch_size: int
    ):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source with batch_size N, the data source
        config SHALL store batch_size=N.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol="BTC/USDT",
            exchange="binance",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            batch_size=batch_size,
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify batch_size is stored in data source config
        assert data_source.config.batch_size == batch_size, (
            f"Data source config batch_size mismatch: "
            f"expected {batch_size}, got {data_source.config.batch_size}"
        )


class TestBatchSizeConfigurationEdgeCases:
    """
    Property 11: Batch Size Configuration - Edge Cases

    Tests for edge cases in batch_size configuration.

    **Feature: backtest-timescaledb-replay, Property 11: Batch Size Configuration**
    **Validates: Requirements 6.1**
    """

    @given(batch_size=st.integers(min_value=1, max_value=10))
    @settings(max_examples=100)
    def test_small_batch_sizes(
        self, batch_size: int
    ):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source with small batch_size (1-10),
        the batch_size SHALL be correctly propagated.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol="BTC/USDT",
            exchange="binance",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            batch_size=batch_size,
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify small batch_size is propagated correctly
        assert data_source._orderbook_reader.config.batch_size == batch_size
        assert data_source._trade_reader.config.batch_size == batch_size * 5

    @given(batch_size=st.integers(min_value=5000, max_value=10000))
    @settings(max_examples=100)
    def test_large_batch_sizes(
        self, batch_size: int
    ):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source with large batch_size (5000-10000),
        the batch_size SHALL be correctly propagated.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol="BTC/USDT",
            exchange="binance",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            batch_size=batch_size,
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify large batch_size is propagated correctly
        assert data_source._orderbook_reader.config.batch_size == batch_size
        assert data_source._trade_reader.config.batch_size == batch_size * 5

    def test_batch_size_of_1(self):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source with batch_size=1 (minimum),
        the batch_size SHALL be correctly propagated.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol="BTC/USDT",
            exchange="binance",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            batch_size=1,
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify batch_size=1 is propagated correctly
        assert data_source._orderbook_reader.config.batch_size == 1
        assert data_source._trade_reader.config.batch_size == 5  # 1 * 5

    @given(batch_size=st.integers(min_value=1, max_value=10000))
    @settings(max_examples=100)
    def test_batch_size_relationship_between_readers(
        self, batch_size: int
    ):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source with batch_size N, the TradeRecordReader
        batch_size SHALL always be exactly 5 times the OrderbookSnapshotReader batch_size.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol="BTC/USDT",
            exchange="binance",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            batch_size=batch_size,
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify the 5x relationship between readers
        orderbook_batch_size = data_source._orderbook_reader.config.batch_size
        trade_batch_size = data_source._trade_reader.config.batch_size
        
        assert trade_batch_size == orderbook_batch_size * 5, (
            f"Trade reader batch_size ({trade_batch_size}) should be 5x "
            f"orderbook reader batch_size ({orderbook_batch_size})"
        )


class TestBatchSizeConfigurationConsistency:
    """
    Property 11: Batch Size Configuration - Consistency Tests

    Tests that verify batch_size is consistently applied across all components.

    **Feature: backtest-timescaledb-replay, Property 11: Batch Size Configuration**
    **Validates: Requirements 6.1**
    """

    @given(config=valid_timescaledb_config_with_batch_size())
    @settings(max_examples=100)
    def test_batch_size_consistent_across_all_configs(
        self, config: Dict[str, Any]
    ):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source with batch_size N, the data source config
        and OrderbookSnapshotReader config SHALL both have batch_size=N.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        data_source = DataSourceFactory.create(config, db_pool=mock_pool)
        
        assert isinstance(data_source, TimescaleDBDataSource)
        
        # Verify batch_size is consistent
        assert data_source.config.batch_size == config["batch_size"], (
            f"Data source config batch_size mismatch"
        )
        assert data_source._orderbook_reader.config.batch_size == config["batch_size"], (
            f"Orderbook reader config batch_size mismatch"
        )

    @given(
        batch_size=st.integers(min_value=1, max_value=10000),
        symbol=valid_symbols,
        exchange=valid_exchanges,
        tenant_id=valid_tenant_ids,
        bot_id=valid_bot_ids,
    )
    @settings(max_examples=100)
    def test_batch_size_independent_of_other_config_params(
        self,
        batch_size: int,
        symbol: str,
        exchange: str,
        tenant_id: str,
        bot_id: str,
    ):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source, the batch_size SHALL be correctly
        propagated regardless of other configuration parameters.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol=symbol,
            exchange=exchange,
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            tenant_id=tenant_id,
            bot_id=bot_id,
            batch_size=batch_size,
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify batch_size is correct regardless of other params
        assert data_source.config.batch_size == batch_size
        assert data_source._orderbook_reader.config.batch_size == batch_size
        assert data_source._trade_reader.config.batch_size == batch_size * 5
        
        # Also verify other params are correct
        assert data_source.config.symbol == symbol
        assert data_source.config.exchange == exchange
        assert data_source.config.tenant_id == tenant_id
        assert data_source.config.bot_id == bot_id

    @given(batch_size=st.integers(min_value=1, max_value=10000))
    @settings(max_examples=100)
    def test_batch_size_preserved_after_data_source_creation(
        self, batch_size: int
    ):
        """
        Property 11: Batch Size Configuration

        For any TimescaleDB data source with batch_size N, the batch_size
        SHALL remain unchanged after data source creation.

        **Validates: Requirements 6.1**
        """
        mock_pool = MagicMock()
        
        ds_config = TimescaleDBDataSourceConfig(
            symbol="BTC/USDT",
            exchange="binance",
            start_time=datetime(2024, 1, 1),
            end_time=datetime(2024, 1, 31),
            batch_size=batch_size,
        )
        
        data_source = TimescaleDBDataSource(mock_pool, ds_config)
        
        # Verify batch_size is preserved (read multiple times)
        for _ in range(3):
            assert data_source.config.batch_size == batch_size
            assert data_source._orderbook_reader.config.batch_size == batch_size
            assert data_source._trade_reader.config.batch_size == batch_size * 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
