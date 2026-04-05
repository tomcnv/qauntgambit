from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.execution.manager import PositionSnapshot
from quantgambit.execution.position_guard_worker import PositionGuardConfig, PositionGuardWorker


def _mock_exchange_with_book() -> MagicMock:
    exchange = MagicMock()
    exchange.reference_prices = MagicMock()
    exchange.reference_prices.get_orderbook_with_ts = MagicMock(
        return_value=({"bids": [[100.0, 1.0]], "asks": [[100.2, 1.0]]}, None)
    )
    return exchange


@pytest.mark.asyncio
async def test_non_emergency_exit_prefers_limit_then_fallback_market():
    exchange = _mock_exchange_with_book()
    exchange.close_position = AsyncMock(
        side_effect=[
            SimpleNamespace(status="open", order_id="limit-1"),
            SimpleNamespace(status="filled", order_id="mkt-1", fill_price=100.0),
        ]
    )
    exchange.cancel_order = AsyncMock(return_value=None)
    exchange.fetch_order_status = AsyncMock(return_value=None)
    exchange.fetch_order_status_by_client_id = AsyncMock(return_value=None)

    worker = PositionGuardWorker(
        exchange_client=exchange,
        position_manager=MagicMock(),
        config=PositionGuardConfig(
            tp_limit_exit_enabled=True,
            tp_limit_fill_window_ms=50,
            tp_limit_poll_interval_ms=10,
            tp_limit_exit_reasons={"max_hold_exceeded"},
        ),
    )
    pos = PositionSnapshot(symbol="BTCUSDT", side="long", size=1.0, entry_price=100.0)

    status, meta = await worker._execute_close_order(pos, "max_hold_exceeded", "cid-1")

    assert status.status == "filled"
    assert meta["tp_limit_attempted"] is True
    assert meta["tp_limit_timeout_fallback"] is True
    assert meta["path"] == "tp_limit_fallback_market"
    assert exchange.close_position.await_count == 2
    first_call = exchange.close_position.await_args_list[0]
    second_call = exchange.close_position.await_args_list[1]
    assert first_call.kwargs.get("order_type") == "limit"
    assert second_call.kwargs.get("order_type") is None


@pytest.mark.asyncio
async def test_emergency_exit_bypasses_limit_path():
    exchange = _mock_exchange_with_book()
    exchange.close_position = AsyncMock(
        return_value=SimpleNamespace(status="filled", order_id="mkt-1", fill_price=100.0)
    )
    exchange.cancel_order = AsyncMock(return_value=None)
    exchange.fetch_order_status = AsyncMock(return_value=None)

    worker = PositionGuardWorker(
        exchange_client=exchange,
        position_manager=MagicMock(),
        config=PositionGuardConfig(
            tp_limit_exit_enabled=True,
            tp_limit_exit_reasons={"stop_loss_hit", "max_hold_exceeded"},
        ),
    )
    pos = PositionSnapshot(symbol="BTCUSDT", side="long", size=1.0, entry_price=100.0)

    status, meta = await worker._execute_close_order(pos, "stop_loss_hit", "cid-2")

    assert status.status == "filled"
    assert meta["path"] == "market"
    assert meta["tp_limit_attempted"] is False
    assert exchange.close_position.await_count == 1
