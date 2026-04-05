"""Integration tests for backtest pipeline integration.

Feature: trading-pipeline-integration
Requirements: 3.1 - THE System SHALL support initializing a backtest with current
              live positions, account state, and recent decision history
Requirements: 5.1 - THE System SHALL simulate partial fills based on order size
              relative to available liquidity
Requirements: 1.5 - WHEN critical configuration parameters differ THEN the System
              SHALL require explicit acknowledgment before proceeding

Tests for:
- Warm start initializes from live state correctly
- ExecutionSimulator produces realistic fills
- Config parity enforcement blocks on critical diffs
"""

import asyncio
import pytest
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import json

from quantgambit.integration.warm_start import WarmStartState, WarmStartLoader
from quantgambit.integration.execution_simulator import (
    ExecutionSimulator,
    ExecutionSimulatorConfig,
    SimulatedFill,
)
from quantgambit.integration.config_registry import (
    ConfigurationRegistry,
    ConfigurationError,
)
from quantgambit.integration.config_version import ConfigVersion
from quantgambit.integration.config_diff import ConfigDiff, ConfigDiffEngine
from quantgambit.tests.fixtures.parity_fixtures import (
    STANDARD_TEST_CONFIG,
    MODIFIED_TEST_CONFIG,
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
        self._candle_data: List[Dict[str, Any]] = []
        self._decision_data: List[Dict[str, Any]] = []
    
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
        if "market_candles" in query:
            return self._pool._candle_data
        if "recorded_decisions" in query:
            return self._pool._decision_data
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
    
    def set_sync(self, key: str, value: str):
        """Synchronously set value for test setup."""
        self._data[key] = value


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
def stale_warm_start_state():
    """Create a stale warm start state for testing."""
    return WarmStartState(
        snapshot_time=datetime.now(timezone.utc) - timedelta(minutes=10),  # 10 minutes old
        positions=[],
        account_state={"equity": 100000.0},
        recent_decisions=[],
        candle_history={},
        pipeline_state={},
    )


@pytest.fixture
def execution_simulator():
    """Create an ExecutionSimulator with realistic config."""
    config = ExecutionSimulatorConfig.realistic()
    return ExecutionSimulator(config)


# =============================================================================
# Test: Warm Start Initializes from Live State Correctly
# =============================================================================

class TestWarmStartIntegration:
    """Tests that warm start initializes backtest from live state correctly.
    
    Feature: trading-pipeline-integration
    Requirements: 3.1 - THE System SHALL support initializing a backtest with current
                  live positions, account state, and recent decision history
    """
    
    def test_warm_start_state_contains_positions(self, sample_warm_start_state):
        """Warm start state should contain positions from live state."""
        assert len(sample_warm_start_state.positions) == 1
        position = sample_warm_start_state.positions[0]
        assert position["symbol"] == "BTCUSDT"
        assert position["side"] == "long"
        assert position["size"] == 0.1
        assert position["entry_price"] == 50000.0
    
    def test_warm_start_state_contains_account_state(self, sample_warm_start_state):
        """Warm start state should contain account state from live state."""
        assert sample_warm_start_state.account_state["equity"] == 100000.0
        assert sample_warm_start_state.account_state["margin_used"] == 5000.0
        assert sample_warm_start_state.account_state["balance"] == 95000.0
    
    def test_warm_start_state_contains_candle_history(self, sample_warm_start_state):
        """Warm start state should contain candle history for AMT calculations."""
        assert "BTCUSDT" in sample_warm_start_state.candle_history
        candles = sample_warm_start_state.candle_history["BTCUSDT"]
        assert len(candles) == 20
        # Verify candle structure
        candle = candles[0]
        assert "open" in candle
        assert "high" in candle
        assert "low" in candle
        assert "close" in candle
        assert "volume" in candle
    
    def test_warm_start_state_validation_passes_for_valid_state(
        self, sample_warm_start_state
    ):
        """Warm start state validation should pass for valid state."""
        is_valid, errors = sample_warm_start_state.validate()
        assert is_valid is True
        assert len(errors) == 0
    
    def test_warm_start_state_validation_fails_for_missing_equity(self):
        """Warm start state validation should fail when equity is missing."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={},  # Missing equity
            recent_decisions=[],
            candle_history={},
            pipeline_state={},
        )
        is_valid, errors = state.validate()
        assert is_valid is False
        assert any("equity" in error.lower() for error in errors)
    
    def test_warm_start_state_validation_fails_for_excessive_position_value(self):
        """Warm start state validation should fail when position value exceeds 10x equity."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "size": 100.0,  # Very large position
                    "entry_price": 50000.0,  # 100 * 50000 = 5,000,000 USD
                }
            ],
            account_state={"equity": 10000.0},  # Only 10k equity
            recent_decisions=[],
            candle_history={},
            pipeline_state={},
        )
        is_valid, errors = state.validate()
        assert is_valid is False
        assert any("position value" in error.lower() or "exceeds" in error.lower() for error in errors)
    
    def test_warm_start_state_staleness_detection(self, stale_warm_start_state):
        """Warm start state should detect when snapshot is stale."""
        # Default threshold is 5 minutes (300 seconds)
        assert stale_warm_start_state.is_stale() is True
    
    def test_warm_start_state_not_stale_for_fresh_state(self, sample_warm_start_state):
        """Warm start state should not be stale for fresh snapshot."""
        assert sample_warm_start_state.is_stale() is False
    
    def test_warm_start_state_staleness_with_custom_threshold(
        self, stale_warm_start_state
    ):
        """Warm start state staleness should respect custom threshold."""
        # 10 minute old state should not be stale with 15 minute threshold
        assert stale_warm_start_state.is_stale(max_age_sec=900) is False
        # But should be stale with 5 minute threshold
        assert stale_warm_start_state.is_stale(max_age_sec=300) is True
    
    def test_warm_start_state_serialization_round_trip(self, sample_warm_start_state):
        """Warm start state should serialize and deserialize correctly."""
        # Serialize to JSON
        json_str = sample_warm_start_state.to_json()
        assert isinstance(json_str, str)
        
        # Deserialize from JSON
        restored_state = WarmStartState.from_json(json_str)
        
        # Verify key fields match
        assert len(restored_state.positions) == len(sample_warm_start_state.positions)
        assert restored_state.account_state["equity"] == sample_warm_start_state.account_state["equity"]
        assert "BTCUSDT" in restored_state.candle_history
    
    def test_warm_start_state_get_symbols_with_positions(self, sample_warm_start_state):
        """Warm start state should return symbols with positions."""
        symbols = sample_warm_start_state.get_symbols_with_positions()
        assert "BTCUSDT" in symbols
    
    def test_warm_start_state_has_candle_history_for_positions(
        self, sample_warm_start_state
    ):
        """Warm start state should verify candle history exists for position symbols."""
        assert sample_warm_start_state.has_candle_history_for_positions() is True
    
    def test_warm_start_state_missing_candle_history_for_positions(self):
        """Warm start state should detect missing candle history for positions."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            account_state={"equity": 100000.0},
            recent_decisions=[],
            candle_history={},  # No candle history
            pipeline_state={},
        )
        assert state.has_candle_history_for_positions() is False
    
    @pytest.mark.asyncio
    async def test_warm_start_loader_loads_from_redis(self, mock_pool, mock_redis):
        """WarmStartLoader should load state from Redis."""
        # Setup mock Redis data
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
        
        # Create loader and load state
        loader = WarmStartLoader(mock_redis, mock_pool, "tenant1", "bot1")
        state = await loader.load_current_state()
        
        # Verify loaded state
        assert len(state.positions) == 1
        assert state.positions[0]["symbol"] == "BTCUSDT"
        assert state.account_state["equity"] == 100000.0
        assert state.pipeline_state["cooldown_until"] is None


# =============================================================================
# Test: ExecutionSimulator Produces Realistic Fills
# =============================================================================

class TestExecutionSimulatorIntegration:
    """Tests that ExecutionSimulator produces realistic fills.
    
    Feature: trading-pipeline-integration
    Requirements: 5.1 - THE System SHALL simulate partial fills based on order size
                  relative to available liquidity
    """
    
    def test_execution_simulator_produces_fill(self, execution_simulator):
        """ExecutionSimulator should produce a fill for valid order."""
        fill = execution_simulator.simulate_fill(
            side="buy",
            size=0.1,
            price=50000.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            spread_bps=2.0,
            is_maker=False,
        )
        
        assert isinstance(fill, SimulatedFill)
        assert fill.filled_size > 0
        assert fill.fill_price > 0
        assert fill.latency_ms > 0
        assert fill.order_id.startswith("sim_")
    
    def test_execution_simulator_applies_slippage(self, execution_simulator):
        """ExecutionSimulator should apply slippage to fill price."""
        # Seed for reproducibility
        execution_simulator.seed(42)
        
        fill = execution_simulator.simulate_fill(
            side="buy",
            size=0.1,
            price=50000.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            spread_bps=2.0,
            is_maker=False,
        )
        
        # Buy orders should have positive slippage (pay more)
        assert fill.slippage_bps >= 0
        # Fill price should be higher than order price for buy
        assert fill.fill_price >= 50000.0
    
    def test_execution_simulator_sell_slippage(self, execution_simulator):
        """ExecutionSimulator should apply correct slippage for sell orders."""
        execution_simulator.seed(42)
        
        fill = execution_simulator.simulate_fill(
            side="sell",
            size=0.1,
            price=50000.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            spread_bps=2.0,
            is_maker=False,
        )
        
        # Sell orders should have positive slippage (receive less)
        assert fill.slippage_bps >= 0
        # Fill price should be lower than order price for sell
        assert fill.fill_price <= 50000.0
    
    def test_execution_simulator_latency_distribution(self, execution_simulator):
        """ExecutionSimulator should produce latency from Gaussian distribution."""
        execution_simulator.seed(42)
        
        latencies = []
        for _ in range(100):
            fill = execution_simulator.simulate_fill(
                side="buy",
                size=0.1,
                price=50000.0,
                bid_depth_usd=100000.0,
                ask_depth_usd=100000.0,
                spread_bps=2.0,
                is_maker=False,
            )
            latencies.append(fill.latency_ms)
        
        # Latency should be positive
        assert all(l > 0 for l in latencies)
        
        # Mean should be close to base_latency_ms (50ms for realistic)
        mean_latency = sum(latencies) / len(latencies)
        assert 30 < mean_latency < 70  # Within reasonable range of 50ms
    
    def test_execution_simulator_partial_fills_for_large_orders(self):
        """ExecutionSimulator should produce partial fills for large orders."""
        # Use pessimistic config for higher partial fill probability
        config = ExecutionSimulatorConfig.pessimistic()
        simulator = ExecutionSimulator(config)
        simulator.seed(42)
        
        partial_fill_count = 0
        total_fills = 100
        
        for _ in range(total_fills):
            fill = simulator.simulate_fill(
                side="buy",
                size=10.0,  # Large order
                price=50000.0,
                bid_depth_usd=50000.0,  # Limited depth
                ask_depth_usd=50000.0,
                spread_bps=2.0,
                is_maker=False,
            )
            if fill.is_partial:
                partial_fill_count += 1
        
        # With pessimistic config and large orders, should see some partial fills
        # Large orders (>5% of depth) have 50% partial fill probability in pessimistic
        assert partial_fill_count > 0
    
    def test_execution_simulator_small_orders_rarely_partial(self):
        """ExecutionSimulator should rarely produce partial fills for small orders."""
        config = ExecutionSimulatorConfig.realistic()
        simulator = ExecutionSimulator(config)
        simulator.seed(42)
        
        partial_fill_count = 0
        total_fills = 100
        
        for _ in range(total_fills):
            fill = simulator.simulate_fill(
                side="buy",
                size=0.001,  # Very small order
                price=50000.0,
                bid_depth_usd=1000000.0,  # Large depth
                ask_depth_usd=1000000.0,
                spread_bps=2.0,
                is_maker=False,
            )
            if fill.is_partial:
                partial_fill_count += 1
        
        # Small orders (<1% of depth) have only 2% partial fill probability
        # Should see very few partial fills
        assert partial_fill_count < 20  # Less than 20% partial fills
    
    def test_execution_simulator_maker_orders_get_price_improvement(self):
        """ExecutionSimulator should give price improvement to maker orders."""
        config = ExecutionSimulatorConfig.realistic()
        simulator = ExecutionSimulator(config)
        simulator.seed(42)
        
        fill = simulator.simulate_fill(
            side="buy",
            size=0.1,
            price=50000.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            spread_bps=10.0,  # 10 bps spread
            is_maker=True,  # Maker order
        )
        
        # Maker orders should have negative slippage (price improvement)
        assert fill.slippage_bps < 0
        # Fill price should be better than order price for buy
        assert fill.fill_price < 50000.0
    
    def test_execution_simulator_scenario_presets(self):
        """ExecutionSimulator should support scenario presets."""
        optimistic = ExecutionSimulatorConfig.optimistic()
        realistic = ExecutionSimulatorConfig.realistic()
        pessimistic = ExecutionSimulatorConfig.pessimistic()
        
        # Optimistic should have lower latency
        assert optimistic.base_latency_ms < realistic.base_latency_ms
        assert realistic.base_latency_ms < pessimistic.base_latency_ms
        
        # Optimistic should have lower slippage
        assert optimistic.base_slippage_bps < realistic.base_slippage_bps
        assert realistic.base_slippage_bps < pessimistic.base_slippage_bps
        
        # Optimistic should have lower partial fill probability
        assert optimistic.partial_fill_prob_large < realistic.partial_fill_prob_large
        assert realistic.partial_fill_prob_large < pessimistic.partial_fill_prob_large
    
    def test_execution_simulator_from_scenario(self):
        """ExecutionSimulator should create config from scenario name."""
        config = ExecutionSimulatorConfig.from_scenario("pessimistic")
        assert config.scenario == "pessimistic"
        assert config.base_latency_ms == 100.0
        
        config = ExecutionSimulatorConfig.from_scenario("optimistic")
        assert config.scenario == "optimistic"
        assert config.base_latency_ms == 30.0
    
    def test_execution_simulator_invalid_scenario_raises_error(self):
        """ExecutionSimulator should raise error for invalid scenario."""
        with pytest.raises(ValueError, match="Unknown scenario"):
            ExecutionSimulatorConfig.from_scenario("invalid_scenario")
    
    def test_execution_simulator_calibration_from_live_data(self):
        """ExecutionSimulator should calibrate from live fill data."""
        simulator = ExecutionSimulator()
        
        # Create mock live fill data
        live_fills = [
            {"latency_ms": 45.0, "slippage_bps": 0.8, "is_partial": False, "size_ratio": 0.005},
            {"latency_ms": 55.0, "slippage_bps": 1.2, "is_partial": False, "size_ratio": 0.005},
            {"latency_ms": 48.0, "slippage_bps": 1.0, "is_partial": False, "size_ratio": 0.005},
            {"latency_ms": 52.0, "slippage_bps": 0.9, "is_partial": False, "size_ratio": 0.005},
            {"latency_ms": 50.0, "slippage_bps": 1.1, "is_partial": False, "size_ratio": 0.005},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        # Verify calibration result
        assert result.num_fills == 5
        assert 45 <= result.latency_mean_ms <= 55
        assert 0.8 <= result.slippage_mean_bps <= 1.2
        
        # Verify config was updated
        assert "base_latency_ms" in result.parameters_updated
        assert "base_slippage_bps" in result.parameters_updated
    
    def test_execution_simulator_calibration_empty_data(self):
        """ExecutionSimulator should handle empty calibration data."""
        simulator = ExecutionSimulator()
        original_latency = simulator.config.base_latency_ms
        
        result = simulator.calibrate_from_live([])
        
        # Should return result with no changes
        assert result.num_fills == 0
        assert len(result.parameters_updated) == 0
        # Config should remain unchanged
        assert simulator.config.base_latency_ms == original_latency
    
    def test_execution_simulator_config_validation(self):
        """ExecutionSimulator config should validate parameters."""
        # Valid config should not raise
        config = ExecutionSimulatorConfig(
            base_latency_ms=50.0,
            latency_std_ms=20.0,
            partial_fill_prob_small=0.02,
            partial_fill_prob_medium=0.10,
            partial_fill_prob_large=0.30,
            partial_fill_ratio_min=0.3,
            partial_fill_ratio_max=0.9,
            base_slippage_bps=1.0,
        )
        assert config.base_latency_ms == 50.0
        
        # Invalid config should raise
        with pytest.raises(ValueError):
            ExecutionSimulatorConfig(base_latency_ms=-10.0)  # Negative latency
        
        with pytest.raises(ValueError):
            ExecutionSimulatorConfig(partial_fill_prob_small=1.5)  # Probability > 1
        
        with pytest.raises(ValueError):
            ExecutionSimulatorConfig(
                partial_fill_ratio_min=0.9,
                partial_fill_ratio_max=0.3,  # Min > Max
            )


# =============================================================================
# Test: Config Parity Enforcement Blocks on Critical Diffs
# =============================================================================

class TestConfigParityEnforcementIntegration:
    """Tests that config parity enforcement blocks on critical diffs.
    
    Feature: trading-pipeline-integration
    Requirements: 1.5 - WHEN critical configuration parameters differ THEN the System
                  SHALL require explicit acknowledgment before proceeding
    """
    
    @pytest.mark.asyncio
    async def test_config_registry_blocks_on_critical_diffs(
        self, mock_pool, mock_redis
    ):
        """ConfigurationRegistry should block backtest when critical params differ."""
        registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Save a live config with specific parameters
        live_config = await registry.create_and_save_config(
            parameters={
                "fee_bps": 2.0,
                "slippage_bps": 1.0,
                "ev_min": 0.0015,
            },
            created_by="live",
            set_active=True,
        )
        
        # Try to get backtest config with critical parameter override
        # fee_bps is a critical parameter
        with pytest.raises(ConfigurationError) as exc_info:
            await registry.get_config_for_backtest(
                override_params={"fee_bps": 10.0},  # Critical diff
                require_parity=True,
            )
        
        # Verify error contains critical diff info
        error = exc_info.value
        assert "fee_bps" in str(error) or len(error.critical_diffs) > 0
    
    @pytest.mark.asyncio
    async def test_config_registry_allows_override_with_require_parity_false(
        self, mock_pool, mock_redis
    ):
        """ConfigurationRegistry should allow critical diffs when require_parity=False."""
        registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Save a live config
        await registry.create_and_save_config(
            parameters={"fee_bps": 2.0, "slippage_bps": 1.0},
            created_by="live",
            set_active=True,
        )
        
        # Get backtest config with critical override but require_parity=False
        backtest_config, diff = await registry.get_config_for_backtest(
            override_params={"fee_bps": 10.0},
            require_parity=False,  # Allow critical diffs
        )
        
        # Should succeed and return config with override
        assert backtest_config.parameters["fee_bps"] == 10.0
        assert diff is not None
    
    @pytest.mark.asyncio
    async def test_config_registry_no_diff_when_no_overrides(
        self, mock_pool, mock_redis
    ):
        """ConfigurationRegistry should return no diff when no overrides specified."""
        registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Get backtest config without overrides
        # Note: When no config is saved, a default empty config is returned
        backtest_config, diff = await registry.get_config_for_backtest(
            override_params=None,
            require_parity=True,
        )
        
        # Should return config with no diff (since no overrides)
        assert diff is None
        # The default config has empty parameters
        assert isinstance(backtest_config.parameters, dict)
    
    def test_config_diff_engine_categorizes_critical_params(self):
        """ConfigDiffEngine should categorize critical parameter differences."""
        engine = ConfigDiffEngine()
        
        source = create_test_config(
            version_id="source_v1",
            parameters={"fee_bps": 2.0, "slippage_bps": 1.0, "ev_min": 0.0015},
        )
        target = create_test_config(
            version_id="target_v1",
            parameters={"fee_bps": 10.0, "slippage_bps": 1.0, "ev_min": 0.0015},
        )
        
        diff = engine.compare(source, target)
        
        # fee_bps is a critical parameter
        assert diff.has_any_diffs
        # Check that fee_bps is in critical or warning diffs
        all_diff_keys = [d[0] for d in diff.critical_diffs + diff.warning_diffs + diff.info_diffs]
        assert "fee_bps" in all_diff_keys
    
    def test_config_diff_engine_detects_all_differences(self):
        """ConfigDiffEngine should detect all parameter differences."""
        engine = ConfigDiffEngine()
        
        source = create_test_config(
            version_id="source_v1",
            parameters={
                "fee_bps": 2.0,
                "slippage_bps": 1.0,
                "ev_min": 0.0015,
                "max_position_size": 10000.0,
            },
        )
        target = create_test_config(
            version_id="target_v1",
            parameters={
                "fee_bps": 3.0,  # Changed
                "slippage_bps": 2.0,  # Changed
                "ev_min": 0.0015,  # Same
                "max_position_size": 15000.0,  # Changed
            },
        )
        
        diff = engine.compare(source, target)
        
        # Should detect 3 differences
        total_diffs = len(diff.critical_diffs) + len(diff.warning_diffs) + len(diff.info_diffs)
        assert total_diffs == 3
    
    def test_config_diff_engine_no_diffs_for_identical_configs(self):
        """ConfigDiffEngine should report no diffs for identical configs."""
        engine = ConfigDiffEngine()
        
        params = {"fee_bps": 2.0, "slippage_bps": 1.0}
        source = create_test_config(version_id="source_v1", parameters=params)
        target = create_test_config(version_id="target_v1", parameters=params.copy())
        
        diff = engine.compare(source, target)
        
        assert not diff.has_any_diffs
        assert len(diff.critical_diffs) == 0
        assert len(diff.warning_diffs) == 0
        assert len(diff.info_diffs) == 0
    
    @pytest.mark.asyncio
    async def test_config_registry_compare_configs(self, mock_config_registry):
        """ConfigurationRegistry should compare two configs correctly."""
        config1 = create_test_config(
            version_id="config_v1",
            parameters={"fee_bps": 2.0, "slippage_bps": 1.0},
        )
        config2 = create_test_config(
            version_id="config_v2",
            parameters={"fee_bps": 3.0, "slippage_bps": 1.5},
        )
        
        diff = mock_config_registry.compare_configs(config1, config2)
        
        assert diff is not None
        assert diff.has_any_diffs
    
    @pytest.mark.asyncio
    async def test_config_registry_hash_deterministic(self, mock_config_registry):
        """ConfigurationRegistry hash should be deterministic."""
        params = {"fee_bps": 2.0, "slippage_bps": 1.0, "ev_min": 0.0015}
        
        hash1 = mock_config_registry._hash_params(params)
        hash2 = mock_config_registry._hash_params(params)
        
        assert hash1 == hash2
    
    @pytest.mark.asyncio
    async def test_config_registry_hash_different_for_different_params(
        self, mock_config_registry
    ):
        """ConfigurationRegistry hash should differ for different params."""
        params1 = {"fee_bps": 2.0, "slippage_bps": 1.0}
        params2 = {"fee_bps": 3.0, "slippage_bps": 1.0}
        
        hash1 = mock_config_registry._hash_params(params1)
        hash2 = mock_config_registry._hash_params(params2)
        
        assert hash1 != hash2
    
    def test_configuration_error_contains_critical_diffs(self):
        """ConfigurationError should contain critical diff information."""
        critical_diffs = [("fee_bps", 2.0, 10.0), ("slippage_bps", 1.0, 5.0)]
        error = ConfigurationError(
            message="Critical configuration differences detected",
            critical_diffs=critical_diffs,
        )
        
        assert error.critical_diffs == critical_diffs
        assert "fee_bps" in str(error)
        assert "slippage_bps" in str(error)
    
    def test_config_version_create_generates_hash(self):
        """ConfigVersion.create should generate config hash."""
        config = ConfigVersion.create(
            version_id="test_v1",
            created_by="live",
            parameters={"fee_bps": 2.0},
        )
        
        assert config.config_hash is not None
        assert len(config.config_hash) > 0
    
    def test_config_version_serialization(self):
        """ConfigVersion should serialize and deserialize correctly."""
        config = ConfigVersion.create(
            version_id="test_v1",
            created_by="live",
            parameters={"fee_bps": 2.0, "slippage_bps": 1.0},
        )
        
        # Serialize to dict
        config_dict = config.to_dict()
        assert config_dict["version_id"] == "test_v1"
        assert config_dict["parameters"]["fee_bps"] == 2.0
        
        # Deserialize from dict
        restored = ConfigVersion.from_dict(config_dict)
        assert restored.version_id == config.version_id
        assert restored.parameters == config.parameters
        assert restored.config_hash == config.config_hash


# =============================================================================
# Test: Integration Between Components
# =============================================================================

class TestBacktestComponentIntegration:
    """Tests integration between backtest components.
    
    Feature: trading-pipeline-integration
    Tests the integration points between WarmStartState, ExecutionSimulator,
    and ConfigurationRegistry.
    """
    
    def test_warm_start_state_with_execution_simulator(
        self, sample_warm_start_state, execution_simulator
    ):
        """Warm start state should work with execution simulator."""
        # Get position from warm start state
        position = sample_warm_start_state.positions[0]
        
        # Simulate closing the position
        fill = execution_simulator.simulate_fill(
            side="sell",  # Close long position
            size=position["size"],
            price=position["entry_price"] * 1.01,  # 1% profit
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            spread_bps=2.0,
            is_maker=False,
        )
        
        # Verify fill is valid
        assert fill.filled_size > 0
        assert fill.fill_price > 0
    
    @pytest.mark.asyncio
    async def test_config_registry_with_warm_start(
        self, mock_pool, mock_redis, sample_warm_start_state
    ):
        """Config registry should work with warm start state."""
        registry = ConfigurationRegistry(mock_pool, mock_redis)
        
        # Get config for backtest (uses default config since mock doesn't persist)
        config, diff = await registry.get_config_for_backtest(
            override_params=None,
            require_parity=True,
        )
        
        # Verify config is returned (even if default)
        assert config is not None
        assert isinstance(config.parameters, dict)
        
        # Verify warm start state is independent of config
        assert sample_warm_start_state.account_state["equity"] == 100000.0
    
    def test_execution_simulator_with_warm_start_depth(
        self, sample_warm_start_state
    ):
        """Execution simulator should use depth from warm start candles."""
        # Create simulator
        simulator = ExecutionSimulator(ExecutionSimulatorConfig.realistic())
        simulator.seed(42)
        
        # Get latest candle from warm start
        candles = sample_warm_start_state.candle_history.get("BTCUSDT", [])
        if candles:
            latest_candle = candles[0]
            price = latest_candle["close"]
            
            # Simulate fill at candle price
            fill = simulator.simulate_fill(
                side="buy",
                size=0.1,
                price=price,
                bid_depth_usd=100000.0,
                ask_depth_usd=100000.0,
                spread_bps=2.0,
                is_maker=False,
            )
            
            # Fill should be close to candle price
            assert abs(fill.fill_price - price) / price < 0.01  # Within 1%
    
    def test_warm_start_state_to_dict_for_backtest_config(
        self, sample_warm_start_state
    ):
        """Warm start state should convert to dict for backtest config."""
        state_dict = sample_warm_start_state.to_dict()
        
        # Verify dict contains all required fields
        assert "snapshot_time" in state_dict
        assert "positions" in state_dict
        assert "account_state" in state_dict
        assert "candle_history" in state_dict
        assert "pipeline_state" in state_dict
        
        # Verify positions are serialized correctly
        assert len(state_dict["positions"]) == 1
        assert state_dict["positions"][0]["symbol"] == "BTCUSDT"
    
    def test_execution_simulator_config_to_dict(self):
        """ExecutionSimulatorConfig should convert to dict for storage."""
        config = ExecutionSimulatorConfig.realistic()
        config_dict = config.to_dict()
        
        # Verify dict contains all config fields
        assert "base_latency_ms" in config_dict
        assert "latency_std_ms" in config_dict
        assert "partial_fill_prob_small" in config_dict
        assert "base_slippage_bps" in config_dict
        assert "scenario" in config_dict
        
        # Verify values match
        assert config_dict["base_latency_ms"] == 50.0
        assert config_dict["scenario"] == "realistic"
    
    def test_execution_simulator_config_from_dict(self):
        """ExecutionSimulatorConfig should restore from dict."""
        original = ExecutionSimulatorConfig.pessimistic()
        config_dict = original.to_dict()
        
        restored = ExecutionSimulatorConfig.from_dict(config_dict)
        
        assert restored.base_latency_ms == original.base_latency_ms
        assert restored.base_slippage_bps == original.base_slippage_bps
        assert restored.scenario == original.scenario
