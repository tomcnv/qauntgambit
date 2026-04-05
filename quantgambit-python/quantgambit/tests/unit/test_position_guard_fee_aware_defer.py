import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.execution.manager import PositionSnapshot
from quantgambit.execution.position_guard_worker import PositionGuardConfig, PositionGuardWorker
from quantgambit.risk.fee_model import FeeConfig, FeeModel


@pytest.mark.asyncio
async def test_time_budget_exit_deferred_when_gross_positive_but_below_fee_breakeven():
    exchange_client = MagicMock()
    position_manager = MagicMock()
    worker = PositionGuardWorker(
        exchange_client=exchange_client,
        position_manager=position_manager,
        config=PositionGuardConfig(
            continuation_gate_enabled=True,
            continuation_min_pnl_bps=10.0,
            continuation_min_confidence=0.6,
            continuation_max_prediction_age_sec=120.0,
            continuation_max_defer_sec=120.0,
        ),
        fee_model=FeeModel(FeeConfig.bybit_regular()),
        min_profit_buffer_bps=18.0,
    )
    worker._load_live_prediction = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "direction": "up",
            "confidence": 0.9,
            "timestamp": time.time(),
        }
    )
    pos = PositionSnapshot(
        symbol="BTCUSDT",
        side="long",
        size=0.02,
        entry_price=100000.0,
        opened_at=time.time() - 600,
    )
    # Gross positive ~6 bps. Below continuation_min_pnl_bps(10), but should still defer
    # for time-budget exits when fee check says not yet profitable net of fees.
    should_defer, meta = await worker._should_defer_soft_exit(
        pos=pos,
        reason="max_hold_exceeded",
        price=100060.0,
        now_ts=time.time(),
    )
    assert should_defer is True
    assert meta.get("fee_shortfall_bps") is not None


@pytest.mark.asyncio
async def test_time_budget_exit_not_deferred_when_not_gross_positive():
    exchange_client = MagicMock()
    position_manager = MagicMock()
    worker = PositionGuardWorker(
        exchange_client=exchange_client,
        position_manager=position_manager,
        config=PositionGuardConfig(
            continuation_gate_enabled=True,
            continuation_min_pnl_bps=10.0,
            continuation_min_confidence=0.6,
            continuation_max_prediction_age_sec=120.0,
            continuation_max_defer_sec=120.0,
        ),
        fee_model=FeeModel(FeeConfig.bybit_regular()),
        min_profit_buffer_bps=18.0,
    )
    worker._load_live_prediction = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "direction": "up",
            "confidence": 0.9,
            "timestamp": time.time(),
        }
    )
    pos = PositionSnapshot(
        symbol="BTCUSDT",
        side="long",
        size=0.02,
        entry_price=100000.0,
        opened_at=time.time() - 600,
    )
    should_defer, meta = await worker._should_defer_soft_exit(
        pos=pos,
        reason="max_hold_exceeded",
        price=99990.0,  # negative pnl_bps
        now_ts=time.time(),
    )
    assert should_defer is False
    assert meta == {}
