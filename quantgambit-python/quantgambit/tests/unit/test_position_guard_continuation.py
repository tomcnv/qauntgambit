import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.execution.manager import PositionSnapshot
from quantgambit.execution.position_guard_worker import PositionGuardConfig, PositionGuardWorker


class _FakeSnapshotReader:
    def __init__(self, payload):
        self._payload = payload

    async def read(self, key: str):
        return self._payload


@pytest.mark.asyncio
async def test_continuation_gate_defers_soft_exit_when_prediction_aligned():
    now = time.time()
    pos = PositionSnapshot(
        symbol="BTCUSDT",
        side="long",
        size=1.0,
        entry_price=100.0,
        opened_at=now - 3600.0,
    )
    exchange_client = MagicMock()
    exchange_client.reference_prices = MagicMock()
    exchange_client.reference_prices.get_reference_price = MagicMock(return_value=101.0)
    exchange_client.close_position = AsyncMock()
    position_manager = MagicMock()
    position_manager.list_open_positions = AsyncMock(return_value=[pos])
    position_manager.mark_closing = AsyncMock()
    position_manager.finalize_close = AsyncMock()
    cfg = PositionGuardConfig(
        max_position_age_sec=3600.0,
        continuation_gate_enabled=True,
        continuation_min_pnl_bps=5.0,
        continuation_min_confidence=0.60,
        continuation_max_prediction_age_sec=30.0,
        continuation_max_defer_sec=120.0,
        continuation_max_defers=10,
    )
    worker = PositionGuardWorker(
        exchange_client=exchange_client,
        position_manager=position_manager,
        config=cfg,
        tenant_id="t1",
        bot_id="b1",
        snapshot_reader=_FakeSnapshotReader(
            {
                "symbol": "BTCUSDT",
                "direction": "up",
                "confidence": 0.82,
                "timestamp": now,
            }
        ),
    )

    should_defer, _ = await worker._should_defer_soft_exit(
        pos=pos,
        reason="max_hold_exceeded",
        price=101.0,
        now_ts=now,
    )

    assert should_defer is True
    position_manager.mark_closing.assert_not_called()
    exchange_client.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_continuation_gate_does_not_defer_when_prediction_not_aligned():
    now = time.time()
    pos = PositionSnapshot(
        symbol="BTCUSDT",
        side="long",
        size=1.0,
        entry_price=100.0,
        opened_at=now - 3600.0,
    )
    exchange_client = MagicMock()
    exchange_client.reference_prices = MagicMock()
    exchange_client.reference_prices.get_reference_price = MagicMock(return_value=101.0)
    exchange_client.close_position = AsyncMock(
        return_value=MagicMock(
            status="filled",
            fill_price=101.0,
            fee_usd=0.0,
            order_id="o1",
            timestamp=now,
            filled_size=1.0,
        )
    )
    position_manager = MagicMock()
    position_manager.list_open_positions = AsyncMock(return_value=[pos])
    position_manager.mark_closing = AsyncMock()
    position_manager.finalize_close = AsyncMock()
    cfg = PositionGuardConfig(
        max_position_age_sec=3600.0,
        continuation_gate_enabled=True,
        continuation_min_pnl_bps=5.0,
        continuation_min_confidence=0.60,
        continuation_max_prediction_age_sec=30.0,
    )
    worker = PositionGuardWorker(
        exchange_client=exchange_client,
        position_manager=position_manager,
        config=cfg,
        tenant_id="t1",
        bot_id="b1",
        snapshot_reader=_FakeSnapshotReader(
            {
                "symbol": "BTCUSDT",
                "direction": "flat",  # not aligned -> do not defer
                "confidence": 0.90,
                "timestamp": now,
            }
        ),
    )

    should_defer, meta = await worker._should_defer_soft_exit(
        pos=pos,
        reason="max_hold_exceeded",
        price=101.0,
        now_ts=now,
    )
    assert should_defer is False
    assert meta == {}
    position_manager.mark_closing.assert_not_called()
    exchange_client.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_continuation_gate_symbol_confidence_override_applies():
    now = time.time()
    pos = PositionSnapshot(
        symbol="SOLUSDT",
        side="long",
        size=1.0,
        entry_price=100.0,
        opened_at=now - 3600.0,
    )
    exchange_client = MagicMock()
    exchange_client.reference_prices = MagicMock()
    exchange_client.reference_prices.get_reference_price = MagicMock(return_value=101.0)
    exchange_client.close_position = AsyncMock(
        return_value=MagicMock(
            status="filled",
            fill_price=101.0,
            fee_usd=0.0,
            order_id="o2",
            timestamp=now,
            filled_size=1.0,
        )
    )
    position_manager = MagicMock()
    position_manager.list_open_positions = AsyncMock(return_value=[pos])
    position_manager.mark_closing = AsyncMock()
    position_manager.finalize_close = AsyncMock()
    cfg = PositionGuardConfig(
        max_position_age_sec=3600.0,
        continuation_gate_enabled=True,
        continuation_min_confidence=0.60,
        continuation_symbol_min_confidence={"SOLUSDT": 0.80},
        continuation_min_pnl_bps=5.0,
        continuation_max_prediction_age_sec=30.0,
    )
    worker = PositionGuardWorker(
        exchange_client=exchange_client,
        position_manager=position_manager,
        config=cfg,
        tenant_id="t1",
        bot_id="b1",
        snapshot_reader=_FakeSnapshotReader(
            {
                "symbol": "SOLUSDT",
                "direction": "up",
                "confidence": 0.75,  # above global floor, below SOL override
                "timestamp": now,
            }
        ),
    )

    should_defer, meta = await worker._should_defer_soft_exit(
        pos=pos,
        reason="max_hold_exceeded",
        price=101.0,
        now_ts=now,
    )
    assert should_defer is False
    assert meta == {}
    position_manager.mark_closing.assert_not_called()
    exchange_client.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_max_age_requires_double_confirmation_before_close():
    now = time.time()
    pos = PositionSnapshot(
        symbol="BTCUSDT",
        side="long",
        size=1.0,
        entry_price=100.0,
        opened_at=now - 3600.0,
    )
    exchange_client = MagicMock()
    position_manager = MagicMock()
    cfg = PositionGuardConfig(
        max_position_age_sec=1200.0,
        max_age_confirmations=2,
        max_age_recheck_sec=1.0,
        max_age_extension_sec=0.0,
        max_age_max_extensions=0,
        continuation_gate_enabled=False,
    )
    worker = PositionGuardWorker(
        exchange_client=exchange_client,
        position_manager=position_manager,
        config=cfg,
        tenant_id="t1",
        bot_id="b1",
        snapshot_reader=_FakeSnapshotReader(None),
    )

    should_close_1, reason_1, _ = await worker._evaluate_max_age_governance(
        pos=pos, price=101.0, now_ts=now
    )
    assert should_close_1 is False
    assert reason_1 is None

    should_close_2, reason_2, _ = await worker._evaluate_max_age_governance(
        pos=pos, price=101.0, now_ts=now + 2.0
    )
    assert should_close_2 is True
    assert reason_2 == "max_age_exceeded"


@pytest.mark.asyncio
async def test_max_age_extension_granted_when_pnl_and_signal_healthy():
    now = time.time()
    pos = PositionSnapshot(
        symbol="ETHUSDT",
        side="long",
        size=1.0,
        entry_price=100.0,
        opened_at=now - 3600.0,
    )
    exchange_client = MagicMock()
    position_manager = MagicMock()
    cfg = PositionGuardConfig(
        max_position_age_sec=1200.0,
        max_age_confirmations=2,
        max_age_recheck_sec=1.0,
        max_age_extension_sec=300.0,
        max_age_max_extensions=1,
        min_pnl_bps_to_extend=6.0,
        continuation_gate_enabled=True,
        continuation_min_confidence=0.6,
        continuation_max_prediction_age_sec=30.0,
    )
    worker = PositionGuardWorker(
        exchange_client=exchange_client,
        position_manager=position_manager,
        config=cfg,
        tenant_id="t1",
        bot_id="b1",
        snapshot_reader=_FakeSnapshotReader(
            {
                "symbol": "ETHUSDT",
                "direction": "up",
                "confidence": 0.9,
                "timestamp": now,
            }
        ),
    )

    should_close, reason, meta = await worker._evaluate_max_age_governance(
        pos=pos, price=101.0, now_ts=now
    )
    assert should_close is False
    assert reason is None
    assert meta.get("policy") == "extension_granted"
