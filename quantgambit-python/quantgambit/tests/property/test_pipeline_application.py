"""Property tests for pipeline application in backtest executor.

Property 1: Pipeline Stage Application
- Test that DecisionEngine is used for all decisions
- Test that all configured stages are invoked

Requirements: 1.1, 1.3
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from hypothesis import given, strategies as st, settings

from quantgambit.backtesting.decision_adapter import BacktestDecisionAdapter, DecisionResult
from quantgambit.backtesting.trend_calculator import TrendCalculator, TrendResult
from quantgambit.backtesting.stage_context_builder import StageContextBuilder
from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput
from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.deeptrader_core.types import MarketSnapshot, Features, AccountState


# Test fixtures
@pytest.fixture
def mock_decision_engine():
    """Create a mock DecisionEngine that tracks calls."""
    engine = MagicMock(spec=DecisionEngine)
    engine.decide_with_context = AsyncMock()
    return engine


@pytest.fixture
def mock_trend_calculator():
    """Create a mock TrendCalculator."""
    calc = MagicMock(spec=TrendCalculator)
    calc.calculate_from_candles = MagicMock(return_value=TrendResult(
        direction="up",
        strength=0.7,
        ema_fast=100.0,
        ema_slow=99.0,
        method="ema",
    ))
    return calc


@pytest.fixture
def mock_context_builder():
    """Create a mock StageContextBuilder."""
    builder = MagicMock(spec=StageContextBuilder)
    builder.build = MagicMock(return_value=StageContext(
        symbol="BTCUSDT",
        data={},
    ))
    return builder


@pytest.fixture
def sample_snapshot():
    """Create a sample MarketSnapshot."""
    return MarketSnapshot(
        symbol="BTCUSDT",
        exchange="bybit",
        timestamp_ns=int(datetime.now(timezone.utc).timestamp() * 1e9),
        snapshot_age_ms=100,
        mid_price=50000.0,
        bid=49990.0,
        ask=50010.0,
        spread_bps=4.0,
        bid_depth_usd=100000.0,
        ask_depth_usd=100000.0,
        depth_imbalance=0.0,
        imb_1s=0.0,
        imb_5s=0.0,
        imb_30s=0.0,
        orderflow_persistence_sec=0,
        rv_1s=0.0,
        rv_10s=0.0,
        rv_1m=0.0,
        vol_shock=False,
        vol_regime="normal",
        vol_regime_score=0.5,
        trend_direction="up",
        trend_strength=0.5,
        poc_price=50000.0,
        vah_price=50500.0,
        val_price=49500.0,
        position_in_value="inside",
        expected_fill_slippage_bps=2.0,
        typical_spread_bps=4.0,
        data_quality_score=1.0,
        ws_connected=True,
    )


@pytest.fixture
def sample_features():
    """Create sample Features."""
    return Features(
        symbol="BTCUSDT",
        price=50000.0,
        spread=0.0004,
        rotation_factor=0.0,
        position_in_value="inside",
        timestamp=datetime.now(timezone.utc).timestamp(),
        distance_to_val=500.0,
        distance_to_vah=500.0,
        distance_to_poc=0.0,
        value_area_low=49500.0,
        value_area_high=50500.0,
        point_of_control=50000.0,
        atr_5m=250.0,
        atr_5m_baseline=250.0,
        bid_depth_usd=100000.0,
        ask_depth_usd=100000.0,
        orderbook_imbalance=0.0,
        orderflow_imbalance=0.0,
    )


@pytest.fixture
def sample_account():
    """Create sample AccountState."""
    return AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=200.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )


class TestPipelineApplication:
    """Property 1: Pipeline Stage Application tests."""
    
    @pytest.mark.asyncio
    async def test_decision_engine_is_called_for_every_decision(
        self,
        mock_decision_engine,
        mock_trend_calculator,
        mock_context_builder,
        sample_snapshot,
        sample_features,
        sample_account,
    ):
        """Test that DecisionEngine.decide_with_context is called for each decision."""
        # Setup mock to return rejection
        mock_ctx = StageContext(symbol="BTCUSDT", data={})
        mock_ctx.rejection_reason = "test_rejection"
        mock_ctx.rejection_stage = "test_stage"
        mock_decision_engine.decide_with_context.return_value = (False, mock_ctx)
        
        adapter = BacktestDecisionAdapter(
            decision_engine=mock_decision_engine,
            trend_calculator=mock_trend_calculator,
            context_builder=mock_context_builder,
        )
        
        # Process multiple snapshots
        for _ in range(5):
            await adapter.process_snapshot(
                symbol="BTCUSDT",
                snapshot=sample_snapshot,
                features=sample_features,
                account_state=sample_account,
            )
        
        # Verify DecisionEngine was called 5 times
        assert mock_decision_engine.decide_with_context.call_count == 5
    
    @pytest.mark.asyncio
    async def test_decision_input_is_properly_constructed(
        self,
        mock_decision_engine,
        mock_trend_calculator,
        mock_context_builder,
        sample_snapshot,
        sample_features,
        sample_account,
    ):
        """Test that DecisionInput is properly constructed with all required fields."""
        mock_ctx = StageContext(symbol="BTCUSDT", data={})
        mock_decision_engine.decide_with_context.return_value = (False, mock_ctx)
        
        adapter = BacktestDecisionAdapter(
            decision_engine=mock_decision_engine,
            trend_calculator=mock_trend_calculator,
            context_builder=mock_context_builder,
        )
        
        await adapter.process_snapshot(
            symbol="BTCUSDT",
            snapshot=sample_snapshot,
            features=sample_features,
            account_state=sample_account,
        )
        
        # Get the DecisionInput that was passed
        call_args = mock_decision_engine.decide_with_context.call_args
        decision_input = call_args[0][0]
        
        # Verify required fields
        assert decision_input.symbol == "BTCUSDT"
        assert "trend_direction" in decision_input.market_context
        assert "mid_price" in decision_input.market_context
        assert "price" in decision_input.features
    
    @pytest.mark.asyncio
    async def test_successful_decision_returns_signal(
        self,
        mock_decision_engine,
        mock_trend_calculator,
        mock_context_builder,
        sample_snapshot,
        sample_features,
        sample_account,
    ):
        """Test that successful decisions return the signal."""
        # Setup mock to return success with signal
        mock_ctx = StageContext(symbol="BTCUSDT", data={})
        mock_ctx.signal = {
            "strategy_id": "mean_reversion",
            "side": "long",
            "size": 0.01,
            "entry_price": 50000.0,
            "stop_loss": 49500.0,
            "take_profit": 50500.0,
        }
        mock_decision_engine.decide_with_context.return_value = (True, mock_ctx)
        
        adapter = BacktestDecisionAdapter(
            decision_engine=mock_decision_engine,
            trend_calculator=mock_trend_calculator,
            context_builder=mock_context_builder,
        )
        
        result = await adapter.process_snapshot(
            symbol="BTCUSDT",
            snapshot=sample_snapshot,
            features=sample_features,
            account_state=sample_account,
        )
        
        assert result.should_trade is True
        assert result.signal is not None
        assert result.signal["side"] == "long"
    
    @pytest.mark.asyncio
    async def test_rejected_decision_records_stage_and_reason(
        self,
        mock_decision_engine,
        mock_trend_calculator,
        mock_context_builder,
        sample_snapshot,
        sample_features,
        sample_account,
    ):
        """Test that rejected decisions record the stage and reason."""
        mock_ctx = StageContext(symbol="BTCUSDT", data={})
        mock_ctx.rejection_reason = "counter_trend_short"
        mock_ctx.rejection_stage = "strategy_trend_alignment"
        mock_decision_engine.decide_with_context.return_value = (False, mock_ctx)
        
        adapter = BacktestDecisionAdapter(
            decision_engine=mock_decision_engine,
            trend_calculator=mock_trend_calculator,
            context_builder=mock_context_builder,
        )
        
        result = await adapter.process_snapshot(
            symbol="BTCUSDT",
            snapshot=sample_snapshot,
            features=sample_features,
            account_state=sample_account,
        )
        
        assert result.should_trade is False
        assert result.rejection_stage == "strategy_trend_alignment"
        assert result.rejection_reason == "counter_trend_short"


class TestAllStagesInvoked:
    """Test that all configured stages are invoked."""
    
    @pytest.mark.asyncio
    async def test_backtesting_mode_enables_all_stages(self):
        """Test that DecisionEngine with backtesting_mode=True has all stages."""
        from quantgambit.signals.stages.data_readiness import DataReadinessConfig
        from quantgambit.signals.stages.global_gate import GlobalGateConfig
        from quantgambit.signals.stages.ev_gate import EVGateConfig
        from quantgambit.signals.stages.ev_position_sizer import EVPositionSizerConfig
        
        engine = DecisionEngine(
            backtesting_mode=True,
            use_gating_system=True,
            data_readiness_config=DataReadinessConfig(
                max_trade_age_sec=float('inf'),
                max_orderbook_feed_age_sec=float('inf'),
                min_bid_depth_usd=0,
                min_ask_depth_usd=0,
            ),
            global_gate_config=GlobalGateConfig(
                max_spread_bps=50.0,
                min_depth_per_side_usd=1000.0,
            ),
            # Use EVGateConfig to avoid deprecated ConfidenceGateStage
            ev_gate_config=EVGateConfig(
                max_book_age_ms=86400000,  # 24 hours for backtesting
                max_spread_age_ms=86400000,
            ),
            # Use EVPositionSizerConfig to avoid deprecated ConfidencePositionSizerStage
            ev_position_sizer_config=EVPositionSizerConfig(
                enabled=True,
            ),
        )
        
        # Verify orchestrator has stages
        assert engine.orchestrator is not None
        assert len(engine.orchestrator.stages) > 0
        
        # Check for key stages
        stage_names = [type(s).__name__ for s in engine.orchestrator.stages]
        
        # Must have these critical stages
        assert "DataReadinessStage" in stage_names
        assert "GlobalGateStage" in stage_names
        assert "StrategyTrendAlignmentStage" in stage_names
        assert "SignalStage" in stage_names
        # Should use EVGateStage instead of deprecated ConfidenceGateStage
        assert "EVGateStage" in stage_names
        assert "EVPositionSizerStage" in stage_names
    
    @pytest.mark.asyncio
    async def test_strategy_trend_alignment_stage_present(self):
        """Test that StrategyTrendAlignmentStage is in the pipeline."""
        from quantgambit.signals.stages.ev_gate import EVGateConfig
        from quantgambit.signals.stages.ev_position_sizer import EVPositionSizerConfig
        
        engine = DecisionEngine(
            backtesting_mode=True,
            use_gating_system=True,
            # Use EVGateConfig to avoid deprecated ConfidenceGateStage
            ev_gate_config=EVGateConfig(
                max_book_age_ms=86400000,
                max_spread_age_ms=86400000,
            ),
            ev_position_sizer_config=EVPositionSizerConfig(
                enabled=True,
            ),
        )
        
        stage_names = [type(s).__name__ for s in engine.orchestrator.stages]
        assert "StrategyTrendAlignmentStage" in stage_names, \
            "StrategyTrendAlignmentStage must be present to reject counter-trend trades"


class TestAdapterStatistics:
    """Test that adapter tracks statistics correctly."""
    
    @pytest.mark.asyncio
    async def test_decisions_processed_counter(
        self,
        mock_decision_engine,
        mock_trend_calculator,
        mock_context_builder,
        sample_snapshot,
        sample_features,
        sample_account,
    ):
        """Test that decisions_processed counter increments."""
        mock_ctx = StageContext(symbol="BTCUSDT", data={})
        mock_decision_engine.decide_with_context.return_value = (False, mock_ctx)
        
        adapter = BacktestDecisionAdapter(
            decision_engine=mock_decision_engine,
            trend_calculator=mock_trend_calculator,
            context_builder=mock_context_builder,
        )
        
        for _ in range(10):
            await adapter.process_snapshot(
                symbol="BTCUSDT",
                snapshot=sample_snapshot,
                features=sample_features,
                account_state=sample_account,
            )
        
        stats = adapter.get_statistics()
        assert stats["decisions_processed"] == 10
    
    @pytest.mark.asyncio
    async def test_rejections_by_stage_tracking(
        self,
        mock_decision_engine,
        mock_trend_calculator,
        mock_context_builder,
        sample_snapshot,
        sample_features,
        sample_account,
    ):
        """Test that rejections are tracked by stage."""
        mock_ctx = StageContext(symbol="BTCUSDT", data={})
        mock_ctx.rejection_reason = "counter_trend"
        mock_ctx.rejection_stage = "strategy_trend_alignment"
        mock_decision_engine.decide_with_context.return_value = (False, mock_ctx)
        
        adapter = BacktestDecisionAdapter(
            decision_engine=mock_decision_engine,
            trend_calculator=mock_trend_calculator,
            context_builder=mock_context_builder,
        )
        
        for _ in range(5):
            await adapter.process_snapshot(
                symbol="BTCUSDT",
                snapshot=sample_snapshot,
                features=sample_features,
                account_state=sample_account,
            )
        
        stats = adapter.get_statistics()
        assert "strategy_trend_alignment" in stats["rejections_by_stage"]
        assert stats["rejections_by_stage"]["strategy_trend_alignment"] == 5
