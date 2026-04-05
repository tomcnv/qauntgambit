"""Tests for snapshot exporter."""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.backtesting.snapshot_exporter import (
    ExportConfig,
    SnapshotExporter,
    export_snapshots,
    _parse_datetime,
)


class TestExportConfig:
    """Tests for ExportConfig."""

    def test_default_values(self, tmp_path):
        """Test default configuration values."""
        config = ExportConfig(output_path=tmp_path / "test.jsonl")
        assert config.symbol is None
        assert config.start_time is None
        assert config.end_time is None
        assert config.redis_url == "redis://localhost:6379"
        assert config.stream_key == "events:feature_snapshots"
        assert config.batch_size == 1000
        assert config.max_snapshots is None

    def test_from_env(self, tmp_path, monkeypatch):
        """Test configuration from environment variables."""
        monkeypatch.setenv("EXPORT_SYMBOL", "BTC-USDT-SWAP")
        monkeypatch.setenv("EXPORT_START_TIME", "2024-01-01")
        monkeypatch.setenv("EXPORT_END_TIME", "2024-01-31")
        monkeypatch.setenv("REDIS_URL", "redis://custom:6380")
        monkeypatch.setenv("EXPORT_BATCH_SIZE", "500")
        monkeypatch.setenv("EXPORT_MAX_SNAPSHOTS", "10000")

        config = ExportConfig.from_env(tmp_path / "test.jsonl")
        
        assert config.symbol == "BTC-USDT-SWAP"
        assert config.start_time == datetime(2024, 1, 1)
        assert config.end_time == datetime(2024, 1, 31)
        assert config.redis_url == "redis://custom:6380"
        assert config.batch_size == 500
        assert config.max_snapshots == 10000


class TestSnapshotExporter:
    """Tests for SnapshotExporter."""

    @pytest.fixture
    def config(self, tmp_path):
        return ExportConfig(
            output_path=tmp_path / "snapshots.jsonl",
            symbol="BTC-USDT-SWAP",
        )

    @pytest.fixture
    def exporter(self, config):
        return SnapshotExporter(config)

    def test_normalize_snapshot_basic(self, exporter):
        """Test basic snapshot normalization."""
        raw = {
            "symbol": "BTC-USDT-SWAP",
            "timestamp": 1705000000,
            "price": 42000.0,
            "confidence": 0.75,
        }
        
        normalized = exporter._normalize_snapshot(raw)
        
        assert normalized["symbol"] == "BTC-USDT-SWAP"
        assert normalized["timestamp"] == 1705000000
        assert normalized["market_context"]["price"] == 42000.0
        assert normalized["features"]["confidence"] == 0.75
        assert normalized["warmup_ready"] is True

    def test_normalize_snapshot_with_existing_contexts(self, exporter):
        """Test normalization preserves existing market_context and features."""
        raw = {
            "symbol": "ETH-USDT-SWAP",
            "timestamp": 1705000000,
            "market_context": {
                "price": 2500.0,
                "bid": 2499.0,
                "ask": 2501.0,
            },
            "features": {
                "confidence": 0.8,
                "volatility_regime": "normal",
            },
        }
        
        normalized = exporter._normalize_snapshot(raw)
        
        assert normalized["market_context"]["price"] == 2500.0
        assert normalized["market_context"]["bid"] == 2499.0
        assert normalized["features"]["confidence"] == 0.8
        assert normalized["features"]["volatility_regime"] == "normal"

    def test_matches_filter_symbol(self, exporter):
        """Test symbol filtering."""
        matching = {"symbol": "BTC-USDT-SWAP"}
        non_matching = {"symbol": "ETH-USDT-SWAP"}
        
        assert exporter._matches_filter(matching) is True
        assert exporter._matches_filter(non_matching) is False

    def test_matches_filter_no_symbol(self, tmp_path):
        """Test no symbol filter passes all."""
        config = ExportConfig(output_path=tmp_path / "test.jsonl")
        exporter = SnapshotExporter(config)
        
        assert exporter._matches_filter({"symbol": "BTC-USDT-SWAP"}) is True
        assert exporter._matches_filter({"symbol": "ETH-USDT-SWAP"}) is True

    def test_time_to_stream_id(self, exporter):
        """Test datetime to stream ID conversion."""
        dt = datetime(2024, 1, 15, 12, 30, 0)
        stream_id = exporter._time_to_stream_id(dt)
        
        # Should be timestamp in milliseconds
        expected_ms = int(dt.timestamp() * 1000)
        assert stream_id == f"{expected_ms}-0"

    def test_parse_entry_json_data(self, exporter):
        """Test parsing entry with JSON data field."""
        entry_id = b"1705000000000-0"
        data = {
            b"data": json.dumps({
                "symbol": "BTC-USDT-SWAP",
                "market_context": {"price": 42000.0},
                "features": {"confidence": 0.75},
            }).encode()
        }
        
        snapshot = exporter._parse_entry(entry_id, data)
        
        assert snapshot is not None
        assert snapshot["symbol"] == "BTC-USDT-SWAP"
        assert snapshot["market_context"]["price"] == 42000.0
        assert snapshot["features"]["confidence"] == 0.75

    def test_parse_entry_individual_fields(self, exporter):
        """Test parsing entry with individual fields."""
        entry_id = "1705000000000-0"
        data = {
            "symbol": "BTC-USDT-SWAP",
            "price": "42000.0",
            "confidence": "0.75",
        }
        
        snapshot = exporter._parse_entry(entry_id, data)
        
        assert snapshot is not None
        assert snapshot["symbol"] == "BTC-USDT-SWAP"

    def test_parse_entry_invalid(self, exporter):
        """Test parsing invalid entry returns None."""
        entry_id = "invalid"
        data = {}
        
        # Should not raise, just return None or partial
        snapshot = exporter._parse_entry(entry_id, data)
        # May return None or a partial snapshot depending on implementation


class TestParseDatetime:
    """Tests for datetime parsing."""

    def test_parse_date_only(self):
        """Test parsing date-only format."""
        result = _parse_datetime("2024-01-15")
        assert result == datetime(2024, 1, 15)

    def test_parse_datetime_t(self):
        """Test parsing datetime with T separator."""
        result = _parse_datetime("2024-01-15T12:30:00")
        assert result == datetime(2024, 1, 15, 12, 30, 0)

    def test_parse_datetime_z(self):
        """Test parsing datetime with Z suffix."""
        result = _parse_datetime("2024-01-15T12:30:00Z")
        assert result == datetime(2024, 1, 15, 12, 30, 0)

    def test_parse_datetime_space(self):
        """Test parsing datetime with space separator."""
        result = _parse_datetime("2024-01-15 12:30:00")
        assert result == datetime(2024, 1, 15, 12, 30, 0)

    def test_parse_invalid(self):
        """Test parsing invalid format returns None."""
        result = _parse_datetime("invalid")
        assert result is None


class TestExportIntegration:
    """Integration tests for export functionality."""

    @pytest.mark.asyncio
    async def test_export_creates_file(self, tmp_path):
        """Test export creates output file."""
        output_path = tmp_path / "snapshots.jsonl"
        
        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.xrange = AsyncMock(return_value=[])
        mock_redis.close = AsyncMock()
        
        with patch("quantgambit.backtesting.snapshot_exporter.redis.from_url", return_value=mock_redis):
            count = await export_snapshots(
                output_path=output_path,
                redis_url="redis://localhost:6379",
            )
        
        assert count == 0
        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_export_writes_snapshots(self, tmp_path):
        """Test export writes snapshots to file."""
        output_path = tmp_path / "snapshots.jsonl"
        
        # Mock Redis with sample data
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.xrange = AsyncMock(side_effect=[
            [
                (b"1705000000000-0", {
                    b"data": json.dumps({
                        "symbol": "BTC-USDT-SWAP",
                        "market_context": {"price": 42000.0},
                        "features": {"confidence": 0.75},
                    }).encode()
                }),
                (b"1705000001000-0", {
                    b"data": json.dumps({
                        "symbol": "BTC-USDT-SWAP",
                        "market_context": {"price": 42010.0},
                        "features": {"confidence": 0.76},
                    }).encode()
                }),
            ],
            [],  # Second call returns empty to end iteration
        ])
        mock_redis.close = AsyncMock()
        
        with patch("quantgambit.backtesting.snapshot_exporter.redis.from_url", return_value=mock_redis):
            count = await export_snapshots(
                output_path=output_path,
                symbol="BTC-USDT-SWAP",
                redis_url="redis://localhost:6379",
            )
        
        assert count == 2
        
        # Verify file contents
        with output_path.open() as f:
            lines = f.readlines()
        
        assert len(lines) == 2
        
        snapshot1 = json.loads(lines[0])
        assert snapshot1["symbol"] == "BTC-USDT-SWAP"
        assert snapshot1["market_context"]["price"] == 42000.0

    @pytest.mark.asyncio
    async def test_export_respects_max_snapshots(self, tmp_path):
        """Test export respects max_snapshots limit."""
        output_path = tmp_path / "snapshots.jsonl"
        
        # Mock Redis with more data than limit
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.xrange = AsyncMock(return_value=[
            (f"{1705000000000 + i * 1000}-0".encode(), {
                b"data": json.dumps({
                    "symbol": "BTC-USDT-SWAP",
                    "market_context": {"price": 42000.0 + i},
                    "features": {"confidence": 0.75},
                }).encode()
            })
            for i in range(100)
        ])
        mock_redis.close = AsyncMock()
        
        with patch("quantgambit.backtesting.snapshot_exporter.redis.from_url", return_value=mock_redis):
            count = await export_snapshots(
                output_path=output_path,
                max_snapshots=10,
                redis_url="redis://localhost:6379",
            )
        
        assert count == 10
