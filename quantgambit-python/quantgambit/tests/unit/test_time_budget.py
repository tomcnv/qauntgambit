"""Unit tests for time budget (MFT scalping) functionality."""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock

from quantgambit.execution.manager import PositionSnapshot
from quantgambit.execution.position_guard_worker import (
    PositionGuardConfig,
    _should_close as _should_close_impl,
)
from quantgambit.signals.pipeline import PositionEvaluationStage, StageContext, StageResult
from quantgambit.deeptrader_core.types import ExitType


def _should_close(pos, price, config, trailing_peaks=None, fee_model=None, now_ts=None):
    if now_ts is None:
        now_ts = time.time()
    if trailing_peaks is None:
        trailing_peaks = {}
    return _should_close_impl(pos, price, now_ts, config, trailing_peaks, fee_model)


class TestTimeBudgetDefaults:
    """Tests for time budget configuration defaults."""
    
    def test_time_budget_defaults_exist(self):
        """Time budget defaults should exist for all strategy families."""
        from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
            TIME_BUDGET_DEFAULTS, StrategyFamily
        )
        
        assert StrategyFamily.MICROSTRUCTURE in TIME_BUDGET_DEFAULTS
        assert StrategyFamily.MOMENTUM in TIME_BUDGET_DEFAULTS
        assert StrategyFamily.MEAN_REVERSION in TIME_BUDGET_DEFAULTS
        assert StrategyFamily.POC_ROTATION in TIME_BUDGET_DEFAULTS
        assert StrategyFamily.TREND in TIME_BUDGET_DEFAULTS
    
    def test_microstructure_has_fastest_times(self):
        """Microstructure strategies should have the fastest time budgets."""
        from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
            TIME_BUDGET_DEFAULTS, StrategyFamily
        )
        
        ms = TIME_BUDGET_DEFAULTS[StrategyFamily.MICROSTRUCTURE]
        mom = TIME_BUDGET_DEFAULTS[StrategyFamily.MOMENTUM]
        mr = TIME_BUDGET_DEFAULTS[StrategyFamily.MEAN_REVERSION]
        
        assert ms.max_hold_sec < mom.max_hold_sec
        assert ms.max_hold_sec < mr.max_hold_sec
        assert ms.time_to_work_sec < mom.time_to_work_sec
    
    def test_get_time_budget_for_strategy(self):
        """Should return correct time budget for known strategies."""
        from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
            get_time_budget_for_strategy, StrategyFamily, TIME_BUDGET_DEFAULTS
        )
        
        # Microstructure strategies
        assert get_time_budget_for_strategy("spread_compression") == TIME_BUDGET_DEFAULTS[StrategyFamily.MICROSTRUCTURE]
        
        # Momentum strategies
        assert get_time_budget_for_strategy("breakout_scalp") == TIME_BUDGET_DEFAULTS[StrategyFamily.MOMENTUM]
        
        # Mean reversion strategies
        assert get_time_budget_for_strategy("mean_reversion_fade") == TIME_BUDGET_DEFAULTS[StrategyFamily.MEAN_REVERSION]
        
        # POC rotation strategies
        assert get_time_budget_for_strategy("poc_magnet_scalp") == TIME_BUDGET_DEFAULTS[StrategyFamily.POC_ROTATION]


class TestPositionGuardTimeBudget:
    """Tests for time budget enforcement in position guard."""
    
    def test_max_hold_exceeded_triggers_close(self):
        """Position should close when max_hold_sec is exceeded."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            opened_at=now - 20.0,  # Opened 20 seconds ago
            max_hold_sec=15.0,  # Max hold is 15 seconds
        )
        config = PositionGuardConfig()
        
        result = _should_close(pos, 100.0, config, {})
        assert result == "max_hold_exceeded"
    
    def test_max_hold_not_exceeded_no_close(self):
        """Position should not close when max_hold_sec is not exceeded."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            opened_at=now - 10.0,  # Opened 10 seconds ago
            max_hold_sec=15.0,  # Max hold is 15 seconds
        )
        config = PositionGuardConfig()
        
        result = _should_close(pos, 100.0, config, {})
        assert result is None
    
    def test_time_to_work_fail_triggers_close(self):
        """Position should close when T_work passed without MFE_min."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            opened_at=now - 5.0,  # Opened 5 seconds ago
            time_to_work_sec=3.0,  # T_work is 3 seconds
            mfe_min_bps=2.0,  # Need 2 bps MFE
            mfe_pct=0.01,  # Only achieved 1 bps (0.01% = 1 bps)
        )
        config = PositionGuardConfig()
        
        result = _should_close(pos, 100.0, config, {})
        assert result == "time_to_work_fail"
    
    def test_time_to_work_met_no_close(self):
        """Position should not close when MFE_min is achieved."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            opened_at=now - 5.0,  # Opened 5 seconds ago
            time_to_work_sec=3.0,  # T_work is 3 seconds
            mfe_min_bps=2.0,  # Need 2 bps MFE
            mfe_pct=0.05,  # Achieved 5 bps (0.05% = 5 bps)
        )
        config = PositionGuardConfig()
        
        result = _should_close(pos, 100.0, config, {})
        assert result is None
    
    def test_time_to_work_not_yet_reached_no_close(self):
        """Position should not close when T_work hasn't been reached yet."""
        now = time.time()
        pos = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            opened_at=now - 2.0,  # Opened 2 seconds ago
            time_to_work_sec=3.0,  # T_work is 3 seconds
            mfe_min_bps=2.0,  # Need 2 bps MFE
            mfe_pct=0.0,  # No MFE yet
        )
        config = PositionGuardConfig()
        
        result = _should_close(pos, 100.0, config, {})
        assert result is None


class TestPositionEvaluationTimeBudget:
    """Tests for time budget enforcement in position evaluation stage."""
    
    @pytest.mark.asyncio
    async def test_max_hold_exceeded_generates_exit(self):
        """Position evaluation should generate exit when max_hold exceeded."""
        stage = PositionEvaluationStage()
        now = time.time()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "positions": [{
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "size": 1.0,
                    "entry_price": 100.0,
                    "opened_at": now - 200.0,  # Opened 200 seconds ago
                    "max_hold_sec": 120.0,  # Max hold is 120 seconds
                }],
                "market_context": {
                    "price": 100.5,
                },
            },
        )
        
        result = await stage.run(ctx)
        
        # Should generate exit signal
        assert result == StageResult.SKIP_TO_EXECUTION
        assert ctx.signal is not None
        assert "max_hold_exceeded" in ctx.signal.get("meta_reason", "")
        assert "confirmation_version" in ctx.signal
        assert "confirmation_mode" in ctx.signal
    
    @pytest.mark.asyncio
    async def test_time_to_work_fail_generates_exit(self):
        """Position evaluation should generate exit when T_work fails."""
        stage = PositionEvaluationStage()
        now = time.time()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "positions": [{
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "size": 1.0,
                    "entry_price": 100.0,
                    "opened_at": now - 10.0,  # Opened 10 seconds ago
                    "time_to_work_sec": 5.0,  # T_work is 5 seconds
                    "mfe_min_bps": 3.0,  # Need 3 bps MFE
                    "mfe_pct": 0.01,  # Only achieved 1 bps
                }],
                "market_context": {
                    "price": 100.01,  # Barely moved
                },
            },
        )
        
        result = await stage.run(ctx)
        
        # Should generate exit signal
        assert result == StageResult.SKIP_TO_EXECUTION
        assert ctx.signal is not None
        assert "time_to_work_fail" in ctx.signal.get("meta_reason", "")
        assert "confirmation_reason_codes" in ctx.signal
    
    @pytest.mark.asyncio
    async def test_healthy_position_no_exit(self):
        """Position evaluation should not exit healthy position."""
        stage = PositionEvaluationStage()
        now = time.time()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "positions": [{
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "size": 1.0,
                    "entry_price": 100.0,
                    "opened_at": now - 5.0,  # Opened 5 seconds ago
                    "max_hold_sec": 120.0,  # Max hold is 120 seconds
                    "time_to_work_sec": 10.0,  # T_work is 10 seconds
                    "mfe_min_bps": 2.0,  # Need 2 bps MFE
                    "mfe_pct": 0.1,  # Achieved 10 bps
                }],
                "market_context": {
                    "price": 100.1,  # Up 0.1%
                },
            },
        )
        
        result = await stage.run(ctx)
        
        # Should continue (no exit)
        assert result == StageResult.CONTINUE
        assert ctx.signal is None


class TestMFEMAETracking:
    """Tests for MFE/MAE tracking in state manager."""
    
    def test_mfe_mae_initialized_on_position_create(self):
        """MFE/MAE should be initialized to entry price on position create."""
        from quantgambit.portfolio.state_manager import InMemoryStateManager
        
        state = InMemoryStateManager()
        state.add_position(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
        )
        
        pos = state.get_position("BTCUSDT")
        assert pos is not None
        assert pos.mfe_price == 100.0
        assert pos.mae_price == 100.0
        assert pos.mfe_pct == 0.0
        assert pos.mae_pct == 0.0
    
    def test_mfe_updates_on_favorable_move_long(self):
        """MFE should update when price moves favorably for long."""
        from quantgambit.portfolio.state_manager import InMemoryStateManager
        
        state = InMemoryStateManager()
        state.add_position(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
        )
        
        # Price moves up (favorable for long)
        state.update_mfe_mae("BTCUSDT", 101.0)
        
        pos = state.get_position("BTCUSDT")
        assert pos.mfe_price == 101.0
        assert pos.mfe_pct == 1.0  # 1% favorable
        assert pos.mae_price == 100.0  # MAE unchanged
    
    def test_mae_updates_on_adverse_move_long(self):
        """MAE should update when price moves adversely for long."""
        from quantgambit.portfolio.state_manager import InMemoryStateManager
        
        state = InMemoryStateManager()
        state.add_position(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
        )
        
        # Price moves down (adverse for long)
        state.update_mfe_mae("BTCUSDT", 99.0)
        
        pos = state.get_position("BTCUSDT")
        assert pos.mfe_price == 100.0  # MFE unchanged
        assert pos.mae_price == 99.0
        assert pos.mae_pct == -1.0  # 1% adverse
    
    def test_mfe_updates_on_favorable_move_short(self):
        """MFE should update when price moves favorably for short."""
        from quantgambit.portfolio.state_manager import InMemoryStateManager
        
        state = InMemoryStateManager()
        state.add_position(
            symbol="BTCUSDT",
            side="short",
            size=1.0,
            entry_price=100.0,
        )
        
        # Price moves down (favorable for short)
        state.update_mfe_mae("BTCUSDT", 99.0)
        
        pos = state.get_position("BTCUSDT")
        assert pos.mfe_price == 99.0
        assert pos.mfe_pct == 1.0  # 1% favorable
        assert pos.mae_price == 100.0  # MAE unchanged
    
    def test_mae_updates_on_adverse_move_short(self):
        """MAE should update when price moves adversely for short."""
        from quantgambit.portfolio.state_manager import InMemoryStateManager
        
        state = InMemoryStateManager()
        state.add_position(
            symbol="BTCUSDT",
            side="short",
            size=1.0,
            entry_price=100.0,
        )
        
        # Price moves up (adverse for short)
        state.update_mfe_mae("BTCUSDT", 101.0)
        
        pos = state.get_position("BTCUSDT")
        assert pos.mfe_price == 100.0  # MFE unchanged
        assert pos.mae_price == 101.0
        assert pos.mae_pct == -1.0  # 1% adverse

    def test_update_mfe_mae_preserves_entry_lineage_fields(self):
        """MFE/MAE updates must not drop entry lineage metadata."""
        from quantgambit.portfolio.state_manager import InMemoryStateManager

        state = InMemoryStateManager()
        state.add_position(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            entry_client_order_id="qg-123",
            entry_decision_id="evt-abc",
        )

        state.update_mfe_mae("BTCUSDT", 101.0)
        pos = state.get_position("BTCUSDT")

        assert pos is not None
        assert pos.entry_client_order_id == "qg-123"
        assert pos.entry_decision_id == "evt-abc"


class TestSignalStrengthTelemetry:
    """Tests for signal strength propagation in telemetry."""
    
    def test_signal_serialization_includes_strength(self):
        """Signal serialization should include signal strength fields."""
        from quantgambit.signals.decision_worker import _serialize_signal
        
        class MockSignal:
            strategy_id = "test_strategy"
            symbol = "BTCUSDT"
            side = "long"
            signal_strength = "strong"
            confidence = 0.85
            confirmation_count = 5
        
        result = _serialize_signal(MockSignal())
        
        assert result is not None
        assert result.get("signal_strength") == "strong"
        assert result.get("confidence") == 0.85
        assert result.get("confirmation_count") == 5
    
    def test_signal_strength_enum_converted_to_string(self):
        """Signal strength enum should be converted to string value."""
        from quantgambit.signals.decision_worker import _serialize_signal
        from quantgambit.deeptrader_core.layer2_signals.trading_signal import SignalStrength
        
        class MockSignal:
            strategy_id = "test_strategy"
            signal_strength = SignalStrength.STRONG
        
        result = _serialize_signal(MockSignal())
        
        assert result is not None
        assert result.get("signal_strength") == "strong"
