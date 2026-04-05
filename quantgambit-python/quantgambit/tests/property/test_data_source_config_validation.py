"""
Property-based tests for Data Source Configuration Validation.

Feature: backtest-timescaledb-replay, Property 8: Configuration Validation
Validates: Requirements 4.1, 4.2, 4.5

Tests that:
- If `data_source` is not "redis" or "timescaledb", validation SHALL fail with an error
- If `data_source` is "timescaledb" and `exchange` is missing, validation SHALL fail with an error
- If `data_source` is "redis" or "timescaledb" with valid parameters, validation SHALL succeed
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, Any
from unittest.mock import MagicMock

from quantgambit.backtesting.data_source import (
    DataSourceFactory,
    DataSourceType,
)


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Valid data source values
valid_data_sources = st.sampled_from(["redis", "timescaledb"])

# Invalid data source values - strings that are not "redis" or "timescaledb"
# Use sampled_from for efficiency instead of filtering arbitrary text
invalid_data_sources = st.sampled_from([
    "postgres", "mysql", "mongodb", "sqlite", "cassandra", "dynamodb",
    "elasticsearch", "influxdb", "clickhouse", "snowflake", "bigquery",
    "redshift", "oracle", "sqlserver", "mariadb", "cockroachdb",
    "file", "csv", "json", "parquet", "avro", "orc",
    "kafka", "rabbitmq", "pulsar", "kinesis", "sqs",
    "s3", "gcs", "azure", "hdfs", "local",
    "memory", "cache", "memcached", "hazelcast",
    "invalid", "unknown", "none", "null", "undefined",
    "reddis", "timescale", "tsdb", "redisdb", "timescaleDB",  # Typos
    "INVALID", "Unknown", "OTHER", "custom", "default",
])

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


@st.composite
def valid_redis_config(draw) -> Dict[str, Any]:
    """Generate valid Redis backtest configuration."""
    return {
        "data_source": "redis",
        "symbol": draw(valid_symbols),
        "start_date": draw(valid_dates),
        "end_date": draw(valid_dates),
        "tenant_id": draw(valid_tenant_ids),
        "bot_id": draw(valid_bot_ids),
    }


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
def timescaledb_config_missing_exchange(draw) -> Dict[str, Any]:
    """Generate TimescaleDB config with missing exchange parameter."""
    return {
        "data_source": "timescaledb",
        "symbol": draw(valid_symbols),
        # exchange is intentionally missing
        "start_date": draw(valid_dates),
        "end_date": draw(valid_dates),
        "tenant_id": draw(valid_tenant_ids),
        "bot_id": draw(valid_bot_ids),
    }


@st.composite
def invalid_data_source_config(draw) -> Dict[str, Any]:
    """Generate config with invalid data_source value."""
    return {
        "data_source": draw(invalid_data_sources),
        "symbol": draw(valid_symbols),
        "exchange": draw(valid_exchanges),
        "start_date": draw(valid_dates),
        "end_date": draw(valid_dates),
        "tenant_id": draw(valid_tenant_ids),
        "bot_id": draw(valid_bot_ids),
    }


# ============================================================================
# Property Tests
# ============================================================================

class TestConfigurationValidation:
    """
    Property 8: Configuration Validation
    
    For any backtest configuration:
    - If `data_source` is not "redis" or "timescaledb", validation SHALL fail with an error
    - If `data_source` is "timescaledb" and `exchange` is missing, validation SHALL fail with an error
    - If `data_source` is "redis" or "timescaledb" with valid parameters, validation SHALL succeed
    
    **Feature: backtest-timescaledb-replay, Property 8: Configuration Validation**
    **Validates: Requirements 4.1, 4.2, 4.5**
    """
    
    @given(config=invalid_data_source_config())
    @settings(max_examples=100)
    def test_invalid_data_source_raises_error(self, config: Dict[str, Any]):
        """
        Property 8: Configuration Validation
        
        For any data_source value that is not "redis" or "timescaledb",
        DataSourceFactory.create() SHALL raise ValueError with an error message.
        
        **Validates: Requirements 4.1, 4.5**
        """
        # Ensure the data_source is actually invalid
        assume(config["data_source"].lower() not in ("redis", "timescaledb"))
        
        with pytest.raises(ValueError) as exc_info:
            DataSourceFactory.create(config)
        
        # Verify error message mentions invalid data_source
        error_message = str(exc_info.value).lower()
        assert "invalid" in error_message or "data_source" in error_message
        # Verify error message lists valid options
        assert "redis" in error_message or "timescaledb" in error_message
    
    @given(config=timescaledb_config_missing_exchange())
    @settings(max_examples=100)
    def test_timescaledb_missing_exchange_raises_error(self, config: Dict[str, Any]):
        """
        Property 8: Configuration Validation
        
        For any configuration with data_source="timescaledb" and missing exchange,
        DataSourceFactory.create() SHALL raise ValueError with an error message.
        
        **Validates: Requirements 4.2**
        """
        # Create a mock db_pool since timescaledb requires it
        mock_pool = MagicMock()
        
        with pytest.raises(ValueError) as exc_info:
            DataSourceFactory.create(config, db_pool=mock_pool)
        
        # Verify error message mentions exchange requirement
        error_message = str(exc_info.value).lower()
        assert "exchange" in error_message
    
    @given(config=valid_redis_config())
    @settings(max_examples=100)
    def test_valid_redis_config_succeeds(self, config: Dict[str, Any]):
        """
        Property 8: Configuration Validation
        
        For any valid Redis configuration with data_source="redis" and required parameters,
        DataSourceFactory.create() SHALL succeed without raising an error.
        
        **Validates: Requirements 4.1**
        """
        # Redis data source should be created successfully
        # Note: This may raise other errors (e.g., connection errors) but not ValueError
        # for configuration validation
        try:
            data_source = DataSourceFactory.create(config)
            # Verify we got a data source back (not None)
            assert data_source is not None
        except ValueError as e:
            # If ValueError is raised, it should NOT be about data_source validation
            error_message = str(e).lower()
            assert "invalid data_source" not in error_message
            assert "data_source" not in error_message or "redis" not in error_message
    
    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_valid_timescaledb_config_passes_validation(self, config: Dict[str, Any]):
        """
        Property 8: Configuration Validation
        
        For any valid TimescaleDB configuration with data_source="timescaledb",
        exchange, and required parameters, configuration validation SHALL succeed.
        
        Note: The actual creation may fail due to NotImplementedError (TimescaleDBDataSource
        not yet implemented) or missing db_pool, but the configuration validation itself
        should pass.
        
        **Validates: Requirements 4.1, 4.2**
        """
        # Create a mock db_pool since timescaledb requires it
        mock_pool = MagicMock()
        
        try:
            DataSourceFactory.create(config, db_pool=mock_pool)
        except NotImplementedError:
            # This is expected - TimescaleDBDataSource is not yet implemented
            # The important thing is that we didn't get a ValueError for config validation
            pass
        except ValueError as e:
            # If ValueError is raised, it should NOT be about data_source or exchange validation
            error_message = str(e).lower()
            # These would indicate config validation failure
            assert "invalid data_source" not in error_message
            assert "exchange is required" not in error_message
    
    @given(
        data_source=st.sampled_from(["redis", "timescaledb", "REDIS", "TIMESCALEDB", "Redis", "TimescaleDB"]),
        symbol=valid_symbols,
        exchange=valid_exchanges
    )
    @settings(max_examples=100)
    def test_data_source_case_insensitive(self, data_source: str, symbol: str, exchange: str):
        """
        Property 8: Configuration Validation
        
        For any valid data_source value regardless of case (e.g., "REDIS", "Redis", "redis"),
        DataSourceFactory.create() SHALL accept the configuration.
        
        **Validates: Requirements 4.1**
        """
        config = {
            "data_source": data_source,
            "symbol": symbol,
            "exchange": exchange,
        }
        
        # Create mock db_pool for timescaledb
        mock_pool = MagicMock()
        
        try:
            DataSourceFactory.create(config, db_pool=mock_pool)
        except NotImplementedError:
            # Expected for timescaledb - not yet implemented
            pass
        except ValueError as e:
            # Should NOT fail due to invalid data_source
            error_message = str(e).lower()
            assert "invalid data_source" not in error_message
    
    @given(
        symbol=valid_symbols,
        exchange=valid_exchanges
    )
    @settings(max_examples=100)
    def test_default_data_source_is_redis(self, symbol: str, exchange: str):
        """
        Property 8: Configuration Validation
        
        For any configuration without data_source specified,
        DataSourceFactory.create() SHALL default to "redis".
        
        **Validates: Requirements 4.1 (backward compatibility)**
        """
        config = {
            # data_source is intentionally missing
            "symbol": symbol,
            "exchange": exchange,
        }
        
        # Should create a Redis data source by default
        try:
            data_source = DataSourceFactory.create(config)
            # Verify we got a data source back
            assert data_source is not None
        except ValueError as e:
            # Should NOT fail due to missing data_source
            error_message = str(e).lower()
            assert "data_source" not in error_message


class TestDataSourceTypeEnum:
    """
    Tests for DataSourceType enum validation.
    
    **Feature: backtest-timescaledb-replay, Property 8: Configuration Validation**
    **Validates: Requirements 4.1**
    """
    
    def test_redis_type_value(self):
        """DataSourceType.REDIS should have value 'redis'."""
        assert DataSourceType.REDIS.value == "redis"
    
    def test_timescaledb_type_value(self):
        """DataSourceType.TIMESCALEDB should have value 'timescaledb'."""
        assert DataSourceType.TIMESCALEDB.value == "timescaledb"
    
    def test_only_two_valid_types(self):
        """DataSourceType should only have REDIS and TIMESCALEDB."""
        valid_types = list(DataSourceType)
        assert len(valid_types) == 2
        assert DataSourceType.REDIS in valid_types
        assert DataSourceType.TIMESCALEDB in valid_types
    
    @given(invalid_value=invalid_data_sources)
    @settings(max_examples=100)
    def test_invalid_enum_value_raises(self, invalid_value: str):
        """
        For any string that is not 'redis' or 'timescaledb',
        DataSourceType(value) SHALL raise ValueError.
        
        **Validates: Requirements 4.5**
        """
        assume(invalid_value.lower() not in ("redis", "timescaledb"))
        
        with pytest.raises(ValueError):
            DataSourceType(invalid_value.lower())


class TestMissingSymbolValidation:
    """
    Tests for missing symbol validation.
    
    **Feature: backtest-timescaledb-replay, Property 8: Configuration Validation**
    """
    
    @given(data_source=valid_data_sources, exchange=valid_exchanges)
    @settings(max_examples=100)
    def test_missing_symbol_raises_error(self, data_source: str, exchange: str):
        """
        For any configuration with missing symbol,
        DataSourceFactory.create() SHALL raise ValueError.
        """
        config = {
            "data_source": data_source,
            # symbol is intentionally missing
            "exchange": exchange,
        }
        
        mock_pool = MagicMock()
        
        with pytest.raises(ValueError) as exc_info:
            DataSourceFactory.create(config, db_pool=mock_pool)
        
        error_message = str(exc_info.value).lower()
        assert "symbol" in error_message
    
    @given(data_source=valid_data_sources, exchange=valid_exchanges)
    @settings(max_examples=100)
    def test_empty_symbol_raises_error(self, data_source: str, exchange: str):
        """
        For any configuration with empty symbol,
        DataSourceFactory.create() SHALL raise ValueError.
        """
        config = {
            "data_source": data_source,
            "symbol": "",  # Empty symbol
            "exchange": exchange,
        }
        
        mock_pool = MagicMock()
        
        with pytest.raises(ValueError) as exc_info:
            DataSourceFactory.create(config, db_pool=mock_pool)
        
        error_message = str(exc_info.value).lower()
        assert "symbol" in error_message


class TestTimescaleDBPoolValidation:
    """
    Tests for TimescaleDB db_pool validation.
    
    **Feature: backtest-timescaledb-replay, Property 8: Configuration Validation**
    """
    
    @given(config=valid_timescaledb_config())
    @settings(max_examples=100)
    def test_timescaledb_missing_pool_raises_error(self, config: Dict[str, Any]):
        """
        For any TimescaleDB configuration without db_pool,
        DataSourceFactory.create() SHALL raise ValueError.
        """
        with pytest.raises(ValueError) as exc_info:
            DataSourceFactory.create(config, db_pool=None)
        
        error_message = str(exc_info.value).lower()
        assert "db_pool" in error_message or "pool" in error_message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
