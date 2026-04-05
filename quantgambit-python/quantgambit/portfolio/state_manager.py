"""In-memory state manager for positions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from quantgambit.execution.manager import PositionSnapshot


@dataclass
class PositionRecord:
    symbol: str
    side: str
    size: float
    closing: bool = False
    close_reason: Optional[str] = None
    entry_client_order_id: Optional[str] = None
    entry_decision_id: Optional[str] = None
    reference_price: Optional[float] = None
    entry_price: Optional[float] = None
    entry_fee_usd: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: Optional[float] = None
    prediction_confidence: Optional[float] = None
    prediction_direction: Optional[str] = None
    prediction_source: Optional[str] = None
    entry_p_hat: Optional[float] = None
    entry_p_hat_source: Optional[str] = None
    strategy_id: Optional[str] = None
    profile_id: Optional[str] = None
    # MFE/MAE tracking (Maximum Favorable/Adverse Excursion)
    mfe_price: Optional[float] = None  # Best price reached
    mae_price: Optional[float] = None  # Worst price reached
    mfe_pct: Optional[float] = None  # MFE as percentage from entry
    mae_pct: Optional[float] = None  # MAE as percentage from entry
    # Signal strength at entry
    entry_signal_strength: Optional[str] = None  # weak/moderate/strong
    entry_signal_confidence: Optional[float] = None  # 0.0-1.0
    entry_confirmation_count: Optional[int] = None  # Number of confirmations
    # Time budget parameters (MFT scalping)
    expected_horizon_sec: Optional[float] = None  # How long signal is expected to be valid
    time_to_work_sec: Optional[float] = None  # T_work: time to first progress
    max_hold_sec: Optional[float] = None  # Max hold time before stale exit
    mfe_min_bps: Optional[float] = None  # Min favorable excursion expected quickly
    # Prediction context (for close-event attribution and post-trade analysis)
    model_side: Optional[str] = None
    p_up: Optional[float] = None
    p_down: Optional[float] = None
    p_flat: Optional[float] = None


class InMemoryStateManager:
    """Minimal in-memory position state.

    Designed for fast reads in the hot path.
    """

    def __init__(self) -> None:
        self._positions: Dict[str, PositionRecord] = {}
        self._account_state = AccountState()

    def add_position(
        self,
        symbol: str,
        side: str,
        size: float,
        reference_price: Optional[float] = None,
        entry_price: Optional[float] = None,
        entry_fee_usd: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        opened_at: Optional[float] = None,
        entry_client_order_id: Optional[str] = None,
        entry_decision_id: Optional[str] = None,
        prediction_confidence: Optional[float] = None,
        prediction_direction: Optional[str] = None,
        prediction_source: Optional[str] = None,
        entry_p_hat: Optional[float] = None,
        entry_p_hat_source: Optional[str] = None,
        strategy_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        entry_signal_strength: Optional[str] = None,
        entry_signal_confidence: Optional[float] = None,
        entry_confirmation_count: Optional[int] = None,
        expected_horizon_sec: Optional[float] = None,
        time_to_work_sec: Optional[float] = None,
        max_hold_sec: Optional[float] = None,
        mfe_min_bps: Optional[float] = None,
        model_side: Optional[str] = None,
        p_up: Optional[float] = None,
        p_down: Optional[float] = None,
        p_flat: Optional[float] = None,
    ) -> None:
        # Initialize MFE/MAE to entry price
        self._positions[symbol] = PositionRecord(
            symbol=symbol,
            side=side,
            size=size,
            entry_client_order_id=entry_client_order_id,
            entry_decision_id=entry_decision_id,
            reference_price=reference_price,
            entry_price=entry_price,
            entry_fee_usd=entry_fee_usd,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=opened_at,
            prediction_confidence=prediction_confidence,
            prediction_direction=prediction_direction,
            prediction_source=prediction_source,
            entry_p_hat=entry_p_hat,
            entry_p_hat_source=entry_p_hat_source,
            strategy_id=strategy_id,
            profile_id=profile_id,
            mfe_price=entry_price,  # Start at entry
            mae_price=entry_price,  # Start at entry
            mfe_pct=0.0,
            mae_pct=0.0,
            entry_signal_strength=entry_signal_strength,
            entry_signal_confidence=entry_signal_confidence,
            entry_confirmation_count=entry_confirmation_count,
            expected_horizon_sec=expected_horizon_sec,
            time_to_work_sec=time_to_work_sec,
            max_hold_sec=max_hold_sec,
            mfe_min_bps=mfe_min_bps,
            model_side=model_side,
            p_up=p_up,
            p_down=p_down,
            p_flat=p_flat,
        )

    def update_position(
        self,
        symbol: str,
        side: str,
        size: float,
        reference_price: Optional[float] = None,
        entry_price: Optional[float] = None,
        entry_fee_usd: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        opened_at: Optional[float] = None,
        entry_client_order_id: Optional[str] = None,
        entry_decision_id: Optional[str] = None,
        prediction_confidence: Optional[float] = None,
        prediction_direction: Optional[str] = None,
        prediction_source: Optional[str] = None,
        entry_p_hat: Optional[float] = None,
        entry_p_hat_source: Optional[str] = None,
        strategy_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        accumulate: bool = False,
        entry_signal_strength: Optional[str] = None,
        entry_signal_confidence: Optional[float] = None,
        entry_confirmation_count: Optional[int] = None,
        expected_horizon_sec: Optional[float] = None,
        time_to_work_sec: Optional[float] = None,
        max_hold_sec: Optional[float] = None,
        mfe_min_bps: Optional[float] = None,
        model_side: Optional[str] = None,
        p_up: Optional[float] = None,
        p_down: Optional[float] = None,
        p_flat: Optional[float] = None,
    ) -> None:
        """Update or create a position.
        
        If accumulate=True and position already exists on the same side,
        add to existing size and compute weighted average entry price.
        Otherwise, replace the position entirely.
        """
        existing = self._positions.get(symbol)
        
        if accumulate and existing and existing.side == side and not existing.closing:
            # Accumulate position: add sizes and compute weighted average entry
            old_size = existing.size
            old_entry = existing.entry_price or reference_price or 0
            new_entry = entry_price or reference_price or old_entry
            existing_fee = existing.entry_fee_usd
            if existing_fee is None and entry_fee_usd is None:
                total_entry_fee = None
            else:
                total_entry_fee = (existing_fee or 0.0) + (entry_fee_usd or 0.0)
            
            total_size = old_size + size
            if total_size > 0 and old_entry > 0 and new_entry > 0:
                # Weighted average entry price
                avg_entry = ((old_size * old_entry) + (size * new_entry)) / total_size
            else:
                avg_entry = new_entry or old_entry
            
            self._positions[symbol] = PositionRecord(
                symbol=symbol,
                side=side,
                size=total_size,
                entry_client_order_id=existing.entry_client_order_id or entry_client_order_id,
                entry_decision_id=existing.entry_decision_id or entry_decision_id,
                reference_price=reference_price or existing.reference_price,
                entry_price=avg_entry,
                entry_fee_usd=total_entry_fee,
                stop_loss=stop_loss or existing.stop_loss,
                take_profit=take_profit or existing.take_profit,
                opened_at=existing.opened_at or opened_at,  # Keep original open time
                prediction_confidence=prediction_confidence or existing.prediction_confidence,
                prediction_direction=prediction_direction or existing.prediction_direction,
                prediction_source=prediction_source or existing.prediction_source,
                entry_p_hat=entry_p_hat or existing.entry_p_hat,
                entry_p_hat_source=entry_p_hat_source or existing.entry_p_hat_source,
                strategy_id=strategy_id or existing.strategy_id,
                profile_id=profile_id or existing.profile_id,
                # Preserve MFE/MAE from existing position
                mfe_price=existing.mfe_price,
                mae_price=existing.mae_price,
                mfe_pct=existing.mfe_pct,
                mae_pct=existing.mae_pct,
                # Preserve signal strength from original entry
                entry_signal_strength=existing.entry_signal_strength or entry_signal_strength,
                entry_signal_confidence=existing.entry_signal_confidence or entry_signal_confidence,
                entry_confirmation_count=existing.entry_confirmation_count or entry_confirmation_count,
                # Preserve time budget from original entry
                expected_horizon_sec=existing.expected_horizon_sec or expected_horizon_sec,
                time_to_work_sec=existing.time_to_work_sec or time_to_work_sec,
                max_hold_sec=existing.max_hold_sec or max_hold_sec,
                mfe_min_bps=existing.mfe_min_bps or mfe_min_bps,
                model_side=model_side or existing.model_side,
                p_up=(p_up if p_up is not None else existing.p_up),
                p_down=(p_down if p_down is not None else existing.p_down),
                p_flat=(p_flat if p_flat is not None else existing.p_flat),
            )
        else:
            # Replace position (original behavior for new positions or position flip)
            # Initialize MFE/MAE to entry price
            self._positions[symbol] = PositionRecord(
                symbol=symbol,
                side=side,
                size=size,
                entry_client_order_id=entry_client_order_id,
                entry_decision_id=entry_decision_id,
                reference_price=reference_price,
                entry_price=entry_price,
                entry_fee_usd=entry_fee_usd,
                stop_loss=stop_loss,
                take_profit=take_profit,
                opened_at=opened_at,
                prediction_confidence=prediction_confidence,
                prediction_direction=prediction_direction,
                prediction_source=prediction_source,
                entry_p_hat=entry_p_hat,
                entry_p_hat_source=entry_p_hat_source,
                strategy_id=strategy_id,
                profile_id=profile_id,
                mfe_price=entry_price,  # Start at entry
                mae_price=entry_price,  # Start at entry
                mfe_pct=0.0,
                mae_pct=0.0,
                entry_signal_strength=entry_signal_strength,
                entry_signal_confidence=entry_signal_confidence,
                entry_confirmation_count=entry_confirmation_count,
                expected_horizon_sec=expected_horizon_sec,
                time_to_work_sec=time_to_work_sec,
                max_hold_sec=max_hold_sec,
                mfe_min_bps=mfe_min_bps,
                model_side=model_side,
                p_up=p_up,
                p_down=p_down,
                p_flat=p_flat,
            )

    def get_account_state(self) -> "AccountState":
        return self._account_state

    def update_account_state(
        self,
        equity: Optional[float] = None,
        daily_pnl: Optional[float] = None,
        peak_balance: Optional[float] = None,
        consecutive_losses: Optional[int] = None,
    ) -> None:
        if equity is not None:
            self._account_state.equity = equity
        if daily_pnl is not None:
            self._account_state.daily_pnl = daily_pnl
        if peak_balance is not None:
            self._account_state.peak_balance = peak_balance
        if consecutive_losses is not None:
            self._account_state.consecutive_losses = consecutive_losses

    def list_symbols(self) -> List[str]:
        return list(self._positions.keys())

    def update_mfe_mae(self, symbol: str, current_price: float) -> None:
        """Update MFE/MAE for a position based on current price.
        
        MFE (Maximum Favorable Excursion): Best price reached in trade direction
        MAE (Maximum Adverse Excursion): Worst price reached against trade direction
        
        For LONG: MFE = highest price, MAE = lowest price
        For SHORT: MFE = lowest price, MAE = highest price
        """
        pos = self._positions.get(symbol)
        if not pos or pos.closing or not pos.entry_price:
            return
        
        entry = pos.entry_price
        is_long = pos.side.lower() in ("long", "buy")
        
        # Calculate current excursion percentage
        if is_long:
            excursion_pct = ((current_price - entry) / entry) * 100.0
        else:
            excursion_pct = ((entry - current_price) / entry) * 100.0
        
        # Update MFE (favorable = positive excursion)
        new_mfe_price = pos.mfe_price
        new_mfe_pct = pos.mfe_pct or 0.0
        if is_long:
            if pos.mfe_price is None or current_price > pos.mfe_price:
                new_mfe_price = current_price
                new_mfe_pct = max(excursion_pct, new_mfe_pct)
        else:
            if pos.mfe_price is None or current_price < pos.mfe_price:
                new_mfe_price = current_price
                new_mfe_pct = max(excursion_pct, new_mfe_pct)
        
        # Update MAE (adverse = negative excursion)
        new_mae_price = pos.mae_price
        new_mae_pct = pos.mae_pct or 0.0
        if is_long:
            if pos.mae_price is None or current_price < pos.mae_price:
                new_mae_price = current_price
                new_mae_pct = min(excursion_pct, new_mae_pct)
        else:
            if pos.mae_price is None or current_price > pos.mae_price:
                new_mae_price = current_price
                new_mae_pct = min(excursion_pct, new_mae_pct)
        
        # Update position record with new MFE/MAE
        self._positions[symbol] = PositionRecord(
            symbol=pos.symbol,
            side=pos.side,
            size=pos.size,
            closing=pos.closing,
            close_reason=pos.close_reason,
            entry_client_order_id=pos.entry_client_order_id,
            entry_decision_id=pos.entry_decision_id,
            reference_price=current_price,  # Update reference price too
            entry_price=pos.entry_price,
            entry_fee_usd=pos.entry_fee_usd,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            opened_at=pos.opened_at,
            prediction_confidence=pos.prediction_confidence,
            prediction_direction=pos.prediction_direction,
            prediction_source=pos.prediction_source,
            entry_p_hat=pos.entry_p_hat,
            entry_p_hat_source=pos.entry_p_hat_source,
            strategy_id=pos.strategy_id,
            profile_id=pos.profile_id,
            mfe_price=new_mfe_price,
            mae_price=new_mae_price,
            mfe_pct=new_mfe_pct,
            mae_pct=new_mae_pct,
            entry_signal_strength=pos.entry_signal_strength,
            entry_signal_confidence=pos.entry_signal_confidence,
            entry_confirmation_count=pos.entry_confirmation_count,
            expected_horizon_sec=pos.expected_horizon_sec,
            time_to_work_sec=pos.time_to_work_sec,
            max_hold_sec=pos.max_hold_sec,
            mfe_min_bps=pos.mfe_min_bps,
            model_side=pos.model_side,
            p_up=pos.p_up,
            p_down=pos.p_down,
            p_flat=pos.p_flat,
        )

    def get_position(self, symbol: str) -> Optional[PositionRecord]:
        """Get position record for a symbol."""
        return self._positions.get(symbol)

    def get_positions(self) -> List[PositionRecord]:
        """Get all position records."""
        return list(self._positions.values())

    def restore_positions(self, snapshots: List[PositionSnapshot]) -> None:
        self._positions = {}
        for snapshot in snapshots:
            self._positions[snapshot.symbol] = PositionRecord(
                symbol=snapshot.symbol,
                side=snapshot.side,
                size=snapshot.size,
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
                mfe_price=snapshot.mfe_price,
                mae_price=snapshot.mae_price,
                mfe_pct=snapshot.mfe_pct,
                mae_pct=snapshot.mae_pct,
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

    async def list_positions(self, include_closing: bool = True) -> List[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol=pos.symbol,
                side=pos.side,
                size=pos.size,
                entry_client_order_id=pos.entry_client_order_id,
                entry_decision_id=pos.entry_decision_id,
                reference_price=pos.reference_price,
                entry_price=pos.entry_price,
                entry_fee_usd=pos.entry_fee_usd,
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                opened_at=pos.opened_at,
                prediction_confidence=pos.prediction_confidence,
                prediction_direction=pos.prediction_direction,
                prediction_source=pos.prediction_source,
                entry_p_hat=pos.entry_p_hat,
                entry_p_hat_source=pos.entry_p_hat_source,
                strategy_id=pos.strategy_id,
                profile_id=pos.profile_id,
                mfe_price=pos.mfe_price,
                mae_price=pos.mae_price,
                mfe_pct=pos.mfe_pct,
                mae_pct=pos.mae_pct,
                entry_signal_strength=pos.entry_signal_strength,
                entry_signal_confidence=pos.entry_signal_confidence,
                entry_confirmation_count=pos.entry_confirmation_count,
                expected_horizon_sec=pos.expected_horizon_sec,
                time_to_work_sec=pos.time_to_work_sec,
                max_hold_sec=pos.max_hold_sec,
                mfe_min_bps=pos.mfe_min_bps,
                model_side=pos.model_side,
                p_up=pos.p_up,
                p_down=pos.p_down,
                p_flat=pos.p_flat,
            )
            for pos in self._positions.values()
            if include_closing or not pos.closing
        ]

    async def list_open_positions(self) -> List[PositionSnapshot]:
        return await self.list_positions(include_closing=False)

    async def mark_closing(self, symbol: str, reason: str) -> None:
        pos = self._positions.get(symbol)
        if not pos:
            return
        pos.closing = True
        pos.close_reason = reason

    async def finalize_close(self, symbol: str) -> None:
        self._positions.pop(symbol, None)


@dataclass
class AccountState:
    equity: float = 0.0
    daily_pnl: float = 0.0
    peak_balance: float = 0.0
    consecutive_losses: int = 0
