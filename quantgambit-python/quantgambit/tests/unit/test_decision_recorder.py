"""Unit tests for DecisionRecorder class.

Feature: trading-pipeline-integration
Requirements: 2.1, 2.2
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantgambit.integration.decision_recording import DecisionRecorder, RecordedDecision


# Test fixtures and mocks

@dataclass
class MockMarketSnapshot:
    """Mock market snapshot for testing."""
    symbol: str = "BTCUSDT"
    mid_price: float = 50000.0
    spread_bps: float = 1.5
    bid: float = 49999.0
    ask: float = 50001.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "mid_price": self.mid_price,
            "spread_bps": self.spread_bps,
            "bid": self.bid,
            "ask": self.ask,
        }


@dataclass
class MockFeatures:
    """Mock features for testing."""
    symbol: str = "BTCUSDT"
    volatility: float = 0.02
    trend: float = 0.5
    price: float = 50000.0


@dataclass
class MockStageContext:
    """Mock stage context for testing."""
    symbol: str = "BTCUSDT"
    data: Dict[str, Any] = None
    rejection_stage: Optional[str] = None
    rejection_reason: Optional[str] = None
    signal: Optional[Dict[str, Any]] = None
    profile_id: Optional[str] = None
    stage_trace: Optional[List[Dict[str, Any]]] = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}
        if self.stage_trace is None:
            self.stage_trace = []


class MockConfigVersion:
    """Mock config version for testing."""
    def __init__(self, version_id: str = "test_v1"):
        self.version_id = version_id
        self.created_at = datetime.now(timezone.utc)
        self.created_by = "test"
        self.config_hash = "abc123"
        self.parameters = {}


class MockConfigRegistry:
    """Mock configuration registry for testing."""
    def __init__(self, version_id: str = "test_v1"):
        self._version = MockConfigVersion(version_id)
    
    async def get_live_config(self):
        return self._version


class MockConnection:
    """Mock database connection for testing."""
    def __init__(self):
        self.executemany_calls = []
    
    async def executemany(self, query: str, args: List):
        self.executemany_calls.append((query, args))


class MockPool:
    """Mock connection pool for testing."""
    def __init__(self):
        self.connection = MockConnection()
    
    def acquire(self):
        return MockPoolContext(self.connection)


class MockPoolContext:
    """Mock pool context manager."""
    def __init__(self, connection):
        self.connection = connection
    
    async def __aenter__(self):
        return self.connection
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


# Test classes

class TestDecisionRecorderCreation:
    """Tests for DecisionRecorder initialization."""
    
    def test_basic_creation(self):
        """DecisionRecorder should be created with default settings."""
        pool = MockPool()
        registry = MockConfigRegistry()
        
        recorder = DecisionRecorder(pool, registry)
        
        assert recorder._pool is pool
        assert recorder._config_registry is registry
        assert recorder._batch == []
        assert recorder._batch_size == DecisionRecorder.DEFAULT_BATCH_SIZE
        assert recorder._flush_interval_sec == DecisionRecorder.DEFAULT_FLUSH_INTERVAL_SEC
    
    def test_custom_batch_size(self):
        """DecisionRecorder should accept custom batch_size."""
        pool = MockPool()
        registry = MockConfigRegistry()
        
        recorder = DecisionRecorder(pool, registry, batch_size=50)
        
        assert recorder._batch_size == 50
        assert recorder.batch_size == 50
    
    def test_custom_flush_interval(self):
        """DecisionRecorder should accept custom flush_interval_sec."""
        pool = MockPool()
        registry = MockConfigRegistry()
        
        recorder = DecisionRecorder(pool, registry, flush_interval_sec=10.0)
        
        assert recorder._flush_interval_sec == 10.0
        assert recorder.flush_interval_sec == 10.0
    
    def test_batch_size_setter(self):
        """batch_size setter should validate input."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        recorder.batch_size = 50
        assert recorder.batch_size == 50
        
        with pytest.raises(ValueError) as exc_info:
            recorder.batch_size = 0
        assert "batch_size must be at least 1" in str(exc_info.value)
    
    def test_flush_interval_setter(self):
        """flush_interval_sec setter should validate input."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        recorder.flush_interval_sec = 10.0
        assert recorder.flush_interval_sec == 10.0
        
        with pytest.raises(ValueError) as exc_info:
            recorder.flush_interval_sec = 0
        assert "flush_interval_sec must be positive" in str(exc_info.value)


class TestDecisionRecorderRecord:
    """Tests for DecisionRecorder.record() method."""
    
    @pytest.fixture
    def recorder(self):
        """Create a DecisionRecorder with mocks."""
        pool = MockPool()
        registry = MockConfigRegistry()
        return DecisionRecorder(pool, registry, batch_size=10)
    
    @pytest.fixture
    def sample_snapshot(self):
        """Create a sample market snapshot."""
        return MockMarketSnapshot()
    
    @pytest.fixture
    def sample_features(self):
        """Create sample features."""
        return MockFeatures()
    
    @pytest.fixture
    def sample_context(self):
        """Create a sample stage context."""
        return MockStageContext(
            data={
                "positions": [{"symbol": "BTCUSDT", "size": 0.1}],
                "account": {"equity": 10000.0},
            },
            stage_trace=[
                {"stage": "data_readiness", "passed": True},
                {"stage": "ev_gate", "passed": True, "ev": 0.05},
            ],
            profile_id="aggressive",
        )
    
    @pytest.mark.asyncio
    async def test_record_accepted_decision(
        self, recorder, sample_snapshot, sample_features, sample_context
    ):
        """record() should create RecordedDecision for accepted decision."""
        sample_context.signal = {"side": "buy", "size": 0.05}
        
        decision_id = await recorder.record(
            symbol="BTCUSDT",
            snapshot=sample_snapshot,
            features=sample_features,
            ctx=sample_context,
            decision="accepted",
        )
        
        assert decision_id.startswith("dec_")
        assert recorder.pending_count == 1
        
        record = recorder._batch[0]
        assert record.symbol == "BTCUSDT"
        assert record.decision == "accepted"
        assert record.config_version == "test_v1"
        assert record.market_snapshot["mid_price"] == 50000.0
        assert record.features["volatility"] == 0.02
        assert record.signal == {"side": "buy", "size": 0.05}
        assert record.profile_id == "aggressive"
    
    @pytest.mark.asyncio
    async def test_record_rejected_decision(
        self, recorder, sample_snapshot, sample_features
    ):
        """record() should capture rejection details."""
        ctx = MockStageContext(
            rejection_stage="ev_gate",
            rejection_reason="EV below threshold",
            stage_trace=[
                {"stage": "data_readiness", "passed": True},
                {"stage": "ev_gate", "passed": False, "ev": -0.02},
            ],
        )
        
        decision_id = await recorder.record(
            symbol="BTCUSDT",
            snapshot=sample_snapshot,
            features=sample_features,
            ctx=ctx,
            decision="rejected",
        )
        
        assert decision_id.startswith("dec_")
        
        record = recorder._batch[0]
        assert record.decision == "rejected"
        assert record.rejection_stage == "ev_gate"
        assert record.rejection_reason == "EV below threshold"
    
    @pytest.mark.asyncio
    async def test_record_shadow_decision(
        self, recorder, sample_snapshot, sample_features, sample_context
    ):
        """record() should support shadow decisions."""
        decision_id = await recorder.record(
            symbol="BTCUSDT",
            snapshot=sample_snapshot,
            features=sample_features,
            ctx=sample_context,
            decision="shadow",
        )
        
        record = recorder._batch[0]
        assert record.decision == "shadow"
    
    @pytest.mark.asyncio
    async def test_record_invalid_decision_raises(
        self, recorder, sample_snapshot, sample_features, sample_context
    ):
        """record() should raise ValueError for invalid decision."""
        with pytest.raises(ValueError) as exc_info:
            await recorder.record(
                symbol="BTCUSDT",
                snapshot=sample_snapshot,
                features=sample_features,
                ctx=sample_context,
                decision="invalid",
            )
        
        assert "decision must be 'accepted', 'rejected', or 'shadow'" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_record_with_dict_snapshot(self, recorder, sample_features, sample_context):
        """record() should accept dict as snapshot."""
        snapshot_dict = {"mid_price": 50000.0, "spread_bps": 1.5}
        
        decision_id = await recorder.record(
            symbol="BTCUSDT",
            snapshot=snapshot_dict,
            features=sample_features,
            ctx=sample_context,
            decision="accepted",
        )
        
        record = recorder._batch[0]
        assert record.market_snapshot == snapshot_dict
    
    @pytest.mark.asyncio
    async def test_record_with_dict_features(self, recorder, sample_snapshot, sample_context):
        """record() should accept dict as features."""
        features_dict = {"volatility": 0.02, "trend": 0.5}
        
        decision_id = await recorder.record(
            symbol="BTCUSDT",
            snapshot=sample_snapshot,
            features=features_dict,
            ctx=sample_context,
            decision="accepted",
        )
        
        record = recorder._batch[0]
        assert record.features == features_dict
    
    @pytest.mark.asyncio
    async def test_record_with_none_context(self, recorder, sample_snapshot, sample_features):
        """record() should handle None context gracefully."""
        decision_id = await recorder.record(
            symbol="BTCUSDT",
            snapshot=sample_snapshot,
            features=sample_features,
            ctx=None,
            decision="rejected",
        )
        
        record = recorder._batch[0]
        assert record.positions == []
        assert record.account_state == {}
        assert record.stage_results == []
        assert record.rejection_stage is None
        assert record.signal is None
        assert record.profile_id is None

    @pytest.mark.asyncio
    async def test_record_sanitizes_non_finite_numbers(self, recorder):
        """record() should replace NaN/Inf with None so JSON payloads are DB-safe."""
        snapshot = {"mid_price": float("nan"), "spread_bps": float("inf")}
        features = {"confidence": float("-inf"), "p_long_win": 0.55}
        ctx = MockStageContext(
            data={"account": {"equity": float("nan")}},
            stage_trace=[{"stage": "prediction", "score": float("nan")}],
        )

        await recorder.record(
            symbol="BTCUSDT",
            snapshot=snapshot,
            features=features,
            ctx=ctx,
            decision="rejected",
        )

        record = recorder._batch[0]
        assert record.market_snapshot["mid_price"] is None
        assert record.market_snapshot["spread_bps"] is None
        assert record.features["confidence"] is None
        assert record.account_state["equity"] is None
        assert record.stage_results[0]["score"] is None


class TestDecisionRecorderAutoFlush:
    """Tests for DecisionRecorder auto-flush behavior."""
    
    @pytest.mark.asyncio
    async def test_auto_flush_when_batch_full(self):
        """record() should auto-flush when batch reaches batch_size."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry, batch_size=3)
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        # Record 2 decisions - should not flush
        await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        assert recorder.pending_count == 2
        assert len(pool.connection.executemany_calls) == 0
        
        # Record 3rd decision - should trigger flush
        await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        assert recorder.pending_count == 0
        assert len(pool.connection.executemany_calls) == 1
        
        # Verify 3 records were flushed
        _, args = pool.connection.executemany_calls[0]
        assert len(args) == 3
    
    @pytest.mark.asyncio
    async def test_force_flush_when_buffer_exceeds_max(self):
        """record() should force flush when buffer exceeds max_buffer_size."""
        pool = MockPool()
        registry = MockConfigRegistry()
        # Set batch_size high but max_buffer_size low
        recorder = DecisionRecorder(
            pool, registry, 
            batch_size=100, 
            max_buffer_size=5
        )
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        # Record 4 decisions - should not flush
        for _ in range(4):
            await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        assert recorder.pending_count == 4
        
        # Record 5th decision - should trigger force flush
        await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        assert recorder.pending_count == 0
        assert len(pool.connection.executemany_calls) == 1


class TestDecisionRecorderFlush:
    """Tests for DecisionRecorder._flush() method."""
    
    @pytest.mark.asyncio
    async def test_flush_empty_batch(self):
        """_flush() should handle empty batch gracefully."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        count = await recorder.flush()
        
        assert count == 0
        assert len(pool.connection.executemany_calls) == 0
    
    @pytest.mark.asyncio
    async def test_flush_writes_to_database(self):
        """_flush() should write records to database."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry, batch_size=100)
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        # Record some decisions
        await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        await recorder.record("ETHUSDT", snapshot, features, ctx, "rejected")
        
        # Manually flush
        count = await recorder.flush()
        
        assert count == 2
        assert recorder.pending_count == 0
        assert len(pool.connection.executemany_calls) == 1
        
        query, args = pool.connection.executemany_calls[0]
        assert "INSERT INTO recorded_decisions" in query
        assert len(args) == 2
    
    @pytest.mark.asyncio
    async def test_flush_clears_batch(self):
        """_flush() should clear the batch after successful write."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry, batch_size=100)
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        assert recorder.pending_count == 1
        
        await recorder.flush()
        
        assert recorder.pending_count == 0
    
    @pytest.mark.asyncio
    async def test_flush_updates_last_flush_time(self):
        """_flush() should update last_flush_time."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry, batch_size=100)
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        initial_time = recorder._last_flush_time
        
        await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        await asyncio.sleep(0.01)  # Small delay
        await recorder.flush()
        
        assert recorder._last_flush_time > initial_time


class TestDecisionRecorderErrorHandling:
    """Tests for DecisionRecorder error handling."""
    
    @pytest.mark.asyncio
    async def test_flush_restores_batch_on_failure(self):
        """_flush() should restore batch on database failure."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry, batch_size=100)
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        # Record some decisions
        await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        await recorder.record("ETHUSDT", snapshot, features, ctx, "accepted")
        
        # Make executemany fail
        async def failing_executemany(*args):
            raise Exception("Database error")
        
        pool.connection.executemany = failing_executemany
        
        # Flush should fail and restore batch
        with pytest.raises(Exception) as exc_info:
            await recorder.flush()
        
        assert "Database error" in str(exc_info.value)
        assert recorder.pending_count == 2  # Records restored
    
    @pytest.mark.asyncio
    async def test_flush_respects_max_buffer_on_restore(self):
        """_flush() should respect max_buffer_size when restoring on failure."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(
            pool, registry, 
            batch_size=100, 
            max_buffer_size=3
        )
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        # Record 5 decisions
        for _ in range(5):
            recorder._batch.append(RecordedDecision(
                decision_id=f"dec_{len(recorder._batch)}",
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                config_version="test_v1",
                decision="accepted",
            ))
        
        # Make executemany fail
        async def failing_executemany(*args):
            raise Exception("Database error")
        
        pool.connection.executemany = failing_executemany
        
        # Flush should fail and only restore up to max_buffer_size
        with pytest.raises(Exception):
            await recorder.flush()
        
        # Only 3 records should be restored (max_buffer_size)
        assert recorder.pending_count == 3


class TestDecisionRecorderPeriodicFlush:
    """Tests for DecisionRecorder periodic flush functionality."""
    
    @pytest.mark.asyncio
    async def test_start_periodic_flush(self):
        """start_periodic_flush() should create background task."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry, flush_interval_sec=0.1)
        
        assert recorder._flush_task is None
        
        await recorder.start_periodic_flush()
        
        assert recorder._flush_task is not None
        
        # Cleanup
        await recorder.stop_periodic_flush()
    
    @pytest.mark.asyncio
    async def test_stop_periodic_flush(self):
        """stop_periodic_flush() should cancel task and flush remaining."""
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry, flush_interval_sec=0.1)
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        await recorder.start_periodic_flush()
        await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        
        await recorder.stop_periodic_flush()
        
        assert recorder._flush_task is None
        assert recorder.pending_count == 0  # Should have flushed
    
    @pytest.mark.asyncio
    async def test_context_manager(self):
        """DecisionRecorder should work as async context manager."""
        pool = MockPool()
        registry = MockConfigRegistry()
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        async with DecisionRecorder(
            pool, registry, 
            batch_size=100,
            flush_interval_sec=0.1
        ) as recorder:
            await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
            assert recorder._flush_task is not None
        
        # After exit, task should be stopped and records flushed
        assert recorder._flush_task is None
        assert recorder.pending_count == 0


class TestDecisionRecorderRequirements:
    """Tests verifying requirements compliance."""
    
    @pytest.mark.asyncio
    async def test_requirement_2_1_complete_decision_context(self):
        """Requirement 2.1: Record complete decision context.
        
        WHEN a live trading decision is made THEN the System SHALL record
        the complete decision context including market snapshot, features,
        stage results, and final decision.
        """
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry, batch_size=100)
        
        snapshot = MockMarketSnapshot(
            mid_price=50000.0,
            spread_bps=1.5,
            bid=49999.0,
            ask=50001.0,
        )
        features = MockFeatures(
            volatility=0.02,
            trend=0.5,
        )
        ctx = MockStageContext(
            data={
                "positions": [{"symbol": "BTCUSDT", "size": 0.1}],
                "account": {"equity": 10000.0},
            },
            stage_trace=[
                {"stage": "data_readiness", "passed": True},
                {"stage": "ev_gate", "passed": True, "ev": 0.05},
            ],
            signal={"side": "buy", "size": 0.05},
            profile_id="aggressive",
        )
        
        decision_id = await recorder.record(
            symbol="BTCUSDT",
            snapshot=snapshot,
            features=features,
            ctx=ctx,
            decision="accepted",
        )
        
        record = recorder._batch[0]
        
        # Verify complete context is captured
        assert record.market_snapshot is not None
        assert "mid_price" in record.market_snapshot
        assert record.features is not None
        assert "volatility" in record.features
        assert len(record.stage_results) > 0
        assert record.decision in ("accepted", "rejected", "shadow")
        assert record.config_version is not None
    
    @pytest.mark.asyncio
    async def test_requirement_2_2_batched_writes(self):
        """Requirement 2.2: Store decision records with efficient writes.
        
        THE System SHALL store decision records in TimescaleDB with
        efficient time-range queries (using batched writes).
        """
        pool = MockPool()
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry, batch_size=5)
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        # Record 5 decisions to trigger batch flush
        for i in range(5):
            await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        
        # Verify batch write occurred
        assert len(pool.connection.executemany_calls) == 1
        query, args = pool.connection.executemany_calls[0]
        
        # Verify INSERT query
        assert "INSERT INTO recorded_decisions" in query
        
        # Verify all 5 records were written in single batch
        assert len(args) == 5
    
    @pytest.mark.asyncio
    async def test_configurable_batch_size(self):
        """Verify batch_size is configurable."""
        pool = MockPool()
        registry = MockConfigRegistry()
        
        # Test with batch_size=3
        recorder = DecisionRecorder(pool, registry, batch_size=3)
        assert recorder.batch_size == 3
        
        snapshot = MockMarketSnapshot()
        features = MockFeatures()
        ctx = MockStageContext()
        
        # Record 3 decisions
        for _ in range(3):
            await recorder.record("BTCUSDT", snapshot, features, ctx, "accepted")
        
        # Should have flushed
        assert recorder.pending_count == 0
        assert len(pool.connection.executemany_calls) == 1
    
    @pytest.mark.asyncio
    async def test_configurable_flush_interval(self):
        """Verify flush_interval_sec is configurable."""
        pool = MockPool()
        registry = MockConfigRegistry()
        
        recorder = DecisionRecorder(pool, registry, flush_interval_sec=2.5)
        assert recorder.flush_interval_sec == 2.5


# Additional mock classes for query tests

class MockConnectionWithFetch:
    """Mock database connection with fetch support for testing queries."""
    
    def __init__(self, rows: List[Dict] = None):
        self.executemany_calls = []
        self.fetch_calls = []
        self.fetchrow_calls = []
        self.fetchval_calls = []
        self._rows = rows or []
    
    async def executemany(self, query: str, args: List):
        self.executemany_calls.append((query, args))
    
    async def fetch(self, query: str, *args):
        self.fetch_calls.append((query, args))
        return self._rows
    
    async def fetchrow(self, query: str, *args):
        self.fetchrow_calls.append((query, args))
        return self._rows[0] if self._rows else None
    
    async def fetchval(self, query: str, *args):
        self.fetchval_calls.append((query, args))
        return len(self._rows)


class MockPoolWithFetch:
    """Mock connection pool with fetch support for testing queries."""
    
    def __init__(self, rows: List[Dict] = None):
        self.connection = MockConnectionWithFetch(rows)
    
    def acquire(self):
        return MockPoolContext(self.connection)


def create_mock_db_row(
    decision_id: str = "dec_test123",
    timestamp: datetime = None,
    symbol: str = "BTCUSDT",
    config_version: str = "test_v1",
    decision: str = "accepted",
    rejection_stage: str = None,
    rejection_reason: str = None,
    profile_id: str = None,
) -> Dict:
    """Create a mock database row for testing."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    return {
        "decision_id": decision_id,
        "timestamp": timestamp,
        "symbol": symbol,
        "config_version": config_version,
        "market_snapshot": '{"mid_price": 50000.0}',
        "features": '{"volatility": 0.02}',
        "positions": '[]',
        "account_state": '{}',
        "stage_results": '[]',
        "rejection_stage": rejection_stage,
        "rejection_reason": rejection_reason,
        "decision": decision,
        "signal": None,
        "profile_id": profile_id,
    }


class TestDecisionRecorderQueryByTimeRange:
    """Tests for DecisionRecorder.query_by_time_range() method."""
    
    @pytest.fixture
    def sample_rows(self):
        """Create sample database rows for testing."""
        base_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        return [
            create_mock_db_row(
                decision_id="dec_001",
                timestamp=base_time,
                symbol="BTCUSDT",
                decision="accepted",
            ),
            create_mock_db_row(
                decision_id="dec_002",
                timestamp=base_time,
                symbol="ETHUSDT",
                decision="rejected",
                rejection_stage="ev_gate",
            ),
            create_mock_db_row(
                decision_id="dec_003",
                timestamp=base_time,
                symbol="BTCUSDT",
                decision="rejected",
                rejection_stage="data_readiness",
            ),
        ]
    
    @pytest.mark.asyncio
    async def test_query_basic_time_range(self, sample_rows):
        """query_by_time_range() should query with time range."""
        pool = MockPoolWithFetch(sample_rows)
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        results = await recorder.query_by_time_range(start_time, end_time)
        
        assert len(results) == 3
        assert all(isinstance(r, RecordedDecision) for r in results)
        
        # Verify query was called
        assert len(pool.connection.fetch_calls) == 1
        query, args = pool.connection.fetch_calls[0]
        assert "timestamp >= $1" in query
        assert "timestamp <= $2" in query
        assert args[0] == start_time
        assert args[1] == end_time
    
    @pytest.mark.asyncio
    async def test_query_with_symbol_filter(self, sample_rows):
        """query_by_time_range() should filter by symbol."""
        pool = MockPoolWithFetch(sample_rows)
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        await recorder.query_by_time_range(
            start_time, end_time, symbol="BTCUSDT"
        )
        
        query, args = pool.connection.fetch_calls[0]
        assert "symbol = $3" in query
        assert "BTCUSDT" in args
    
    @pytest.mark.asyncio
    async def test_query_with_decision_filter(self, sample_rows):
        """query_by_time_range() should filter by decision outcome."""
        pool = MockPoolWithFetch(sample_rows)
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        await recorder.query_by_time_range(
            start_time, end_time, decision="rejected"
        )
        
        query, args = pool.connection.fetch_calls[0]
        assert "decision = $3" in query
        assert "rejected" in args
    
    @pytest.mark.asyncio
    async def test_query_with_rejection_stage_filter(self, sample_rows):
        """query_by_time_range() should filter by rejection_stage."""
        pool = MockPoolWithFetch(sample_rows)
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        await recorder.query_by_time_range(
            start_time, end_time, rejection_stage="ev_gate"
        )
        
        query, args = pool.connection.fetch_calls[0]
        assert "rejection_stage = $3" in query
        assert "ev_gate" in args
    
    @pytest.mark.asyncio
    async def test_query_with_all_filters(self, sample_rows):
        """query_by_time_range() should support all filters combined."""
        pool = MockPoolWithFetch(sample_rows)
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        await recorder.query_by_time_range(
            start_time, end_time,
            symbol="BTCUSDT",
            decision="rejected",
            rejection_stage="ev_gate",
        )
        
        query, args = pool.connection.fetch_calls[0]
        assert "symbol = $3" in query
        assert "decision = $4" in query
        assert "rejection_stage = $5" in query
        assert "BTCUSDT" in args
        assert "rejected" in args
        assert "ev_gate" in args
    
    @pytest.mark.asyncio
    async def test_query_with_custom_limit(self, sample_rows):
        """query_by_time_range() should respect limit parameter."""
        pool = MockPoolWithFetch(sample_rows)
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        await recorder.query_by_time_range(
            start_time, end_time, limit=50
        )
        
        query, args = pool.connection.fetch_calls[0]
        assert "LIMIT $3" in query
        assert 50 in args
    
    @pytest.mark.asyncio
    async def test_query_orders_by_timestamp_desc(self, sample_rows):
        """query_by_time_range() should order by timestamp DESC."""
        pool = MockPoolWithFetch(sample_rows)
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        await recorder.query_by_time_range(start_time, end_time)
        
        query, _ = pool.connection.fetch_calls[0]
        assert "ORDER BY timestamp DESC" in query
    
    @pytest.mark.asyncio
    async def test_query_invalid_decision_raises(self):
        """query_by_time_range() should raise ValueError for invalid decision."""
        pool = MockPoolWithFetch([])
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        with pytest.raises(ValueError) as exc_info:
            await recorder.query_by_time_range(
                start_time, end_time, decision="invalid"
            )
        
        assert "decision must be 'accepted', 'rejected', or 'shadow'" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_query_adds_timezone_to_naive_timestamps(self, sample_rows):
        """query_by_time_range() should add UTC timezone to naive timestamps."""
        pool = MockPoolWithFetch(sample_rows)
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        # Naive timestamps (no timezone)
        start_time = datetime(2024, 1, 1)
        end_time = datetime(2024, 1, 31)
        
        await recorder.query_by_time_range(start_time, end_time)
        
        _, args = pool.connection.fetch_calls[0]
        # Verify timezone was added
        assert args[0].tzinfo == timezone.utc
        assert args[1].tzinfo == timezone.utc
    
    @pytest.mark.asyncio
    async def test_query_returns_empty_list_when_no_results(self):
        """query_by_time_range() should return empty list when no results."""
        pool = MockPoolWithFetch([])  # No rows
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        results = await recorder.query_by_time_range(start_time, end_time)
        
        assert results == []


class TestDecisionRecorderCountByTimeRange:
    """Tests for DecisionRecorder.count_by_time_range() method."""
    
    @pytest.mark.asyncio
    async def test_count_basic_time_range(self):
        """count_by_time_range() should count with time range."""
        pool = MockPoolWithFetch([{}, {}, {}])  # 3 rows
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        count = await recorder.count_by_time_range(start_time, end_time)
        
        assert count == 3
        
        # Verify query was called
        assert len(pool.connection.fetchval_calls) == 1
        query, args = pool.connection.fetchval_calls[0]
        assert "SELECT COUNT(*)" in query
        assert "timestamp >= $1" in query
        assert "timestamp <= $2" in query
    
    @pytest.mark.asyncio
    async def test_count_with_symbol_filter(self):
        """count_by_time_range() should filter by symbol."""
        pool = MockPoolWithFetch([{}, {}])
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        await recorder.count_by_time_range(
            start_time, end_time, symbol="BTCUSDT"
        )
        
        query, args = pool.connection.fetchval_calls[0]
        assert "symbol = $3" in query
        assert "BTCUSDT" in args
    
    @pytest.mark.asyncio
    async def test_count_with_decision_filter(self):
        """count_by_time_range() should filter by decision outcome."""
        pool = MockPoolWithFetch([{}])
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        await recorder.count_by_time_range(
            start_time, end_time, decision="accepted"
        )
        
        query, args = pool.connection.fetchval_calls[0]
        assert "decision = $3" in query
        assert "accepted" in args
    
    @pytest.mark.asyncio
    async def test_count_with_rejection_stage_filter(self):
        """count_by_time_range() should filter by rejection_stage."""
        pool = MockPoolWithFetch([{}])
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        await recorder.count_by_time_range(
            start_time, end_time, rejection_stage="ev_gate"
        )
        
        query, args = pool.connection.fetchval_calls[0]
        assert "rejection_stage = $3" in query
        assert "ev_gate" in args
    
    @pytest.mark.asyncio
    async def test_count_with_all_filters(self):
        """count_by_time_range() should support all filters combined."""
        pool = MockPoolWithFetch([{}])
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        await recorder.count_by_time_range(
            start_time, end_time,
            symbol="BTCUSDT",
            decision="rejected",
            rejection_stage="ev_gate",
        )
        
        query, args = pool.connection.fetchval_calls[0]
        assert "symbol = $3" in query
        assert "decision = $4" in query
        assert "rejection_stage = $5" in query
    
    @pytest.mark.asyncio
    async def test_count_invalid_decision_raises(self):
        """count_by_time_range() should raise ValueError for invalid decision."""
        pool = MockPoolWithFetch([])
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        with pytest.raises(ValueError) as exc_info:
            await recorder.count_by_time_range(
                start_time, end_time, decision="invalid"
            )
        
        assert "decision must be 'accepted', 'rejected', or 'shadow'" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_count_returns_zero_when_no_results(self):
        """count_by_time_range() should return 0 when no results."""
        pool = MockPoolWithFetch([])
        # Override fetchval to return None (simulating no results)
        pool.connection._rows = []
        
        async def fetchval_none(query, *args):
            pool.connection.fetchval_calls.append((query, args))
            return None
        
        pool.connection.fetchval = fetchval_none
        
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        count = await recorder.count_by_time_range(start_time, end_time)
        
        assert count == 0


class TestDecisionRecorderGetById:
    """Tests for DecisionRecorder.get_by_id() method."""
    
    @pytest.mark.asyncio
    async def test_get_by_id_found(self):
        """get_by_id() should return RecordedDecision when found."""
        row = create_mock_db_row(
            decision_id="dec_test123",
            symbol="BTCUSDT",
            decision="accepted",
        )
        pool = MockPoolWithFetch([row])
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        result = await recorder.get_by_id("dec_test123")
        
        assert result is not None
        assert isinstance(result, RecordedDecision)
        assert result.decision_id == "dec_test123"
        assert result.symbol == "BTCUSDT"
        assert result.decision == "accepted"
        
        # Verify query was called
        assert len(pool.connection.fetchrow_calls) == 1
        query, args = pool.connection.fetchrow_calls[0]
        assert "decision_id = $1" in query
        assert "dec_test123" in args
    
    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self):
        """get_by_id() should return None when not found."""
        pool = MockPoolWithFetch([])  # No rows
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        result = await recorder.get_by_id("dec_nonexistent")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_by_id_empty_string(self):
        """get_by_id() should return None for empty string."""
        pool = MockPoolWithFetch([])
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        result = await recorder.get_by_id("")
        
        assert result is None
        # Should not have made a database call
        assert len(pool.connection.fetchrow_calls) == 0
    
    @pytest.mark.asyncio
    async def test_get_by_id_with_rejection_details(self):
        """get_by_id() should return decision with rejection details."""
        row = create_mock_db_row(
            decision_id="dec_rejected123",
            symbol="ETHUSDT",
            decision="rejected",
            rejection_stage="ev_gate",
            rejection_reason="EV below threshold",
        )
        pool = MockPoolWithFetch([row])
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        result = await recorder.get_by_id("dec_rejected123")
        
        assert result is not None
        assert result.decision == "rejected"
        assert result.rejection_stage == "ev_gate"
        assert result.rejection_reason == "EV below threshold"


class TestDecisionRecorderQueryRequirements:
    """Tests verifying query requirements compliance."""
    
    @pytest.mark.asyncio
    async def test_requirement_2_4_query_by_time_range(self):
        """Requirement 2.4: Support querying by time range.
        
        THE System SHALL support querying decisions by time range,
        symbol, decision outcome, and rejection stage.
        """
        rows = [
            create_mock_db_row(decision_id="dec_001", symbol="BTCUSDT", decision="accepted"),
            create_mock_db_row(decision_id="dec_002", symbol="ETHUSDT", decision="rejected"),
        ]
        pool = MockPoolWithFetch(rows)
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        # Query by time range only
        results = await recorder.query_by_time_range(start_time, end_time)
        assert len(results) == 2
        
        # Query by time range + symbol
        await recorder.query_by_time_range(start_time, end_time, symbol="BTCUSDT")
        query, _ = pool.connection.fetch_calls[-1]
        assert "symbol" in query
        
        # Query by time range + decision outcome
        await recorder.query_by_time_range(start_time, end_time, decision="accepted")
        query, _ = pool.connection.fetch_calls[-1]
        assert "decision" in query
        
        # Query by time range + rejection stage
        await recorder.query_by_time_range(start_time, end_time, rejection_stage="ev_gate")
        query, _ = pool.connection.fetch_calls[-1]
        assert "rejection_stage" in query
    
    @pytest.mark.asyncio
    async def test_requirement_2_4_query_filters_correctly(self):
        """Requirement 2.4: Query filters should work correctly.
        
        Verify that all filter parameters are properly included in the query.
        """
        pool = MockPoolWithFetch([])
        registry = MockConfigRegistry()
        recorder = DecisionRecorder(pool, registry)
        
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 31, tzinfo=timezone.utc)
        
        # Query with all filters
        await recorder.query_by_time_range(
            start_time, end_time,
            symbol="BTCUSDT",
            decision="rejected",
            rejection_stage="ev_gate",
        )
        
        query, args = pool.connection.fetch_calls[0]
        
        # Verify all filters are in query
        assert "timestamp >= $1" in query
        assert "timestamp <= $2" in query
        assert "symbol = $3" in query
        assert "decision = $4" in query
        assert "rejection_stage = $5" in query
        
        # Verify all filter values are in args
        assert start_time in args
        assert end_time in args
        assert "BTCUSDT" in args
        assert "rejected" in args
        assert "ev_gate" in args
