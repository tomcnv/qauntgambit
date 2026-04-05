"""Position store adapter backed by the in-memory state manager."""

from __future__ import annotations

from typing import List

from quantgambit.execution.adapters import PositionStoreProtocol
from quantgambit.execution.manager import PositionSnapshot
from quantgambit.portfolio.state_manager import InMemoryStateManager


class InMemoryPositionStore(PositionStoreProtocol):
    """Position store that reads/writes to the in-memory state manager."""

    def __init__(self, state_manager: InMemoryStateManager) -> None:
        self.state_manager = state_manager

    async def list_positions(self) -> List[PositionSnapshot]:
        return await self.state_manager.list_open_positions()

    async def upsert_position(self, snapshot: PositionSnapshot, accumulate: bool = True) -> None:
        """Update or create a position.
        
        By default, accumulates size for same-side positions (proper position tracking).
        Set accumulate=False to replace the position entirely (e.g., from reconciliation).
        """
        self.state_manager.update_position(
            snapshot.symbol,
            snapshot.side,
            snapshot.size,
            entry_client_order_id=snapshot.entry_client_order_id,
            entry_decision_id=snapshot.entry_decision_id,
            reference_price=snapshot.reference_price,
            entry_price=snapshot.entry_price,
            entry_fee_usd=snapshot.entry_fee_usd,
            stop_loss=snapshot.stop_loss,
            take_profit=snapshot.take_profit,
            opened_at=snapshot.opened_at,
            prediction_confidence=snapshot.prediction_confidence,
            prediction_direction=snapshot.prediction_direction,
            prediction_source=snapshot.prediction_source,
            entry_p_hat=snapshot.entry_p_hat,
            entry_p_hat_source=snapshot.entry_p_hat_source,
            strategy_id=snapshot.strategy_id,
            profile_id=snapshot.profile_id,
            accumulate=accumulate,
            entry_signal_strength=snapshot.entry_signal_strength,
            entry_signal_confidence=snapshot.entry_signal_confidence,
            entry_confirmation_count=snapshot.entry_confirmation_count,
            expected_horizon_sec=snapshot.expected_horizon_sec,
            time_to_work_sec=snapshot.time_to_work_sec,
            max_hold_sec=snapshot.max_hold_sec,
            mfe_min_bps=snapshot.mfe_min_bps,
            model_side=snapshot.model_side,
            p_up=snapshot.p_up,
            p_down=snapshot.p_down,
            p_flat=snapshot.p_flat,
        )

    def update_mfe_mae(self, symbol: str, current_price: float) -> None:
        """Update MFE/MAE for a position based on current price."""
        self.state_manager.update_mfe_mae(symbol, current_price)

    async def mark_closing(self, symbol: str, reason: str) -> None:
        await self.state_manager.mark_closing(symbol, reason)

    async def finalize_close(self, symbol: str) -> None:
        await self.state_manager.finalize_close(symbol)
