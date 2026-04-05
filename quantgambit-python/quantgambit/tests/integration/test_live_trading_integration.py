"""Integration tests for live trading pipeline integration.

Feature: trading-pipeline-integration
Requirements: 2.1 - WHEN a live trading decision is made THEN the System SHALL record
              the complete decision context
Requirements: 1.1 - THE System SHALL maintain a single source of truth for all trading
              configuration parameters
Requirements: 4.1 - THE System SHALL support running a shadow pipeline that processes
              live market data through an alternative configuration

Tests for:
- DecisionRecorder captures decisions in live runtime
- ConfigurationRegistry provides consistent configuration
- Shadow mode runs both pipelines and compares decisions
"""

import asyncio
import json
from decimal import Decimal
import pytest
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.integration.decision_recording import DecisionRecorder, RecordedDecision
from quantgambit.execution.manager import PositionSnapshot
from quantgambit.integration.config_registry import ConfigurationRegistry, ConfigurationError
from quantgambit.integration.config_version import ConfigVersion
from quantgambit.integration.shadow_comparison import (
    ShadowComparator,
    ComparisonResult,
    ComparisonMetrics,
)
from quantgambit.tests.fixtures.parity_fixtures import (
    STANDARD_TEST_CONFIG,
    ParityTestFixtures,
    create_test_decision,
    create_test_config,
)


# =============================================================================
# Mock Classes for Testing
# =============================================================================

class MockTimescalePool:
    """Mock asyncpg connection pool for testing."""
    
    def __init__(self):
        self._records: List[tuple] = []
        self._config_versions: Dict[str, ConfigVersion] = {}
        self._active_version_id: Optional[str] = None
    
    def acquire(self):
        """Return async context manager for connection."""
        return MockConnection(self)
    
    def get_records(self) -> List[tuple]:
        """Get all recorded decision tuples."""
        return self._records.copy()
    
    def clear_records(self):
        """Clear all recorded decisions."""
        self._records.clear()


class MockTransaction:
    """Mock asyncpg transaction for testing."""
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockConnection:
    """Mock asyncpg connection for testing."""
    
    def __init__(self, pool: MockTimescalePool):
        self._pool = pool
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
    async def executemany(self, query: str, records: List[tuple]):
        """Store records for verification."""
        self._pool._records.extend(records)
    
    async def execute(self, query: str, *args):
        """Execute a query."""
        pass
    
    async def fetch(self, query: str, *args) -> List[dict]:
        """Fetch records from mock database."""
        return []
    
    async def fetchrow(self, query: str, *args) -> Optional[dict]:
        """Fetch a single row."""
        return None
    
    async def fetchval(self, query: str, *args) -> Any:
        """Fetch a single value."""
        return None
    
    def transaction(self):
        """Return a mock transaction context manager."""
        return MockTransaction()


class MockRedisClient:
    """Mock Redis client for testing."""
    
    def __init__(self):
        self._data: Dict[str, str] = {}
    
    async def get(self, key: str) -> Optional[str]:
        """Get value from mock Redis."""
        return self._data.get(key)
    
    async def set(self, key: str, value: str, **kwargs):
        """Set value in mock Redis."""
        self._data[key] = value
    
    async def delete(self, key: str):
        """Delete key from mock Redis."""
        self._data.pop(key, None)


@dataclass
class MockStageContext:
    """Mock stage context for testing."""
    data: Dict[str, Any]
    rejection_stage: Optional[str] = None
    rejection_reason: Optional[str] = None
    signal: Optional[Dict[str, Any]] = None
    profile_id: Optional[str] = None
    stage_trace: Optional[List[Dict[str, Any]]] = None


@dataclass
class MockDecisionInput:
    """Mock decision input for shadow comparison testing."""
    symbol: str
    timestamp: datetime
    market_snapshot: Dict[str, Any]
    features: Dict[str, Any]


class MockDecisionEngine:
    """Mock decision engine for shadow comparison testing."""
    
    def __init__(
        self,
        default_result: bool = True,
        rejection_stage: Optional[str] = None,
        profile_id: str = "test_profile",
    ):
        self._default_result = default_result
        self._rejection_stage = rejection_stage
        self._profile_id = profile_id
        self._call_count = 0
    
    async def decide_with_context(
        self, decision_input: MockDecisionInput
    ) -> tuple[bool, MockStageContext]:
        """Run mock decision pipeline."""
        self._call_count += 1
        
        ctx = MockStageContext(
            data={"positions": [], "account": {"equity": 100000.0}},
            rejection_stage=self._rejection_stage if not self._default_result else None,
            rejection_reason="Test rejection" if not self._default_result else None,
            signal={"side": "long", "entry_price": 50000.0} if self._default_result else None,
            profile_id=self._profile_id,
            stage_trace=[],
        )
        
        return self._default_result, ctx
    
    @property
    def call_count(self) -> int:
        """Get number of times decide_with_context was called."""
        return self._call_count


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_pool():
    """Create a mock TimescaleDB pool."""
    return MockTimescalePool()


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    return MockRedisClient()


@pytest.fixture
def mock_config_registry(mock_pool, mock_redis):
    """Create a ConfigurationRegistry with mocks."""
    return ConfigurationRegistry(mock_pool, mock_redis)


@pytest.fixture
def mock_decision_recorder(mock_pool, mock_config_registry):
    """Create a DecisionRecorder with mocks."""
    return DecisionRecorder(
        timescale_pool=mock_pool,
        config_registry=mock_config_registry,
        batch_size=10,
        flush_interval_sec=1.0,
    )


@pytest.fixture
def sample_market_snapshot():
    """Create a sample market snapshot for testing."""
    return {
        "price": 50000.0,
        "bid": 49995.0,
        "ask": 50005.0,
        "spread_bps": 2.0,
        "volume_24h": 1000000.0,
        "bid_depth_usd": 500000.0,
        "ask_depth_usd": 500000.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def sample_features():
    """Create sample features for testing."""
    return {
        "ev": 0.002,
        "trend_strength": 0.6,
        "volatility": 0.02,
        "momentum": 0.5,
        "signal_strength": 0.7,
        "regime": "trending",
    }


@pytest.fixture
def sample_stage_context():
    """Create a sample stage context for testing."""
    return MockStageContext(
        data={
            "positions": [{"symbol": "BTCUSDT", "side": "long", "size": 0.1}],
            "account": {"equity": 100000.0, "margin_used": 5000.0},
        },
        rejection_stage=None,
        rejection_reason=None,
        signal={"side": "long", "entry_price": 50000.0, "size": 0.1},
        profile_id="micro_range_mean_reversion",
        stage_trace=[
            {"stage": "DataReadiness", "passed": True},
            {"stage": "EVGate", "passed": True, "ev": 0.002},
        ],
    )


# =============================================================================
# Test: DecisionRecorder Captures Decisions in Live Runtime
# =============================================================================

class TestDecisionRecorderIntegration:
    """Tests that DecisionRecorder captures decisions in live runtime.
    
    Feature: trading-pipeline-integration
    Requirements: 2.1 - WHEN a live trading decision is made THEN the System SHALL
                  record the complete decision context including market snapshot,
                  features, stage results, and final decision
    """
    
    @pytest.mark.asyncio
    async def test_recorder_captures_accepted_decision(
        self,
        mock_decision_recorder,
        sample_market_snapshot,
        sample_features,
        sample_stage_context,
    ):
        """DecisionRecorder should capture accepted decisions with full context."""
        # Record an accepted decision
        decision_id = await mock_decision_recorder.record(
            symbol="BTCUSDT",
            snapshot=sample_market_snapshot,
            features=sample_features,
            ctx=sample_stage_context,
            decision="accepted",
        )
        
        # Verify decision was recorded
        assert decision_id is not None
        assert decision_id.startswith("dec_")
        
        # Verify pending count
        assert mock_decision_recorder.pending_count == 1

    @pytest.mark.asyncio
    async def test_recorder_serializes_position_snapshots(
        self,
        mock_pool,
        mock_config_registry,
        sample_market_snapshot,
        sample_features,
    ):
        """DecisionRecorder should serialize PositionSnapshot payloads."""
        ctx = MockStageContext(
            data={
                "positions": [
                    PositionSnapshot(
                        symbol="BTCUSDT",
                        side="long",
                        size=0.1,
                        entry_price=50000.0,
                        profile_id="micro_range_mean_reversion",
                    )
                ],
                "account": {"equity": 100000.0, "margin_used": 5000.0},
            },
            rejection_stage=None,
            rejection_reason=None,
            signal={"side": "long", "entry_price": 50000.0, "size": 0.1},
            profile_id="micro_range_mean_reversion",
            stage_trace=[],
        )

        recorder = DecisionRecorder(
            timescale_pool=mock_pool,
            config_registry=mock_config_registry,
            batch_size=1,
        )

        await recorder.record(
            symbol="BTCUSDT",
            snapshot=sample_market_snapshot,
            features=sample_features,
            ctx=ctx,
            decision="accepted",
        )

        records = mock_pool.get_records()
        assert len(records) == 1
        positions_json = records[0][6]
        positions = json.loads(positions_json)
        assert positions[0]["symbol"] == "BTCUSDT"
        assert positions[0]["side"] == "long"

    @pytest.mark.asyncio
    async def test_recorder_serializes_decimal_positions(
        self,
        mock_pool,
        mock_config_registry,
        sample_market_snapshot,
        sample_features,
    ):
        ctx = MockStageContext(
            data={
                "positions": [
                    {
                        "symbol": "ETHUSDT",
                        "side": "short",
                        "size": Decimal("1.25"),
                        "entry_price": Decimal("2000.5"),
                    }
                ],
                "account": {"equity": Decimal("100000.0")},
            },
            rejection_stage=None,
            rejection_reason=None,
            signal={"side": "short", "entry_price": 2000.5, "size": 1.25},
            profile_id="micro_range_mean_reversion",
            stage_trace=[],
        )

        recorder = DecisionRecorder(
            timescale_pool=mock_pool,
            config_registry=mock_config_registry,
            batch_size=1,
        )

        await recorder.record(
            symbol="ETHUSDT",
            snapshot=sample_market_snapshot,
            features=sample_features,
            ctx=ctx,
            decision="accepted",
        )

        records = mock_pool.get_records()
        assert len(records) == 1
        positions_json = records[0][6]
        positions = json.loads(positions_json)
        assert positions[0]["symbol"] == "ETHUSDT"
        assert positions[0]["side"] == "short"
        assert positions[0]["size"] == pytest.approx(1.25)
    
    @pytest.mark.asyncio
    async def test_recorder_captures_rejected_decision(
        self,
        mock_decision_recorder,
        sample_market_snapshot,
        sample_features,
    ):
        """DecisionRecorder should capture rejected decisions with rejection details."""
        # Create a rejected context
        rejected_ctx = MockStageContext(
            data={"positions": [], "account": {"equity": 100000.0}},
            rejection_stage="EVGate",
            rejection_reason="EV below threshold",
            signal=None,
            profile_id="micro_range_mean_reversion",
            stage_trace=[
                {"stage": "DataReadiness", "passed": True},
                {"stage": "EVGate", "passed": False, "ev": 0.0008},
            ],
        )
        
        # Record a rejected decision
        decision_id = await mock_decision_recorder.record(
            symbol="BTCUSDT",
            snapshot=sample_market_snapshot,
            features=sample_features,
            ctx=rejected_ctx,
            decision="rejected",
        )
        
        # Verify decision was recorded
        assert decision_id is not None
        assert mock_decision_recorder.pending_count == 1

    
    @pytest.mark.asyncio
    async def test_recorder_batch_flush(
        self,
        mock_pool,
        mock_config_registry,
        sample_market_snapshot,
        sample_features,
        sample_stage_context,
    ):
        """DecisionRecorder should flush batch when batch_size is reached."""
        # Create recorder with small batch size
        recorder = DecisionRecorder(
            timescale_pool=mock_pool,
            config_registry=mock_config_registry,
            batch_size=3,
            flush_interval_sec=60.0,  # Long interval to prevent time-based flush
        )
        
        # Record decisions up to batch size
        for i in range(3):
            await recorder.record(
                symbol="BTCUSDT",
                snapshot=sample_market_snapshot,
                features=sample_features,
                ctx=sample_stage_context,
                decision="accepted",
            )
        
        # Batch should have been flushed
        assert recorder.pending_count == 0
        assert len(mock_pool.get_records()) == 3
    
    @pytest.mark.asyncio
    async def test_recorder_captures_config_version(
        self,
        mock_pool,
        mock_redis,
        sample_market_snapshot,
        sample_features,
        sample_stage_context,
    ):
        """DecisionRecorder should include config version in recorded decisions."""
        # Create config registry with a known config
        config_registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Create recorder
        recorder = DecisionRecorder(
            timescale_pool=mock_pool,
            config_registry=config_registry,
            batch_size=1,  # Flush immediately
        )
        
        # Record a decision
        await recorder.record(
            symbol="BTCUSDT",
            snapshot=sample_market_snapshot,
            features=sample_features,
            ctx=sample_stage_context,
            decision="accepted",
        )
        
        # Verify config version was captured
        records = mock_pool.get_records()
        assert len(records) == 1
        # Config version is at index 3 in the tuple
        config_version = records[0][3]
        assert config_version is not None
        assert config_version.startswith("default_")  # Default config when none exists
    
    @pytest.mark.asyncio
    async def test_recorder_captures_stage_results(
        self,
        mock_pool,
        mock_config_registry,
        sample_market_snapshot,
        sample_features,
    ):
        """DecisionRecorder should capture all pipeline stage results."""
        # Create context with detailed stage trace
        ctx = MockStageContext(
            data={"positions": [], "account": {"equity": 100000.0}},
            rejection_stage=None,
            rejection_reason=None,
            signal={"side": "long", "entry_price": 50000.0},
            profile_id="test_profile",
            stage_trace=[
                {"stage": "DataReadiness", "passed": True, "reason": None},
                {"stage": "GlobalGate", "passed": True, "reason": None},
                {"stage": "EVGate", "passed": True, "ev": 0.002, "threshold": 0.0015},
                {"stage": "ExecutionFeasibility", "passed": True, "reason": None},
            ],
        )
        
        recorder = DecisionRecorder(
            timescale_pool=mock_pool,
            config_registry=mock_config_registry,
            batch_size=1,
        )
        
        await recorder.record(
            symbol="BTCUSDT",
            snapshot=sample_market_snapshot,
            features=sample_features,
            ctx=ctx,
            decision="accepted",
        )
        
        # Verify stage results were captured
        records = mock_pool.get_records()
        assert len(records) == 1
        # Stage results are at index 8 in the tuple (JSON string)
        import json
        stage_results_json = records[0][8]
        stage_results = json.loads(stage_results_json)
        assert len(stage_results) == 4
        assert stage_results[0]["stage"] == "DataReadiness"
        assert stage_results[2]["ev"] == 0.002
    
    @pytest.mark.asyncio
    async def test_recorder_invalid_decision_raises_error(
        self,
        mock_decision_recorder,
        sample_market_snapshot,
        sample_features,
        sample_stage_context,
    ):
        """DecisionRecorder should raise error for invalid decision values."""
        with pytest.raises(ValueError, match="decision must be"):
            await mock_decision_recorder.record(
                symbol="BTCUSDT",
                snapshot=sample_market_snapshot,
                features=sample_features,
                ctx=sample_stage_context,
                decision="invalid_decision",
            )


# =============================================================================
# Test: ConfigurationRegistry Provides Consistent Configuration
# =============================================================================

class TestConfigurationRegistryIntegration:
    """Tests that ConfigurationRegistry provides consistent configuration.
    
    Feature: trading-pipeline-integration
    Requirements: 1.1 - THE System SHALL maintain a single source of truth for all
                  trading configuration parameters including fee models, slippage
                  estimates, entry/exit thresholds, and strategy parameters
    """
    
    @pytest.mark.asyncio
    async def test_registry_returns_consistent_live_config(
        self,
        mock_pool,
        mock_redis,
    ):
        """ConfigurationRegistry should return consistent live config on multiple calls."""
        # Create registry and save a config first
        config_registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Save a config to establish a baseline
        saved_config = await config_registry.create_and_save_config(
            parameters={"fee_bps": 2.0},
            created_by="live",
            set_active=True,
        )
        
        # Get live config multiple times
        config1 = await config_registry.get_live_config()
        config2 = await config_registry.get_live_config()
        
        # Should return consistent config (same parameters and hash)
        # Note: When no config is saved, a new default is created each time
        # After saving, it should return the saved config consistently
        assert config1.config_hash == config2.config_hash
        assert config1.parameters == config2.parameters
    
    @pytest.mark.asyncio
    async def test_registry_backtest_config_inherits_live(
        self,
        mock_pool,
        mock_redis,
    ):
        """Backtest config should inherit from live config when no overrides."""
        config_registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # First get live config to establish baseline
        live_config = await config_registry.get_live_config()
        
        # Get backtest config without overrides
        backtest_config, diff = await config_registry.get_config_for_backtest(
            override_params=None,
            require_parity=False,
        )
        
        # Should have same parameters as live config (even if version_id differs)
        assert backtest_config.parameters == live_config.parameters
        assert backtest_config.config_hash == live_config.config_hash
        assert diff is None
    
    @pytest.mark.asyncio
    async def test_registry_backtest_config_with_overrides(
        self,
        mock_config_registry,
    ):
        """Backtest config should apply overrides correctly."""
        # Get backtest config with overrides
        overrides = {"slippage_bps": 2.0, "custom_param": "test_value"}
        backtest_config, diff = await mock_config_registry.get_config_for_backtest(
            override_params=overrides,
            require_parity=False,
        )
        
        # Should have different version ID
        live_config = await mock_config_registry.get_live_config()
        assert backtest_config.version_id != live_config.version_id
        assert backtest_config.version_id.startswith("backtest_")
        
        # Should have overrides applied
        assert backtest_config.parameters.get("slippage_bps") == 2.0
        assert backtest_config.parameters.get("custom_param") == "test_value"
        
        # Should have diff
        assert diff is not None
    
    @pytest.mark.asyncio
    async def test_registry_config_hash_deterministic(
        self,
        mock_config_registry,
    ):
        """Config hash should be deterministic for same parameters."""
        # Create two configs with same parameters
        params = {"fee_bps": 2.0, "slippage_bps": 1.0}
        
        hash1 = mock_config_registry._hash_params(params)
        hash2 = mock_config_registry._hash_params(params)
        
        assert hash1 == hash2
    
    @pytest.mark.asyncio
    async def test_registry_config_hash_different_for_different_params(
        self,
        mock_config_registry,
    ):
        """Config hash should differ for different parameters."""
        params1 = {"fee_bps": 2.0, "slippage_bps": 1.0}
        params2 = {"fee_bps": 3.0, "slippage_bps": 1.0}
        
        hash1 = mock_config_registry._hash_params(params1)
        hash2 = mock_config_registry._hash_params(params2)
        
        assert hash1 != hash2
    
    @pytest.mark.asyncio
    async def test_registry_compare_configs(
        self,
        mock_config_registry,
    ):
        """ConfigurationRegistry should compare configs correctly."""
        # Create two configs
        config1 = create_test_config(
            version_id="config_v1",
            parameters={"fee_bps": 2.0, "slippage_bps": 1.0},
        )
        config2 = create_test_config(
            version_id="config_v2",
            parameters={"fee_bps": 3.0, "slippage_bps": 1.5},
        )
        
        # Compare configs
        diff = mock_config_registry.compare_configs(config1, config2)
        
        # Should detect differences
        assert diff is not None
        # The diff should contain the changed parameters
        all_diffs = diff.critical_diffs + diff.warning_diffs + diff.info_diffs
        diff_keys = [d[0] for d in all_diffs]
        assert "fee_bps" in diff_keys or any("fee" in k for k in diff_keys)


# =============================================================================
# Test: Shadow Mode Runs Both Pipelines
# =============================================================================

class TestShadowModeIntegration:
    """Tests that shadow mode runs both live and shadow pipelines.
    
    Feature: trading-pipeline-integration
    Requirements: 4.1 - THE System SHALL support running a shadow pipeline that
                  processes live market data through an alternative configuration
    """
    
    @pytest.mark.asyncio
    async def test_shadow_comparator_runs_both_pipelines(self):
        """ShadowComparator should run both live and shadow pipelines."""
        # Create mock engines
        live_engine = MockDecisionEngine(default_result=True, profile_id="live_profile")
        shadow_engine = MockDecisionEngine(default_result=True, profile_id="shadow_profile")
        
        # Create comparator
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=None,
            alert_threshold=0.20,
            window_size=100,
        )
        
        # Create decision input
        decision_input = MockDecisionInput(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            market_snapshot={"price": 50000.0},
            features={"ev": 0.002},
        )
        
        # Run comparison
        result = await comparator.compare(decision_input)
        
        # Both engines should have been called
        assert live_engine.call_count == 1
        assert shadow_engine.call_count == 1
        
        # Result should indicate agreement
        assert result.agrees is True
        assert result.live_decision == "accepted"
        assert result.shadow_decision == "accepted"
    
    @pytest.mark.asyncio
    async def test_shadow_comparator_detects_divergence(self):
        """ShadowComparator should detect when pipelines diverge."""
        # Create engines with different results
        live_engine = MockDecisionEngine(default_result=True, profile_id="live_profile")
        shadow_engine = MockDecisionEngine(
            default_result=False,
            rejection_stage="EVGate",
            profile_id="shadow_profile",
        )
        
        # Create comparator
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=None,
            alert_threshold=0.20,
        )
        
        # Create decision input
        decision_input = MockDecisionInput(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            market_snapshot={"price": 50000.0},
            features={"ev": 0.002},
        )
        
        # Run comparison
        result = await comparator.compare(decision_input)
        
        # Should detect divergence
        assert result.agrees is False
        assert result.live_decision == "accepted"
        assert result.shadow_decision == "rejected"
        assert result.divergence_reason is not None
    
    @pytest.mark.asyncio
    async def test_shadow_comparator_identifies_stage_divergence(self):
        """ShadowComparator should identify divergence reason from stage differences."""
        # Create engines with different rejection stages
        live_engine = MockDecisionEngine(
            default_result=False,
            rejection_stage="EVGate",
            profile_id="live_profile",
        )
        shadow_engine = MockDecisionEngine(
            default_result=False,
            rejection_stage="GlobalGate",
            profile_id="shadow_profile",
        )
        
        # Create comparator
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=None,
        )
        
        # Create decision input
        decision_input = MockDecisionInput(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            market_snapshot={"price": 50000.0},
            features={"ev": 0.002},
        )
        
        # Run comparison
        result = await comparator.compare(decision_input)
        
        # Both rejected but at different stages
        assert result.agrees is True  # Both rejected
        assert result.live_rejection_stage == "EVGate"
        assert result.shadow_rejection_stage == "GlobalGate"
    
    @pytest.mark.asyncio
    async def test_shadow_comparator_computes_agreement_rate(self):
        """ShadowComparator should compute correct agreement rate."""
        # Create engines - live always accepts, shadow alternates
        live_engine = MockDecisionEngine(default_result=True)
        shadow_engine = MockDecisionEngine(default_result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=None,
            window_size=10,
        )
        
        # Run 5 comparisons with agreement
        for i in range(5):
            decision_input = MockDecisionInput(
                symbol="BTCUSDT",
                timestamp=datetime.now(timezone.utc),
                market_snapshot={"price": 50000.0 + i},
                features={"ev": 0.002},
            )
            await comparator.compare(decision_input)
        
        # Check metrics
        metrics = comparator.get_metrics()
        assert metrics.total_comparisons == 5
        assert metrics.agreements == 5
        assert metrics.agreement_rate == 1.0

    
    @pytest.mark.asyncio
    async def test_shadow_comparator_rolling_window(self):
        """ShadowComparator should maintain rolling window of comparisons."""
        live_engine = MockDecisionEngine(default_result=True)
        shadow_engine = MockDecisionEngine(default_result=True)
        
        # Small window size for testing
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=None,
            window_size=5,
        )
        
        # Run more comparisons than window size
        for i in range(10):
            decision_input = MockDecisionInput(
                symbol="BTCUSDT",
                timestamp=datetime.now(timezone.utc),
                market_snapshot={"price": 50000.0 + i},
                features={"ev": 0.002},
            )
            await comparator.compare(decision_input)
        
        # Should only keep window_size comparisons
        assert comparator.comparison_count == 5
        metrics = comparator.get_metrics()
        assert metrics.total_comparisons == 5
    
    @pytest.mark.asyncio
    async def test_shadow_comparator_divergence_by_reason(self):
        """ShadowComparator should track divergence reasons."""
        # Create engines that will diverge
        live_engine = MockDecisionEngine(default_result=True, profile_id="live")
        shadow_engine = MockDecisionEngine(
            default_result=False,
            rejection_stage="EVGate",
            profile_id="shadow",
        )
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=None,
        )
        
        # Run multiple comparisons
        for i in range(5):
            decision_input = MockDecisionInput(
                symbol="BTCUSDT",
                timestamp=datetime.now(timezone.utc),
                market_snapshot={"price": 50000.0 + i},
                features={"ev": 0.002},
            )
            await comparator.compare(decision_input)
        
        # Check divergence tracking
        metrics = comparator.get_metrics()
        assert metrics.disagreements == 5
        assert len(metrics.divergence_by_reason) > 0
    
    @pytest.mark.asyncio
    async def test_shadow_comparator_clear_comparisons(self):
        """ShadowComparator should support clearing comparison history."""
        live_engine = MockDecisionEngine(default_result=True)
        shadow_engine = MockDecisionEngine(default_result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=None,
        )
        
        # Run some comparisons
        for i in range(5):
            decision_input = MockDecisionInput(
                symbol="BTCUSDT",
                timestamp=datetime.now(timezone.utc),
                market_snapshot={"price": 50000.0 + i},
                features={"ev": 0.002},
            )
            await comparator.compare(decision_input)
        
        assert comparator.comparison_count == 5
        
        # Clear comparisons
        comparator.clear_comparisons()
        
        assert comparator.comparison_count == 0
        metrics = comparator.get_metrics()
        assert metrics.total_comparisons == 0


# =============================================================================
# Test: Integration Between Components
# =============================================================================

class TestLiveTradingComponentIntegration:
    """Tests for integration between live trading components.
    
    Feature: trading-pipeline-integration
    Requirements: 2.1, 1.1, 4.1
    """
    
    @pytest.mark.asyncio
    async def test_decision_recorder_with_config_registry(
        self,
        mock_pool,
        mock_redis,
    ):
        """DecisionRecorder should work with ConfigurationRegistry."""
        # Create config registry and save a config
        config_registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Create recorder
        recorder = DecisionRecorder(
            timescale_pool=mock_pool,
            config_registry=config_registry,
            batch_size=1,
        )
        
        # Record a decision
        ctx = MockStageContext(
            data={"positions": [], "account": {"equity": 100000.0}},
            rejection_stage=None,
            signal={"side": "long"},
            profile_id="test",
            stage_trace=[],
        )
        
        decision_id = await recorder.record(
            symbol="BTCUSDT",
            snapshot={"price": 50000.0},
            features={"ev": 0.002},
            ctx=ctx,
            decision="accepted",
        )
        
        # Verify decision was recorded with config version
        records = mock_pool.get_records()
        assert len(records) == 1
        assert records[0][3] is not None  # config_version
    
    @pytest.mark.asyncio
    async def test_shadow_mode_with_decision_recording(
        self,
        mock_pool,
        mock_redis,
    ):
        """Shadow mode should work alongside decision recording."""
        # Create components
        config_registry = ConfigurationRegistry(mock_pool, mock_redis)
        recorder = DecisionRecorder(
            timescale_pool=mock_pool,
            config_registry=config_registry,
            batch_size=10,
        )
        
        live_engine = MockDecisionEngine(default_result=True)
        shadow_engine = MockDecisionEngine(default_result=True)
        
        comparator = ShadowComparator(
            live_engine=live_engine,
            shadow_engine=shadow_engine,
            telemetry=None,
        )
        
        # Simulate live trading with shadow comparison
        decision_input = MockDecisionInput(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            market_snapshot={"price": 50000.0},
            features={"ev": 0.002},
        )
        
        # Run shadow comparison
        comparison_result = await comparator.compare(decision_input)
        
        # Record the live decision
        ctx = MockStageContext(
            data={"positions": [], "account": {"equity": 100000.0}},
            rejection_stage=None,
            signal={"side": "long"},
            profile_id="test",
            stage_trace=[],
        )
        
        await recorder.record(
            symbol="BTCUSDT",
            snapshot=decision_input.market_snapshot,
            features=decision_input.features,
            ctx=ctx,
            decision="accepted",
        )
        
        # Verify both worked
        assert comparison_result.agrees is True
        assert recorder.pending_count == 1

    
    @pytest.mark.asyncio
    async def test_config_parity_enforcement_in_backtest(
        self,
        mock_pool,
        mock_redis,
    ):
        """ConfigurationRegistry should enforce parity when required."""
        config_registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Get backtest config with no overrides - should work
        config, diff = await config_registry.get_config_for_backtest(
            override_params=None,
            require_parity=True,
        )
        assert config is not None
        assert diff is None
        
        # Get backtest config with overrides but parity not required - should work
        config, diff = await config_registry.get_config_for_backtest(
            override_params={"custom_param": "value"},
            require_parity=False,
        )
        assert config is not None
        assert diff is not None


# =============================================================================
# Test: ComparisonResult and ComparisonMetrics
# =============================================================================

class TestComparisonDataStructures:
    """Tests for shadow comparison data structures.
    
    Feature: trading-pipeline-integration
    Requirements: 4.2, 4.3
    """
    
    def test_comparison_result_creation(self):
        """ComparisonResult should be created correctly."""
        result = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="accepted",
        )
        
        assert result.agrees is True
        assert result.symbol == "BTCUSDT"
        assert result.divergence_reason is None
    
    def test_comparison_result_divergence(self):
        """ComparisonResult should detect divergence."""
        result = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="rejected",
            divergence_reason="stage_diff:nonevs EVGate",
        )
        
        assert result.agrees is False
        assert result.divergence_reason is not None
    
    def test_comparison_result_serialization(self):
        """ComparisonResult should serialize to dict correctly."""
        result = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="rejected",
            live_signal={"side": "long"},
            shadow_signal=None,
        )
        
        data = result.to_dict()
        
        assert data["symbol"] == "BTCUSDT"
        assert data["live_decision"] == "accepted"
        assert data["shadow_decision"] == "rejected"
        assert data["agrees"] is False
        assert data["live_signal"] == {"side": "long"}
    
    def test_comparison_metrics_from_comparisons(self):
        """ComparisonMetrics should aggregate comparisons correctly."""
        comparisons = [
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="accepted",
            ),
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="rejected",
                divergence_reason="stage_diff",
            ),
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="rejected",
                shadow_decision="rejected",
            ),
        ]
        
        metrics = ComparisonMetrics.from_comparisons(comparisons)
        
        assert metrics.total_comparisons == 3
        assert metrics.agreements == 2
        assert metrics.disagreements == 1
        assert metrics.agreement_rate == pytest.approx(2/3)
    
    def test_comparison_metrics_empty(self):
        """ComparisonMetrics should handle empty comparisons."""
        metrics = ComparisonMetrics.create_empty()
        
        assert metrics.total_comparisons == 0
        assert metrics.agreements == 0
        assert metrics.disagreements == 0
        assert metrics.agreement_rate == 1.0
    
    def test_comparison_metrics_exceeds_threshold(self):
        """ComparisonMetrics should detect when divergence exceeds threshold."""
        # 50% divergence
        metrics = ComparisonMetrics(
            total_comparisons=10,
            agreements=5,
            disagreements=5,
            agreement_rate=0.5,
        )
        
        assert metrics.exceeds_threshold(0.20) is True  # 50% > 20%
        assert metrics.exceeds_threshold(0.60) is False  # 50% < 60%
    
    def test_comparison_metrics_top_divergence_reasons(self):
        """ComparisonMetrics should return top divergence reasons."""
        metrics = ComparisonMetrics(
            total_comparisons=10,
            agreements=5,
            disagreements=5,
            agreement_rate=0.5,
            divergence_by_reason={
                "stage_diff": 3,
                "profile_diff": 1,
                "unknown": 1,
            },
        )
        
        top_reasons = metrics.top_divergence_reasons(2)
        
        assert len(top_reasons) == 2
        assert top_reasons[0] == ("stage_diff", 3)
        assert top_reasons[1] == ("profile_diff", 1)


# =============================================================================
# Test: Edge Cases and Error Handling
# =============================================================================

class TestEdgeCasesAndErrorHandling:
    """Tests for edge cases and error handling.
    
    Feature: trading-pipeline-integration
    Requirements: 2.1, 1.1, 4.1
    """
    
    @pytest.mark.asyncio
    async def test_recorder_handles_empty_context(
        self,
        mock_decision_recorder,
    ):
        """DecisionRecorder should handle empty/minimal context."""
        # Minimal context
        ctx = MockStageContext(
            data={},
            rejection_stage=None,
            signal=None,
            profile_id=None,
            stage_trace=None,
        )
        
        decision_id = await mock_decision_recorder.record(
            symbol="BTCUSDT",
            snapshot={},
            features={},
            ctx=ctx,
            decision="rejected",
        )
        
        assert decision_id is not None
    
    @pytest.mark.asyncio
    async def test_recorder_handles_none_context(
        self,
        mock_decision_recorder,
    ):
        """DecisionRecorder should handle None context."""
        decision_id = await mock_decision_recorder.record(
            symbol="BTCUSDT",
            snapshot={"price": 50000.0},
            features={"ev": 0.002},
            ctx=None,
            decision="rejected",
        )
        
        assert decision_id is not None
    
    def test_comparison_result_invalid_decision_raises_error(self):
        """ComparisonResult should raise error for invalid decisions."""
        with pytest.raises(ValueError, match="live_decision must be"):
            ComparisonResult(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="invalid",
                shadow_decision="accepted",
                agrees=False,
            )
    
    def test_comparison_result_empty_symbol_raises_error(self):
        """ComparisonResult should raise error for empty symbol."""
        with pytest.raises(ValueError, match="symbol cannot be empty"):
            ComparisonResult(
                timestamp=datetime.now(timezone.utc),
                symbol="",
                live_decision="accepted",
                shadow_decision="accepted",
                agrees=True,
            )
    
    def test_comparison_metrics_negative_values_raise_error(self):
        """ComparisonMetrics should raise error for negative values."""
        with pytest.raises(ValueError, match="cannot be negative"):
            ComparisonMetrics(
                total_comparisons=-1,
                agreements=0,
                disagreements=0,
                agreement_rate=1.0,
            )
    
    def test_comparison_metrics_inconsistent_totals_raise_error(self):
        """ComparisonMetrics should raise error for inconsistent totals."""
        with pytest.raises(ValueError, match="must equal total_comparisons"):
            ComparisonMetrics(
                total_comparisons=10,
                agreements=3,
                disagreements=3,  # 3 + 3 != 10
                agreement_rate=0.3,
            )
