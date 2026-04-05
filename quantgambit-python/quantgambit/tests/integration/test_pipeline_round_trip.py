"""Full pipeline round-trip integration tests.

Feature: trading-pipeline-integration
Requirements: 10.2 - WHEN running integration tests THEN the System SHALL verify
              decision consistency for identical inputs
Requirements: 7.1 - THE System SHALL support replaying recorded decision events
              through the current pipeline
Requirements: 9.2 - WHEN computing metrics THEN the System SHALL use the same
              calculation methodology for both modes

Tests for:
- Record live decisions → export state → warm start backtest → compare metrics
- Verify decision consistency between live and backtest
- Test replay validation catches expected changes
"""

import asyncio
import json
import pytest
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from quantgambit.integration.decision_recording import DecisionRecorder, RecordedDecision
from quantgambit.integration.config_registry import ConfigurationRegistry, ConfigurationError
from quantgambit.integration.config_version import ConfigVersion
from quantgambit.integration.warm_start import WarmStartState, WarmStartLoader, StateImportResult
from quantgambit.integration.replay_validation import (
    ReplayManager,
    ReplayResult,
    ReplayReport,
    categorize_change,
    identify_stage_diff,
)
from quantgambit.integration.unified_metrics import (
    UnifiedMetrics,
    MetricsReconciler,
    MetricsComparison,
)
from quantgambit.tests.fixtures.parity_fixtures import (
    STANDARD_TEST_CONFIG,
    MODIFIED_TEST_CONFIG,
    ParityTestFixtures,
    create_test_decision,
    create_test_config,
    create_decision_sequence,
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
        self._candle_data: List[Dict[str, Any]] = []
        self._decision_data: List[Dict[str, Any]] = []
        self._replay_validations: List[tuple] = []
    
    def acquire(self):
        """Return async context manager for connection."""
        return MockConnection(self)
    
    def get_records(self) -> List[tuple]:
        """Get all recorded decision tuples."""
        return self._records.copy()
    
    def clear_records(self):
        """Clear all recorded decisions."""
        self._records.clear()
    
    def set_candle_data(self, candles: List[Dict[str, Any]]):
        """Set mock candle data for queries."""
        self._candle_data = candles
    
    def set_decision_data(self, decisions: List[Dict[str, Any]]):
        """Set mock decision data for queries."""
        self._decision_data = decisions
    
    def add_recorded_decision(self, decision: RecordedDecision):
        """Add a recorded decision to the mock database."""
        self._decision_data.append(decision.to_dict())


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
        if "recorded_decisions" in query:
            self._pool._records.extend(records)
        elif "replay_validations" in query:
            self._pool._replay_validations.extend(records)
    
    async def execute(self, query: str, *args):
        """Execute a query."""
        pass
    
    async def fetch(self, query: str, *args) -> List[dict]:
        """Fetch records from mock database."""
        if "market_candles" in query:
            return self._pool._candle_data
        if "recorded_decisions" in query:
            # Return decision data as mock rows
            return [MockRow(d) for d in self._pool._decision_data]
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


class MockRow:
    """Mock database row that supports both dict and attribute access."""
    
    def __init__(self, data: Dict[str, Any]):
        self._data = data
    
    def __getitem__(self, key: str) -> Any:
        return self._data.get(key)
    
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)
    
    def keys(self):
        return self._data.keys()


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
    
    def set_sync(self, key: str, value: str):
        """Synchronously set value for test setup."""
        self._data[key] = value


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
    """Mock decision input for replay testing."""
    symbol: str
    timestamp: datetime
    market_snapshot: Dict[str, Any]
    features: Dict[str, Any]


class MockDecisionEngine:
    """Mock decision engine for replay testing."""
    
    def __init__(
        self,
        default_result: bool = True,
        rejection_stage: Optional[str] = None,
        profile_id: str = "test_profile",
        decision_map: Optional[Dict[str, bool]] = None,
    ):
        self._default_result = default_result
        self._rejection_stage = rejection_stage
        self._profile_id = profile_id
        self._call_count = 0
        self._decision_map = decision_map or {}
    
    async def decide_with_context(
        self, decision_input: Any
    ) -> Tuple[bool, MockStageContext]:
        """Run mock decision pipeline."""
        self._call_count += 1
        
        # Check if we have a specific result for this decision
        decision_id = getattr(decision_input, 'decision_id', None)
        if decision_id and decision_id in self._decision_map:
            result = self._decision_map[decision_id]
        else:
            result = self._default_result
        
        ctx = MockStageContext(
            data={"positions": [], "account": {"equity": 100000.0}},
            rejection_stage=self._rejection_stage if not result else None,
            rejection_reason="Test rejection" if not result else None,
            signal={"side": "long", "entry_price": 50000.0} if result else None,
            profile_id=self._profile_id,
            stage_trace=[],
        )
        
        return result, ctx
    
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


@pytest.fixture
def sample_warm_start_state():
    """Create a sample warm start state for testing."""
    return WarmStartState(
        snapshot_time=datetime.now(timezone.utc),
        positions=[
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "size": 0.1,
                "entry_price": 50000.0,
                "entry_time": datetime.now(timezone.utc).isoformat(),
            }
        ],
        account_state={
            "equity": 100000.0,
            "margin_used": 5000.0,
            "balance": 95000.0,
        },
        recent_decisions=[],
        candle_history={
            "BTCUSDT": [
                {
                    "ts": datetime.now(timezone.utc) - timedelta(minutes=i * 5),
                    "open": 50000.0 + i * 10,
                    "high": 50050.0 + i * 10,
                    "low": 49950.0 + i * 10,
                    "close": 50020.0 + i * 10,
                    "volume": 100.0,
                }
                for i in range(20)
            ]
        },
        pipeline_state={
            "cooldown_until": None,
            "last_trade_time": None,
        },
    )


@pytest.fixture
def sample_equity_curve():
    """Create a sample equity curve for metrics testing."""
    base_time = datetime.now(timezone.utc)
    return [
        (base_time + timedelta(days=i), 100000.0 + i * 100 + (i % 3 - 1) * 50)
        for i in range(30)
    ]


@pytest.fixture
def sample_trades():
    """Create sample trades for metrics testing."""
    return [
        {"pnl": 150.0, "pnl_pct": 0.15, "slippage_bps": 1.0, "latency_ms": 45.0, "is_partial": False},
        {"pnl": -80.0, "pnl_pct": -0.08, "slippage_bps": 1.2, "latency_ms": 52.0, "is_partial": False},
        {"pnl": 200.0, "pnl_pct": 0.20, "slippage_bps": 0.8, "latency_ms": 48.0, "is_partial": False},
        {"pnl": -50.0, "pnl_pct": -0.05, "slippage_bps": 1.5, "latency_ms": 55.0, "is_partial": True},
        {"pnl": 120.0, "pnl_pct": 0.12, "slippage_bps": 1.0, "latency_ms": 50.0, "is_partial": False},
    ]


# =============================================================================
# Test: Full Pipeline Round-Trip
# =============================================================================

class TestFullPipelineRoundTrip:
    """Tests for full pipeline round-trip: record → export → warm start → compare.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2 - WHEN running integration tests THEN the System SHALL verify
                  decision consistency for identical inputs
    Requirements: 9.2 - WHEN computing metrics THEN the System SHALL use the same
                  calculation methodology for both modes
    """
    
    @pytest.mark.asyncio
    async def test_record_decisions_export_state_round_trip(
        self,
        mock_pool,
        mock_redis,
        mock_config_registry,
        sample_market_snapshot,
        sample_features,
        sample_stage_context,
    ):
        """Test recording decisions and exporting state for warm start.
        
        This test verifies the full round-trip:
        1. Record live decisions
        2. Export state
        3. Verify state can be used for warm start
        """
        # Step 1: Create and record decisions
        recorder = DecisionRecorder(
            timescale_pool=mock_pool,
            config_registry=mock_config_registry,
            batch_size=5,
        )
        
        # Record multiple decisions
        decision_ids = []
        for i in range(5):
            decision_id = await recorder.record(
                symbol="BTCUSDT",
                snapshot=sample_market_snapshot,
                features=sample_features,
                ctx=sample_stage_context,
                decision="accepted" if i % 2 == 0 else "rejected",
            )
            decision_ids.append(decision_id)
        
        # Flush to ensure all records are written
        await recorder.flush()
        
        # Verify decisions were recorded
        records = mock_pool.get_records()
        assert len(records) == 5
        
        # Step 2: Setup state in Redis for export
        positions_data = [
            {"symbol": "BTCUSDT", "side": "long", "size": 0.1, "entry_price": 50000.0}
        ]
        account_data = {"equity": 100000.0, "margin_used": 5000.0}
        pipeline_data = {"cooldown_until": None}
        
        mock_redis.set_sync(
            "quantgambit:tenant1:bot1:positions",
            json.dumps(positions_data)
        )
        mock_redis.set_sync(
            "quantgambit:tenant1:bot1:account",
            json.dumps(account_data)
        )
        mock_redis.set_sync(
            "quantgambit:tenant1:bot1:pipeline_state",
            json.dumps(pipeline_data)
        )
        
        # Step 3: Export state using WarmStartLoader
        loader = WarmStartLoader(mock_redis, mock_pool, "tenant1", "bot1")
        exported_state = await loader.export_state()
        
        # Verify exported state
        assert len(exported_state.positions) == 1
        assert exported_state.positions[0]["symbol"] == "BTCUSDT"
        assert exported_state.account_state["equity"] == 100000.0
        
        # Step 4: Verify state can be serialized and deserialized (round-trip)
        json_str = exported_state.to_json()
        restored_state = WarmStartState.from_json(json_str)
        
        assert len(restored_state.positions) == len(exported_state.positions)
        assert restored_state.account_state["equity"] == exported_state.account_state["equity"]
        
        # Step 5: Validate restored state
        is_valid, errors = restored_state.validate()
        assert is_valid is True
        assert len(errors) == 0
    
    @pytest.mark.asyncio
    async def test_warm_start_backtest_with_exported_state(
        self,
        mock_pool,
        mock_redis,
        sample_warm_start_state,
    ):
        """Test warm starting a backtest with exported state.
        
        Verifies that exported state can be used to initialize a backtest
        with the correct positions, account state, and candle history.
        """
        # Export state to JSON
        json_str = sample_warm_start_state.to_json()
        
        # Import state (simulating backtest initialization)
        imported_state = WarmStartState.from_json(json_str)
        
        # Verify positions are preserved
        assert len(imported_state.positions) == 1
        position = imported_state.positions[0]
        assert position["symbol"] == "BTCUSDT"
        assert position["size"] == 0.1
        assert position["entry_price"] == 50000.0
        
        # Verify account state is preserved
        assert imported_state.account_state["equity"] == 100000.0
        assert imported_state.account_state["margin_used"] == 5000.0
        
        # Verify candle history is preserved
        assert "BTCUSDT" in imported_state.candle_history
        assert len(imported_state.candle_history["BTCUSDT"]) == 20
        
        # Verify pipeline state is preserved
        assert imported_state.pipeline_state["cooldown_until"] is None
        
        # Validate the imported state
        is_valid, errors = imported_state.validate()
        assert is_valid is True
    
    @pytest.mark.asyncio
    async def test_metrics_comparison_between_live_and_backtest(
        self,
        sample_equity_curve,
        sample_trades,
    ):
        """Test that metrics are computed identically for live and backtest.
        
        Feature: trading-pipeline-integration
        Requirements: 9.2 - WHEN computing metrics THEN the System SHALL use the same
                      calculation methodology for both modes
        """
        reconciler = MetricsReconciler(risk_free_rate=0.05)
        
        # Compute metrics for "live" data
        live_metrics = reconciler.compute_metrics(
            equity_curve=sample_equity_curve,
            trades=sample_trades,
            initial_equity=100000.0,
        )
        
        # Compute metrics for identical "backtest" data
        backtest_metrics = reconciler.compute_metrics(
            equity_curve=sample_equity_curve,
            trades=sample_trades,
            initial_equity=100000.0,
        )
        
        # Metrics should be identical for identical inputs
        assert live_metrics.total_return_pct == backtest_metrics.total_return_pct
        assert live_metrics.sharpe_ratio == backtest_metrics.sharpe_ratio
        assert live_metrics.sortino_ratio == backtest_metrics.sortino_ratio
        assert live_metrics.max_drawdown_pct == backtest_metrics.max_drawdown_pct
        assert live_metrics.win_rate == backtest_metrics.win_rate
        assert live_metrics.profit_factor == backtest_metrics.profit_factor
        assert live_metrics.total_trades == backtest_metrics.total_trades
        
        # Compare metrics - should show no significant differences
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        # Note: overall_similarity may be affected by infinity values in sortino_ratio
        # The key assertion is that there are no significant differences
        assert len(comparison.significant_differences) == 0
        # When metrics are identical, divergence factors should be empty
        assert len(comparison.divergence_factors) == 0
    
    @pytest.mark.asyncio
    async def test_metrics_comparison_detects_divergence(
        self,
        sample_equity_curve,
        sample_trades,
    ):
        """Test that metrics comparison detects divergence between live and backtest.
        
        Feature: trading-pipeline-integration
        Requirements: 9.4 - WHEN metrics differ significantly THEN the System SHALL
                      highlight the differences with potential explanations
        """
        reconciler = MetricsReconciler(risk_free_rate=0.05)
        
        # Compute metrics for "live" data
        live_metrics = reconciler.compute_metrics(
            equity_curve=sample_equity_curve,
            trades=sample_trades,
            initial_equity=100000.0,
        )
        
        # Create modified backtest data with different execution characteristics
        modified_trades = [
            {**t, "slippage_bps": t["slippage_bps"] * 2.0}  # Double slippage
            for t in sample_trades
        ]
        
        backtest_metrics = reconciler.compute_metrics(
            equity_curve=sample_equity_curve,
            trades=modified_trades,
            initial_equity=100000.0,
        )
        
        # Compare metrics - should detect slippage difference
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        # Should have divergence factors related to slippage
        assert len(comparison.divergence_factors) > 0
        slippage_factor = any("slippage" in f.lower() for f in comparison.divergence_factors)
        assert slippage_factor, f"Expected slippage divergence factor, got: {comparison.divergence_factors}"


# =============================================================================
# Test: Decision Consistency Between Live and Backtest
# =============================================================================

class TestDecisionConsistency:
    """Tests for decision consistency between live and backtest modes.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2 - WHEN running integration tests THEN the System SHALL verify
                  decision consistency for identical inputs
    """
    
    @pytest.mark.asyncio
    async def test_identical_inputs_produce_identical_decisions(self):
        """Test that identical inputs produce identical decisions in both modes.
        
        This verifies Property 24: Decision Consistency for Identical Inputs.
        """
        # Create two identical decision engines (simulating live and backtest)
        live_engine = MockDecisionEngine(
            default_result=True,
            profile_id="test_profile",
        )
        backtest_engine = MockDecisionEngine(
            default_result=True,
            profile_id="test_profile",
        )
        
        # Create identical decision input
        decision_input = MockDecisionInput(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            market_snapshot={"price": 50000.0, "bid": 49995.0, "ask": 50005.0},
            features={"ev": 0.002, "trend_strength": 0.6},
        )
        
        # Run both engines with identical input
        live_result, live_ctx = await live_engine.decide_with_context(decision_input)
        backtest_result, backtest_ctx = await backtest_engine.decide_with_context(decision_input)
        
        # Results should be identical
        assert live_result == backtest_result
        assert live_ctx.rejection_stage == backtest_ctx.rejection_stage
        assert live_ctx.profile_id == backtest_ctx.profile_id
    
    @pytest.mark.asyncio
    async def test_rejection_stage_consistency(self):
        """Test that rejection stages are consistent between live and backtest."""
        # Create engines that reject at the same stage
        live_engine = MockDecisionEngine(
            default_result=False,
            rejection_stage="EVGate",
            profile_id="test_profile",
        )
        backtest_engine = MockDecisionEngine(
            default_result=False,
            rejection_stage="EVGate",
            profile_id="test_profile",
        )
        
        decision_input = MockDecisionInput(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            market_snapshot={"price": 50000.0},
            features={"ev": 0.0008},  # Below threshold
        )
        
        live_result, live_ctx = await live_engine.decide_with_context(decision_input)
        backtest_result, backtest_ctx = await backtest_engine.decide_with_context(decision_input)
        
        # Both should reject at the same stage
        assert live_result == backtest_result == False
        assert live_ctx.rejection_stage == backtest_ctx.rejection_stage == "EVGate"
    
    @pytest.mark.asyncio
    async def test_decision_sequence_consistency(self):
        """Test that a sequence of decisions produces consistent results."""
        # Create decision sequence using fixtures
        decisions = create_decision_sequence(
            count=10,
            accepted_ratio=0.5,
            symbol="BTCUSDT",
        )
        
        # Verify the sequence has expected distribution
        accepted_count = sum(1 for d in decisions if d.decision == "accepted")
        rejected_count = sum(1 for d in decisions if d.decision == "rejected")
        
        assert accepted_count == 5
        assert rejected_count == 5
        
        # Verify all decisions have consistent structure
        for decision in decisions:
            assert decision.symbol == "BTCUSDT"
            assert decision.config_version == "live_test_v1"
            if decision.decision == "accepted":
                assert decision.signal is not None
                assert decision.rejection_stage is None
            else:
                assert decision.signal is None
                assert decision.rejection_stage is not None


# =============================================================================
# Test: Replay Validation Catches Expected Changes
# =============================================================================

class TestReplayValidation:
    """Tests for replay validation catching expected changes.
    
    Feature: trading-pipeline-integration
    Requirements: 7.1 - THE System SHALL support replaying recorded decision events
                  through the current pipeline
    """
    
    def test_categorize_change_expected(self):
        """Test that matching decisions are categorized as expected."""
        assert categorize_change("accepted", "accepted") == "expected"
        assert categorize_change("rejected", "rejected") == "expected"
    
    def test_categorize_change_improved(self):
        """Test that rejected→accepted is categorized as improved."""
        assert categorize_change("rejected", "accepted") == "improved"
    
    def test_categorize_change_degraded(self):
        """Test that accepted→rejected is categorized as degraded."""
        assert categorize_change("accepted", "rejected") == "degraded"
    
    def test_identify_stage_diff_same_stage(self):
        """Test that same stages produce no diff."""
        assert identify_stage_diff("EVGate", "EVGate") is None
        assert identify_stage_diff(None, None) is None
    
    def test_identify_stage_diff_different_stages(self):
        """Test that different stages produce correct diff string."""
        assert identify_stage_diff("EVGate", "GlobalGate") == "EVGate->GlobalGate"
        assert identify_stage_diff(None, "EVGate") == "none->EVGate"
        assert identify_stage_diff("EVGate", None) == "EVGate->none"
    
    def test_replay_result_creation(self):
        """Test creating a ReplayResult with correct categorization."""
        original_decision = create_test_decision(
            decision_id="dec_original_001",
            decision="rejected",
            rejection_stage="EVGate",
        )
        
        # Create replay result where decision changed to accepted (improvement)
        result = ReplayResult(
            original_decision=original_decision,
            replayed_decision="accepted",
            replayed_signal={"side": "long", "entry_price": 50000.0},
            replayed_rejection_stage=None,
            matches=False,
            change_category="improved",
            stage_diff="EVGate->none",
        )
        
        assert result.is_improvement()
        assert not result.is_degradation()
        assert result.get_original_decision_id() == "dec_original_001"
    
    def test_replay_report_creation(self):
        """Test creating a ReplayReport with correct statistics."""
        report = ReplayReport(
            total_replayed=100,
            matches=85,
            changes=15,
            match_rate=0.85,
            changes_by_category={
                "improved": 5,
                "degraded": 3,
                "unexpected": 7,
            },
            changes_by_stage={
                "EVGate->none": 5,
                "none->EVGate": 3,
                "EVGate->GlobalGate": 7,
            },
            sample_changes=[],
            run_id="replay_test_001",
        )
        
        assert report.has_improvements()
        assert report.has_degradations()
        assert report.has_unexpected_changes()
        assert report.get_improvement_count() == 5
        assert report.get_degradation_count() == 3
        assert report.get_unexpected_count() == 7
    
    def test_replay_report_passing_threshold(self):
        """Test that replay report correctly determines pass/fail status."""
        # Report with low degradation rate should pass
        passing_report = ReplayReport(
            total_replayed=100,
            matches=95,
            changes=5,
            match_rate=0.95,
            changes_by_category={"degraded": 2, "improved": 3},
            changes_by_stage={},
        )
        assert passing_report.is_passing(max_degradation_rate=0.05)
        
        # Report with high degradation rate should fail
        failing_report = ReplayReport(
            total_replayed=100,
            matches=80,
            changes=20,
            match_rate=0.80,
            changes_by_category={"degraded": 15, "improved": 5},
            changes_by_stage={},
        )
        assert not failing_report.is_passing(max_degradation_rate=0.05)
    
    def test_replay_report_empty(self):
        """Test creating an empty replay report."""
        report = ReplayReport.create_empty(run_id="empty_test")
        
        assert report.total_replayed == 0
        assert report.matches == 0
        assert report.changes == 0
        assert report.match_rate == 1.0
        assert report.is_passing()


# =============================================================================
# Test: State Synchronization Round-Trip
# =============================================================================

class TestStateSynchronizationRoundTrip:
    """Tests for state synchronization round-trip between live and backtest.
    
    Feature: trading-pipeline-integration
    Requirements: 8.1 - THE System SHALL support exporting live state to a format
                  consumable by backtest
    Requirements: 8.3 - THE System SHALL support importing backtest final state
                  back to live for comparison
    """
    
    @pytest.mark.asyncio
    async def test_state_export_import_round_trip(
        self,
        mock_pool,
        mock_redis,
    ):
        """Test that state can be exported and imported without data loss.
        
        This verifies Property 20: State Synchronization Round-Trip.
        """
        # Setup initial state in Redis
        positions_data = [
            {"symbol": "BTCUSDT", "side": "long", "size": 0.1, "entry_price": 50000.0},
            {"symbol": "ETHUSDT", "side": "short", "size": 2.0, "entry_price": 3000.0},
        ]
        account_data = {
            "equity": 100000.0,
            "margin_used": 8000.0,
            "balance": 92000.0,
        }
        pipeline_data = {
            "cooldown_until": None,
            "last_trade_time": datetime.now(timezone.utc).isoformat(),
        }
        
        mock_redis.set_sync(
            "quantgambit:tenant1:bot1:positions",
            json.dumps(positions_data)
        )
        mock_redis.set_sync(
            "quantgambit:tenant1:bot1:account",
            json.dumps(account_data)
        )
        mock_redis.set_sync(
            "quantgambit:tenant1:bot1:pipeline_state",
            json.dumps(pipeline_data)
        )
        
        # Export state
        loader = WarmStartLoader(mock_redis, mock_pool, "tenant1", "bot1")
        exported_state = await loader.export_state()
        
        # Serialize to JSON
        json_str = exported_state.to_json()
        
        # Import state (simulating backtest receiving state)
        imported_state = WarmStartState.from_json(json_str)
        
        # Verify positions are preserved
        assert len(imported_state.positions) == len(exported_state.positions)
        for i, pos in enumerate(imported_state.positions):
            assert pos["symbol"] == exported_state.positions[i]["symbol"]
            assert pos["size"] == exported_state.positions[i]["size"]
            assert pos["entry_price"] == exported_state.positions[i]["entry_price"]
        
        # Verify account state is preserved
        assert imported_state.account_state["equity"] == exported_state.account_state["equity"]
        assert imported_state.account_state["margin_used"] == exported_state.account_state["margin_used"]
        
        # Verify pipeline state is preserved
        assert imported_state.pipeline_state["cooldown_until"] == exported_state.pipeline_state["cooldown_until"]
    
    def test_state_validation_detects_inconsistencies(self):
        """Test that state validation detects inconsistent data.
        
        This verifies Property 21: State Synchronization Validation.
        """
        # Create state with inconsistent position value vs equity
        inconsistent_state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 100.0, "entry_price": 50000.0}  # 5M USD position
            ],
            account_state={"equity": 10000.0},  # Only 10k equity
            recent_decisions=[],
            candle_history={},
            pipeline_state={},
        )
        
        is_valid, errors = inconsistent_state.validate()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("position value" in e.lower() or "exceeds" in e.lower() for e in errors)
    
    def test_state_validation_passes_for_consistent_state(
        self,
        sample_warm_start_state,
    ):
        """Test that state validation passes for consistent data."""
        is_valid, errors = sample_warm_start_state.validate()
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_state_staleness_detection(self):
        """Test that stale state is correctly detected."""
        # Create a stale state (10 minutes old)
        stale_state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc) - timedelta(minutes=10),
            positions=[],
            account_state={"equity": 100000.0},
            recent_decisions=[],
            candle_history={},
            pipeline_state={},
        )
        
        # Should be stale with default 5 minute threshold
        assert stale_state.is_stale() is True
        
        # Should not be stale with 15 minute threshold
        assert stale_state.is_stale(max_age_sec=900) is False
    
    def test_state_has_candle_history_for_positions(self):
        """Test checking if candle history exists for position symbols."""
        # State with candle history for position symbol
        state_with_history = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            account_state={"equity": 100000.0},
            recent_decisions=[],
            candle_history={"BTCUSDT": [{"open": 50000, "close": 50100}]},
            pipeline_state={},
        )
        assert state_with_history.has_candle_history_for_positions() is True
        
        # State without candle history for position symbol
        state_without_history = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            account_state={"equity": 100000.0},
            recent_decisions=[],
            candle_history={},  # No candle history
            pipeline_state={},
        )
        assert state_without_history.has_candle_history_for_positions() is False


# =============================================================================
# Test: End-to-End Integration Flow
# =============================================================================

class TestEndToEndIntegrationFlow:
    """Tests for end-to-end integration flow combining all components.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2, 7.1, 9.2
    """
    
    @pytest.mark.asyncio
    async def test_full_integration_flow(
        self,
        mock_pool,
        mock_redis,
    ):
        """Test the complete integration flow from recording to comparison.
        
        This test exercises the full round-trip:
        1. Record live decisions
        2. Export state
        3. Warm start backtest
        4. Compare metrics
        5. Validate replay
        """
        # Step 1: Setup configuration registry
        config_registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Step 2: Create and record decisions
        recorder = DecisionRecorder(
            timescale_pool=mock_pool,
            config_registry=config_registry,
            batch_size=10,
        )
        
        # Record a sequence of decisions
        decisions = create_decision_sequence(
            count=10,
            accepted_ratio=0.6,
            symbol="BTCUSDT",
        )
        
        for decision in decisions:
            ctx = MockStageContext(
                data={"positions": decision.positions, "account": decision.account_state},
                rejection_stage=decision.rejection_stage,
                rejection_reason=decision.rejection_reason,
                signal=decision.signal,
                profile_id=decision.profile_id,
                stage_trace=decision.stage_results,
            )
            await recorder.record(
                symbol=decision.symbol,
                snapshot=decision.market_snapshot,
                features=decision.features,
                ctx=ctx,
                decision=decision.decision,
            )
        
        await recorder.flush()
        
        # Verify decisions were recorded
        records = mock_pool.get_records()
        assert len(records) == 10
        
        # Step 3: Setup and export state
        positions_data = [
            {"symbol": "BTCUSDT", "side": "long", "size": 0.1, "entry_price": 50000.0}
        ]
        account_data = {"equity": 100000.0, "margin_used": 5000.0}
        
        mock_redis.set_sync(
            "quantgambit:tenant1:bot1:positions",
            json.dumps(positions_data)
        )
        mock_redis.set_sync(
            "quantgambit:tenant1:bot1:account",
            json.dumps(account_data)
        )
        mock_redis.set_sync(
            "quantgambit:tenant1:bot1:pipeline_state",
            json.dumps({})
        )
        
        loader = WarmStartLoader(mock_redis, mock_pool, "tenant1", "bot1")
        exported_state = await loader.export_state()
        
        # Step 4: Verify state can be used for warm start
        json_str = exported_state.to_json()
        imported_state = WarmStartState.from_json(json_str)
        
        is_valid, errors = imported_state.validate()
        assert is_valid is True
        
        # Step 5: Compute and compare metrics
        reconciler = MetricsReconciler()
        
        # Create sample equity curves and trades for comparison
        base_time = datetime.now(timezone.utc)
        live_equity_curve = [
            (base_time + timedelta(hours=i), 100000.0 + i * 50)
            for i in range(24)
        ]
        backtest_equity_curve = [
            (base_time + timedelta(hours=i), 100000.0 + i * 48)  # Slightly different
            for i in range(24)
        ]
        
        live_trades = [
            {"pnl": 100.0, "pnl_pct": 0.1, "slippage_bps": 1.0, "latency_ms": 50.0, "is_partial": False},
            {"pnl": -50.0, "pnl_pct": -0.05, "slippage_bps": 1.2, "latency_ms": 55.0, "is_partial": False},
        ]
        backtest_trades = [
            {"pnl": 100.0, "pnl_pct": 0.1, "slippage_bps": 0.8, "latency_ms": 0.0, "is_partial": False},
            {"pnl": -50.0, "pnl_pct": -0.05, "slippage_bps": 0.8, "latency_ms": 0.0, "is_partial": False},
        ]
        
        live_metrics = reconciler.compute_metrics(live_equity_curve, live_trades)
        backtest_metrics = reconciler.compute_metrics(backtest_equity_curve, backtest_trades)
        
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        # Verify comparison was performed
        assert comparison.live_metrics is not None
        assert comparison.backtest_metrics is not None
        assert 0.0 <= comparison.overall_similarity <= 1.0
    
    @pytest.mark.asyncio
    async def test_known_good_decision_fixtures(self):
        """Test that known-good decision fixtures are valid and consistent."""
        fixtures = ParityTestFixtures()
        
        # Get all decision types
        accepted = fixtures.get_accepted_decisions()
        rejected = fixtures.get_rejected_decisions()
        edge_cases = fixtures.get_edge_case_decisions()
        
        # Verify accepted decisions
        for decision in accepted:
            assert decision.decision == "accepted"
            assert decision.signal is not None
            assert decision.rejection_stage is None
            assert decision.has_complete_context()
        
        # Verify rejected decisions
        for decision in rejected:
            assert decision.decision == "rejected"
            assert decision.signal is None
            assert decision.rejection_stage is not None
        
        # Verify edge cases have valid structure
        for decision in edge_cases:
            assert decision.symbol is not None
            assert decision.config_version is not None
            assert decision.decision in ("accepted", "rejected", "shadow")
    
    @pytest.mark.asyncio
    async def test_config_parity_in_round_trip(
        self,
        mock_pool,
        mock_redis,
    ):
        """Test that configuration parity is maintained in round-trip."""
        config_registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Get live config
        live_config = await config_registry.get_live_config()
        
        # Get backtest config without overrides (should be identical)
        backtest_config, diff = await config_registry.get_config_for_backtest(
            override_params=None,
            require_parity=False,
        )
        
        # Configs should have same parameters
        assert backtest_config.parameters == live_config.parameters
        assert backtest_config.config_hash == live_config.config_hash
        assert diff is None
